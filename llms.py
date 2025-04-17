from typing import Dict, List, Tuple
from google import genai
from google.genai import types
import discord
from config import (
    GOOGLE_API_KEY, CEREBRAS_API_KEY,
    LOCAL_API_URL, CEREBRAS_API_URL,
    MODEL_ROUTES
)
import re
import requests



client = genai.Client(api_key=GOOGLE_API_KEY)

class ModelRouter:
    def __init__(self):
        self.gemini_client = genai.Client(api_key=GOOGLE_API_KEY)

    def _get_provider(self, model: str) -> str:
        """Determine which provider to use based on the model name prefix."""
        for prefix, provider in MODEL_ROUTES.items():
            if model.lower().startswith(prefix):
                return provider
        return "gemini"  # Default to Gemini if no match

    def _call_openai_compatible_api(self, url: str, api_key: str | None, payload: dict) -> str:
        """Make a call to an OpenAI-compatible API endpoint."""
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()  # Raise exception for bad status codes
        return response.json()["choices"][0]["message"]["content"]

    def generate_content(self, model: str, contents: List[str], config: types.GenerateContentConfig) -> str:
        provider = self._get_provider(model)
        
        # Prepare the OpenAI-compatible payload
        base_payload = {
            "model": model,
            "messages": [{"role": "user", "content": c} for c in contents],
            "temperature": config.temperature,
            "max_tokens": -1,
            "stream": False
        }

        if provider == "local":
            return self._call_openai_compatible_api(LOCAL_API_URL, None, base_payload)
        elif provider == "cerebras":
            return self._call_openai_compatible_api(CEREBRAS_API_URL, CEREBRAS_API_KEY, base_payload)
        else:  # gemini
            response = self.gemini_client.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )
            return response.text


def flag_messages(messages: list[str], waived_people_names: list[str], local: bool = False) -> str:
    flash = "gemini-2.0-flash"
    llama = "llama-3.3-70b"
    hermes = "hermes-3-llama-3.2-3b"
    router = ModelRouter()
    response = router.generate_content(
        model=(llama if not local else hermes),
        contents=[f"""
You will be given a list of Discord messages related to a video game (Cosmoteer: Ship Architect and Commander). Your task is to identify messages that contain unsolicited and unconstructive criticism. 

Messages are in the format "(index) user: ❝content❞". Here is the list of messages:

<discord_messages>
{messages}
</discord_messages>

Analyze each message to determine if it contains either unsolicited and/or unconstructive criticism for the Cosmoteer. Unconstructive criticism typically does one or more of the following:
1. Offers negative feedback (which may or may not include specific issues)
2. Focuses solely on flaws without acknowledging any positive aspects or providing encouragement (this is the most important)
3. Lacks specific suggestions to fix stated issues
4. Is a joke at someone elses expense

A message is exempt from the above if it satisfies any of the following:
1. The criticism references something or someone outside of the provided context (before index 0)
2. Contains enough positive feedback to justify not flagging it
3. The person asking for advice mentions they are ok with harsh criticism
4. The person is criticizing themselves
5. The criticism is directed at the game in general, someone not present in the conversation, or something unrelated to Cosmoteer
6. The criticism is sarcastic ('~~message~~' and '/s' syntax is usually sarcasm, but there may not be an explicit indicator)
7. The person being criticised is in the below list of people who have pre-opted-in to potentially harsh criticism

Here is that (potentially empty) list:
<waived_people>
{waived_people_names}
</waived_people>

Examples of problematic messages include:
- "variety of suboptimal decisions with no clear reasoning behind choosing them over more conventionally optimal things"
- "Your missing significant side / rear armor on a majority of ships ammo factories are objectively never needed in dom"
- "Just as bad as the first time ;)"
- "Where efficacy?"

Examples of acceptable messages that should not be flagged:
- "I share a similar opinion that the others. Do you want a more detailed breakdown on your ships?"
- "I like youre creative ship layouts. Some of them are worse than the established meta designs but for me its just important that those off meta layouts are well optimised in their own right."
- "aye, it does look notably better than the other stuff. 5-launcher HE modules are unconventional, but definitely not bad, it's mostly the armour shaping that's an issue on that ship (big gaps, easy for rammers to hook onto or various things to snipe through)"

If it looks like someone is trying to defend themselves from someone elses criticism or comment instead of discussing as equals, then the criticism, comment, or joke is likely problematic.
If someone did not explicitely ask for (solicit) criticism, then hold any comments on their designs, descriptions, or opinions to a higher standard. Anything that violates one of the bullet points for unconstructive criticism should be flagged.

Create a list of indexes for messages that contain unsolicited and unconstructive criticism. If no messages are problematic, return an empty list.
Take into account other messages by the same user to determine whether to flag a specific one. If that user included only negative criticism in one message, but positive in another, don't flag either.

For each flagged message, assign a confidence level:
 - "high": Clear violation with obvious targeting of users/work
 - "medium": Likely problematic but contains some ambiguity
 - "low": Potentially problematic but requires more context
Remember, if the user being criticized is in the waived people list, rate the criticism as "low" or not at all.

Provide your response in the following format (result section should be a valid python dict):
<analysis>
[Your brief thought process and reasoning for potentially problematic messages, not quoting the messages themselves]
</analysis>

<result>
{{"message_ids": [list of indexes], "confidence": {{"index": "confidence_level", ...}}}}
</result>
""".strip()],
        config=types.GenerateContentConfig(
            temperature=0.2
        )
    )

    return response


def flag_messages_in_thread(thread: discord.Thread, messages: list[str], waived_people_names: list[str]) -> str:
    thread_info = f"Thread Title: {thread.name}\n"
    
    first_message = thread.starting_message
    
    if first_message and first_message.content not in ''.join(messages):
        thread_info += f"First Thread Message: {first_message.author.display_name}: ❝{first_message.content}❞\n...\n"
    
    messages_with_context = [thread_info] + messages
    
    return flag_messages(messages_with_context, waived_people_names)



def extract_flagged_messages(llm_response: str) -> Tuple[List[int], Dict[int, str]]:
    try:
        llm_response = llm_response.split('</analysis>')[-1].strip()
        result_pattern = r'<result>\s*(\{.*?\})\s*</result>'
        match = re.search(result_pattern, llm_response, re.DOTALL)
        
        if match:
            result_str = match.group(1).strip()
            if result_str:
                result_dict = eval(result_str)
                message_ids = result_dict.get('message_ids', [])
                confidence = result_dict.get('confidence', {})
                return message_ids, confidence
    except Exception as e:
        print(f"Error extracting flagged messages: {e}")
        return None
    
    return [], {}


def filter_confidence(confidence: Dict[int, str], confidence_threshold: str) -> List[int]:
    valid_thresholds = {'low': ['low', 'medium', 'high'],
                        'medium': ['medium', 'high'],
                        'high': ['high']}
    
    if confidence_threshold not in valid_thresholds:
        raise ValueError(f"Invalid confidence threshold: {confidence_threshold}")
    
    return [int(idx) for idx, conf in confidence.items() if conf in valid_thresholds[confidence_threshold]]


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
                """.strip(),
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
