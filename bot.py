import asyncio
from typing import Optional
import discord
from discord.ext import tasks
from collections import deque
import datetime
from message_store import FlaggedMessageStore

from config import DISCORD_BOT_TOKEN, CHANNEL_ALLOW_LIST, GENERIC_PING_RESPONSE, GUIDELINES, HISTORY_PER_CHECK, LOG_CHANNEL_ID, MESSAGES_PER_CHECK, SECS_BETWEEN_AUTO_CHECKS, SEND_RESPONSES_TO_LOG_CHANNEL_ONLY, WAIVER_ROLE_NAME, REACT_WITH_EMOJI_IF_NOT_RESPONDING, REACTION_EMOJI
from llms import extract_flagged_messages, flag_messages, generate_user_feedback_message
from utils import format_consecutive_user_messages, format_discord_message, format_discord_messages, respond_long_message, sanitize_external_content, send_long_message

global_llm_lock = False
global_check_timers_running = {}

class MessageHistory:
    def __init__(self, maxlen=50):
        self.messages = deque(maxlen=maxlen)
        self.messages_since_last_check = 0
        self.time_of_last_message = None
    
    def add_message(self, message: discord.Message):
        # print(f"Adding message {message.id} to history in channel {message.channel.id}")
        self.messages.append(message)
        self.messages_since_last_check += 1
        self.time_of_last_message = message.created_at
    
    def edit_message(self, message: discord.Message):
        try:
            index = self.messages.index(message)
            self.messages[index] = message
        except ValueError:
            print(f"Message {message.id} not found in history")

    def delete_message(self, message: discord.Message):
        try:
            self.messages.remove(message)
        except ValueError:
            print(f"Message {message.id} not found in history")
    
    def get_messages(self) -> list[discord.Message]:
        return list(self.messages)

    async def get_users_with_waiver_role(self) -> list[discord.Member]:
        """
        Fetches a list of users in this message history who have the specified waiver role.
        May require additional checks if the Member object is partial.
        """
        users = []
        for message in self.messages:
            # Ensure we have a Member object with roles
            if hasattr(message.author, "roles"):
                for role in message.author.roles:
                    if role.name == WAIVER_ROLE_NAME:
                        users.append(message.author)
        return users
    
    def bot_message_in_history(self, num_messages: int) -> bool:
        message_list = list(self.messages)
        for message in reversed(message_list[-num_messages:]):
            if message.author.id == bot.user.id and not message.flags.ephemeral:
                if message.reference is not None:
                    return True
        return False

    def reset_messages_since_last_check(self):
        self.messages_since_last_check = 0

class MessageHistoryManager:
    def __init__(self):
        self.histories: dict[int, MessageHistory] = {}
    
    def get_history(self, channel_id: int) -> MessageHistory | None:
        print(f"Retrieving history for channel {channel_id}")
        return self.histories.get(channel_id)
    
    def create_history(self, channel_id: int, initial_messages: list[discord.Message] = None) -> MessageHistory:
        history = MessageHistory()
        if initial_messages:
            for msg in initial_messages:
                history.add_message(msg)
        self.histories[channel_id] = history
        print(f"Created history for channel {channel_id}")
        return history
    
    def get_or_create_history(self, channel_id: int) -> MessageHistory:
        return self.histories.setdefault(channel_id, MessageHistory())


class DiscordMessageGroup:
    """
    A group of multiple discord messages sent in succession by the same user
    """

    def __init__(self, messages: list[discord.Message]):
        self.messages = messages
        self.author = messages[0].author
        self.channel = messages[0].channel
        self.count = len(messages)
        self.reply = None
        self.reply_group_id = None

        if not all(msg.author == self.author for msg in messages):
            raise ValueError("All messages in the group must be sent by the same user.")

        for msg in messages:
            if msg.reference is not None:
                self.reply = msg.reference.resolved
                if isinstance(self.reply, discord.DeletedReferencedMessage):
                    self.reply = None
                break
    
    def update_reply_group_id(self, group_id: int):
        self.reply_group_id = group_id

    def oldest_message(self) -> discord.Message:
        return min(self.messages, key=lambda msg: msg.created_at)

    def newest_message(self) -> discord.Message:
        return max(self.messages, key=lambda msg: msg.created_at)

    def format(self, relative_id: Optional[int] = None, reply_rel_id: Optional[int] = None) -> str:
        return format_consecutive_user_messages(self.messages, relative_id, reply_rel_id)

