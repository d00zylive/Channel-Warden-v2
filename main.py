import discord
from discord import app_commands
import sqlite3
import decouple
import datetime

intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
TOKEN: str = decouple.config("TOKEN")

connection = sqlite3.connect('ChannelWarden.db')
cursor = connection.cursor()
print("Database connected successfully.")

cursor.execute("""
               CREATE TABLE IF NOT EXISTS Levels(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   serverId INTEGER NOT NULL,
                   name TEXT NOT NULL DEFAULT '',
                   expReq INTEGER NOT NULL DEFAULT 0,
                   roleId INTEGER NOT NULL DEFAULT 0,
                   message TEXT NOT NULL DEFAULT ''
                   );
               """)
cursor.execute("""
               CREATE TABLE IF NOT EXISTS MemberLevels(
                   memberId INTEGER NOT NULL,
                   levelId INTEGER NOT NULL
                   );
                   """)
cursor.execute("""
               CREATE TABLE IF NOT EXISTS Members(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   userId INTEGER NOT NULL,
                   serverId INTEGER NOT NULL,
                   exp REAL NOT NULL DEFAULT 0,
                   messageCount INTEGER DEFAULT NULL
                   );
               """)
cursor.execute("""
               CREATE TABLE IF NOT EXISTS Servers(
                   id INTEGER PRIMARY KEY,
                   dayMult REAL NOT NULL DEFAULT 1,
                   messageMult REAL NOT NULL DEFAULT 1,
                   wantedAge INTEGER NOT NULL DEFAULT 365,
                   accountAgeMax INTEGER NOT NULL DEFAULT 100,
                   channel INTEGER NOT NULL DEFAULT 0,
                   silent INTEGER NOT NULL DEFAULT TRUE
                   );
               """)
connection.commit()

async def CalibrateLevels(userId: int, guildId: int):
    guild: discord.Guild = client.get_guild(guildId)
    assert guild is not None, "Guild not found"
    member = guild.get_member(userId)
    assert member is not None, "Member not found"
    
    cursor.execute("""
                   SELECT id, exp
                   FROM Members
                   WHERE userId = ? AND serverId = ?;
                   """, (userId, guildId,))
    memberId, exp = cursor.fetchone()
    
    cursor.execute("""
                   SELECT id, expReq
                   FROM Levels
                   WHERE serverId = ?;
                   """, (guildId,))
    levels = cursor.fetchall()
    for level in levels:
        levelId, expReq = level
        
        cursor.execute("""
                        SELECT EXISTS(
                            SELECT 1
                            FROM MemberLevels
                            WHERE memberId = ? AND levelId = ?
                            LIMIT 1
                        );
                        """, (memberId, levelId,))
        if not cursor.fetchone()[0]:
            if expReq <= exp:
                cursor.execute("""
                               INSERT INTO MemberLevels (memberId, levelId)
                               VALUES (?, ?)
                               """, (memberId, levelId,))
                connection.commit()
                
                cursor.execute("""
                               SELECT roleId, message
                               FROM Levels
                               WHERE id = ?
                               """, (levelId,))
                roleId: int
                message: str
                roleId, message = cursor.fetchone()
                
                cursor.execute("""
                               SELECT channel
                               FROM Servers
                               WHERE id = ?
                               """, (guildId,))
                channelId = cursor.fetchone()[0]
                if channelId != 0:
                    channel: discord.TextChannel = client.get_channel(channelId)
                    assert channel is not None, "Channel not found"
                    await channel.send(message.replace("{{user}}", f"<@{userId}>"))
                
                if roleId != 0:
                    await member.add_roles(guild.get_role(roleId))
                
        else:
            if expReq > exp:
                pass
                
        
        
    

