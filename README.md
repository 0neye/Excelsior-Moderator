## Excelsior Moderation Assistant (AKA Ellie)

A system that attempts to spot unconstructive and/or unsolicited feedback by monitoring Discord messages in real-time.
Logs suspected message groups to a moderator log channel. Can also publicly react or respond to suspected message groups.

**Includes:**
- Timer-based and message-number-based channel checking to balance speed and API calls
- Includes channel context to help the LLM determine intent
- A waiver role and accompanying filtering system for people to opt out of criticism "protection"
- A confidence level system to reduce false positives
- An evaluation set updated by moderator feedback
- Manual flagging by moderators adds messages to the eval set when the AI doesn't catch them

**Examples:**
<img width="1586" height="888" alt="image" src="https://github.com/user-attachments/assets/a4fb0a94-100d-4ce5-abce-4050f3ffe7e6" />
<img width="970" height="796" alt="image" src="https://github.com/user-attachments/assets/cf9740d5-143a-4d81-84c2-5b0bf5e921a2" />


**What can be improved (but probably won't unless someone wants to):**
- An actual DB instead of json files
- De-cluttering the code
- Ditching the message cluster idea (it confuses people when the wrong message is reacted to)
- Using a larger model through cerebras; they've added a lot more since I last optimized the prompt and it might improve accuracy
