from typing import Dict, List, Tuple
from cerebras.cloud.sdk import Cerebras
import discord
from config import CEREBRAS_API_KEY
import re

client = Cerebras(
    api_key=CEREBRAS_API_KEY
)

def flag_messages(messages: list[str], waived_people: list[discord.Member]) -> str:

    waived_people_names = [person.display_name for person in waived_people]

    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": f"""
You will be given a list of Discord messages related to a video game (Cosmoteer: Ship Architect and Commander). Your task is to identify messages that contain unsolicited and unconstructive criticism. 

Messages are in the format "(index) user: ❝content❞". Here is the list of messages:

<discord_messages>
{messages}
</discord_messages>

Analyze each message to determine if it contains either unsolicited and/or unconstructive criticism for the Cosmoteer.

**Flag messages with one of:**
1. Offers negative feedback (which may or may not include specific issues)
2. Focuses solely on flaws without acknowledging any positive aspects or providing encouragement (this is the most important)
3. Lacks specific suggestions to fix stated issues
4. Is a joke at someone elses expense

**Exemptions (do not flag messages with):**
1. The criticism references something or someone outside of the provided context
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

**Other considerations:**
- If it looks like someone is trying to defend themselves from someone elses criticism or comment instead of discussing as equals, then the criticism, comment, or joke is likely problematic.
- If someone did not explicitely ask for (solicit) criticism, then hold any comments on their designs, descriptions, or opinions to a higher standard. Anything that violates one of the bullet points for unconstructive criticism should be flagged.

**Response Format**
Create a list of indexes for messages that contain unsolicited and unconstructive criticism. If no messages are problematic, return an empty list.
Take into account other messages by the same user to determine whether to flag a specific one. If that user included only negative criticism in one message, but positive in another, don't flag either.

For each flagged message, assign a confidence level:
 - "high": Clear violation with obvious targeting of users/work
 - "medium": Likely problematic but contains some ambiguity
 - "low": Potentially problematic but requires more context

Provide your response in the following format:
<analysis>
[each bullet point in the flag/not flag lists and the messages that might apply to each]
[your thoughts on which messages to flag given whether they meet a criteria or exception]
</analysis>

The result should be in result tags and contain a valid python dictionary.
<result>
{{"message_ids": [list of indexes], "confidence": {{"index": "confidence_level", ...}}}}
</result>

**Best In Class Examples:**

