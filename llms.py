from cerebras.cloud.sdk import Cerebras
import discord
from config import CEREBRAS_API_KEY
import re

client = Cerebras(
    api_key=CEREBRAS_API_KEY
)

def flag_messages(messages: list[str], waived_people: list[discord.User]) -> str:

    waived_people_names = [person.display_name for person in waived_people]

    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": f"""
You will be given a list of Discord messages related to a video game. Your task is to identify messages that contain unsolicited and unconstructive criticism. 

Messages are in the format "(index) user: ❝content❞". Here is the list of messages:

<discord_messages>
{messages}
</discord_messages>

Analyze each message to determine if it contains either unsolicited and/or unconstructive criticism for the video game. Unconstructive criticism typically:
1. Offers negative feedback (which may or may not include specific issues)
2. Focuses solely on flaws without acknowledging any positive aspects or providing encouragement (this is the most important)
3. Lacks specific suggestions to fix stated issues

A message can be exempt from the above if it satisfies any of the following:
1. Is part of an ongoing multi-way discussion that has been going since before message index 0 (so you can't check whether it is solicited or not)
2. Contains enough positive feedback to justify not flagging it
3. The person asking for advice mentions they are ok with harsh criticism
4. The person critiquing is criticising their own ships
5. The topic being discussed is not related to the video game
6. The person being criticised is in the below list of people who have pre-opted-in to potentially harsh criticism

Here is that (potentially empty) list:
<waived_people>
{waived_people_names}
</waived_people>

Examples of problematic messages include:
- "variety of suboptimal decisions with no clear reasoning behind choosing them over more conventionally optimal things"
- "Your missing significant side / rear armor on a majority of ships ammo factories are objectively never needed in dom"
- "Where efficacy"

Examples of acceptable messages that should not be flagged:
- "I share a similar opinion that the others. Do you want a more detailed breakdown on your ships?"
- "I like youre creative ship layouts. Some of them are worse than the established meta designs but for me its just important that those off meta layouts are well optimised in their own right."
- "aye, it does look notably better than the other stuff. 5-launcher HE modules are unconventional, but definitely not bad, it's mostly the armour shaping that's an issue on that ship (big gaps, easy for rammers to hook onto or various things to snipe through)"

Create a list of indexes for messages that contain unsolicited and unconstructive criticism. If no messages are problematic, return an empty list.
Take into account other messages by the same user to determine whether to flag a specific one. If that user included only negative criticism in one message, but positive in another, don't flag either.

Provide your response in the following format:
<analysis>
[Your brief thought process and reasoning for potentially problematic messages; not quoting the messages themselves]
</analysis>

<result>
[List of indexes for actually problematic messages, or an empty list if none are found]
</result>
                """,
            }
    ],
        model="llama3.3-70b",
        temperature=0.2
    )

    return chat_completion.choices[0].message.content


async def flag_messages_in_thread(thread: discord.Thread, messages: list[str], waived_people: list[discord.User]) -> str:
    thread_info = f"Thread Title: {thread.name}\n"
    
    first_message = thread.starting_message
    
    if first_message:
        thread_info += f"First Thread Message: {first_message.author.display_name}: ❝{first_message.content}❞\n\n"
    
    messages_with_context = [thread_info] + messages
    
    return flag_messages(messages_with_context, waived_people)



def extract_flagged_messages(llm_response: str) -> list[int]:

    # Remove everything before the closing analysis tag
    llm_response = llm_response.split('</analysis>')[-1].strip()

    result_pattern = r'<result>\s*\[(.*?)\]\s*</result>'
    match = re.search(result_pattern, llm_response, re.DOTALL)
    
    if match:
        result_str = match.group(1).strip()
        if result_str:
            return [int(idx.strip()) for idx in result_str.split(',')]
        else:
            return []
    else:
        return []

async def generate_user_feedback_message(message_strs: list[str], message_indexes: list[int], guidelines: str) -> str:
    
    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": f"""
    As a Discord moderator, provide a brief warning/reminder for the following messages with indexes {message_indexes}:
    Construct your response addressing all messages at once, even if there are multiple. Don't try to address them individually.

    Here is the conversation in question:
    <discord_messages>
    {message_strs}
    </discord_messages>

    Guidelines for feedback:
    <guidelines>
    {guidelines}
    </guidelines>

    Instructions:
    1. Acknowledge the user's perspective
    2. Note what about the guidelines they broke
    3. Suggest improvements

    Keep your response concise and constructive, while in a casual tone. Three sentences most.
    Format your response within <response> tags.

    <response>
    [Your feedback here]
    </response>
                """,
            }
        ],
        model="llama3.1-8b",
        temperature=0.6
    )

    response_text = chat_completion.choices[0].message.content

    match = re.search(r'<response>(.*?)</response>', response_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""
