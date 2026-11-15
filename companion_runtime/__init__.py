"""External Companion Runtime package for AI Stalker Companion."""

from .journal import (
    CompanionJournal,
    IdempotencyConflict,
    JournalError,
    MessageRecord,
)

__all__ = [
    "CompanionJournal",
    "IdempotencyConflict",
    "JournalError",
    "MessageRecord",
]