Example 1:
<example_messages>
(0) [reply to 5] Antithesis [M]: ❝It's still useful on avoiders but in top meta terms no it's useless lol❞
(1) piNck: ❝😔
I loved auxillary boost.❞
(2) Antithesis [M]: ❝They just lack consistency that top meta ships need❞
(3) piNck: ❝You guys' rampdown abuse ships caused the nerf >:[❞
(4) Antithesis [M]: ❝Ya know what's funny
The boost "nerf" was actually a huge buff to boost avoiders xd❞
(5) piNck: ❝For the love of god.
Why because now the not being used but active boost lingers for longer, right?
That was my suggestion :>❞
(6) Antithesis [M]: ❝That's exactly why
Boost avoiders don't need 8 batteries of boost power, they like being able to boost for shorter periods multiple times❞
(7) piNck: ❝Get me a spot on the council 😉❞
(8) Antithesis [M]: ❝Also, the smaller battery capacity makes them recharge to full faster❞
(9) piNck: ❝Battery nerf was to make up for the full charge requirement.❞
(10) Antithesis [M]: ❝Alpha ships didn't like that one <:agony:547055653194170381>❞
(11) piNck: ❝Yup.
Very sad.
But those plausine boost only abominations got curbed, so GUD❞
(12) Antithesis [M]: ❝My flak v 😭❞
(13) piNck: ❝You killed that thing, YOU are to blame.
Omg ellie is back from her sexy beach vacation in brazil!❞
[reactions: 👁️ 6]
(14) lets get µnbanned: ❝i need to friend request ellie❞
(15) expewt: ❝true
<@1333546604694732892> hi❞
(16) [reply to 4] TheFish28: ❝Boost nerf made boost unusable in dom btw
But mrt is in a fine state atm it's used along supplemental turning thrust on most ships with 1 exception and I think that's fine❞
(17) Antithesis [M]: ❝ul nuke should be solved with a nuke nerf rather than an mrt nerf❞
(18) expewt: ❝ul nuke should be solved with a nuke ~~nerf~~ rebalance \*and* an mrt ~~nerf~~ rebalance❞
[reactions: ❌ 1]
(19) Antithesis [M]: ❝mrt is mostly fine imo just a bit overtuned on the amount of thrust it provides, but that's less of an mrt exclusive issue and more of a thrust power creep issue
hybrid thrust is viable at the moment and we do not want to change that❞
(20) expewt: ❝i suppose❞
(21) [reply to 17] TheFish28: ❝Make sure you are also tackling the issues large shields present without changing the actual nuke mechanics and I'm likely to be on board
At least imo that's the best way to nerf them❞
(22) Salephz: ❝what are LS issues? i'm washed❞
(23) CoconutTrebuchet: ❝large shield issues?❞
(24) [reply to 18] Nightlord: ❝Large shields are perfect like that.
Maybe play the game and then provide advice?❞
</example_messages>
<example_response>
<analysis>
Flagging criteria:
1. Offers negative feedback: Not applicable to any messages.
2. Focuses solely on flaws: Message 24 violates this by dismissing the other user's opinion without offering constructive feedback.
3. Lacks specific suggestions: Message 24 fails to provide any specific suggestions for improvement.
4. Joke at someone's expense: Message 13 contains a mild joke blaming another user for an in-game change.

Exemptions:
1. Criticism references something outside context: Not applicable.
2. Contains enough positive feedback: Most messages (0-12, 14-23) contain balanced or constructive discussions.
3. Person asking is ok with harsh criticism: Not mentioned in the context.
4. Self-criticism: Not present in any messages.
5. Criticism directed at the game or absent parties: Messages 16-21 discuss game mechanics without targeting individuals.
6. Sarcasm: No clear indicators of sarcasm in flagged messages.
7. Pre-opted-in users: No information provided about waived users.

Other considerations:
- Message 13 is a borderline case, as it's a mild joke but directly blames another user.
- Message 24 clearly violates multiple criteria for constructive criticism.

Messages 0-12 and 14-23 are exempt as they contain constructive discussions or neutral comments about game mechanics and balance.

Analysis:
Message 13 is a borderline case, as it's a mild joke, but it directly blames another user. It's assigned a low confidence.
Message 24 is clearly unconstructive and dismissive, warranting a high confidence flag.

</analysis>
<result>
{{"message_ids": [13, 24], "confidence": {{13: "low", 24: "high"}}}}
</result>
</example_response>

