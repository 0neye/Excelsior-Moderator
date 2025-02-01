from collections import deque
from typing import Optional, Self

import discord

from config import WAIVER_ROLE_NAME
from message_store import FlaggedMessageStore
from utils import format_consecutive_user_messages


class MessageHistory:
    """A class to manage message history for a channel with a fixed maximum length."""
    def __init__(self, maxlen=50):
        """Initialize history with max length of messages."""
        self.messages = deque(maxlen=maxlen)
        self.messages_since_last_check = 0
        self.time_of_last_message = None
    
    def add_message(self, message: discord.Message):
        """Add a new message to the history."""
        # print(f"Adding message {message.id} to history in channel {message.channel.id}")
        self.messages.append(message)
        self.messages_since_last_check += 1
        self.time_of_last_message = message.created_at
    
    def edit_message(self, message: discord.Message):
        """Edit an existing message in the history."""
        try:
            index = self.messages.index(message)
            self.messages[index] = message
        except ValueError:
            print(f"Message {message.id} not found in history")

    def delete_message(self, message: discord.Message):
        """Delete a message from the history."""
        try:
            self.messages.remove(message)
        except ValueError:
            print(f"Message {message.id} not found in history")
    
    def get_messages(self) -> list[discord.Message]:
        """Get all messages in the history."""
        return list(self.messages)

    def get_members_with_waiver_role(self) -> list[discord.Member]:
        """
        Fetches a list of users in this message history who have the specified waiver role.
        May require additional checks if the Member object is partial.
        """
        members = []
        for message in self.messages:
            # Ensure we have a Member object with roles
            if hasattr(message.author, "roles"):
                for role in message.author.roles:
                    if role.name == WAIVER_ROLE_NAME:
                        members.append(message.author)
        return members
    
    def bot_message_in_history(self, num_messages: int, bot_id: int) -> bool:
        """
        Check if there are any bot messages in the recent history.
        
        Args:
            num_messages (int): Number of recent messages to check
            bot_id (int): ID of the bot to check for
            
        Returns:
            bool: True if a bot message is found
        """
        message_list = list(self.messages)
        for message in reversed(message_list[-num_messages:]):
            if message.author.id == bot_id and not message.flags.ephemeral:
                if message.reference is not None:
                    return True
        return False

    def reset_messages_since_last_check(self):
        """Reset the counter for messages since last check."""
        self.messages_since_last_check = 0


class MessageHistoryManager:
    """Manages multiple MessageHistory instances for different channels."""
    def __init__(self):
        """Initialize a new MessageHistoryManager."""
        self.histories: dict[int, MessageHistory] = {}
    
    def get_history(self, channel_id: int) -> MessageHistory | None:
        """Get message history for a channel by ID."""
        return self.histories.get(channel_id)
    
    def create_history(self, channel_id: int, initial_messages: list[discord.Message] = None) -> MessageHistory:
        """Create new message history for a channel with optional initial messages."""
        history = MessageHistory()
        if initial_messages:
            for msg in initial_messages:
                history.add_message(msg)
        self.histories[channel_id] = history
        return history
    
    def get_or_create_history(self, channel_id: int) -> MessageHistory:
        """Get existing history or create new one for channel."""
        return self.histories.setdefault(channel_id, MessageHistory())


class DiscordMessageGroup:
    """A group of consecutive messages from the same user."""
    def __init__(self, messages: list[discord.Message], relative_id: int = None):
        """Initialize with list of messages from same user."""
        self.messages = messages
        self.author = messages[0].author
        self.channel = messages[0].channel
        self.count = len(messages)
        self.relative_id = relative_id
        self.flagged = False
        self.reply_to = None
        self.reply_group_id = None

        if not all(msg.author == self.author for msg in messages):
            raise ValueError("All messages in the group must be sent by the same user.")

        for msg in messages:
            if msg.reference is not None:
                self.reply_to = msg.reference.resolved
                if isinstance(self.reply_to, discord.DeletedReferencedMessage):
                    self.reply_to = None
                break
    
    def flag(self):
        """Mark this message group as flagged."""
        self.flagged = True

    def is_flagged(self) -> bool:
        """Check if this message group is flagged."""
        return self.flagged

    def is_in_store(self, message_store: FlaggedMessageStore) -> bool:
        """Check if this message group is in the flagged message store."""
        return self.oldest_message().id in [msg["message_id"] for msg in message_store._load_messages()]

    def update_reply_group_id(self, group_id: int):
        """Set the ID of the group this message replies to."""
        self.reply_group_id = group_id

    def oldest_message(self) -> discord.Message:
        """Get the oldest message in the group."""
        return min(self.messages, key=lambda msg: msg.created_at)

    def newest_message(self) -> discord.Message:
        """Get the newest message in the group."""
        return max(self.messages, key=lambda msg: msg.created_at)

    def format(self, relative_id: Optional[int] = None, reply_rel_id: Optional[int] = None) -> str:
        """Format the message group as a string with optional IDs."""
        return format_consecutive_user_messages(self.messages, relative_id, reply_rel_id)

    def __eq__(self, other):
        if not self.messages or not other.messages:
            return False
        return self.messages[0].id == other.messages[0].id

    def __ne__(self, other):
        return not self.__eq__(other)

