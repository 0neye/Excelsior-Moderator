import discord
from config import (
    CEREBRAS_API_KEY,
    LOCAL_API_URL, CEREBRAS_API_URL,
    MODEL_ROUTES
)
import re
import requests
from typing import Any

class ModelRouter:
    def __init__(self):
        pass

    def _get_provider(self, model: str) -> str:
        """Determine which provider to use based on the model name prefix."""
        for prefix, provider in MODEL_ROUTES.items():
            if model.lower().startswith(prefix):
                return provider
        return "cerebras"  # Default to Cerebras if no match

    def _call_openai_compatible_api(self, url: str, api_key: str | None, payload: dict) -> str:
        """Make a call to an OpenAI-compatible API endpoint."""
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()  # Raise exception for bad status codes
        return response.json()["choices"][0]["message"]["content"]

    def generate_content(self, model: str, system_message: str, user_message: str, config: dict) -> str:
        provider = self._get_provider(model)
        
        # Prepare the OpenAI-compatible payload
        base_payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ],
            "temperature": config.get("temperature", 0.0),
            "max_tokens": -1,
            "stream": False
        }

        if provider == "local":
            return self._call_openai_compatible_api(LOCAL_API_URL, None, base_payload)
        elif provider == "cerebras":
            return self._call_openai_compatible_api(CEREBRAS_API_URL, CEREBRAS_API_KEY, base_payload)
        else:
            # Fallback to cerebras for unknown providers
            return self._call_openai_compatible_api(CEREBRAS_API_URL, CEREBRAS_API_KEY, base_payload)


def flag_messages(messages: list[str], waived_people_names: list[str], local: bool = False) -> str:

    llama = "llama-3.3-70b"
    hermes = "hermes-3-llama-3.2-3b"
    router = ModelRouter()

    # System message: task and rules
    # Optimized via prompt evolver system
    system_message = (
        "You will receive a time-ordered list of Cosmoteer Discord messages.\n\nYour single job is to decide, message-by-message, whether a line is an unsolicited “cheap shot” that should be flagged.\n\nDefinition – a flaggable “cheap shot” is a clear, uninvited insult or sneer directed at another present user (or their ship / playstyle) that supplies zero real help.\n\n────────────────────────────────\nA. FLAG ONLY IF EVERY CHECK IS YES\n1. Tone Unmistakable insult, ridicule, put-down, or dismissal  \n   • “skill issue”, “still trash”, 🙄 gifs, etc.  \n2. Target A specific, identifiable user, their just-posted ship, or their current strategy  \n   • Must be obvious via mention, reply, or context in the same thread.  \n3. Help Contains no concrete fix, reason, or genuine question  \n   • Buzz like “just kite” or “git gud” counts as NO help.  \n4. Consent Harshness wasn’t clearly invited (no “roast me”, not in a roast or critique request).  \n5. Perspective Speaker is judging someone else (not self-criticism).  \n6. Certainty You are ≥90 % sure it is a jab; when uncertain, do NOT flag.\n\n────────────────────────────────\nB. DO NOT FLAG IF ANY OF THESE APPLY\n1. The message offers at least one actionable suggestion, explanation, or honest question.  \n2. The recipient explicitly asked for critique or a roast, or the channel is for build help.  \n3. The negativity is about the game, devs, bots, or other non-present targets.  \n4. Pure banter, puns, memes, hype, or word-play with no clear victim.  \n5. Clearly marked joke that removes the sting (e.g., /s, 😜, obvious meme).  \n6. Self-directed criticism only.  \n7. Target is ambiguous—err on the side of NOT flagging.\n\n────────────────────────────────\nC. QUICK TRIAGE FLOW\n0. Is there a clear target?  If NO → ignore.  \n1. Is it a negative jab?  \n2. Aimed at that target?  \n3. Was harshness invited? (YES → ignore)  \n4. Any specific help? (YES → ignore)  \n5. Are you ≥90 % sure it’s a jab?  \nIf answers are YES, YES, YES, NO, NO, YES → Flag.\n\n────────────────────────────────\nD. EXAMPLES\nFlag:  \n• “cope lol”  \n• “Still garbage, learn to build.”  \n• “No, you’re using interceptors wrong. Giga harass + backshots.” ← vague, no fix  \n• “truly a competitive builder moment”  \n• “still just as bad as the first time ;)”\n\nIgnore:  \n• “Was your ship not centered when you built it?” (genuine question)  \n• “Pretty good, but fill the gaps with armour.” (gives fix)  \n• “evil and fuc̈ked up” (no clear victim)  \n• “To be railed forever” (pun, no target)  \n• “Unpractical—also removes your best side ram.” (gives reason)\n\n────────────────────────────────\nTHINKING GUIDELINES\n• First locate an explicit target; if none, stop.  \n• Distinguish playful teasing from real digs; flag only when the sting outweighs any help.  \n• Prioritise precision over volume—better to miss a borderline jab than to flag normal critique."
    )

    # User message: actual Discord messages to analyze
    user_message = f"""Conversation Analysis Task:
Please analyze the following conversation and identify any messages that violate community guidelines.

Messages are in the format "(index) user: ❝content❞":
<discord_messages>
{chr(10).join(messages)}
</discord_messages>

For each flagged message, output a dict with:
- index: The message index.
- confidence: "high", "medium", or "low" (based on clarity/severity/ambiguity).
- target_user: The display name of the user the criticism is directed at, or 'Unknown' if unclear. Default to 'Unknown' unless it's clear who the criticism is directed at.

Return a list of these dicts. If no messages are problematic, return an empty list.

Provide your response in the following format:
<analysis>
[Your step-by-step analysis starting with the potentials and flow-chart question answering to get to a final list]
</analysis>

<result>
[your list of dicts here]
</result>
"""

    response = router.generate_content(
        model=(llama if not local else hermes),
        system_message=system_message,
        user_message=user_message,
        config={"temperature": 0.0}
    )
    return response


