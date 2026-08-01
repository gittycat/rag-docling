# Chat and memory

Audience: developers working on RAGBench. This covers session state, the
`condense_plus_context` chat engine, and the in-process chat-memory caches
sitting in front of Postgres. Retrieval mechanics (BM25, vector search, RRF,
reranking) are covered in `retrieval.md`.

## Persistent vs temporary sessions

A query request carries a `session_id` and an `is_temporary` flag. Sessions
come in two kinds:

- **Persistent sessions** have their chat history backed by `PostgresChatStore`,
  which persists messages to the `chat_sessions`/`chat_messages` tables. An
  in-process `ChatMemoryBuffer` for a persistent session is a warm cache in
  front of that durable storage — if it gets evicted from the cache, the
  conversation is not lost, just reloaded from Postgres on next access.
- **Temporary sessions** have no Postgres row and no `chat_store` at all
  (`chat_store=None`). The in-memory `ChatMemoryBuffer` for a temporary
  session is the *only* copy of that conversation anywhere. There is no
  durable backing to fall back on.

This distinction drives the asymmetry in cache eviction described below.

## `condense_plus_context`

The chat engine is LlamaIndex's `CondensePlusContextChatEngine` (this repo
uses an async-safe subclass for the streaming/async query paths — see
"Async safety" below). On each turn it does two things: condense the
follow-up question into a standalone question, then retrieve and inject
context for that standalone question.

**Condensation**: if there is no prior chat history (the first turn of a
conversation) or condensation is explicitly skipped, the raw user message is
used unchanged — condensation is short-circuited on the first turn, since
there is no prior context to fold into a follow-up rewrite. Otherwise, the
chat history and the new question are formatted into a condense prompt (this
repo does not override the library's default condense prompt — the
`prompts.condense` config key is `null`) and sent to the LLM to produce a
standalone question, which is what actually gets embedded and searched.

**Context injection**: the (possibly condensed) question goes to the
configured retriever — the hybrid RRF retriever, or a plain vector retriever
if hybrid search is disabled (see `retrieval.md`) — and the resulting nodes
run through the node-postprocessor chain (reranker, then PII masking) before
being formatted into the `context_prompt` template's context placeholder and
handed to the response synthesizer.

### Async safety

The base `CondensePlusContextChatEngine` runs node postprocessors
synchronously even inside its async node-fetching method, which would block
the event loop for the duration of the reranker's CPU-bound work. This repo's
subclass overrides that method to run postprocessing in a thread instead,
so the reranker doesn't stall other concurrent requests on the same process.
This subclass is used whenever queries come through the async entry points,
which is always true for the live API routes.

## The two memory caches

Chat memory is held in two separate module-level, in-process caches — one for
persistent sessions, one for temporary sessions — each an ordered map from
session ID to a `ChatMemoryBuffer` plus a last-used timestamp.

| Cache | Max sessions (LRU cap) | Idle TTL |
|---|---|---|
| Persistent | 500 | 3600s (1 hour) |
| Temporary | 200 | 1800s (30 min) |

Both values are configurable via `chat_memory.persistent.*` and
`chat_memory.temporary.*` in `config.yml`.

**Eviction is lazy, not background-timed, on both axes:**

- **Idle TTL expiry** is checked at the start of every cache read: any entry
  whose idle time exceeds its cache's TTL is dropped at that point, not on a
  separate timer or scheduled sweep.
- **LRU capacity** is enforced after every cache write: once a cache exceeds
  its max-sessions cap, the least-recently-used entry is popped. Access order
  is maintained by moving an entry to the end of the ordered map on both read
  and write.

**The asymmetry that matters**: because a persistent session's
`ChatMemoryBuffer` is just a cache in front of Postgres, evicting it — whether
by idle TTL or LRU pressure — costs nothing more than a reload from the
database on the next access. Evicting a **temporary** session's entry, by
either mechanism, destroys the only copy of that conversation that exists
anywhere; there is no store to reload from, and the conversation is simply
gone. The same eviction code path has categorically different consequences
depending on which cache it fires in.

## Chat-history token budget

Each `ChatMemoryBuffer` reserves roughly **50% of the active LLM's context
window** for chat history, derived by introspecting the LLM's metadata
(`context_window`, read off the configured LLM client). When that
introspection fails — the metadata isn't available or doesn't expose a
context window — the code falls back to a **hardcoded 3000-token budget**.
This fallback is not configurable and is not sourced from `config.yml`; it is
a fixed constant in code, used purely as a safety net when the active LLM
provider doesn't expose usable context-window metadata.

## Postgres chat store, session titles, clearing a session

Persistent session history lives in Postgres via `PostgresChatStore`, backed
by the `chat_sessions`/`chat_messages` tables. Session titles are
auto-generated from the first user message the first time a session is
touched with the default placeholder title still in place — subsequent turns
do not overwrite an already-set title.

Clearing a session removes its entry from **both** in-process caches
(persistent and temporary), clears any PII token mapping associated with it,
and deletes its rows from `PostgresChatStore`. This is the one path that
treats both cache kinds uniformly, since it's an explicit user action rather
than passive eviction.
