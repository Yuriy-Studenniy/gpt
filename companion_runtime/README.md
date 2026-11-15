# Companion Runtime — M2 journal

This is the first external-runtime slice. It is deliberately independent of X-Ray,
the game save format, and any LLM provider.

## Guarantees

- SQLite is the durable source of truth; messages are append-only.
- Every message has a stable message ID, conversation ID, per-conversation
  sequence, speaker, source, timestamp, content, and JSON metadata.
- Retrying the same message ID with the same payload is idempotent and returns
  the original sequence. Reusing an ID for different content is rejected.
- SQLite uses WAL, foreign keys, a busy timeout, and a transaction around
  sequence allocation plus insert.
- Database triggers reject UPDATE and DELETE against the messages table.
- The module does not call an LLM, perform retrieval, or communicate with Lua.

## Initialize

From the repository root, run:

    python -m companion_runtime.journal --db "data\companion_memory.sqlite3" init

## Append and read

    python -m companion_runtime.journal --db "data\companion_memory.sqlite3" append --conversation "campaign-main" --speaker player --content "We agreed to visit Skadovsk tomorrow." --message-id "example-message-001" --source external_dialog --metadata-json "{}"
    python -m companion_runtime.journal --db "data\companion_memory.sqlite3" recent --conversation "campaign-main" --limit 20
    python -m companion_runtime.journal --db "data\companion_memory.sqlite3" check

Use a stable message ID supplied by the caller when retrying delivery. Do not
generate a fresh ID for a retry of an already accepted event.

## Tests

From the repository root, run:

    python -m unittest discover -s tests -p "test_companion_journal.py" -v

The tests cover append/read after reopening, idempotent retry, ID conflict,
immutability, bounded recent reads, scope consistency, concurrent sequence
allocation, and SQLite integrity.
