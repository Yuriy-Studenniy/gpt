#!/usr/bin/env python3
"""Журнал AI Stalker Companion на SQLite с добавлением без перезаписи.

Модуль намеренно не зависит от игры, сети или LLM. Это граница долговременного
хранения этапа M2; IPC и адаптеры поставщиков моделей находятся отдельно.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional


SCHEMA_VERSION = 1
DEFAULT_DATABASE = Path("data") / "companion_memory.sqlite3"
ALLOWED_SPEAKERS = frozenset(
    {"player", "companion", "external_assistant", "npc", "engine"}
)


class JournalError(ValueError):
    """Базовый класс ошибок при некорректных операциях с журналом."""


class IdempotencyConflict(JournalError):
    """ID сообщения повторно использован для другого неизменяемого сообщения."""


@dataclass(frozen=True)
class MessageRecord:
    message_id: str
    conversation_id: str
    sequence: int
    speaker: str
    content: str
    created_at: str
    source: str
    metadata: dict[str, Any]
    duplicate: bool = False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _required_text(value: str, field: str, max_length: int = 4096) -> str:
    if not isinstance(value, str):
        raise JournalError(f"поле {field} должно быть строкой")
    value = value.strip()
    if not value:
        raise JournalError(f"поле {field} не должно быть пустым")
    if len(value) > max_length:
        raise JournalError(f"поле {field} превышает лимит в {max_length} символов")
    return value


class CompanionJournal:
    """Журнал SQLite с неизменяемыми сообщениями и идемпотентностью по ID."""

    def __init__(self, database_path: str | Path = DEFAULT_DATABASE) -> None:
        self.database_path = Path(database_path).expanduser()
        if str(self.database_path) != ":memory:":
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=10.0,
            isolation_level=None,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.execute("PRAGMA synchronous = NORMAL")
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    scope_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL
                        REFERENCES conversations(conversation_id),
                    sequence INTEGER NOT NULL CHECK(sequence > 0),
                    speaker TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    UNIQUE(conversation_id, sequence)
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conversation_sequence
                    ON messages(conversation_id, sequence DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_speaker_created
                    ON messages(speaker, created_at);

                CREATE TRIGGER IF NOT EXISTS messages_no_update
                BEFORE UPDATE ON messages
                BEGIN
                    SELECT RAISE(ABORT, 'сообщения доступны только для добавления');
                END;

                CREATE TRIGGER IF NOT EXISTS messages_no_delete
                BEFORE DELETE ON messages
                BEGIN
                    SELECT RAISE(ABORT, 'messages are append-only');
                END;
                """
            )
            current_version = connection.execute("PRAGMA user_version").fetchone()[0]
            if current_version not in (0, SCHEMA_VERSION):
                raise JournalError(
                    f"Неподдерживаемая версия схемы базы данных: {current_version}"
                )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @staticmethod
    def _record(row: sqlite3.Row, duplicate: bool = False) -> MessageRecord:
        return MessageRecord(
            message_id=row["message_id"],
            conversation_id=row["conversation_id"],
            sequence=int(row["sequence"]),
            speaker=row["speaker"],
            content=row["content"],
            created_at=row["created_at"],
            source=row["source"],
            metadata=json.loads(row["metadata_json"]),
            duplicate=duplicate,
        )

    def append_message(
        self,
        *,
        conversation_id: str,
        speaker: str,
        content: str,
        message_id: Optional[str] = None,
        scope_id: str = "default",
        source: str = "external_dialog",
        metadata: Optional[dict[str, Any]] = None,
        created_at: Optional[str] = None,
    ) -> MessageRecord:
        conversation_id = _required_text(conversation_id, "conversation_id", 160)
        scope_id = _required_text(scope_id, "scope_id", 160)
        speaker = _required_text(speaker, "speaker", 40).lower()
        if speaker not in ALLOWED_SPEAKERS:
            raise JournalError(
                "speaker должен быть одним из значений: " + ", ".join(sorted(ALLOWED_SPEAKERS))
            )
        if not isinstance(content, str):
            raise JournalError("content должен быть строкой")
        if len(content) > 200_000:
            raise JournalError("content превышает лимит в 200000 символов")
        source = _required_text(source, "source", 160)
        message_id = _required_text(message_id if message_id is not None else uuid.uuid4().hex, "message_id", 160)
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise JournalError("metadata должен быть JSON-объектом")
        try:
            metadata_json = json.dumps(
                metadata,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise JournalError(f"metadata нельзя преобразовать в JSON: {exc}") from exc
        timestamp = _required_text(created_at, "created_at", 80) if created_at else utc_now()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT * FROM messages WHERE message_id = ?",
                    (message_id,),
                ).fetchone()
                if existing is not None:
                    existing_conversation = connection.execute(
                        "SELECT scope_id FROM conversations WHERE conversation_id = ?",
                        (conversation_id,),
                    ).fetchone()
                    if (
                        existing_conversation is None
                        or existing_conversation["scope_id"] != scope_id
                    ):
                        raise JournalError(
                            f"беседа {conversation_id!r} не принадлежит области {scope_id!r}"
                        )
                    same_payload = (
                        existing["conversation_id"] == conversation_id
                        and existing["speaker"] == speaker
                        and existing["content"] == content
                        and existing["source"] == source
                        and existing["metadata_json"] == metadata_json
                    )
                    if not same_payload:
                        raise IdempotencyConflict(
                            f"message_id {message_id!r} уже связан с другими данными"
                        )
                    connection.execute("COMMIT")
                    return self._record(existing, duplicate=True)

                conversation = connection.execute(
                    "SELECT scope_id FROM conversations WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
                if conversation is None:
                    connection.execute(
                        """
                        INSERT INTO conversations(
                            conversation_id, scope_id, created_at, updated_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (conversation_id, scope_id, timestamp, timestamp),
                    )
                elif conversation["scope_id"] != scope_id:
                    raise JournalError(
                        f"беседа {conversation_id!r} принадлежит области "
                        f"{conversation['scope_id']!r}, а не {scope_id!r}"
                    )

                sequence = int(
                    connection.execute(
                        """
                        SELECT COALESCE(MAX(sequence), 0) + 1
                        FROM messages WHERE conversation_id = ?
                        """,
                        (conversation_id,),
                    ).fetchone()[0]
                )
                connection.execute(
                    """
                    INSERT INTO messages(
                        message_id, conversation_id, sequence, speaker, content,
                        created_at, source, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message_id,
                        conversation_id,
                        sequence,
                        speaker,
                        content,
                        timestamp,
                        source,
                        metadata_json,
                    ),
                )
                connection.execute(
                    "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                    (timestamp, conversation_id),
                )
                row = connection.execute(
                    "SELECT * FROM messages WHERE message_id = ?",
                    (message_id,),
                ).fetchone()
                connection.execute("COMMIT")
                return self._record(row)
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def get_message(self, message_id: str) -> Optional[MessageRecord]:
        message_id = _required_text(message_id, "message_id", 160)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM messages WHERE message_id = ?", (message_id,)
            ).fetchone()
            return self._record(row) if row is not None else None

    def list_messages(
        self,
        conversation_id: str,
        *,
        limit: int = 20,
        before_sequence: Optional[int] = None,
    ) -> list[MessageRecord]:
        conversation_id = _required_text(conversation_id, "conversation_id", 160)
        if not isinstance(limit, int) or not 1 <= limit <= 500:
            raise JournalError("limit должен быть целым числом от 1 до 500")
        sql = "SELECT * FROM messages WHERE conversation_id = ?"
        params: list[Any] = [conversation_id]
        if before_sequence is not None:
            if not isinstance(before_sequence, int) or before_sequence < 1:
                raise JournalError("before_sequence должен быть положительным целым числом")
            sql += " AND sequence < ?"
            params.append(before_sequence)
        sql += " ORDER BY sequence DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._record(row) for row in reversed(rows)]

    def conversation_info(self, conversation_id: str) -> Optional[dict[str, Any]]:
        conversation_id = _required_text(conversation_id, "conversation_id", 160)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT c.conversation_id, c.scope_id, c.created_at, c.updated_at,
                       COUNT(m.message_id) AS message_count,
                       COALESCE(MAX(m.sequence), 0) AS last_sequence
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.conversation_id
                WHERE c.conversation_id = ?
                GROUP BY c.conversation_id
                """,
                (conversation_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def integrity_check(self) -> list[str]:
        with self._connect() as connection:
            return [
                str(row[0])
                for row in connection.execute("PRAGMA integrity_check").fetchall()
            ]


def _record_json(record: MessageRecord) -> str:
    return json.dumps(asdict(record), ensure_ascii=False, sort_keys=True)


def _main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="create the journal schema")
    append = commands.add_parser("append", help="append one immutable message")
    append.add_argument("--conversation", required=True)
    append.add_argument("--scope", default="default")
    append.add_argument("--speaker", required=True, choices=sorted(ALLOWED_SPEAKERS))
    append.add_argument("--content", required=True)
    append.add_argument("--message-id")
    append.add_argument("--source", default="external_dialog")
    append.add_argument("--metadata-json", default="{}")

    recent = commands.add_parser("recent", help="read recent messages")
    recent.add_argument("--conversation", required=True)
    recent.add_argument("--limit", type=int, default=20)

    commands.add_parser("check", help="run SQLite integrity_check")

    args = parser.parse_args(argv)
    try:
        journal = CompanionJournal(args.db)
        if args.command == "init":
            print(json.dumps({"ok": True, "db": str(args.db), "schema": SCHEMA_VERSION}))
        elif args.command == "append":
            metadata = json.loads(args.metadata_json)
            if not isinstance(metadata, dict):
                raise JournalError("--metadata-json должен содержать JSON-объект")
            result = journal.append_message(
                conversation_id=args.conversation,
                scope_id=args.scope,
                speaker=args.speaker,
                content=args.content,
                message_id=args.message_id,
                source=args.source,
                metadata=metadata,
            )
            print(_record_json(result))
        elif args.command == "recent":
            records = journal.list_messages(args.conversation, limit=args.limit)
            print(json.dumps([asdict(item) for item in records], ensure_ascii=False))
        elif args.command == "check":
            results = journal.integrity_check()
            print(json.dumps({"integrity": results}))
            return 0 if results == ["ok"] else 1
        return 0
    except (JournalError, sqlite3.Error, OSError, json.JSONDecodeError) as exc:
        print(f"ошибка_журнала: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