class GroupedHistory:
    """
    A collection of DiscordMessageGroups representing the message history of a channel
    in a way that's easier to pass to llms.
    """

    def __init__(self, history: MessageHistory):
        self.base_history = history
        self.groups: list[DiscordMessageGroup] = []

        # Turn messages into groups
        current_group = []
        
        for message in self.base_history.get_messages():
            if not current_group or message.author == current_group[-1].author:
                current_group.append(message)
            else:
                self.groups.append(DiscordMessageGroup(current_group))
                current_group = [message]
        
        if current_group:
            self.groups.append(DiscordMessageGroup(current_group))

        self.count = len(self.groups)

        # Set reply_group_ids
        for i, group in enumerate(self.groups):
            if group.reply:
                for j in range(i - 1, -1, -1):
                    if any(msg.id == group.reply.id for msg in self.groups[j].messages):
                        group.update_reply_group_id(j)
                        break


    def oldest_message(self) -> discord.Message:
        return min(self.base_history.get_messages(), key=lambda msg: msg.created_at)

    def newest_message(self) -> discord.Message:
        return max(self.base_history.get_messages(), key=lambda msg: msg.created_at)

    def oldest_message_by_userid(self, user_id: int) -> Optional[discord.Message]:
        user_messages = [msg for msg in self.base_history.get_messages() if msg.author.id == user_id]
        return min(user_messages, key=lambda msg: msg.created_at) if user_messages else None

    def newest_message_by_userid(self, user_id: int) -> Optional[discord.Message]:
        user_messages = [msg for msg in self.base_history.get_messages() if msg.author.id == user_id]
        return max(user_messages, key=lambda msg: msg.created_at) if user_messages else None
    
    def oldest_group_by_userid(self, user_id: int) -> Optional[DiscordMessageGroup]:
        user_groups = [group for group in self.groups if group.author.id == user_id]
        return min(user_groups, key=lambda g: g.oldest_message().created_at) if user_groups else None

    def newest_group_by_userid(self, user_id: int) -> Optional[DiscordMessageGroup]:
        user_groups = [group for group in self.groups if group.author.id == user_id]
        return max(user_groups, key=lambda g: g.newest_message().created_at) if user_groups else None

    def format(self) -> str:
        res = ""
        for i, group in enumerate(self.groups):
            res += "\n" + group.format(i, group.reply_group_id)
        return res


bot = discord.Bot(intents=discord.Intents.all())
history_manager = MessageHistoryManager()
message_store = FlaggedMessageStore()


