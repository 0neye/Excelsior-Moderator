import asyncio
import re
from typing import Optional
import discord
from collections import deque
import datetime
from history import GroupedHistory, MessageHistory, MessageHistoryManager
from message_store import FlaggedMessageStore
import json

from config import DISCORD_BOT_TOKEN, CHANNEL_ALLOW_LIST, EVALUATION_RESULTS_FILE, EVALUATION_STORE_FILE, GENERIC_PING_RESPONSE, GUIDELINES, HISTORY_PER_CHECK, LOG_CHANNEL_ID, MESSAGE_GROUPS_PER_CHECK, SECS_BETWEEN_AUTO_CHECKS, SEND_RESPONSES_TO_LOG_CHANNEL_ONLY, WAIVER_ROLE_NAME, REACT_WITH_EMOJI_IF_NOT_RESPONDING, REACTION_EMOJI, MODERATOR_ROLES
from llms import extract_flagged_messages, flag_messages, flag_messages_in_thread, generate_user_feedback_message
from utils import format_consecutive_user_messages, format_discord_message, respond_long_message, sanitize_external_content, send_long_message

global_llm_lock = False
global_check_timers_running = {}

bot = discord.Bot(intents=discord.Intents.all())
history_manager = MessageHistoryManager()
message_store = FlaggedMessageStore()


async def check_channel_on_timer(channel: discord.TextChannel | discord.Thread, secs: int):
    """
    Checks a channel for moderation on a timer. Resets the timer on new messages being sent in the channel.
    
    Args:
        channel (discord.TextChannel | discord.Thread): The channel or thread to check
        secs (int): Number of seconds for the timer to wait
    """
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
    """
    Retries moderation if the LLM is locked.
    
    Args:
        channel (discord.TextChannel | discord.Thread): The channel or thread to moderate
        history (MessageHistory): Message history object for the channel
        messages_per_check (int): Number of messages to check per moderation run
    """
    global global_llm_lock
    while global_llm_lock:
        await asyncio.sleep(2)
    await moderate(channel, history, messages_per_check)

async def moderate(channel: discord.TextChannel | discord.Thread, history: MessageHistory, history_per_check: int) -> str:
    """
    Performs moderation on a channel by checking message history for flagged content.
    
    Args:
        channel (discord.TextChannel | discord.Thread): The channel or thread to moderate
        history (MessageHistory): Message history object for the channel
        history_per_check (int): Number of message groups to check in this moderation run
    """
    if not history:
        print(f"No message history available in channel {channel.id}")
        return

    if history.bot_message_in_history(history_per_check * 2, bot.user.id):
        print("Bot message found in history. Skipping moderation.")
        return

    global global_llm_lock
    if global_llm_lock:
        print("LLM is currently processing messages. Scheduling a retry...")
        asyncio.create_task(retry_moderation(channel, history, history_per_check))
        return

    print(f"Moderating channel {channel.id}... Using {history_per_check} message groups this check.")

    message_groups = GroupedHistory(history).last_n_groups(history_per_check)

    formatted_messages = message_groups.format_as_str_list()
    print("Formatted messages:\n", '\n'.join(formatted_messages))

    # The number of groups added since the last check (the new ones)
    # We only want to flag new messages, and not ones near to the beginning of the visible context
    new_groups_since_last_check = max(MESSAGE_GROUPS_PER_CHECK, message_groups.get_group_count_since_last_check())

    waived_people = history.get_members_with_waiver_role()

    global_llm_lock = True
    if isinstance(channel, discord.Thread):
        llm_response = flag_messages_in_thread(channel, formatted_messages, waived_people)
    else:
        llm_response = flag_messages(formatted_messages, waived_people)
    global_llm_lock = False

    print(f"LLM response: `{llm_response}`")

    extracted = extract_flagged_messages(llm_response)

    print("Flagged message indexes:", extracted)

    if not extracted:
        return llm_response
    
    flagged_groups = message_groups \
        .flag_groups(extracted) \
        .last_n_groups(new_groups_since_last_check) \
        .get_flagged_groups()

    flagged_groups = [group for group in flagged_groups if not group.is_in_store(message_store)]

    # Always add flagged messages to the store and send a log to the log channel
    for group in flagged_groups:

        for message in group.messages:
            rel_id = message_groups.get_id_of_group(group)
            message_store.add_flagged_message(message, rel_id, formatted_messages, llm_response, [member.display_name for member in waived_people])

        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        print("Flagged message group:", group.format())
        await send_long_message(log_channel, f"Flagged message: {group.oldest_message().jump_url}\nContent: ```{group.format()[:200]}{'...' if len(group.format()) > 200 else ''}```")

    # If we should only send flagged messages to a log channel and not respond to the user
    if SEND_RESPONSES_TO_LOG_CHANNEL_ONLY:
        
        # If we should react with emojis as a subsitute
        if REACT_WITH_EMOJI_IF_NOT_RESPONDING:
            for group in flagged_groups:
                await group.newest_message().add_reaction(REACTION_EMOJI)

    # If we do want to directly respond to the user
    else:
        pass

    return llm_response