Example 2:
<example_messages>
(0) CoconutTrebuchet: ❝but i mean definitions change over time
these days, people say squib for any small ship that is intended to navigate to an opponent's exposed areas❞
(1) [reply to 5] TheFish28: ❝They are just awful in elim tho
So the definition changed bc nobody was using it❞
(2) ∛3 Circles(ℏ): ❝wwwhat are they then❞
(3) CoconutTrebuchet: ❝yeah heres the fun thing
we dont have a name for them yet
even though spinner squib is literally meta 😭❞
(4) [reply to 2] TheFish28: ❝Interceptor❞
(5) ∛3 Circles(ℏ): ❝fym 😭❞
(6) CoconutTrebuchet: ❝who the heck is calling them spinner-interceptor❞
(7) j_yukki (fe rammer specialist): ❝they are called interceptors
that is for sure❞
(8) ∛3 Circles(ℏ): ❝why does almost nobody use that name then❞
[reactions: ⬆️ 1]
(9) j_yukki (fe rammer specialist): ❝bc squibs are catchier
idrc❞
(10) [reply to 6] TheFish28: ❝If that ship was in dom standalone I'd call it a interceptor
Bc players better than me used it❞
(11) [reply to 8] j_yukki (fe rammer specialist): ❝because newgens
xd❞
(12) ∛3 Circles(ℏ): ❝im just going to use whatever is more widely recognized 😭❞
(13) j_yukki (fe rammer specialist): ❝also they called it spinner squib which kinda caused all of it❞
(14) CoconutTrebuchet: ❝and plus i feel like the name changes based on *how* you use the ship, like i said
an interceptor in dom is a fast, multi-tool ship that can cap points and fight other dom ships head on
a squib is intended to circle a larger opponent and exploit weaknesses❞
(15) j_yukki (fe rammer specialist): ❝i wonder how air let that happen❞
(16) [reply to 14] TheFish28: ❝No your using interceptors in dom wrong
They do the same thing in both
Giga harass + backshots❞
(17) ∛3 Circles(ℏ): ❝💀❞
(18) TheFish28: ❝Shrimple❞
(19) j_yukki (fe rammer specialist): ❝<@652322179572301842> did you say anything when slowking tried to call spinner squib instead of spinner interceptor or did it js slip past you❞
(20) CoconutTrebuchet: ❝if you wanted to counter 2DC, why would you play an interceptor like a squib when you can just use nukes❞
(21) [reply to 20] j_yukki (fe rammer specialist): ❝nukes are far far less versatile❞
(22) CoconutTrebuchet: ❝true true❞
(23) [reply to 17] TheFish28: ❝That's the nicer way of saying what tonie thinks they do theory wise❞
(24) j_yukki (fe rammer specialist): ❝also interceptors arent a 2dc counter
thats not what he said❞
</example_messages>
<example_response>
<analysis>
Flagging criteria:
1. Offers negative feedback: Message 16 offers negative feedback by stating "No your using interceptors in dom wrong".
2. Focuses solely on flaws: Message 16 focuses solely on the perceived incorrect usage without offering constructive advice.
3. Lacks specific suggestions: Message 16 does explain the correct usage, but not in a helpful way.
4. Joke at someone's expense: Message 18 contains a joke ("Shrimple") that, in context, appears to be at the expense of the person who was just criticized.

Exemptions:
1. Criticism references something outside context: Not applicable.
2. Contains enough positive feedback: Messages 16 and 18 do not contain any positive feedback to balance the criticism.
3. Person asking is ok with harsh criticism: Not mentioned in the context.
4. Self-criticism: Not present in any messages.
5. Criticism directed at the game or absent parties: Not applicable, as the criticism is directed at another user's understanding.
6. Sarcasm: No clear indicators of sarcasm in the flagged messages.
7. Pre-opted-in users: No information provided about waived users.

Other considerations:
- The conversation is generally a discussion about game terminology and mechanics.
- Most messages contain constructive discussion, but messages 16 and 18 stand out as potentially unconstructive.

Analysis:
Messages 16 and 18 violate multiple criteria for constructive criticism. Message 16 directly tells another user they are wrong without offering a balanced perspective or specific suggestions for improvement. The tone is somewhat dismissive. Message 18 follows up with a joke ("Shrimple") that, in this context, appears to be making light of the other user's perceived lack of understanding. Together, these messages create an unconstructive interaction that could be perceived as belittling in the context of a discussion about game mechanics.

</analysis>
<result>
{{"message_ids": [16, 18], "confidence": {{16: "high", 18: "medium"}}}}
</result>
</example_response>