class GroupedHistory:
    """
    A collection of DiscordMessageGroups representing the message history of a channel
    in a way that's easier to pass to llms.
    """
    def __init__(self, history: MessageHistory):
        """Initialize with a MessageHistory instance."""
        self.base_history = history
        self.groups: list[DiscordMessageGroup] = []

        # Turn messages into groups
        current_group = []
        
        for message in self.base_history.get_messages():
            if not current_group or message.author == current_group[-1].author:
                current_group.append(message)
            else:
                self.groups.append(DiscordMessageGroup(current_group, len(self.groups)))
                current_group = [message]
        
        if current_group:
            self.groups.append(DiscordMessageGroup(current_group, len(self.groups)))

        self._calc_rel_ids()

    def _calc_rel_ids(self):
        self.count = len(self.groups)

        # Set reply_group_ids and update relative_ids
        for i, group in enumerate(self.groups):
            group.relative_id = i
            if group.reply_to:
                for j in range(i):
                    if any(msg.id == group.reply_to.id for msg in self.groups[j].messages):
                        group.update_reply_group_id(j)
                        break

    def last_n_groups(self, n: int) -> Self:
        """Get the last n groups in the history."""
        self.groups = self.groups[-n:]
        self._calc_rel_ids()
        return self

    def flag_groups(self, group_ids: list[int]) -> Self:
        """Flag the specified groups by their IDs."""
        for group_id in group_ids:
            self.groups[group_id].flag()
        return self

    def get_group_by_id(self, group_id: int) -> Optional[DiscordMessageGroup]:
        """Get a group by its ID."""
        return self.groups[group_id] if 0 <= group_id < len(self.groups) else None

    def get_id_of_group(self, group: DiscordMessageGroup) -> Optional[int]:
        """Get the ID of a group."""
        return self.groups.index(group)

    def oldest_message(self) -> discord.Message:
        """Get the oldest message in the history."""
        return min(self.base_history.get_messages(), key=lambda msg: msg.created_at)

    def newest_message(self) -> discord.Message:
        """Get the newest message in the history."""
        return max(self.base_history.get_messages(), key=lambda msg: msg.created_at)

    def oldest_message_by_userid(self, user_id: int) -> Optional[discord.Message]:
        """Get the oldest message from a specific user."""
        user_messages = [msg for msg in self.base_history.get_messages() if msg.author.id == user_id]
        return min(user_messages, key=lambda msg: msg.created_at) if user_messages else None

    def newest_message_by_userid(self, user_id: int) -> Optional[discord.Message]:
        """Get the newest message from a specific user."""
        user_messages = [msg for msg in self.base_history.get_messages() if msg.author.id == user_id]
        return max(user_messages, key=lambda msg: msg.created_at) if user_messages else None
    
    def oldest_group_by_userid(self, user_id: int) -> Optional[DiscordMessageGroup]:
        """Get the oldest message group from a specific user."""
        user_groups = [group for group in self.groups if group.author.id == user_id]
        return min(user_groups, key=lambda g: g.oldest_message().created_at) if user_groups else None

    def newest_group_by_userid(self, user_id: int) -> Optional[DiscordMessageGroup]:
        """Get the newest message group from a specific user."""
        user_groups = [group for group in self.groups if group.author.id == user_id]
        return max(user_groups, key=lambda g: g.newest_message().created_at) if user_groups else None

    def get_group(self, group_id: int) -> Optional[DiscordMessageGroup]:
        """Get a message group by its ID."""
        return self.groups[group_id] if 0 <= group_id < len(self.groups) else None

    def get_flagged_groups(self) -> list[DiscordMessageGroup]:
        """Get all flagged message groups."""
        return [group for group in self.groups if group.is_flagged()]
    
    def get_newest_flagged_messages(self) -> list[discord.Message]:
        """Get newest messages from all flagged groups."""
        return [group.newest_message() for group in self.get_flagged_groups()]

    def get_distinct_users(self) -> set[int]:
        """Get IDs of all users in the history."""
        return set(group.author.id for group in self.groups)

    def get_flagged_users(self) -> set[int]:
        """Get IDs of users with flagged messages."""
        return set(group.author.id for group in self.get_flagged_groups())

    def get_group_count_since_last_check(self) -> int:
        """Get number of groups since last check."""
        for i, group in enumerate(reversed(self.groups)):
            if group.oldest_message().created_at < self.base_history.get_messages()[-self.base_history.messages_since_last_check].created_at:
                return i + 1
        return 0

    def format(self) -> str:
        """Format entire history as a string."""
        res = ""
        for i, group in enumerate(self.groups):
            res += "\n" + group.format(i, group.reply_group_id)
        return res

    def format_as_str_list(self) -> list[str]:
        """Format history as list of strings."""
        return [group.format(i, group.reply_group_id) for i, group in enumerate(self.groups)]
