# Design decisions

Why the system works the way it does, not just what it does. Each entry follows
the same shape — context, problem, resolution, lesson — because that's the
order you need the information in when you're staring at similar symptoms and
trying to figure out whether you're about to repeat a mistake that was already
paid for once.

## In-house eval framework instead of RAGAS / DeepEval

**Context.** RAG evaluation needs a judge and a metric catalogue. The project
didn't start in-house: it used RAGAS first, then switched to DeepEval
(December 2025, with Anthropic Claude as the judge and pytest integration),
then dropped DeepEval's metrics once nothing in the codebase imported it
anymore, replacing them with hand-rolled implementations in
`evals/metrics/`.

**Problem.** With DeepEval gone, the question got re-litigated on 2026-08-01:
should the project re-adopt DeepEval, RAGAS, or Phoenix rather than keep
maintaining metrics by hand?

**Resolution.** Declined, for three reasons, in order of weight:

1. Re-adopting would trade a *calibrated* judge for an *uncalibrated* one.
   `evals/calibration.py` measures the current judge against RAGBench's
   human-verified TRACe labels — a real, if partial, check on whether the
   scores mean anything. A third-party framework arrives with prompts the
   project doesn't control and no calibration against this corpus; that
   calibration work would have to be redone from scratch, and it isn't cheap
   to redo per framework upgrade.
2. Telemetry posture conflicts with the product's own thesis. DeepEval phones
   home on import (a call to `api.ipify.org`) and is built around a hosted
   platform. The judge path is also the one place in the whole pipeline where
   PII masking never applies (see the PII tier boundary decision below) —
   putting a default-telemetry dependency exactly on that path is the wrong
   direction for a privacy-first product.
3. Low overlap, high switching cost. A framework would replace on the order of
   200 lines out of roughly 6,900 in `services/evals/evals/` — specifically
   the generation-metric judge calls — and contributes nothing to the six
   dataset loaders, the citation/abstention metrics, the Pareto frontier
   analysis, cost telemetry, or the dashboard API. Most of what the eval
   service does has no third-party equivalent to swap in.

What would justify revisiting: needing metric types not worth maintaining
in-house — multi-turn conversational eval, agentic tool-use eval, red-teaming
suites — or the team growing to a point where hand-rolled metrics stop paying
for themselves. Even then, the better move is to vendor specific metric
*implementations* rather than adopt a framework wholesale, and to check
telemetry defaults before anything else.

One idea is worth stealing without taking the dependency: G-Eval's scoring
approach (chain-of-thought reasoning plus token-probability-weighted scoring)
discriminates better than the current single-shot `SCORE: 0.8` text parse used
in `llm_judge.py`. That's a improvement to port into the existing judge, not a
reason to import a framework.

**Lesson.** What's gained by staying in-house: a judge that's actually
calibrated against ground truth for this corpus, and no unaudited telemetry on
the one prompt path that can't be PII-masked. What's given up: everyone
maintaining `evals/metrics/` is on their own for scoring-approach improvements
that a mature framework would ship for free — the G-Eval-style scoring
mentioned above is still on the to-do list, not implemented.

## The async / NullPool incident

**Context.** The stack runs FastAPI (async-native) against PostgreSQL through
SQLAlchemy's async engine on the `asyncpg` driver. Three layers with
incompatible async characteristics sit on top of each other: FastAPI route
handlers are `async def` running on uvicorn's main event loop; LlamaIndex's
core interfaces (`BaseChatStore`, `BaseRetriever`, the chat engine's
`.chat()`/`.stream_chat()`) are sync-only by framework design; and asyncpg
connections are bound to the event loop that created them — an asyncpg
invariant, not something SQLAlchemy chose or could opt out of.