Example 3:
<example_messages>
(0) CoconutTrebuchet: ❝im also sorry for causing a tangent in your role app (i know i myself get annoyed when people go on a tangent in my classroom posts or role requests)❞,
(1) Volkhat: ❝Ah, no problem. It is interesting to see it lol.\nHere is for when I applied for Expert, but this was after I got adept \n\nhttps://discord.com/channels/546229904488923141/546946524265971714/1014216283069370548\nHere when I requested Adept:\nhttps://discord.com/channels/546229904488923141/546946524265971714/1001648433716805732❞,
(2) CoconutTrebuchet: ❝i like your msf\nfrom the OG adept req❞,
(3) Volkhat: ❝Here:\nhttps://discord.com/channels/546229904488923141/546946524265971714/1005568734250930197❞,
(4) CoconutTrebuchet: ❝ye❞,
(5) Volkhat: ❝That was my second attempt at getting Adept.❞,
(6) [reply to @CoconutTrebuchet] expewt: ❝https://tenor.com/view/guh-gif-25116077\nwhy is that relevant❞,
(7) [reply to CoconutTrebuchet] Volkhat: ❝Just don't try to piss me, Air.\nNo problem, I will be waiting for your feedback.❞ (edited),
(8) [reply to 7] expewt: ❝i am not❞,
(9) Volkhat: ❝Ok❞,
(10) [reply to 7] CoconutTrebuchet: ❝(i get home an hour from now :p)❞ (edited),
(11) Dyno: ❝\n❞,
(12) LunastroD ions :3 [M]: ❝rules 2,5,6,7❞,
(13) [reply to @Role Voting] expewt: ❝that is not a beginner and feedback was specifically not requested\narguably less helpful is ok?❞\n[reactions: 👁️ 1],
(14) [reply to @expewt] LunastroD ions :3 [M]: ❝don't be mean... I know volkhat played in the past but you're making people unconfortable and you keep going\nnot just in the role request❞,
(15) expewt: ❝wdym\nthat is not to be mean\ngenerally people improve over time\nimo logistics on newer ships are not as good as the classic ones❞,
(16) [reply to 15] [E] THETA: ❝intentions don't always translate over into what actually happens\nyou may not intend to be mean, but the words that you actually type turn out to be far less polite or kind than intended❞,
(17) [reply to @Volkhat] CoconutTrebuchet: ❝Railfan:\n- Colossal amount of ammo you have here lol. The factory : rail ratio is very good by classic standards; but going forward with your future railfans I would strongly recommend using one 2x3 storage of ammo per 2 rails.\n- If you insist on going with a factory setup while you adjust to modern mechanics, then you can safely cut down a ton of your sulphur and still have nearly infinite ammo (in the scope of a 1.5mil elim lobby). I think that one 3x4 storage per side of the railfan is a good start.\n- You have a ton of internal armor on the railfan. I would distribute some of it to the sides and back to outlive rams better.\n- I don't think you need a whole bridge in the top module. I will describe how to know \n\nMorbiter:\n- That is a very, very exposed bridge lol.\n\n- Your ship only uses 342 crew points, meaning that you can save a ton of credits by just using one CR and a cockpit. The way you know how many crew points you should use is to pay attention to the CP bar (a ss of it is attached in the image) and only spending just enough to keep the bar above zero to the best of your ability\n\n- Missile module-- i thought it was cute that you tried to retrofit the classic modules into modern, but sadly, having the Fe/S storages this far away from the factories isn't very good. Think of it like how new players put their factories at the center of thier ship instead of adjacent to the launchers.\n- Your 30 launchers is definetly overwhelming, but i feel like you are better off shaving away one module (in total,) for some more armor\n [uploaded attachment/image]\nthe most important thing to take away is to not just use a bridge every time\npay attention to how much CP your ship's parts use, and only buy just enough control rooms or cockpits to keep the bar above zero❞ (edited),
(18) Volkhat: ❝It was more by symetry and space rather than another thing.\nI think I did a new variant a few days ago, I am playing World Of Warplanes. But later I submit it.\nAlso the railfan got currently improved yesterday, I just haven't submitted it yet.❞\n[reactions: 👍 1],
(19) [reply to 18] CoconutTrebuchet: ❝__Archetypes I recommend building to help transition into modern__\n- DC bricks: easy af to pilot, but also introduces parts and building concepts unique to modern like deck cannons and storage-based logi\n- TB rail: a nice, familiar face from classic with further developments going into modern. very high skill floor and ceiling but (supposedly) playing this is very good for improving overall piloting\n- Morbiters: I will miss the classic missile modules, but i would take a look at what a modern module looks like. Since the resources were heavily reworked going into modern, missile modules also changed a lot. They will also introduce you to using LS in your designs.\nfor symmetry, I would still recommend using 2 CRs than a whole bridge, because of the ~~sheer amount of credits you save~~ *reasonable amount of credits you save from crew\n(i forgor that the two individual parts are both the same cost <:agony:547055653194170381>)\nbut ideally you want to go with one CR and up to 2 cockpits\nsadly, you will have to look past the L symmetry❞ (edited),
(20) [reply to 19] Volkhat: ❝Ah, I was thinking in use them yes. I didn't because people starts to complain lol.❞,
(21) CoconutTrebuchet: ❝oh yeah people dont really care about perfect symmetry anymore lmao\njust see what modern ~~fastwalls~~ avoiders look like\n(this is a shitty avoider but at least its an example of one)\n [uploaded attachment/image]\nbut yeah, people literally make it very slightly asymmetric❞ (edited),
(22) expewt: ❝still just as bad as the first time ;)\nthe 3 mr thrust block has also gotten a lot more popular\nlots of relatively niche optimizations like ul and whatnot become more mainstream❞\n[reactions: 👁️ 1],
(23) Volkhat: ❝\n [uploaded attachment/image]\n\n [uploaded attachment/image]❞
</example_messages>
<example_response>
<analysis>
Flagging criteria:
1. Offers negative feedback: Message 22 offers negative feedback by stating "still just as bad as the first time ;)".
2. Focuses solely on flaws: Message 22 focuses on perceived flaws without offering constructive advice.
3. Lacks specific suggestions: While mentioning some changes, message 22 doesn't provide specific suggestions for improvement.
4. Joke at someone's expense: The winking face ";)" could be interpreted as making light of the situation.

