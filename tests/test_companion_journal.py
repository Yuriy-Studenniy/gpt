from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from companion_runtime.journal import (
    CompanionJournal,
    IdempotencyConflict,
    JournalError,
)


class CompanionJournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "memory.sqlite3"
        self.journal = CompanionJournal(self.database)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def append(self, message_id: str, content: str = "hello", speaker: str = "player"):
        return self.journal.append_message(
            conversation_id="campaign-1",
            message_id=message_id,
            speaker=speaker,
            content=content,
        )

    def test_append_order_and_read_after_reopen(self) -> None:
        first = self.append("msg-1", "first")
        second = self.append("msg-2", "second", "companion")
        self.assertEqual((first.sequence, second.sequence), (1, 2))

        reopened = CompanionJournal(self.database)
        rows = reopened.list_messages("campaign-1", limit=10)
        self.assertEqual([row.content for row in rows], ["first", "second"])
        self.assertEqual(reopened.conversation_info("campaign-1")["message_count"], 2)

    def test_idempotent_retry_returns_original_sequence(self) -> None:
        first = self.append("stable-id", "same payload")
        retry = self.append("stable-id", "same payload")
        self.assertEqual(first.sequence, retry.sequence)
        self.assertTrue(retry.duplicate)
        self.assertEqual(self.journal.conversation_info("campaign-1")["message_count"], 1)

    def test_reusing_id_for_different_payload_is_rejected(self) -> None:
        self.append("stable-id", "original")
        with self.assertRaises(IdempotencyConflict):
            self.append("stable-id", "changed")

    def test_messages_are_append_only(self) -> None:
        self.append("immutable")
        with sqlite3.connect(self.database) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE messages SET content = 'rewritten' WHERE message_id = 'immutable'"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM messages WHERE message_id = 'immutable'"
                )

    def test_recent_limit_and_before_sequence(self) -> None:
        for index in range(1, 6):
            self.append(f"m-{index}", str(index))
        recent = self.journal.list_messages("campaign-1", limit=2)
        before = self.journal.list_messages(
            "campaign-1", limit=10, before_sequence=4
        )
        self.assertEqual([row.sequence for row in recent], [4, 5])
        self.assertEqual([row.sequence for row in before], [1, 2, 3])

    def test_idempotent_retry_cannot_cross_scope(self) -> None:
        self.journal.append_message(
            conversation_id="campaign-1",
            scope_id="save-A",
            speaker="player",
            content="hello",
            message_id="scope-retry",
        )
        with self.assertRaises(JournalError):
            self.journal.append_message(
                conversation_id="campaign-1",
                scope_id="save-B",
                speaker="player",
                content="hello",
                message_id="scope-retry",
            )

    def test_scope_cannot_change_inside_conversation(self) -> None:
        self.journal.append_message(
            conversation_id="campaign-1",
            scope_id="save-A",
            speaker="player",
            content="hello",
            message_id="scope-1",
        )
        with self.assertRaises(JournalError):
            self.journal.append_message(
                conversation_id="campaign-1",
                scope_id="save-B",
                speaker="player",
                content="again",
                message_id="scope-2",
            )

    def test_parallel_appends_get_unique_sequences(self) -> None:
        def write(index: int):
            return self.journal.append_message(
                conversation_id="parallel",
                message_id=f"parallel-{index}",
                speaker="engine",
                content=str(index),
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = list(pool.map(write, range(18)))
        self.assertEqual(sorted(row.sequence for row in rows), list(range(1, 19)))

    def test_integrity_check(self) -> None:
        self.append("check-1")
        self.assertEqual(self.journal.integrity_check(), ["ok"])


if __name__ == "__main__":
    unittest.main()