**Problem.** Three components independently needed to call async database code
from LlamaIndex's sync interfaces — `PostgresChatStore` (chat history),
`PgSearchBM25Retriever` (BM25 search), and the session-metadata service. All
three solved it the same wrong way: spin up a brand-new event loop in a thread
pool worker for every call (`asyncio.new_event_loop()` + `run_until_complete()`,
or a bare `asyncio.run()`), on the theory that the connection pool was
thread-safe so it must also be loop-portable. That theory is half right:
SQLAlchemy's pool correctly serializes concurrent checkout/checkin across
threads, but the asyncpg connections *inside* the pool carry loop-bound
internal state — pending futures, protocol buffers, waiter callbacks. A
connection created on one temporary loop, checked back into the shared pool,
and later checked out by a different (or by-then-dead) loop raised
`RuntimeError: Task got Future attached to a different loop`. Every request had
a chance of creating connections on a fresh loop, so over time the shared pool
became a mix of connections bound to various dead loops, and pool-maintenance
connection-termination errors cascaded outward from there. The streaming query
path (`POST /query/stream`) was hit hardest: Starlette runs the sync generator
in a thread pool concurrently with the main loop, so the main loop was often
simultaneously touching the same shared pool the temporary loop was
contaminating — maximizing collision odds. Non-streaming queries blocked the
main loop directly while the temporary loop did its work, which accidentally
reduced (but didn't eliminate) the overlap window.

Symptom in the logs: `RuntimeError: Task got Future attached to a different
loop`, surfacing first as `AsyncAdaptedQueuePool` connection-termination errors
and then as failed queries. In production terms this reads exactly like
Postgres running out of room: `FATAL: too many clients already`, once enough
poisoned connections piled up that the pool stopped being able to hand out
usable ones and effectively started leaking.

The instinctive fix people reach for here — `NullPool`, i.e. a new connection
per operation instead of a shared pool — was considered and correctly avoided.
NullPool sidesteps the loop-binding problem because there's no cross-loop
reuse, but it does so by paying for a brand new Postgres connection on every
single database operation. Combined with any fire-and-forget
`asyncio.create_task()` pattern elsewhere in the code, that's a direct route to
exhausting Postgres's connection limit under any real concurrency — trading an
intermittent bug for a guaranteed one.

**Resolution.** The principle: all asyncpg operations must execute on the same
event loop, always. Concretely:

- A single process-wide bridge function, `run_async_safely()` in `postgres.py`,
  stores the main event loop at startup (`set_main_event_loop()`, called from
  `main.py`'s startup hook) and uses `asyncio.run_coroutine_threadsafe(coro,
  main_loop)` to schedule *any* asyncpg work back onto that one loop, no matter
  which thread the call originates from. All three ad hoc bridges
  (`sessions.py`, `session.py`, `bm25_retriever.py`) were replaced with calls to
  this single function — no component gets to invent its own bridge anymore.
- Any sync call made directly from an `async def` route handler was wrapped in
  `await loop.run_in_executor(None, ...)` so the main loop is never blocked by
  it. This isn't cosmetic: `run_coroutine_threadsafe` only works if the target
  loop is free to pick up the scheduled coroutine. If the calling thread *is*
  the main loop's own thread, `future.result()` blocks that thread while the
  loop needs that same thread to run the coroutine — a guaranteed deadlock.
  `query_rag()`, `get_chat_history()`, `clear_session_memory()`, and
  `delete_session()` were all wrapped this way. The one exception,
  `query_rag_stream()`, already ran inside a thread via Starlette's own
  `StreamingResponse` threadpool handling and needed no change.
- Connection pooling itself moved from ad hoc defaults to an explicit,
  documented configuration: `QueuePool` with `pool_size=10` (persistent
  connections held open), `max_overflow=20` (burst capacity above that),
  `pool_pre_ping=True` (a lightweight liveness check before handing out a
  connection, so a connection killed by the database or network doesn't get
  used and fail downstream), and `pool_recycle=3600` (recycle any connection
  older than an hour, to avoid connections going stale under a load balancer or
  firewall's idle-connection timeout).

To check whether the pool is actually within budget in a running system:

```sql
SELECT count(*) FROM pg_stat_activity WHERE datname = 'ragbench';
```

Expected under normal operation is comfortably under the `pool_size +
max_overflow` ceiling (well under 30 connections for a single rag-server
worker); anything climbing toward `max_connections` on the Postgres side, or a
`too many clients already` error, means either a NullPool-style pattern crept
back in somewhere or a fire-and-forget `asyncio.create_task()` is spawning
concurrent database work outside the pool's accounting.

**Lesson.** Rules that came directly out of this, verbatim from the
postmortem, because they're the kind of thing that's easy to violate by
accident in a new piece of code six months from now:

1. Never create a temporary event loop for a database operation. If you need
   to call async DB code from sync code, that's what `run_async_safely()` is
   for.
2. Never call blocking sync code directly from an `async def` handler body —
   either offload it with `run_in_executor`, or make the handler a plain `def`
   so FastAPI's own threadpool offloading handles it for you.
3. `run_coroutine_threadsafe` requires the target loop to be free. If the
   calling thread is the main loop's own thread, you will deadlock, not error
   — which makes this mistake quieter and worse than the original bug.
4. "Thread-safe connection pool" and "loop-portable connection" are different
   guarantees. SQLAlchemy's pool gives you the first. asyncpg does not give you
   the second, and no amount of pool configuration changes that — the fix has
   to be architectural (one loop for all DB work), not a pool-tuning knob.

The connections created by NullPool being expensive and exhaustion-prone under
load is exactly why NullPool is flagged as the wrong direction rather than a
viable alternative fix — it was seriously considered and rejected, not merely
overlooked.

## Docling + LlamaIndex JSON export-type constraint

**Context.** Docling parses complex source formats (PDF, DOCX, PPTX, XLSX,
HTML) into structured documents before LlamaIndex's `DoclingNodeParser` chunks
them into retrievable nodes.

**Problem.** `DoclingNodeParser` expects Docling's structured JSON export
specifically — it parses that structure to preserve section boundaries,
headings, and layout information when building chunks. If `DoclingReader` is
instead configured for a different export type (plain text or markdown), the
node parser either breaks outright or silently loses the structural
information it depends on, degrading chunk quality without raising an error
that points back at the cause.

**Resolution.** Always instantiate `DoclingReader(export_type=DoclingReader.ExportType.JSON)`.
There is no supported alternative for this pairing.

**Lesson.** This is a hard framework-pairing constraint, not a style
preference or a leftover default someone forgot to change — it needs to stay
visible in any ingestion or pipeline documentation so a future cleanup pass
doesn't "simplify" it away on the reasonable-looking assumption that a plain
text or markdown export would be equivalent and simpler.

## PyTorch CPU index strategy

**Context.** The reranker depends on `sentence-transformers`, which pulls in
PyTorch. The Docker images are CPU-only — no CUDA — and PyTorch ships separate
wheel builds for CPU versus GPU.

**Problem.** Default `uv`/pip index resolution does not reliably resolve to
the CPU-only PyTorch wheel across platforms; left to its own defaults, the
resolver can pick a GPU-targeting build that either fails to install correctly
or bloats the image with CUDA dependencies nothing in this stack uses.

**Resolution.** The Dockerfile passes `--index-strategy unsafe-best-match` to
force resolution toward the correct CPU wheels. Separately, but for the same
dependency chain, the image installs `gcc`, `g++`, and `make` because
`pystemmer` — a transitive dependency of `sentence-transformers` — needs to
compile from source.

**Lesson.** This shows up as a recurring "Docker build fails" support issue
when it's missing, which is why it's called out directly in three places
(`CLAUDE.md`'s Gotchas, its Common Issues section, and the observability
troubleshooting notes) rather than left to a single doc — it's exactly the
kind of one-line Dockerfile flag that looks removable to someone who doesn't
know what it's protecting against.

## No separate test-runner service

**Context.** Integration tests need a running stack — Postgres, TEI,
rag-server all up together — not just the application code in isolation.

**Problem.** The obvious approach, a dedicated `test-runner` service in
`docker-compose.yml`, would need its own environment variables, secrets
mounts, volumes, and network configuration — all of which would have to
mirror `rag-server`'s own service definition. Two service definitions holding
the same configuration by hand is a config-drift risk: any change to
`rag-server`'s env, secrets, or networking would need a matching, easy-to-forget
edit in the test-runner definition, and the two would silently diverge the
first time someone updated one and not the other.

**Resolution.** Integration tests reuse the `rag-server` service definition
directly, rather than adding a parallel one — `docker compose exec rag-server
.venv/bin/pytest tests/integration ...` locally, `docker compose run --rm
rag-server ...` in CI. There is no separate `test-runner` entry in the compose
file at all.

**Lesson.** Prefer reusing an existing service definition over standing up a
parallel one purely to execute tests, whenever the two would otherwise need to
carry identical environment configuration — the maintenance cost of keeping
two definitions in sync exceeds the cost of running tests inside the real
service's container.

## Judge failures excluded from averages, not scored 0.0

**Context.** Three generation metrics — faithfulness, answer correctness,
answer relevancy — depend on an LLM judge call that parses a `SCORE: [0.0-1.0]`
line out of a free-text response. Judge calls can fail outright (timeout,
provider error) or come back malformed (no parseable `SCORE:` line).

**Problem.** The original implementation treated both failure modes as a
score of `0.0`: `LLMJudge._evaluate` returned `score=0.0` after exhausting
retries, and `_parse_response` returned `0.0` when it found no `SCORE:` line.
Because the retry loop only re-tried on outright exceptions and never on a
successfully-received-but-unparseable response, a malformed response wasn't
even retried — it was accepted as a valid zero on the first pass. Since
aggregation is a plain `sum(scores) / len(scores)` average, every judge
timeout or malformed reply was indistinguishable from "the model's answer was
completely unfaithful to the retrieved context." A flaky judge — a transient
provider hiccup, a rate limit, an oddly formatted response — would silently
drag every batch average down and read as a quality regression that never
happened. Worse, this same aggregation feeds `evals/calibration.py`, so the
one measurement meant to validate whether the judge can be trusted at all was
itself being corrupted by the judge's own transient failures.

**Resolution.** A failed or malformed judge call is missing data, not evidence
of a bad answer, and is now handled as such throughout the pipeline:

- `_parse_response` raises `JudgeParseError` (a subclass of `JudgeError`) on a
  missing or unparseable `SCORE:` line, which routes it back through
  `_evaluate`'s retry loop instead of being silently accepted as `0.0`.
- `_evaluate` raises `JudgeError` once retries are exhausted, rather than
  returning a fabricated score.
- `BaseMetric.compute_batch` catches `JudgeError`, drops that sample, and
  reports a `sample_size` reflecting only the successful calls; the average is
  computed over successes only.
- `calibration.py` runs the two judge calls per item with
  `asyncio.gather(..., return_exceptions=True)` so one call's exception
  doesn't orphan its sibling task, and drops the whole item on either failure
  rather than scoring it — surfacing `dropped_judge_failures` and
  `items_requested` in the result metadata so a calibration run over a flaky
  judge visibly reads as thin, instead of quietly reporting a number computed
  over whatever happened to succeed.

Genuine `0.0` scores are still possible and remain meaningfully distinct: no
context was retrieved at all (`Faithfulness`), or no expected answer was
defined for the question (`AnswerCorrectness`). Those are real answers to "how
did this score," not a stand-in for "we don't know."

**Lesson.** Scoring a missing measurement as the worst possible value biases
every downstream number toward looking worse than reality, and it does so in a
way that's invisible unless someone happens to notice `sample_size` shrinking.
An exclusion with a visible dropped-count is honest about what was actually
measured; a substituted `0.0` is not, even though the two look identical in a
single averaged headline number.

## Chat memory cache bounds

**Context.** Two in-process caches sit in front of chat history:
`_memory_cache`, a cache of `ChatMemoryBuffer` objects in front of the
PostgreSQL-backed chat store, and `_temporary_sessions`, the cache backing
sessions that have no database row at all. Both hold cleartext user messages
in RAM for as long as an entry survives, whether or not PII masking is turned
on — the caches are session-history plumbing, not part of the PII feature.

**Problem.** Neither cache was originally bounded. A long-lived rag-server
process would accumulate a `ChatMemoryBuffer` for every session it had ever
served, for the life of the process — an unbounded memory growth path, and,
independent of memory pressure, an unbounded amount of cleartext conversation
history sitting in RAM indefinitely.

**Resolution.** Both caches are now bounded two ways: an idle TTL (entries
unused for longer than the TTL are expired) and an LRU cap (the least
recently used entries are evicted once the cache exceeds its session-count
ceiling), tracked via `OrderedDict`-backed entries carrying a `last_used`
timestamp. The two caches are deliberately sized differently:

- `chat_memory.persistent` (the cache in front of Postgres): `max_sessions:
  500`, `ttl_seconds: 3600`. Eviction here just costs one reload from the
  database on the next access — cheap, so it can be sized generously.
- `chat_memory.temporary` (no database backing at all): `max_sessions: 200`,
  `ttl_seconds: 1800` — half the idle window and less than half the capacity
  of the persistent cache. This is the *only* copy of that conversation's
  history anywhere; there's no row to reload from and no delete hook to clean
  up after it. Evicting a temporary session doesn't just lose a cache entry,
  it ends the conversation. The shorter bounds are a deliberate acknowledgment
  of that asymmetry, not an oversight — "temporary" already implies the
  history isn't durable, and the cache bounds are what actually enforces that
  promise rather than leaving it as just a naming convention.

**Lesson.** The two caches look symmetric (same data structure, same eviction
mechanism) but carry different real costs on eviction, and the config
reflects that difference explicitly rather than giving both the same numbers
for consistency's sake. Both caches are process-local by design — the
rag-server runs a single uvicorn worker — so there is no cross-worker
invalidation problem today, but that assumption would need revisiting before
ever scaling rag-server horizontally.

## PII tier boundary

**Context.** PII masking is an opt-in, defense-in-depth control for the cloud
generation tier: detected entities are replaced with reversible tokens before
text is sent to a cloud LLM, and unmasked again in the response. It sits
alongside — not instead of — getting a Zero Data Retention agreement or
equivalent DPA from the provider, which is the stronger control and the one
that should be in place first.

**Problem.** Masking only covers text sent to the *generation* LLM: the query,
retrieved context, chat history, session-title generation, and the document
name plus chunk preview sent during contextual-retrieval enrichment at
ingestion time. Three other paths touch the same corpus text and are never
masked: embedding generation (the embedder sees original, unmasked text),
contextual enrichment's *output* once it's generated (the enrichment prefix is
unmasked again before it's stored and embedded locally), and reranking. If any
of those paths were pointed at a cloud provider while masking was enabled, the
masking would create a false sense of protection — the corpus would still be
leaving the network through the unmasked path, just a different one than the
operator was watching.

**Resolution.** Rather than try to extend masking to cover embeddings and
reranking too (which would mean masking the very text whose semantic content
those steps need to operate on correctly), the system draws a hard product
boundary: embeddings, contextual enrichment, and reranking stay local/VM-side,
full stop, and this is enforced at boot rather than left as a configuration
convention someone could violate by accident. `ModelsConfig.validate_privacy_posture()`
raises a `ValueError` at startup — refusing to boot, not degrading gracefully
— if `pii.enabled` is true and the configured embedding provider is not in the
local-provider set (currently just `tei`). The evaluation judge was originally
gated the same way — with `pii.enabled: true`, a non-local judge provider raised
unless `allow_cloud_judge: true` was set — because judge prompts interpolate
retrieved chunks and generated answers verbatim, making the eval path the one
place in the whole pipeline where masking never applies at all. That half of the
gate has since moved out of `pii.*` into its own `data_policy` block, for the
reasons in [Execution boundary instead of a local/cloud
boolean](#execution-boundary-instead-of-a-localcloud-boolean) below. The
embedding refusal described here is unchanged and still lives in
`validate_privacy_posture()`.

Separately, GLiNER support (an optional second, higher-recall entity
recognizer layered alongside spaCy and the regex recognizers) gets the same
fail-at-boot treatment: enabling `pii.gliner.enabled` without the optional
package installed refuses to start rather than silently falling back to
spaCy-only detection — a missing optional dependency must not quietly
downgrade the detection an operator explicitly asked for.

**Lesson.** A privacy boundary that depends on every operator remembering not
to point three different config keys at a cloud provider is not a boundary —
it's a documentation footnote waiting to be missed. Enforcing it as a refusal
to boot turns "please don't do this" into "the system won't let you do this by
accident," at the cost of a config combination that looks locally reasonable
(masking is on!) failing loudly for a reason that isn't obvious from that one
setting alone. The tradeoff is accepted deliberately: a loud, early failure at
startup is worth more here than a permissive default that fails silently at
the network boundary instead.

## Execution boundary instead of a local/cloud boolean

**Context.** Judge prompts are the one path in the system that carries corpus
content out unmasked, so something has to decide whether a given judge endpoint
may see it. The first attempt was a boolean: a `LOCAL_JUDGE_PROVIDERS` set of
provider strings, consulted only when `pii.enabled` was true, with a
`pii.allow_cloud_judge` opt-out.

**Problem.** Three separate things were wrong with it, and each one was load-bearing.

*The set was empty.* `LOCAL_JUDGE_PROVIDERS` shipped with no members, so every
judge was classified cloud regardless of where it ran. The check therefore had
exactly one reachable outcome, and the only way to run any eval at all was the
opt-out — which meant the opt-out was permanently on in practice and the gate
measured nothing.

*"Local" is not a property of a provider string.* An OpenAI-compatible transport
can address a vLLM container on the operator's own host or `api.openai.com`; the
provider name is identical in both cases. Any classification derived from the
provider field is a guess, and it guesses wrong in the direction that matters —
the self-hosted case, which is the whole point of having the control.

*Binary forces a false framing.* With only "local" and "cloud" available, Bedrock
has to be filed under one of them. Calling it cloud refuses a deployment that
never leaves the customer's AWS account. Calling it local claims the model runs on
the operator's host, which is not true and would make "local" mean two
incompatible things at once — the sort of definition that survives review and then
misleads whoever reads the config two quarters later. There is no honest binary
answer, because there are genuinely three positions.

*And it was gated on the wrong predicate.* Tying corpus egress to `pii.enabled`
assumed confidential content contains PII. Commercially sensitive material —
pricing, contracts, unreleased designs — routinely contains none, and masking is
not the relevant control for it anyway.

**Resolution.** `ExecutionBoundary` names the three positions that actually exist:
`customer_managed` (a host or VPC the operator runs), `aws_managed`
(Bedrock/SageMaker — inside the customer's AWS boundary, but not on their host),
and `third_party` (a vendor API). It is declared per model definition in
`config.yml`, as a property of the resolved endpoint, because the config author is
the only party who knows what a `base_url` points at. Nothing is inferred from
`provider`.

Policy is an allow-list rather than a deny-list — `data_policy.allowed_judge_boundaries`,
defaulting to `{customer_managed, aws_managed}` — so a boundary added later is
refused until someone deliberately permits it, rather than being permitted until
someone remembers to forbid it. For the same reason, **a missing boundary fails
closed**: an endpoint that declares nothing is unknown, and unknown is not
`customer_managed`.

The gate now sits in `data_policy`, independent of `pii.enabled`.
`corpus_confidential` defaults to `true` — an operator who has said nothing has
not said "public". The escape hatch is deliberately about the *dataset* rather
than the corpus: a production corpus can be confidential while the eval set is a
public HuggingFace benchmark, in which case judge egress leaks nothing at all.
That is the narrow case `pii.allow_cloud_judge` was reaching for, stated
precisely.

**That escape hatch was first built as one global boolean, and that was a defect,
not a simplification.** `eval_dataset_is_public: true` was a claim about the
deployment, evaluated at a moment that could not see which dataset a run was
using — so the same `true` that made a RAGBench run safe also let a `golden` run,
authored from the operator's own documents, ship them verbatim to a third-party
judge. The flag's *name* said "dataset" while its *scope* said "deployment", and
the gap between those two was the whole vulnerability.

The replacement makes publicity a property of the run: `public_datasets` is the
set of datasets that carry nothing of the operator's, and a run is public only if
every dataset it uses is in that set. `golden` is deliberately absent, and adding
it is a claim about a specific corpus that only its operator can make.

A second axis came out of the same reasoning. Dataset publicity is not sufficient
in the `end_to_end` tier, because there the eval queries the live rag-server
index and the judge sees whatever comes back — the operator's chunks included —
regardless of which dataset asked the question. `eval_index_is_isolated` is the
narrow, separately-stated claim that covers it: this index holds nothing but the
eval's own uploaded documents. Keeping it separate from `public_datasets` matters,
because the two are different facts and conflating them is how the first version
went wrong.

Enforcement is split rather than duplicated, and the split is the design.
`validate_privacy_posture()` at config load checks only what config load can
know — that the judge declares a boundary at all. `enforce_judge_boundary()` at
judge resolution applies the allow-list, once the run's datasets and tier exist.
The earlier arrangement ran the identical check twice; that was defensible when
the inputs were identical, and became wrong the moment the decision needed
per-run inputs, since a load-time check would have had to fail closed on every
run or wave every run through. Callers that omit the datasets or tier fail
closed, which is what keeps the lazily-constructed metric paths honest, and a
completed run records the conclusion under `metadata.judge_gate_basis` so it can
be audited after the fact. The enum and the
policy model are mirrored verbatim in both services, following the existing
`LLMProvider` duplication; the two services share no package.

**Lesson.** A trust classification derived from a field that does not determine
trust will be wrong exactly when it matters, and a boolean over a domain with
three members forces one of them to be mislabelled. The cost of getting this
wrong is not a failed request — it is a privacy claim in the documentation that
the code does not implement. Naming the real positions and defaulting to refusal
is cheaper than any amount of care applied to the wrong abstraction.

## Self-managed inference over Bedrock, despite `aws_managed` being permitted

**Context.** `allowed_judge_boundaries` defaults to `{customer_managed,
aws_managed}`, so Bedrock and SageMaker are policy-legal for both inference and
judging. Hosting the models on AWS rather than a laptop also removes the hardware
ceiling that made a 32B judge impractical locally. That leaves a real choice
between two permitted boundaries, and the boundary enum deliberately does not
make it for us.

**What Bedrock actually guarantees.** More than the usual vendor-API posture, and
it is worth stating precisely rather than dismissing it. Bedrock deploys each
provider's models into a dedicated AWS-operated account; the provider cannot
reach it, and invocations stay on the AWS network. `PutAccountDataRetention`
takes a `mode` of `none`, under which prompts and responses are discarded
immediately, and an SCP denying that call for any value other than `none`,
attached at the root OU, makes the setting non-negotiable account-wide. Models
declare `allowed_modes`; one that requires `provider_data_share` reports
`status: "unavailable"` under `none` rather than silently downgrading — the same
fail-closed shape this codebase already applies to unknown boundaries. A VPC
interface endpoint keeps the traffic off the public internet.

**The residual, which is the whole decision.** Bedrock runs automated CSAM
detection over model input and output, and AWS states that flagged content may be
stored and reviewed **even when `mode` is `none`**. The probability is negligible
and the mechanism is legitimate; that is not the point. The point is that the
guarantee we make to a customer about a confidential corpus becomes "no human
sees this, unless an automated classifier we do not control decides otherwise" —
a claim with a carve-out that we can neither inspect nor disable. On our own
EC2 instance there is no such clause to explain. A privacy posture whose weakest
sentence needs a footnote is worth avoiding when the alternative is a container
we already run.

**Resolution.** Self-managed vLLM behind the VPC boundary is the primary path for
both inference and judging; Bedrock stays permitted for corpora that are not
confidential, and for that case it is the better tool. Cost did not decide this.
Per-token Bedrock is cheaper than a busy GPU is per hour, but RAGBench is spun up
for demos and torn down afterwards, so the GPU only bills while it is genuinely
working, and the two land close enough that the difference is not worth a privacy
carve-out. Self-hosting also keeps the deployment portable: an OpenAI-compatible
`base_url` moves to another provider without touching anything above the config,
which matters more than the hourly rate, given that AWS's cheapest rates require
a multi-year commitment we are not in a position to make.

**Lesson.** "Can this vendor be trusted?" is the wrong question when the vendor
publishes its controls; the useful question is what the controls still permit
after every switch is set correctly. Bedrock's answer is small but non-empty and
non-configurable, and an irreducible exception is a different kind of risk from a
large one you can turn off.
