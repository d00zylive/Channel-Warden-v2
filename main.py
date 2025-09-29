import discord
from discord import app_commands
import sqlite3
import decouple
import datetime

intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
TOKEN: str = decouple.config("TOKEN") # pyright: ignore[reportAssignmentType]

connection = sqlite3.connect('ChannelWarden.db')
cursor = connection.cursor()
print("Database connected successfully.")

cursor.execute("""
               SELECT id
               FROM Servers;
               """)
result = cursor.fetchall()
print(result)

async def CalibrateMember(userId: int, guildId: int) -> None:
    guild: discord.Guild = client.get_guild(guildId) # pyright: ignore[reportAssignmentType]
    assert guild is not None, "Guild not found"
    member = guild.get_member(userId)
    assert member is not None, "Member not found"

    dayMult, messageMult, wantedAge, accountAgeMax = result[0]

    # gives experience for every day someone has been in the server
    exp = (datetime.datetime.now(datetime.timezone.utc)-member.joined_at).days*dayMult # pyright: ignore[reportOperatorIssue]

    # sets the message count to the amount of messages sent in the last 1000 messages of every text channel in the the server if messageCount is 0
    if cursor.execute("SELECT messageCount FROM Members WHERE userId = ? AND serverId = ?", (userId, guildId)).fetchall()[0][0] == None: messageCount = len([message for channel in guild.channels if type(channel) == discord.channel.TextChannel and channel.permissions_for(guild.me).read_messages and channel.permissions_for(guild.me).read_message_history async for message in channel.history(limit=1000) if message.author.id == userId])

    # gives experience for every recorded message that they have sent
    exp += messageCount*messageMult
    
    # gives or takes experience for the time they have been on discord 
    exp += (accountAgeMax-(accountAgeMax)/((((datetime.datetime.now(datetime.timezone.utc)-member.created_at)).days+1)/(wantedAge+1)))

    cursor.execute("""Update Members
                     SET exp = ?, messageCount = ?
                     WHERE userId = ? AND serverId = ?;
                     """, (exp, messageCount, userId, guildId))
    connection.commit()

@client.event
async def on_guild_join(guild: discord.Guild):
    sendMessage = False
    if not (guild.id in [row[0] for row in cursor.execute("SELECT id FROM Servers;").fetchall()]):
        if guild.system_channel != None and guild.system_channel_flags.join_notifications:
            message = await guild.system_channel.send("Setting everything up for you")
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