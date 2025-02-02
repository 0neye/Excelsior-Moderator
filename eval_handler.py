import os
import json
import asyncio
from typing import List, Dict, Optional
import discord
from config import EVALUATION_STORE_FILE, EVALUATION_RESULTS_FILE, MODERATOR_ROLES
from llms import flag_messages, extract_flagged_messages


class EvalHandler:
    def __init__(self, message_store, filepath: str = EVALUATION_STORE_FILE):
        self.message_store = message_store
        self.eval_cases_file = filepath
        self._ensure_eval_file_exists()

    def _ensure_eval_file_exists(self):
        if not os.path.exists(self.eval_cases_file):
            with open(self.eval_cases_file, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def _load_eval_cases(self) -> List[Dict]:
        try:
            with open(self.eval_cases_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []

    def _save_eval_cases(self, eval_cases: List[Dict]):
        with open(self.eval_cases_file, 'w', encoding='utf-8') as f:
            json.dump(eval_cases, f, indent=4)

    def add_eval_case(self, message_id: int, correct_outcome: bool) -> bool:
        """Add or update an evaluation test case. Returns True if added, False if updated."""
        flagged = self.message_store.get_flagged_message(message_id)
        if flagged is None:
            # Flagged message not found; nothing to add.
            return False

        test_case = {
            "message_id": flagged["message_id"],
            "history": flagged.get("history", []),
            "waived_people": flagged.get("waived_people", []),
            "relative_id": flagged.get("relative_id"),
            "correct_outcome": correct_outcome
        }
        eval_cases = self._load_eval_cases()
        for i, case in enumerate(eval_cases):
            if case.get("message_id") == message_id:
                eval_cases[i] = test_case
                self._save_eval_cases(eval_cases)
                return False
        eval_cases.append(test_case)
        self._save_eval_cases(eval_cases)
        return True

    def get_eval_case(self, message_id: int) -> Optional[Dict]:
        eval_cases = self._load_eval_cases()
        return next((case for case in eval_cases if case.get("message_id") == message_id), None)

    def get_eval_cases(self) -> List[Dict]:
        return self._load_eval_cases()

    async def run_eval_command(self, ctx: discord.ApplicationContext):
        # Check if the user has a moderator role
        if not any(role.name in MODERATOR_ROLES for role in ctx.author.roles):
            await ctx.respond("You do not have permission to run this command.", ephemeral=True)
            return

        # Send an initial ephemeral message
        initial_response = await ctx.respond("running eval...", ephemeral=True)
        try:
            eval_cases = self.get_eval_cases()
            results = []
            passed_count = 0

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
                    'waived_people': waived_people
                })

                progress_message = f"Processed {len(results)}/{len(eval_cases)} cases. Current pass rate: {passed_count/len(results):.2%}"
                await initial_response.edit(content=progress_message)
                await asyncio.sleep(1)

            total_cases = len(eval_cases)
            failed_count = total_cases - passed_count

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

            with open(EVALUATION_RESULTS_FILE, "w", encoding="utf-8") as f:
                f.write(md_content)

            overview = f"Evaluation complete: {total_cases} cases processed. {passed_count} passed, {failed_count} failed. Pass rate: {passed_count/total_cases:.2%}"
            await initial_response.edit(content=overview)
            await ctx.followup.send(file=discord.File(EVALUATION_RESULTS_FILE), ephemeral=True)
        except Exception as e:
            error_message = f"Error during evaluation: {e}"
            await initial_response.edit(content=error_message)
