import discord
from discord import app_commands
import sqlite3
import decouple
import datetime

intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
TOKEN: str|bool = decouple.config("TOKEN")
assert isinstance(TOKEN, str), "Invalid token"

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
    guild: discord.Guild|None = client.get_guild(guildId)
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
    levels: list[list[int]] = cursor.fetchall()
    
    for level in levels:
        assert len(level) == 2 and isinstance(level[0], int) and isinstance(level[1], int), "Level invalid"
        levelId, expReq = level
        
        cursor.execute("""
                        SELECT EXISTS(
                            SELECT 1
                            FROM MemberLevels
                            WHERE memberId = ? AND levelId = ?
                            LIMIT 1
                        );
                        """, (memberId, levelId,))
        if not cursor.fetchone()[0]: # Check if member doesn't already have the level
            if exp >= expReq:
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
                    channel: discord.abc.GuildChannel|discord.Thread|discord.abc.PrivateChannel|None = client.get_channel(channelId)
                    assert channel is not None, "Channel not found"
                    assert isinstance(channel, discord.TextChannel), "Channel of wrong type"
                    await channel.send(message.replace("{{user}}", f"<@{userId}>"))
                
                if roleId != 0:
                    role: discord.Role|None = guild.get_role(roleId)
                    assert role is not None, "Role not found"
                    await member.add_roles(role)

async def CalibrateMember(userId: int, guildId: int) -> None:
    guild: discord.Guild|None = client.get_guild(guildId)
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
    joinDate: datetime.datetime|None = member.joined_at
    assert joinDate is not None, "Member join date not found"
    exp = (datetime.datetime.now(datetime.timezone.utc)-joinDate).days*dayMult
    
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
                                    async for message in channel.history(limit=100000)
                                        if message.author.id == userId
                            ])
        
    # gives experience for every recorded message that they have sent
    exp += messageCount*messageMult
    
    # gives or takes experience for the time they have been on discord 
    accountAge:int = ((datetime.datetime.now(datetime.timezone.utc)-member.created_at)).days
    exp += accountAgeMax-accountAgeMax*(wantedAge+1)/(accountAge+1)

    cursor.execute("""UPDATE Members
                     SET exp = ?, messageCount = ?
                     WHERE userId = ? AND serverId = ?;
                     """, (exp, messageCount, userId, guildId))
    connection.commit()
    
    await CalibrateLevels(userId=userId, guildId=guildId)

async def CalibrateServer(guild: discord.Guild, statusMessage:bool|None = None, channel:discord.TextChannel|None = None) -> None:
    sendMessage = False
    if (guild.system_channel is not None or channel is not None) and (statusMessage or guild.system_channel_flags.join_notifications and not statusMessage):
        sendMessage = True
        if guild.system_channel is not None:
            message = await guild.system_channel.send("Setting everything up for you")
        elif channel is not None:
            message = await channel.send("Setting everything up for you")
        else:
            sendMessage = False
    members = [member.id for member in guild.members if not member.bot]
    for i, member in enumerate(members):
        if sendMessage:
            await message.edit(content=f"Setting everything up for you\n{i}/{len(members)} users calibrated, currently calibrating <@{member}>")
        await CalibrateMember(userId=member, guildId=guild.id)
    if sendMessage:
        await message.edit(content=f"Finished setting everything up for you! {len(members)}/{len(members)} users have been calibrated")



async def level_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    guild: discord.Guild|None = interaction.guild
    assert guild is not None, "Guild not found"
    cursor.execute("""
                   SELECT name, id
                   FROM Levels
                   WHERE serverId = ? AND name LIKE ?
                   """, (guild.id, ("%"+current+"%")))
    return [app_commands.Choice(name=f"{level[0]} ({level[1]})", value=level[1]) for level in cursor.fetchall()]


