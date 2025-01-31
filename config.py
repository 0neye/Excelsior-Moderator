import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
CEREBRAS_API_KEY = os.getenv('CEREBRAS_API_KEY')

# The text or forum channels to allow
excelsior = [546229904488923145, 1101149194498089051, 546327169014431746, 1240185912525324300, 546907635149045775, 546947839008440330]
CHANNEL_ALLOW_LIST = [1240462346808463362, 779084507768291379, 1077332289190625300] + excelsior

MODERATOR_ROLES = ["Sentinel (mod)", "Custodian (admin)"]

FLAGGED_MESSAGE_STORE_FILE = "flagged_messages.json"
EVALUATION_STORE_FILE = "convo_eval.json"
EVALUATION_RESULTS_FILE = "eval_results.md"

# How many message groups to wait for before sending them to the llm for moderation
MESSAGE_GROUPS_PER_CHECK = 10

# How many message groups of history to send to the llm for analysis
HISTORY_PER_CHECK = 25

# If there are new messages in a channel that haven't been checked, but not enough to trigger the above, check anyway after this time
# Resets after a new message, and doesn't trigger if all messages in channel have already been checked
SECS_BETWEEN_AUTO_CHECKS = 60

# The role for people who don't care about harsh feedback
WAIVER_ROLE_NAME = "Waiver"

# The guidelines for constructive criticism
GUIDELINES = """
__**Giving Feedback**__

To put this post in two sentences:

Make sure your feedback is __consented__.
Be __positive__ with that feedback.

When giving feedback, above all else, you want to be respectful. It's easy to point out a bunch of flaws in someone's build, especially if you're an experienced player, but that's not your goal unless that's what that player is specifically requesting. Please be mindful of this...pretty much always. Only give feedback on role requests, classroom posts, module posts, ship posts, idea posts, etc, in the way that is being requested, if at all. At the time of writing, this has been a huge issue for a while. Adhering to this rule will help solve that.

It's easy to say "your X is wrong" or "your layout is unoptimal", but these are all negative phrases. Feedback is the most useful to the most people when phrased positively. "I like the way you did "X" is a good optimistic comment you will always find yourself able to make about something. Include at least a few positive takeaways in your feedback as well as your suggested improvements - it shows that you recognize that you're talking to a person and not just grading their homework.

Additionally, try to focus on the *how* and *why* instead of just the *what*. Telling someone their crew management is bad doesn't help them improve. Instead phrase things like "instead of doing X, you could do Y which would be better because Z".
"""

GENERIC_PING_RESPONSE = "Hello! I'm a moderation bot helping find unconstructive criticism."


LOG_CHANNEL_ID = 1333899222541406310

# For dev testing
SEND_RESPONSES_TO_LOG_CHANNEL_ONLY = True

REACT_WITH_EMOJI_IF_NOT_RESPONDING = True
REACTION_EMOJI = "👁️"