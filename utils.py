from typing import Optional, Tuple
import discord
import re


async def get_user_names(bot: discord.Bot, guild: discord.Guild, user_id: int) -> Tuple[str, str]:
    """
    Get a user's display name, handling cases where the user is not in the guild.

    Args:
        guild (discord.Guild): The guild the user is in (hopefully).
        user_id (int): The ID of the user.

    Returns:
        Tuple[str, str]: The display name of the user and their global username. Can be identical.
    """
    try:
        member: discord.Member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        return member.display_name, member.name
    except discord.errors.NotFound:
        user: Optional[discord.User] = await bot.get_or_fetch_user(user_id)
        if user is None:
            return 'User', f'#{user_id}'

        return user.display_name, user.name


def format_discord_message(message: discord.Message, relative_id: int = None, reply_rel_id: int = None) -> str:
    """Format a discord message as a string for passing to llm."""
    rel_id = f"({relative_id}) " if relative_id is not None else ""
    reply = ""
    if message.reference and message.reference.resolved:
        reference = message.reference.resolved.author.display_name
        pinged = len(message.mentions) > 0
        reply_str = f"{reply_rel_id}" if reply_rel_id else f"{'@' if pinged else ''}{reference}"
        reply = f"[reply to {reply_str}] "
    
    content = message.content
    if message.attachments:
        content += " [uploaded attachment/image]"
    
    msg = f"{message.author.display_name}: ❝{content}❞"
    edited = " (edited)" if message.edited_at else ""
    reactions = "\n[reactions: " + ', '.join([f"{r.emoji} {r.count}" for r in message.reactions]) + "]" if message.reactions else ""

    return (rel_id + reply + msg + edited + reactions).strip()

def format_consecutive_user_messages(messages: list[discord.Message], relative_id: Optional[int] = None, reply_rel_id: Optional[int] = None) -> str:
    if not messages:
        return ""
    
    author = messages[0].author.display_name
    content_parts = []
    for msg in messages:
        content_parts.append(msg.content)
        if msg.attachments:
            content_parts.append(" [uploaded attachment/image]")
    content = "\n".join(content_parts)
    
    edited = " (edited)" if any(msg.edited_at for msg in messages) else ""
    
    reactions = []
    for msg in messages:
        reactions.extend([f"{r.emoji} {r.count}" for r in msg.reactions])
    
    reaction_str = f"\n[reactions: {', '.join(reactions)}]" if reactions else ""
    
    rel_id = f"({relative_id}) " if relative_id is not None else ""
    reply = f"[reply to {reply_rel_id}] " if reply_rel_id is not None else ""
    
    return f"{rel_id}{reply}{author}: ❝{content}❞{edited}{reaction_str}".strip()
    

def format_discord_messages(messages: list[discord.Message]) -> list[str]:
    if not messages:
        return []

    combined_message_idxs = []
    current_user_id = None
    unique_users = 0
    for msg in messages:
        user_id = msg.author.id
        if user_id != current_user_id:
            if current_user_id is not None:
                unique_users += 1
            current_user_id = user_id
        combined_message_idxs.append(unique_users)

    formatted_messages = []
    current_messages = []
    current_idx = -1
    reply_rel_id = None

    for msg, idx in zip(messages, combined_message_idxs):
        if idx != current_idx:
            if current_messages:
                formatted_messages.append(format_consecutive_user_messages(current_messages, relative_id=current_idx, reply_rel_id=reply_rel_id))
            current_messages = [msg]
            current_idx = idx
            if msg.reference and msg.reference.message_id in [m.id for m in messages]:
                try:
                    reply_rel_id = combined_message_idxs[[m.id for m in messages].index(msg.reference.message_id)]
                except ValueError:
                    reply_rel_id = None
            else:
                reply_rel_id = None
        else:
            current_messages.append(msg)

    if current_messages:
        formatted_messages.append(format_consecutive_user_messages(current_messages, relative_id=current_idx, reply_rel_id=reply_rel_id))

    return formatted_messages


def sanitize_external_content(content: str) -> str:
    bad_inputs: list[str] = [r"<\|.*\|>"]
    for pattern in bad_inputs:
        content = re.sub(pattern, '', content, count=1000000)
    return content

async def get_discord_message_by_id(channel: discord.abc.Messageable, discord_message_id: int, fetch: bool = False) -> discord.Message | None:
    """Retrieve a discord message by its id from the discord api"""
    if fetch:
        return await channel.fetch_message(discord_message_id)
    else:
        return channel.get_message(discord_message_id) or await channel.fetch_message(
            discord_message_id
        )


async def respond_long_message(
    interaction: discord.Interaction,
    text: str,
    chunk_size: int = 1800,
    use_codeblock: bool = False,
    **kwargs,
):
    """
    Sends a message longer than discord's character limit by chunking it.
    Supports all kwargs for discord.Interaction.respond().
    """
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

    for chunk in chunks:
        if use_codeblock:
            chunk = f"```md\n{chunk}\n```"

        await interaction.respond(chunk, **kwargs)

async def send_long_message(
    channel: discord.abc.Messageable,
    text: str,
    chunk_size: int = 1800,
    use_codeblock: bool = False,
    **kwargs,
):
    """
    Sends a message longer than discord's character limit by chunking it.
    Supports all kwargs for discord.Message.send().
    """
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

    for chunk in chunks:
        if use_codeblock:
            chunk = f"```md\n{chunk}\n```"

        await channel.send(chunk, **kwargs)