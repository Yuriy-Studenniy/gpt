from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from companion_runtime.runtime import CompanionRuntime, run_stdio


class CompanionRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "runtime.sqlite3"
        self.runtime = CompanionRuntime(self.database)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def request(self, request_id: str, op: str, payload=None):
        return self.runtime.handle_request(
            {"request_id": request_id, "op": op, "payload": payload or {}}
        )

    def test_health_echoes_request_id(self) -> None:
        response = self.request("health-1", "health")
        self.assertEqual(response["request_id"], "health-1")
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["storage"], "sqlite")

    def test_append_retry_and_read(self) -> None:
        payload = {
            "conversation_id": "campaign-1",
            "scope_id": "save-slot-1",
            "speaker": "player",
            "content": "We agreed to visit Skadovsk.",
            "message_id": "msg-stable-1",
            "source": "external_dialog",
            "metadata": {"topic": "plan"},
        }
        first = self.request("append-1", "append_message", payload)
        retry = self.request("append-2", "append_message", payload)
        self.assertTrue(first["ok"])
        self.assertTrue(retry["ok"])
        self.assertFalse(first["result"]["duplicate"])
        self.assertTrue(retry["result"]["duplicate"])
        self.assertEqual(first["result"]["sequence"], retry["result"]["sequence"])

        recent = self.request(
            "recent-1",
            "list_messages",
            {"conversation_id": "campaign-1", "limit": 10},
        )
        self.assertEqual(recent["request_id"], "recent-1")
        self.assertEqual(len(recent["result"]), 1)
        self.assertEqual(recent["result"][0]["content"], "We agreed to visit Skadovsk.")

    def test_unknown_operation_returns_structured_error(self) -> None:
        response = self.request("bad-op", "delete_all")
        self.assertEqual(response["request_id"], "bad-op")
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["type"], "JournalError")

    def test_stdio_handles_bad_json_and_keeps_serving(self) -> None:
        input_stream = io.StringIO(
            "{not json}\n"
            + json.dumps(
                {"request_id": "health-after-error", "op": "health", "payload": {}}
            )
            + "\n"
        )
        output_stream = io.StringIO()
        result = run_stdio(self.runtime, input_stream, output_stream)
        responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
        self.assertEqual(result, 0)
        self.assertEqual(len(responses), 2)
        self.assertFalse(responses[0]["ok"])
        self.assertEqual(responses[0]["error"]["type"], "invalid_json")
        self.assertEqual(responses[1]["request_id"], "health-after-error")
        self.assertTrue(responses[1]["ok"])


if __name__ == "__main__":
    unittest.main()
