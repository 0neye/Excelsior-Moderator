import os
import json
import asyncio
from typing import List, Dict, Optional
import discord
from config import EVALUATION_STORE_FILE, EVALUATION_RESULTS_FILE, MODERATOR_ROLES
from llms import flag_messages, extract_flagged_messages
from message_store import FlaggedMessageStore


class EvalHandler:
    def __init__(self, message_store: FlaggedMessageStore, filepath: str = EVALUATION_STORE_FILE):
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