async def CalibrateMember(userId: int, guildId: int) -> None:
    guild: discord.Guild = client.get_guild(guildId)
    assert guild is not None, "Guild not found"
    member = guild.get_member(userId)
    assert member is not None, "Member not found"

    cursor.execute("""
                   SELECT dayMult, messageMult, wantedAge, accountAgeMax
                   FROM Servers
                   WHERE id = ?
                   """, (guildId,))
    
    dayMult, messageMult, wantedAge, accountAgeMax = cursor.fetchone()
    
    cursor.execute("""
                   SELECT EXISTS(
                       SELECT 1
                       FROM Members
                       WHERE userId = ? AND serverId = ?
                       LIMIT 1
                   )
                   """, (userId, guildId,))
    if not cursor.fetchone()[0]: # Check if member is in database
        cursor.execute("""
                       INSERT INTO Members (userId, serverId, exp, messageCount)
                       VALUES (?, ?, ?, ?);
                       """, (userId, guildId, 0, None))
        connection.commit()

    # gives experience for every day someone has been in the server
    exp = (datetime.datetime.now(datetime.timezone.utc)-member.joined_at).days*dayMult
    
    # sets the message count to the amount of messages sent in the last 1000 messages of every text channel in the the server if messageCount is 0
    cursor.execute("""
                   SELECT messageCount
                   FROM Members
                   WHERE userId = ? AND serverId = ?
                   """, (userId, guildId))
    messageCount = cursor.fetchone()[0]
    if messageCount == None:
        messageCount = len([message
                            for channel in guild.channels
                                if type(channel) == discord.channel.TextChannel
                                and channel.permissions_for(guild.me).read_messages
                                and channel.permissions_for(guild.me).read_message_history
                                    async for message in channel.history(limit=1000)
                                        if message.author.id == userId
                            ])
        
    # gives experience for every recorded message that they have sent
    exp += messageCount*messageMult
    
    # gives or takes experience for the time they have been on discord 
    exp += (accountAgeMax-(accountAgeMax)/((((datetime.datetime.now(datetime.timezone.utc)-member.created_at)).days+1)/(wantedAge+1)))

    cursor.execute("""UPDATE Members
                     SET exp = ?, messageCount = ?
                     WHERE userId = ? AND serverId = ?;
                     """, (exp, messageCount, userId, guildId))
    connection.commit()
    
    await CalibrateLevels(userId=userId, guildId=guildId)

async def CalibrateServer(guild: discord.Guild) -> None:
    sendMessage = False
    if guild.system_channel != None and guild.system_channel_flags.join_notifications:
        message = await guild.system_channel.send("Setting everything up for you")
        sendMessage = True
    members = [member.id for member in guild.members if not member.bot]
    for i, member in enumerate(members):
        if sendMessage: await message.edit(content=f"Setting everything up for you\n{i}/{len(members)} users calibrated, currently calibrating <@{member}>")
        await CalibrateMember(userId=member, guildId=guild.id)
    if sendMessage: await message.edit(content=f"Finished setting everything up for you! {len(members)}/{len(members)} users have been calibrated")



async def level_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    cursor.execute("""
                   SELECT name, id
                   FROM Levels
                   WHERE serverId = ? AND name LIKE ?
                   """, (interaction.guild.id, ("%"+current+"%")))
    return [app_commands.Choice(name=f"{level[0]} ({level[1]})", value=level[1]) for level in cursor.fetchall()]