@bot.event
async def on_ready():
    """
    Event handler for when the bot is ready. Initializes message history for all channels and threads.
    """
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
    """
    Event handler for new messages. Updates message history and performs moderation checks.
    
    Args:
        message (discord.Message): The new message that was sent
    """
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

    if history.messages_since_last_check >= MESSAGE_GROUPS_PER_CHECK:
        print("Checking for moderation actions...")
        history.reset_messages_since_last_check()
        await moderate(channel, history, HISTORY_PER_CHECK)
    else:
        asyncio.create_task(check_channel_on_timer(channel, SECS_BETWEEN_AUTO_CHECKS))

    # print(format_discord_messages(history.get_messages()))

    # Handle when a user mentions the bot
    # if bot.user in message.mentions:
    #     await message.channel.send(GENERIC_PING_RESPONSE)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    """
    Event handler for edited messages. Updates message history with edited content.
    
    Args:
        before (discord.Message): The message before the edit
        after (discord.Message): The message after the edit
    """
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
    """
    Event handler for deleted messages. Removes deleted messages from history.
    
    Args:
        message (discord.Message): The message that was deleted
    """
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
    """
    Event handler for new thread creation. Initializes message history for the new thread.
    
    Args:
        thread (discord.Thread): The newly created thread
    """
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
    """
    Event handler for thread updates. Handles changes in thread state.
    
    Args:
        before (discord.Thread): The thread state before the update
        after (discord.Thread): The thread state after the update
    """
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

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    # Ignore bot reactions
    if payload.user_id == bot.user.id:
        return

    # Check for thumbs up or thumbs down reactions on bot's messages in the log channel
    if payload.emoji.name in ('👍', '👎') and payload.channel_id == LOG_CHANNEL_ID:
        print(f"Valid reaction in log channel: {payload.emoji.name}")
        channel = await bot.fetch_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)

        # Verify that the reaction is on a message sent by the bot
        if message.author.id == bot.user.id:
            print("Reaction is on bot's message")
            # Extract flagged message ID from the jump URL in the message
            match = re.search(r'https://discord\.com/channels/\d+/\d+/(\d+)', message.content)
            if not match:
                print("No jump URL found in message")
                return  # Exit if no jump URL is found
            flagged_message_id = int(match.group(1))
            print(f"Extracted flagged message ID: {flagged_message_id}")

            # Retrieve flagged message info from the message store
            info = message_store.get_flagged_message(flagged_message_id)
            history = info.get('history', None)
            waived_people = info.get('waived_people', [])
            relative_id = info.get('relative_id', None)
            print(f"Retrieved info: history={len(history)}, waived_people={waived_people}, relative_id={relative_id}")

            # Determine correct outcome based on reactions
            reaction_counts = {r.emoji: r.count for r in message.reactions}
            thumbs_up = reaction_counts.get('👍', 0)
            thumbs_down = reaction_counts.get('👎', 0)
            correct_outcome = thumbs_up >= thumbs_down
            print(f"Correct outcome: {correct_outcome}")

            # Create test case dictionary
            test_case = {
                'history': history,
                'waived_people': waived_people,
                'message_id': flagged_message_id,
                'relative_id': relative_id,
                'correct_outcome': correct_outcome
            }
            print("Created test case")

            # Load existing test cases or create an empty list
            try:
                with open(EVALUATION_STORE_FILE, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    test_cases = json.loads(content) if content else []
                print(f"Loaded {len(test_cases)} existing test cases")
            except FileNotFoundError:
                test_cases = []
                print("No existing test cases found")
            except json.JSONDecodeError:
                print("Error decoding JSON, starting with empty list")
                test_cases = []
            
            # Replace or append the test case
            for i, case in enumerate(test_cases):
                if case['message_id'] == test_case['message_id']:
                    test_cases[i] = test_case
                    break
            else:
                test_cases.append(test_case)
            
            # Save updated test cases
            with open(EVALUATION_STORE_FILE, 'w', encoding='utf-8') as f:
                json.dump(test_cases, f, indent=4)
            print(f"Saved {len(test_cases)} test cases to file")


@bot.command(description="Check recent messages for unconstructive criticism")
async def check(ctx: discord.ApplicationContext):
    """
    Slash command to manually trigger a moderation check on a channel.
    
    Args:
        ctx (discord.ApplicationContext): The command context
    """

    if not any(role.name in MODERATOR_ROLES for role in ctx.author.roles):
        await ctx.respond("You don't have permission to use this command.", ephemeral=True)
        return

    history = history_manager.get_history(ctx.channel.id)
    if not history:
        await ctx.respond("No message history available", ephemeral=True)
        return
    
    llm_response = await moderate(ctx.channel, history, HISTORY_PER_CHECK)
    await respond_long_message(ctx.interaction, f"Moderation check completed. LLM response:\n```{llm_response}```", ephemeral=True)


@bot.command(description="Run evaluation over flagged examples (moderators only)")
async def run_eval(ctx: discord.ApplicationContext):
    # Check if the user has a moderator role
    if not any(role.name in MODERATOR_ROLES for role in ctx.author.roles):
        await ctx.respond("You do not have permission to run this command.", ephemeral=True)
        return

    # Send an initial ephemeral message
    initial_response = await ctx.respond("running eval...", ephemeral=True)
    try:
        # Load evaluation cases from EVALUATION_STORE_FILE
        with open(EVALUATION_STORE_FILE, 'r') as f:
            eval_cases = json.load(f)


        results = []
        passed_count = 0

        # Iterate over each evaluation case while respecting rate limits (~1 sec per case)
        for case in eval_cases:
            print(f"Processing case: {case.get('message_id')}")
            history = case.get('history', [])
            waived_people = case.get('waived_people', [])
            expected = case.get('correct_outcome', None)
            relative_id = case.get('relative_id', None)

            try:
                print("Calling flag_messages...")
                llm_response = flag_messages(history, waived_people)
            except Exception as e:
                print(f"Error in flag_messages: {e}")
                llm_response = f"Error: {e}"

            print("Extracting flagged messages...")
            extracted = extract_flagged_messages(llm_response)
            passed = (relative_id in extracted) == expected
            print(f"Case passed: {passed}")

            if passed:
                passed_count += 1
            results.append({
                'message_id': case.get('message_id'),
                'llm_response': llm_response,
                'expected': expected,
                'relative_id': relative_id,
                'passed': passed,
                'waived_people': case.get('waived_people', [])
            })

            # Update progress
            progress_message = f"Processed {len(results)}/{len(eval_cases)} cases. Current pass rate: {passed_count/len(results):.2%}"
            await initial_response.edit(content=progress_message)

            await asyncio.sleep(1)

        total_cases = len(eval_cases)
        failed_count = total_cases - passed_count

        # Create markdown content for detailed results
        md_content = "# Evaluation Results\n\n"
        md_content += f"Total Cases: {total_cases}\n"
        md_content += f"Passed: {passed_count}\n"
        md_content += f"Failed: {failed_count}\n\n"
        md_content += "## Detailed Results\n\n"
        for res in results:
            md_content += f"### Message ID: {res['message_id']}\n"
            md_content += f"- LLM Response: ```{res['llm_response']}```\n"
            md_content += f"- Correct Relative ID: {res['relative_id']}\n"
            md_content += f"- Passed: {res['passed']}\n"
            md_content += f"- Waived People: {', '.join(res['waived_people'])}\n\n"

        # Write markdown content to a file
        with open(EVALUATION_RESULTS_FILE, "w", encoding="utf-8") as f:
            f.write(md_content)

        overview = f"Evaluation complete: {total_cases} cases processed. {passed_count} passed, {failed_count} failed. Pass rate: {passed_count/total_cases:.2%}"

        # Edit the initial ephemeral message with the updated summary
        await initial_response.edit(content=overview)

        # Send a followup ephemeral message with an attachment containing the full report
        await ctx.followup.send(file=discord.File(EVALUATION_RESULTS_FILE), ephemeral=True)
    except Exception as e:
        error_message = f"Error during evaluation: {e}"
        await initial_response.edit(content=error_message)

bot.run(DISCORD_BOT_TOKEN)