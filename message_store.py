import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
import discord
from config import FLAGGED_MESSAGE_STORE_FILE

class FlaggedMessageStore:
    def __init__(self, filepath: str = FLAGGED_MESSAGE_STORE_FILE):
        self.filepath = filepath
        self._ensure_file_exists()
        
    def _ensure_file_exists(self):
        """Create the JSON file if it doesn't exist."""
        if not os.path.exists(self.filepath):
            with open(self.filepath, 'w') as f:
                json.dump([], f)
                
    def _load_messages(self) -> List[Dict]:
        """Load all flagged messages from the JSON file."""
        try:
            with open(self.filepath, 'r') as f:
                loaded = json.load(f)

                # Update missing fields
                if loaded:
                    updated = False
                    for item in loaded:
                        if 'waived_people' not in item:
                            item['waived_people'] = []
                            updated = True
                        if 'history' not in item:
                            item['history'] = None
                            updated = True
                        if 'reason' not in item:
                            item['reason'] = None
                            updated = True
                        if 'relative_id' not in item:
                            item['relative_id'] = None
                            updated = True
                    if updated:
                        self._save_messages(loaded)
                return loaded

        except json.JSONDecodeError:
            return []
            
    def _save_messages(self, messages: List[Dict]):
        """Save messages to the JSON file."""
        with open(self.filepath, 'w') as f:
            json.dump(messages, f, indent=2)
            
    def add_flagged_message(self, message: discord.Message, relative_id: int, history: Optional[List[str]] = None, reason: Optional[str] = None, waived_people: Optional[List[str]] = None):
        """Add a new flagged message to the store."""
        # Check if message is already flagged
        if self.is_message_flagged(message.id):
            return False
            
        messages = self._load_messages()
        
        # Create message entry
        message_data = {
            "message_id": message.id,
            "channel_id": message.channel.id,
            "guild_id": message.guild.id if message.guild else None,
            "author_id": message.author.id,
            "author_name": message.author.display_name,
            "content": message.content,
            "timestamp": message.created_at.isoformat(),
            "flagged_at": datetime.now(timezone.utc).isoformat(),
            "jump_url": message.jump_url,
            "waived_people": waived_people or [],
            "history": history,
            "relative_id": relative_id,
            "reason": reason
        }
        
        messages.append(message_data)
        self._save_messages(messages)
        
    def is_message_flagged(self, message_id: int) -> bool:
        """Check if a message has already been flagged."""
        messages = self._load_messages()
        return any(msg["message_id"] == message_id for msg in messages)
        
    def get_flagged_message(self, message_id: int) -> Optional[Dict]:
        """Get a flagged message by its ID."""
        messages = self._load_messages()
        return next((msg for msg in messages if msg["message_id"] == message_id), None)

    def get_flagged_messages(self, 
                           user_id: Optional[int] = None, 
                           channel_id: Optional[int] = None,
                           guild_id: Optional[int] = None) -> List[Dict]:
        """
        Retrieve flagged messages with optional filters.
        
        Args:
            user_id: Filter by user ID
            channel_id: Filter by channel ID
            guild_id: Filter by guild ID
            
        Returns:
            List of matching flagged message entries
        """
        messages = self._load_messages()
        
        if user_id:
            messages = [m for m in messages if m["author_id"] == user_id]
        if channel_id:
            messages = [m for m in messages if m["channel_id"] == channel_id]
        if guild_id:
            messages = [m for m in messages if m["guild_id"] == guild_id]
            
        return messages