class Level(app_commands.Group):
    def __init__(self):
        super().__init__(name="level", description="Commands related to leveling")

    @app_commands.command(name="create", description="Create a level")
    @app_commands.describe(name="The name of the level", exp_req="The experience required to reach this level", role_id="The role ID to assign at this level", message="The message to send when reaching this level")
    @app_commands.checks.has_permissions(administrator=True)
    async def create(self, interaction: discord.Interaction, name: str, exp_req: int, role_id: int = 0, message: str = ""):
        expReq, roleId = exp_req, role_id
        cursor.execute("""
                       INSERT INTO Levels (serverId, name, expReq, roleId, message)
                       VALUES (?, ?, ?, ?, ?);
                       """, (interaction.guild.id, name, expReq, roleId, message,))
        connection.commit()
        await interaction.response.send_message(f"Level {name} created successfully")

    @app_commands.command(name="delete", description="Delete a level")
    @app_commands.describe(level_id="The ID of the level to delete")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.autocomplete(level_id=level_autocomplete)
    async def delete(self, interaction: discord.Interaction, level_id: int):
        levelId = level_id

        cursor.execute("""
               SELECT EXISTS(
               SELECT 1
               FROM Levels
               WHERE id = ? AND serverId = ?
               LIMIT 1);
               """, (levelId, interaction.guild.id))
        exists = cursor.fetchone()[0]

        if exists:
            cursor.execute("""
                       DELETE FROM Levels
                       WHERE id = ? AND serverId = ?;
                       """, (levelId, interaction.guild.id))
            connection.commit()
            await interaction.response.send_message(f"Level {levelId} deleted successfully")
        else:
            await interaction.response.send_message(f"Level does not exist, in your server")
    
    @app_commands.command(name="edit", description="Edit a level")
    @app_commands.describe(level_id="The ID of the level to edit", name="The new name of the level", exp_req="The new experience required to reach this level", role_id="The new role ID to assign at this level", message="The new message to send when reaching this level")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.autocomplete(level_id=level_autocomplete)
    async def edit(self, interaction: discord.Interaction, level_id: int, name: str = None, exp_req: int = None, role_id: int = None, message: str = None):
        levelId, expReq, roleId = level_id, exp_req, role_id

        cursor.execute("""
               SELECT EXISTS(
               SELECT 1
               FROM Levels
               WHERE id = ? AND serverId = ?
               LIMIT 1);
               """, (levelId, interaction.guild.id))
        exists = cursor.fetchone()[0]

        if exists:
            cursor.execute("""
                           UPDATE Levels
                           SET name=coalesce(?,name), expReq=coalesce(?,expReq), roleId=coalesce(?,roleId), message=coalesce(?,message)
                           WHERE id = ? AND serverId = ?;
                           """, (name, expReq, roleId, message, levelId, interaction.guild.id))
            connection.commit()
            await interaction.response.send_message(f"Level {levelId} has been edited successfully")
        else:
            await interaction.response.send_message(f"Level does not exist, in your server")
    
    @app_commands.command(name="list", description="List all levels")
    @app_commands.checks.has_permissions(administrator=True)
    async def list(self, interaction: discord.Interaction):
        cursor.execute("""
                       SELECT ALL *
                       FROM Levels
                       WHERE serverId = ?
                       """, (interaction.guild.id,))
        levels = sorted(cursor.fetchall(), key=lambda row: row[3]) # sort based on experience requirement (expReq)
        msg = ""
        for level in levels:
            msg += f"# {level[2]}:\n**id:** *{level[0]}*\n**expReq:** *{level[3]}*\n**role:** <@&{level[4]}>\n"
            if level[5] != "":
                msg += f"message:\n  *{level[5]}*\n"

        await interaction.response.send_message(msg, silent=True)


class Calibrate(app_commands.Group):
    def __init__(self):
        super().__init__(name="calibrate", description="Commands related to calibrating", parent=Level())
        
    @app_commands.command(name="member", description="Calibrate a single member's exp and levels")
    @app_commands.describe(member="The member you want to calibrate")
    @app_commands.checks.has_permissions(administrator=True)
    async def member(self, interaction: discord.Interaction, member: discord.Member):
        if not member.bot:
            await CalibrateMember(userId=member.id, guildId=interaction.guild.id)
            await interaction.response.send_message("Calibrated member succesfully!")
        else:
            await interaction.response.send_message("ERROR: Member is a bot, could not calibrate")
        
    @app_commands.command(name="server")
    @app_commands.checks.has_permissions(administrator=True)
    async def server(self, interaction: discord.Interaction, status_msg: bool = True):
        await CalibrateServer(guild=interaction.guild)

tree.add_command(Calibrate())

@client.event
async def on_guild_join(guild: discord.Guild):
    if not (guild.id in [row[0] for row in cursor.execute("SELECT id FROM Servers;").fetchall()]):
        cursor.execute("""
                    INSERT INTO Servers (id, dayMult, messageMult, wantedAge, accountAgeMax, channel, silent)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """, (guild.id, 1, 1, 365, 100, 0, True))
        connection.commit()
        await CalibrateServer(guild=guild)
            
@client.event
async def on_message(message: discord.Message):
    cursor.execute("""
               SELECT EXISTS(
               SELECT 1
               FROM Servers
               WHERE id = ?
               LIMIT 1);
               """, (message.guild.id,))
    if cursor.fetchone()[0]: # Check if server is in database
        if not message.author.bot:
            cursor.execute("""
                           SELECT EXISTS(
                               SELECT 1
                               FROM Members
                               WHERE userId = ? AND serverId = ?
                               LIMIT 1
                           );
                           """, (message.author.id, message.guild.id,))
            if cursor.fetchone()[0]: # Check if member is in database
                cursor.execute("""
                               UPDATE Members
                               SET messageCount = messageCount + 1
                               WHERE userId = ? AND serverId = ?;
                               """, (message.author.id, message.guild.id,))
            await CalibrateMember(userId=message.author.id, guildId=message.guild.id)
    else:
        await CalibrateServer(guild=message.guild)

@client.event
async def on_ready():
    await tree.sync()
    print("Ready!")

client.run(TOKEN)