async def check_channel_on_timer(channel: discord.TextChannel | discord.Thread, secs: int):
    global global_check_timers_running
    if global_check_timers_running.get(channel.id, 0):
        global_check_timers_running[channel.id] = secs
        return

    global_check_timers_running[channel.id] = secs
    history = history_manager.get_history(channel.id)
    if not history:
        print(f"No history found for channel {channel.id}. Skipping moderation.")
        return

    if history.time_of_last_message:
        print(f"Channel {channel.id} last checked at {history.time_of_last_message}. Sleeping until next check in {secs} seconds...")
        while history.time_of_last_message + datetime.timedelta(seconds=global_check_timers_running[channel.id]) > datetime.datetime.now(datetime.timezone.utc):
            time_until_check = (history.time_of_last_message + datetime.timedelta(seconds=global_check_timers_running[channel.id]) - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
            print(f"Sleeping until next check in {time_until_check:.2f} seconds...")
            await asyncio.sleep(min(time_until_check, 10))

        if history.messages_since_last_check > 0:
            global_check_timers_running[channel.id] = 0
            await moderate(channel, history, HISTORY_PER_CHECK)


async def retry_moderation(channel: discord.TextChannel | discord.Thread, history: MessageHistory, messages_per_check: int):
    global global_llm_lock
    while global_llm_lock:
        await asyncio.sleep(2)
    await moderate(channel, history, messages_per_check)

async def moderate(channel: discord.TextChannel | discord.Thread, history: MessageHistory, messages_per_check: int):
    if not history:
        print(f"No message history available in channel {channel.id}")
        return

    if history.bot_message_in_history(messages_per_check):
        print("Bot message found in history. Skipping moderation.")
        return

    print(f"Moderating channel {channel.id}...")
    messages = history.get_messages()[-messages_per_check:]

    formatted_messages = format_discord_messages(messages)

    global global_llm_lock
    if global_llm_lock:
        print("LLM is currently processing messages. Scheduling a retry...")
        asyncio.create_task(retry_moderation(channel, history, messages_per_check))
        return

    global_llm_lock = True
    llm_response = flag_messages(formatted_messages, await history.get_users_with_waiver_role())
    global_llm_lock = False

    temp = '\n'.join(formatted_messages)
    print(f"Messages:\n{temp}\n\nLLM response: `{llm_response}`")

    extracted = extract_flagged_messages(llm_response)

    print("Flagged message indexes:", extracted)

    if not extracted:
        return
    flagged_messages = [formatted_messages[idx] for idx in extracted]
    distinct_users = {}

    for idx, message_str in enumerate(flagged_messages):
        target_messages = [msg for msg in reversed(messages) if msg.content in message_str]
        if target_messages:
            target_message = target_messages[0]
            
            # Skip if message is already flagged
            if message_store.is_message_flagged(target_message.id):
                print(f"Message {target_message.id} already flagged, skipping...")
                continue
                
            user_id = target_message.author.id
            if user_id not in distinct_users:
                distinct_users[user_id] = {"messages": [], "indexes": [], "discord_messages": []}
            distinct_users[user_id]["messages"].append(message_str)
            distinct_users[user_id]["indexes"].append(extracted[idx])
            distinct_users[user_id]["discord_messages"].append(target_message)

    # If we're not sending responses to log channel only, do that
    if not SEND_RESPONSES_TO_LOG_CHANNEL_ONLY:
        print("Sending responses to users...")
        for user_id, user_data in distinct_users.items():
            global_llm_lock = True
            response = ""
            while not response:
                response = await generate_user_feedback_message(user_data["messages"], user_data["indexes"], GUIDELINES)
                if not response:
                    print("Empty response, retrying...")
                    await asyncio.sleep(1)
            print("Got feedback:", response)
            global_llm_lock = False
            
            # Store flagged messages with the feedback as the reason
            for message in user_data["discord_messages"]:
                if message_store.add_flagged_message(message, reason=response):
                    print(f"Flagged message {message.id}")
                else:
                    print(f"Message {message.id} was already flagged")
                
            target_message = user_data["discord_messages"][0]
            await target_message.reply(response)
    
    elif REACT_WITH_EMOJI_IF_NOT_RESPONDING:
        for user_data in distinct_users.values():
            if user_data["discord_messages"]:
                most_recent_message = user_data["discord_messages"][-1]
                try:
                    await most_recent_message.add_reaction(REACTION_EMOJI)
                    print(f"Added reaction {REACTION_EMOJI} to message {most_recent_message.id}")
                except discord.errors.HTTPException as e:
                    print(f"Failed to add reaction to message {most_recent_message.id}: {e}")

    


    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    for user_data in distinct_users.values():
        for idx, message_str in enumerate(user_data["messages"]):
            target_message = user_data["discord_messages"][idx]

            # Save flagged message if not already saved
            if not message_store.is_message_flagged(target_message.id):
                message_store.add_flagged_message(target_message)
                print(f"Saved flagged message {target_message.id}")
            else:
                print(f"Message {target_message.id} was already flagged, skipping...")


            await send_long_message(log_channel, f"Flagged message: {target_message.jump_url}\nContent: ```{message_str[:200]}```")


@bot.event
async def on_ready():
    print(f'Bot ready as {bot.user}')
    
    # Populate message history for all channels and threads
    for guild in bot.guilds:
        # Handle text channels
        for channel in [channel for channel in guild.text_channels if channel.id in CHANNEL_ALLOW_LIST]:
            try:
                messages = await channel.history(limit=50).flatten()
                if messages:
                    history = history_manager.create_history(channel.id, messages[::-1])
                    print(f"Loaded {len(messages)} messages from channel {channel.name}")
                
                # Handle active threads in the channel
                for thread in channel.threads:
                    if not thread.archived:
                        thread_messages = await thread.history(limit=50).flatten()
                        if thread_messages:
                            if thread.message_count < 50:
                                first_message = await channel.fetch_message(thread.id)
                                first_thread_message_idx = messages.index(first_message)
                                parent_context = messages[first_thread_message_idx:][::-1]
                                history = history_manager.create_history(thread.id, parent_context + thread_messages[::-1])
                                print(f"Loaded {len(thread_messages) + len(parent_context)} messages from thread {thread.name}")
                            else:
                                history = history_manager.create_history(thread.id, thread_messages[::-1])
                                print(f"Loaded {len(thread_messages)} messages from thread {thread.name}")
            except Exception as e:
                print(f"Error loading messages from channel {channel.name}: {e}")

        for forum in [forum for forum in guild.forum_channels if forum.id in CHANNEL_ALLOW_LIST]:
            for thread in forum.threads:
                try:
                    messages = await thread.history(limit=50).flatten()
                    if messages:
                        history = history_manager.create_history(thread.id, messages[::-1])
                        print(f"Loaded {len(messages)} messages from thread {thread.name}")
                except Exception as e:
                    print(f"Error loading messages from thread {thread.name}: {e}")

    print("Message history population complete")

@bot.event
async def on_message(message: discord.Message):
    if message.channel.id not in CHANNEL_ALLOW_LIST:
        if not isinstance(message.channel, discord.Thread):
            return
        if message.channel.parent.id not in CHANNEL_ALLOW_LIST:
            return
    if message.flags.ephemeral:
        return

    # print(f"{message.author}: {message.content}")
    
    # Handle message history for all channels
    channel = message.channel
    history = history_manager.get_or_create_history(channel.id)
    history.add_message(message)
    print("New message:", format_discord_message(message))

    if history.messages_since_last_check >= MESSAGES_PER_CHECK:
        print("Checking for moderation actions...")
        history.reset_messages_since_last_check()
        await moderate(channel, history, HISTORY_PER_CHECK)
    else:
        asyncio.create_task(check_channel_on_timer(channel, SECS_BETWEEN_AUTO_CHECKS))

    # print(format_discord_messages(history.get_messages()))

    # Handle when a user mentions the bot
    if bot.user in message.mentions:
        await message.channel.send(GENERIC_PING_RESPONSE)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if after.channel.id not in CHANNEL_ALLOW_LIST:
        if not isinstance(after.channel, discord.Thread):
            return
        if after.channel.parent.id not in CHANNEL_ALLOW_LIST:
            return

    # Handle message history for all channels
    channel = after.channel
    history = history_manager.get_or_create_history(channel.id)
    history.edit_message(after)
    print(f"Edited message from {format_discord_message(before)} -> {format_discord_message(after)}")

    # print(format_discord_messages(history.get_messages()))

@bot.event
async def on_message_delete(message: discord.Message):
    if message.channel.id not in CHANNEL_ALLOW_LIST:
        if not isinstance(message.channel, discord.Thread):
            return
        if message.channel.parent.id not in CHANNEL_ALLOW_LIST:
            return
        
    # Handle message history for all channels
    channel = message.channel
    history = history_manager.get_or_create_history(channel.id)
    history.delete_message(message)
    print(f"Deleted message from {format_discord_message(message)}")

    # print(format_discord_messages(history.get_messages()))

@bot.event
async def on_thread_create(thread: discord.Thread):
    if isinstance(thread.parent, discord.TextChannel):
        parent_history = history_manager.get_history(thread.parent.id)
        if parent_history:
            cutoff = thread.created_at
            parent_messages = [msg for msg in parent_history.get_messages() if msg.created_at < cutoff]
            thread_history = history_manager.create_history(thread.id, parent_messages[-50:])
        else:
            thread_history = history_manager.create_history(thread.id)
    elif isinstance(thread.parent, discord.ForumChannel):
        thread_history = history_manager.create_history(thread.id)
    else:
        return

    try:
        async for msg in thread.history(limit=100, oldest_first=True):
            if msg not in thread_history.get_messages():
                thread_history.add_message(msg)
    except discord.HTTPException:
        pass

@bot.event
async def on_thread_update(before: discord.Thread, after: discord.Thread):
    # Clean up history if thread is archived
    if after.archived:
        history_manager.histories.pop(after.id, None)

# @tasks.loop(seconds=300)
# async def history_cleanup():
#     # Cleanup histories for deleted channels/threads
#     current_ids = {channel.id for channel in bot.get_all_channels()}
#     current_ids.update({thread.id for thread in bot.private_threads})
#     history_manager.histories = {
#         k: v for k, v in history_manager.histories.items()
#         if k in current_ids
#     }

# Example moderation command
@bot.command(description="Check recent messages for unconstructive criticism")
async def check(ctx: discord.ApplicationContext):
    history = history_manager.get_history(ctx.channel.id)
    if not history:
        await ctx.respond("No message history available", ephemeral=True)
        return
    
    await moderate(ctx.channel, history, HISTORY_PER_CHECK)
    await ctx.respond("Moderation check completed.", ephemeral=True)

bot.run(DISCORD_BOT_TOKEN)