class Level(app_commands.Group):
    def __init__(self):
        super().__init__(name="level", description="Commands related to leveling")

    @app_commands.command(name="create", description="Create a level")
    @app_commands.describe(name="The name of the level", exp_req="The experience required to reach this level", role_id="The role ID to assign at this level", message="The message to send when reaching this level")
    @app_commands.checks.has_permissions(administrator=True)
    async def create(self, interaction: discord.Interaction, name: str, exp_req: int, role_id: int = 0, message: str = ""):
        expReq, roleId = exp_req, role_id
        
        guild: discord.Guild|None = interaction.guild
        assert guild is not None, "Guild not found"
        
        cursor.execute("""
                       INSERT INTO Levels (serverId, name, expReq, roleId, message)
                       VALUES (?, ?, ?, ?, ?);
                       """, (guild.id, name, expReq, roleId, message,))
        connection.commit()
        await interaction.response.send_message(f"Level {name} created successfully")

    @app_commands.command(name="delete", description="Delete a level")
    @app_commands.describe(level_id="The ID of the level to delete")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.autocomplete(level_id=level_autocomplete)
    async def delete(self, interaction: discord.Interaction, level_id: int):
        levelId = level_id
        
        guild: discord.Guild|None = interaction.guild
        assert guild is not None, "Guild not found"

        cursor.execute("""
               SELECT EXISTS(
               SELECT 1
               FROM Levels
               WHERE id = ? AND serverId = ?
               LIMIT 1);
               """, (levelId, guild.id,))
        exists = cursor.fetchone()[0]

        if exists:
            cursor.execute("""
                       DELETE FROM Levels
                       WHERE id = ? AND serverId = ?;
                       """, (levelId, guild.id,))
            connection.commit()
            await interaction.response.send_message(f"Level {levelId} deleted successfully")
        else:
            await interaction.response.send_message(f"Level does not exist, in your server")
    
    @app_commands.command(name="edit", description="Edit a level")
    @app_commands.describe(level_id="The ID of the level to edit", name="The new name of the level", exp_req="The new experience required to reach this level", role_id="The new role ID to assign at this level", message="The new message to send when reaching this level")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.autocomplete(level_id=level_autocomplete)
    async def edit(self, interaction: discord.Interaction, level_id: int, name: str|None = None, exp_req: int|None = None, role_id: int|None = None, message: str|None = None):
        levelId, expReq, roleId = level_id, exp_req, role_id
        
        guild: discord.Guild|None = interaction.guild
        assert guild is not None, "Guild not found"

        cursor.execute("""
               SELECT EXISTS(
               SELECT 1
               FROM Levels
               WHERE id = ? AND serverId = ?
               LIMIT 1);
               """, (levelId, guild.id))
        exists = cursor.fetchone()[0]

        if exists:
            cursor.execute("""
                           UPDATE Levels
                           SET name=coalesce(?,name), expReq=coalesce(?,expReq), roleId=coalesce(?,roleId), message=coalesce(?,message)
                           WHERE id = ? AND serverId = ?;
                           """, (name, expReq, roleId, message, levelId, guild.id,))
            connection.commit()
            await interaction.response.send_message(f"Level {levelId} has been edited successfully")
        else:
            await interaction.response.send_message(f"Level does not exist, in your server")
    
    @app_commands.command(name="list", description="List all levels")
    @app_commands.checks.has_permissions(administrator=True)
    async def list(self, interaction: discord.Interaction):
        guild: discord.Guild|None = interaction.guild
        assert guild is not None, "Guild not found"
        
        cursor.execute("""
                       SELECT ALL *
                       FROM Levels
                       WHERE serverId = ?
                       """, (guild.id,))
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
        guild: discord.Guild|None = interaction.guild
        assert guild is not None, "Guild not found"
        
        if not member.bot:
            await interaction.response.defer()
            await CalibrateMember(userId=member.id, guildId=guild.id)
            await interaction.response.send_message("Calibrated member succesfully!")
        else:
            await interaction.response.send_message("ERROR: Member is a bot, could not calibrate")
        
    @app_commands.command(name="server", description="Calibrate all members' exp and levels")
    @app_commands.checks.has_permissions(administrator=True)
    async def server(self, interaction: discord.Interaction, status_message: bool = True):
        guild: discord.Guild|None = interaction.guild
        assert guild is not None, "Guild not found"
        
        channel: discord.abc.GuildChannel|discord.Thread|discord.abc.PrivateChannel|None = interaction.channel
        assert channel is not None, "Channel not found"
        assert isinstance(channel, discord.TextChannel), "Channel of wrong type"
        
        await interaction.response.defer()
        await CalibrateServer(guild=guild, statusMessage=status_message, channel=channel)
        await interaction.response.send_message("Server calibrated succesfully!")

tree.add_command(Calibrate())