Exemptions:
1. Criticism references something outside context: Not applicable.
2. Contains enough positive feedback: Message 22 does not contain any positive feedback to balance the criticism.
3. Person asking is ok with harsh criticism: No information provided about waived users.
4. Self-criticism: Not present in the message.
5. Criticism directed at the game or absent parties: The criticism appears to be directed at Volkhat's design.
6. Sarcasm: The message may contain sarcasm, but it's still hurtful, especially since they were just warned about their behavior by moderators ([M] tagged users).
7. Pre-opted-in users: No information provided about waived users.

Other considerations:
- The conversation is generally constructive, with users providing feedback and suggestions.
- Message 22 stands out as potentially unconstructive compared to the rest of the conversation.

Analysis:
Message 22 violates multiple criteria for constructive criticism. It starts with a negative comment about the design being "still just as bad as the first time", which is neither constructive nor encouraging. While it does mention some changes in the game, it doesn't provide specific suggestions for improvement related to these changes. The tone of the message, especially with the winking face, could be perceived as dismissive or mocking. This type of feedback could discourage the user from seeking further advice or participating in discussions.

</analysis>
<result>
{{"message_ids": [22], "confidence": {{22: "high"}}}}
</result>
</example_response>
""".strip(),
            }
    ],
        model="llama3.3-70b",
        temperature=0.2
    )

    return chat_completion.choices[0].message.content


def flag_messages_in_thread(thread: discord.Thread, messages: list[str], waived_people: list[discord.Member]) -> str:
    thread_info = f"Thread Title: {thread.name}\n"
    
    first_message = thread.starting_message
    
    if first_message and first_message.content not in ''.join(messages):
        thread_info += f"First Thread Message: {first_message.author.display_name}: ❝{first_message.content}❞\n...\n"
    
    messages_with_context = [thread_info] + messages
    
    return flag_messages(messages_with_context, waived_people)



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
    
    return [idx for idx, conf in confidence.items() if conf in valid_thresholds[confidence_threshold]]


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
