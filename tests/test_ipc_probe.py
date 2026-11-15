from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from tools.gpt_companion_ipc_probe import run_probe


class IpcProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_round_trip_matches_request_id(self) -> None:
        command = self.root / "gpt_companion_ipc_cmd.txt"
        reply = self.root / "gpt_companion_ipc_reply.txt"

        def fake_game() -> None:
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if command.is_file():
                    payload = command.read_text(encoding="ascii")
                    fields = payload.strip().split()
                    if len(fields) == 3:
                        request_id = fields[1]
                        command.unlink(missing_ok=True)
                        temp_reply = self.root / "gpt_companion_ipc_reply.tmp"
                        temp_reply.write_text(
                            f"v1 {request_id} ok pong_gpt_companion_ipc_probe_v1\\n",
                            encoding="ascii",
                        )
                        os.replace(temp_reply, reply)
                        return
                time.sleep(0.01)

        worker = threading.Thread(target=fake_game, daemon=True)
        worker.start()
        result = run_probe(self.root, timeout=2.0)
        worker.join(timeout=1.0)
        self.assertEqual(result, 0)
        self.assertFalse(command.exists())
        self.assertFalse((self.root / "gpt_companion_ipc_cmd.tmp").exists())

    def test_timeout_preserves_command_and_status(self) -> None:
        status = self.root / "gpt_companion_ipc_status.txt"
        status.write_text("state=lua_hook_active\\n", encoding="ascii")

        result = run_probe(self.root, timeout=0.1)

        command = self.root / "gpt_companion_ipc_cmd.txt"
        self.assertEqual(result, 1)
        self.assertTrue(command.exists())
        self.assertEqual(status.read_text(encoding="ascii"), "state=lua_hook_active\\n")
        self.assertEqual(len(command.read_text(encoding="ascii").strip().split()), 3)
        self.assertFalse((self.root / "gpt_companion_ipc_cmd.tmp").exists())

    def test_existing_pending_command_is_not_overwritten(self) -> None:
        command = self.root / "gpt_companion_ipc_cmd.txt"
        command.write_text("v1 pending ping\\n", encoding="ascii")

        result = run_probe(self.root, timeout=0.1)

        self.assertEqual(result, 2)
        self.assertEqual(command.read_text(encoding="ascii"), "v1 pending ping\\n")


if __name__ == "__main__":
    unittest.main()