class Config(app_commands.Group):
    def __init__(self):
        super().__init__(name="config", description="Commands for configurating this bot")
        
    @app_commands.command(name="channel", description="Configurate which channel gets notifications")
    @app_commands.describe(channel="The channel notifications should be sent in")
    @app_commands.checks.has_permissions(administrator=True)
    async def channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guild: discord.Guild|None = interaction.guild
        assert guild is not None, "Guild not found"
        
        cursor.execute("""
                        UPDATE Servers
                        SET channel=?
                        WHERE Id=?
                        """, (channel.id,guild.id,))
        await interaction.response.send_message(f"Notification channel succesfully set to <#{channel.id}>")
        
    @app_commands.command(name="silent", description="Configurate whether notifications should ping users")
    @app_commands.describe(silent="Silence notification pings?")
    @app_commands.checks.has_permissions(administrator=True)
    async def silent(self, interaction: discord.Interaction, silent: bool):
        guild: discord.Guild|None = interaction.guild
        assert guild is not None, "Guild not found"
        
        cursor.execute("""
                        UPDATE Servers
                        SET silent=?
                        WHERE Id=?
                        """, (int(silent),guild.id,))
        await interaction.response.send_message(f"Silent succesfully set to {silent}")
            

class ExpGain(app_commands.Group):
    def __init__(self):
        super().__init__(name="expgain", description="Configurations related to experience gain parameters", parent=Config())
    
    @app_commands.command(name="daymult", description="Configurate how much exp a member should get for every day in the server")
    @app_commands.describe(daymult="The amount of exp a member should get for every day in the server")
    @app_commands.checks.has_permissions(administrator=True)
    async def dayMult(self, interaction: discord.Interaction, daymult: float):
        guild: discord.Guild|None = interaction.guild
        assert guild is not None, "Guild not found"
        
        cursor.execute("""
                        UPDATE Servers
                        SET dayMult=?
                        WHERE Id=?
                        """, (daymult,guild.id,))
        await interaction.response.send_message(f"Daily exp multiplier succesfully set to {daymult}")
        
    @app_commands.command(name="messagemult", description="Configurate how much exp a member should get for every message they send")
    @app_commands.describe(messagemult="The amount of exp a member should get for every message they send")
    @app_commands.checks.has_permissions(administrator=True)
    async def messageMult(self, interaction: discord.Interaction, messagemult: float):
        guild: discord.Guild|None = interaction.guild
        assert guild is not None, "Guild not found"
        
        cursor.execute("""
                        UPDATE Servers
                        SET messageMult=?
                        WHERE Id=?
                        """, (messagemult,guild.id,))
        await interaction.response.send_message(f"Message exp multiplier succesfully set to {messagemult}")
        
    @app_commands.command(name="wantedage", description="Configurate at what account age a member will start to gain exp")
    @app_commands.describe(wantedage="The acount age in days when they will start gaining exp")
    @app_commands.checks.has_permissions(administrator=True)
    async def wantedAge(self, interaction: discord.Interaction, wantedage: float):
        guild: discord.Guild|None = interaction.guild
        assert guild is not None, "Guild not found"
        
        cursor.execute("""
                        UPDATE Servers
                        SET wantedAge=?
                        WHERE Id=?
                        """, (wantedage,guild.id,))
        await interaction.response.send_message(f"Wanted age succesfully set to {wantedage}")
        
    @app_commands.command(name="accountagemax", description="Configurate the maximum amount of exp a member can gain from account age")
    @app_commands.describe(accountagemax="The maximum amount of exp a member can gain from account age")
    @app_commands.checks.has_permissions(administrator=True)
    async def accountAgeMax(self, interaction: discord.Interaction, accountagemax: float):
        guild: discord.Guild|None = interaction.guild
        assert guild is not None, "Guild not found"
        
        cursor.execute("""
                        UPDATE Servers
                        SET accountAgeMax=?
                        WHERE Id=?
                        """, (accountagemax,guild.id,))
        await interaction.response.send_message(f"Maximum exp account age exp gain succesfully set to {accountagemax}")
    

tree.add_command(ExpGain())

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
    guild: discord.Guild|None = message.guild
    assert guild is not None, "Guild not found"
    
    cursor.execute("""
               SELECT EXISTS(
               SELECT 1
               FROM Servers
               WHERE id = ?
               LIMIT 1);
               """, (guild.id,))
    if cursor.fetchone()[0]: # Check if server is in database
        if not message.author.bot:
            cursor.execute("""
                           SELECT EXISTS(
                               SELECT 1
                               FROM Members
                               WHERE userId = ? AND serverId = ?
                               LIMIT 1
                           );
                           """, (message.author.id, guild.id,))
            if cursor.fetchone()[0]: # Check if member is in database
                cursor.execute("""
                               UPDATE Members
                               SET messageCount = messageCount + 1
                               WHERE userId = ? AND serverId = ?;
                               """, (message.author.id, guild.id,))
            await CalibrateMember(userId=message.author.id, guildId=guild.id)
    else:
        await CalibrateServer(guild=guild)

@client.event
async def on_ready():
    await tree.sync()
    print("Ready!")

client.run(TOKEN)