#!/usr/bin/env python3
"""Внешний процесс Companion Runtime с API JSON-lines.

Процесс управляет журналом SQLite, но не загружает игровые модули, не обращается
к сети и не вызывает LLM. На каждый входящий JSON-объект выдаётся один JSON-
ответ с тем же request_id.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional, TextIO

from .journal import (
    SCHEMA_VERSION,
    CompanionJournal,
    JournalError,
)


MAX_REQUEST_LINE = 1_000_000


class CompanionRuntime:
    def __init__(self, database_path: str | Path) -> None:
        self.journal = CompanionJournal(database_path)

    @staticmethod
    def _error(request_id: Optional[str], error_type: str, message: str) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "ok": False,
            "error": {"type": error_type, "message": message},
        }

    def handle_request(self, request: Any) -> dict[str, Any]:
        request_id: Optional[str] = None
        try:
            if not isinstance(request, dict):
                raise JournalError("запрос должен быть JSON-объектом")
            raw_id = request.get("request_id")
            if not isinstance(raw_id, str) or not raw_id.strip() or len(raw_id) > 160:
                raise JournalError("request_id должен быть непустой строкой длиной не более 160 символов")
            request_id = raw_id.strip()

            operation = request.get("op")
            if not isinstance(operation, str):
                raise JournalError("op должен быть строкой")
            payload = request.get("payload", {})
            if not isinstance(payload, dict):
                raise JournalError("payload должен быть JSON-объектом")

            if operation == "health":
                result: Any = {
                    "runtime": "companion_runtime",
                    "schema_version": SCHEMA_VERSION,
                    "storage": "sqlite",
                }
            elif operation == "append_message":
                record = self.journal.append_message(
                    conversation_id=payload.get("conversation_id"),
                    scope_id=payload.get("scope_id", "default"),
                    speaker=payload.get("speaker"),
                    content=payload.get("content"),
                    message_id=payload.get("message_id"),
                    source=payload.get("source", "external_dialog"),
                    metadata=payload.get("metadata", {}),
                    created_at=payload.get("created_at"),
                )
                result = asdict(record)
            elif operation == "get_message":
                message_id = payload.get("message_id")
                record = self.journal.get_message(message_id)
                result = asdict(record) if record is not None else None
            elif operation == "list_messages":
                records = self.journal.list_messages(
                    payload.get("conversation_id"),
                    limit=payload.get("limit", 20),
                    before_sequence=payload.get("before_sequence"),
                )
                result = [asdict(record) for record in records]
            elif operation == "conversation_info":
                result = self.journal.conversation_info(
                    payload.get("conversation_id")
                )
            elif operation == "integrity_check":
                integrity = self.journal.integrity_check()
                result = {"integrity": integrity, "ok": integrity == ["ok"]}
            else:
                raise JournalError(f"неподдерживаемая операция: {operation}")

            return {"request_id": request_id, "ok": True, "result": result}
        except (JournalError, TypeError, ValueError) as exc:
            return self._error(request_id, type(exc).__name__, str(exc))
        except Exception as exc:
            # Одна ошибочная команда не должна завершать длительно работающий процесс.
            return self._error(request_id, "internal_error", str(exc))


def run_stdio(
    runtime: CompanionRuntime,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> int:
    """Обрабатывать JSON по одной строке до закрытия stdin."""
    for line_number, raw_line in enumerate(input_stream, start=1):
        if len(raw_line) > MAX_REQUEST_LINE:
            response = CompanionRuntime._error(
                None, "request_too_large", f"строка {line_number} превышает допустимый размер"
            )
        else:
            try:
                request = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                response = CompanionRuntime._error(
                    None, "invalid_json", f"строка {line_number}: {exc.msg}"
                )
            else:
                response = runtime.handle_request(request)
        output_stream.write(
            json.dumps(response, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            + "\n"
        )
        output_stream.flush()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data") / "companion_memory.sqlite3",
        help="путь к файлу журнала SQLite",
    )
    args = parser.parse_args(argv)
    try:
        runtime = CompanionRuntime(args.db)
        return run_stdio(runtime)
    except (OSError, JournalError) as exc:
        print(f"не удалось запустить Runtime: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
