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
               SELECT EXISTS(
               SELECT 1
               FROM Levels
               WHERE id = 1 AND serverId = 1052133479795662909
               LIMIT 1);
               """)
result = cursor.fetchone()[0]
print(result)

async def CalibrateMember(userId: int, guildId: int) -> None:
    guild: discord.Guild = client.get_guild(guildId)
    assert guild is not None, "Guild not found"
    member = guild.get_member(userId)
    assert member is not None, "Member not found"

    dayMult, messageMult, wantedAge, accountAgeMax = result[0]

    # gives experience for every day someone has been in the server
    exp = (datetime.datetime.now(datetime.timezone.utc)-member.joined_at).days*dayMult

    # sets the message count to the amount of messages sent in the last 1000 messages of every text channel in the the server if messageCount is 0
    if cursor.execute("SELECT messageCount FROM Members WHERE userId = ? AND serverId = ?", (userId, guildId)).fetchone()[0] == None: messageCount = len([message for channel in guild.channels if type(channel) == discord.channel.TextChannel and channel.permissions_for(guild.me).read_messages and channel.permissions_for(guild.me).read_message_history async for message in channel.history(limit=1000) if message.author.id == userId])

    # gives experience for every recorded message that they have sent
    exp += messageCount*messageMult
    
    # gives or takes experience for the time they have been on discord 
    exp += (accountAgeMax-(accountAgeMax)/((((datetime.datetime.now(datetime.timezone.utc)-member.created_at)).days+1)/(wantedAge+1)))

    cursor.execute("""UPDATE Members
                     SET exp = ?, messageCount = ?
                     WHERE userId = ? AND serverId = ?;
                     """, (exp, messageCount, userId, guildId))
    connection.commit()



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
                       """, (interaction.guild.id, name, expReq, roleId, message))
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

tree.add_command(Level())

@client.event
async def on_guild_join(guild: discord.Guild):
    sendMessage = False
    if not (guild.id in [row[0] for row in cursor.execute("SELECT id FROM Servers;").fetchall()]):
        if guild.system_channel != None and guild.system_channel_flags.join_notifications:
            message = await guild.system_channel.send("Setting everything up fo r you")
            sendMessage = True
        cursor.execute("""
                       INSERT INTO Servers (id, dayMult, messageMult, wantedAge, accountAgeMax, channel, silent)
                       VALUES (?, ?, ?, ?, ?, ?, ?);
                       """, (guild.id, 1, 1, 365, 100, 0, True))
        connection.commit()
        members = [member.id for member in guild.members if not member.bot]
        for i, member in enumerate(members):
            if sendMessage: await message.edit(content=f"Setting everything up for you\n{i+1}/{len(members)} users calibrated, currently calibrating <@{member}>")
            cursor.execute("""
                           INSERT INTO Members (userId, serverId, exp, messageCount)
                            VALUES (?, ?, ?, ?);
                            """, (member, guild.id, 0, None))
            await CalibrateMember(userId=member, guildId=guild.id)

@client.event
async def on_ready():
    await tree.sync()
    print("Ready!")

client.run(TOKEN)