def filter_flagged_messages(flagged_list: list[dict], waived_people_names: list[str], present_people_names: list[str]) -> list[dict]:
    """
    Filter out flagged messages where the target_user is in the waived people list, unknown, or not present in the conversation.
    If present_people_names is empty, skip the present people check.
    """
    def is_valid_target(target_user: str) -> bool:
        if not target_user or target_user.strip().lower() == 'unknown':
            return False
        if target_user in waived_people_names:
            return False
        if present_people_names:
            return target_user in present_people_names
        return True

    return [
        msg for msg in flagged_list
        if is_valid_target(msg.get('target_user'))
    ]

def flag_messages_in_thread(thread: discord.Thread, messages: list[str], waived_people_names: list[str]) -> str:
    thread_info = f"Thread Title: {thread.name}\n"
    
    first_message = thread.starting_message
    
    if first_message and first_message.content not in ''.join(messages):
        thread_info += f"First Thread Message: {first_message.author.display_name}: ❝{first_message.content}❞\n...\n"
    
    messages_with_context = [thread_info] + messages
    
    return flag_messages(messages_with_context, waived_people_names)



def extract_flagged_messages(llm_response: str) -> list[dict[str, Any]]:
    try:
        llm_response = llm_response.split('</analysis>')[-1].strip()
        result_pattern = r'<result>\s*(\[.*?\])\s*</result>'
        match = re.search(result_pattern, llm_response, re.DOTALL)
        if match:
            result_str = match.group(1).strip()
            if result_str:
                # Use ast.literal_eval for safety
                import ast
                flagged_list = ast.literal_eval(result_str)
                if isinstance(flagged_list, list):
                    return flagged_list
    except Exception as e:
        print(f"Error extracting flagged messages: {e}")
        return None
    return []



def filter_confidence(flagged_list: list[dict], confidence_threshold: str) -> list[dict]:
    """
    Filter flagged messages by confidence threshold.
    """
    valid_thresholds = {'low': ['low', 'medium', 'high'],
                        'medium': ['medium', 'high'],
                        'high': ['high']}
    if confidence_threshold not in valid_thresholds:
        raise ValueError(f"Invalid confidence threshold: {confidence_threshold}")
    allowed = valid_thresholds[confidence_threshold]
    return [msg for msg in flagged_list if msg.get('confidence') in allowed]


async def generate_user_feedback_message(message_strs: list[str], message_indexes: list[int], guidelines: str) -> str:
    """Generate feedback message using the ModelRouter with an OpenAI-compatible API."""
    router = ModelRouter()
    
    system_message = """You are a Discord moderator providing brief warnings/reminders for messages that violate community guidelines. Keep your response concise and constructive, while in a casual tone. Three sentences most."""
    
    user_message = f"""
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

Format your response within <response> tags.

<response>
[Your feedback here]
</response>
    """.strip()

    response_text = router.generate_content(
        model="llama3.1-8b",
        system_message=system_message,
        user_message=user_message,
        config={"temperature": 0.6}
    )

    match = re.search(r'<response>(.*?)</response>', response_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""
