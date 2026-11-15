# Companion Runtime — M2 foundation

The external Runtime is a separate Python process. This first vertical slice
contains a durable journal and a JSON-lines process API. It has no game imports,
network calls, LLM provider, or per-frame work.

## Journal guarantees

- SQLite is the durable source of truth; messages are append-only.
- Every message has a stable message ID, conversation ID, per-conversation
  sequence, speaker, source, timestamp, content, and JSON metadata.
- Retrying the same message ID and payload is idempotent and returns the
  original sequence. Reusing an ID for different content is rejected.
- SQLite uses WAL, foreign keys, a busy timeout, and a transaction around
  sequence allocation plus insert.
- Database triggers reject UPDATE and DELETE against the messages table.
- The journal API supports append, get, recent reads, conversation metadata,
  and an integrity check.

## Initialize the database

From the repository root, run:

    python -m companion_runtime.journal --db "data\companion_memory.sqlite3" init

## Run the external Runtime

    python -m companion_runtime.runtime --db "data\companion_memory.sqlite3"

The process reads one JSON object per line from stdin and writes one JSON
response per line to stdout. Every response echoes the request_id. Supported
operations are health, append_message, get_message, list_messages,
conversation_info, and integrity_check.

Example health request:

    {"request_id":"health-001","op":"health","payload":{}}

Example append request:

    {"request_id":"append-001","op":"append_message","payload":{"conversation_id":"campaign-main","scope_id":"save-slot-1","speaker":"player","content":"We agreed to visit Skadovsk tomorrow.","message_id":"message-001","source":"external_dialog","metadata":{}}}

Example recent read:

    {"request_id":"recent-001","op":"list_messages","payload":{"conversation_id":"campaign-main","limit":20}}

The process is intentionally stdio-only at M2. The filesystem bridge to X-Ray
is a separate adapter and must not be mixed into database code.

## Tests

From the repository root, run:

    python -m unittest discover -s tests -p "test_*.py" -v

The suite covers persistence after reopening, order, idempotent retry, ID
conflict, append-only triggers, bounded reads, scope consistency, concurrent
sequence allocation, IPC reply matching/timeout recovery, JSON-lines request
correlation, and continued service after malformed input.
