# 8. Privacy and PII masking

Two privacy postures. They are not equivalent, and conflating them is the mistake
this chapter exists to prevent.

| Posture | How | Strength |
|---|---|---|
| **Keep everything local** | `active.inference` and `active.embedding` both Ollama-backed | **Structural guarantee.** No request to intercept, no provider to trust, no masking to get wrong. |
| **Cloud models, masked** | `pii.enabled: true` — identifiers replaced with tokens before text leaves, restored in the response | **Mitigation.** Reduces exposure; does not eliminate it. |

The second is strictly weaker. If your corpus is genuinely sensitive, use a local
model. The masking tier exists for when you have decided a frontier model's
capability is worth the exposure and want to reduce that exposure.

---

## What this protects against, and what it does not

**It reduces** the volume of directly identifying information reaching a cloud
provider in query text, chat history, retrieved passages, and generated session
titles.

**It does not make your data anonymous.** This is **pseudonymisation** — a
reversible substitution with the mapping held by your system. The content still
goes to the provider. A document about a specific person, with the name masked, is
often still about an identifiable person: surrounding facts, dates, and
relationships frequently make re-identification straightforward.

**It is not a compliance control.** Nothing here makes transmitting personal data
to a third party lawful under any regime. Treat it as defence in depth, not a legal
basis.

**It cannot catch what it does not recognize.** Detection is a machine-learning
model with a confidence threshold. It misses things. Presidio's own documentation
states that "because it is using automated detection mechanisms, there is no
guarantee that Presidio will find all sensitive information," and recommends that
"additional systems and protections should be employed" alongside it.

**No residual-leak rate can be quoted.** Neither this repository nor any source
consulted provides a measured miss rate for the shipped configuration. Anyone who
gives you a percentage here is guessing.

### A realistic threat model

| Concern | Does masking help? |
|---|---|
| Provider logs prompts and staff can read them | Partially — names and identifiers are tokenized; context is not |
| Provider trains on your data | Partially — same limitation |
| Your data appears in another customer's output | Partially |
| A subpoena to the provider | Barely — pseudonymized data is still your data |
| Network interception | No — that is TLS's job, and TLS is already in use |
| Identifying that a document concerns a specific person | **No** — this is the fundamental limit |

---

## Turning it on

```yaml
pii:
  enabled: true
```

Then restart. Boot-time validation **refuses to start** in two configurations:

| Condition | Why |
|---|---|
| **Non-local embedding provider** | Masking covers the generation path. Shipping raw document text to a cloud embedding API would render the exercise pointless. The error names the provider. |
| **GLiNER enabled without the package** | You asked for stronger detection; you get an error rather than a quiet downgrade to spaCy-only. |

A third refusal lives in the eval service: with `pii.enabled`, it will not start
against a cloud judge unless `pii.allow_cloud_judge` is explicitly true. Judge
prompts embed retrieved chunks and answers **verbatim and unmasked**, so a cloud
judge would leak exactly what masking protects. Set that flag only when your
evaluation data contains no real PII.

---

## What gets masked, and where

| Masked | Never masked | Why not |
|---|---|---|
| The user's query, before it reaches the model | **Embeddings** — chunk text is embedded unmasked | Safe only because a local embedding provider is enforced at boot. That check is not negotiable. |
| Chat history, before condensation | **The reranker** — it scores original text | Deliberate: masked text ranks worse, and the reranker is a local cross-encoder. Nothing is transmitted. |
| Retrieved context, before the prompt | **Sources returned to you** | You see real text, never `[[[PERSON_0]]]` |
| Session-title generation (a separate LLM call) | **Judge prompts** | Verbatim and unmasked — which is why the eval service refuses a cloud judge |
| The contextual-prefix ingestion call — document name and chunk preview are masked, and the returned prefix is unmasked before storage | **Data at rest** | Documents, chunks, and chat history are stored unmasked in PostgreSQL. Masking is a transmission-time transformation, not storage encryption. |

---

## How masking works

Detection uses **Microsoft Presidio**, combining pattern-based recognizers for
structured identifiers with a spaCy NER model (`en_core_web_md` by default) for
names.

Seven entity types by default:

`PERSON` · `EMAIL_ADDRESS` · `PHONE_NUMBER` · `CREDIT_CARD` · `US_SSN` ·
`IBAN_CODE` · `IP_ADDRESS`

Anything scoring above `pii.score_threshold` (default `0.5`) is replaced with a
token shaped by `pii.token_format`, default `[[[{entity_type}_{index}]]]`. The
bracket format is deliberately distinctive so a model is unlikely to alter it in
passing.

The token-to-value mapping is held **in memory, per session, and never persisted**,
bounded by an idle TTL (`ttl_seconds`, 3600) and a session cap (`max_sessions`,
500). Losing a mapping is safe: the next turn re-masks from stored history, and
only the token numbering changes.

### Structured identifiers versus names

This distinction predicts most of your results.

Credit cards, SSNs, IBANs, IP addresses, and emails have rigid formats. Pattern
recognizers catch them reliably.

**Names do not have a format.** Detecting them means a model deciding whether a
capitalized word is a person, an organization, a place, or a product. This is where
misses happen, and `PERSON` is where the shipped configuration is weakest — the
project's own configuration comments say so.

Common failure cases: unusual and non-Western names, names that are also common
words, names in unusual grammatical positions, and names inside tables.

### Improving name detection

| Option | Cost | What to expect |
|---|---|---|
| **`pii.spacy_model: en_core_web_lg`** | 382 MB vs 31 MB on disk (~12×) | Marginal. spaCy's published tables put `lg` at 0.855 overall NER F-score against `md`'s 0.847, and recall at 0.859 vs 0.851 — under one point apart. **Not a targeted fix for weak `PERSON` detection.** Test it rather than assuming. |
| **`pii.gliner.enabled: true`** | ~10× the CPU cost per call (~160 ms vs ~15 ms, per the project's own figures) and a ~200 MB model download | Registers a second recognizer *alongside* spaCy for NER-shaped entities. Requires `uv sync --extra gliner`. On ingestion across a large corpus that multiplier is significant. |

---

## The safety nets

| Net | Default | What it does |
|---|---|---|
| `pii.validation.enabled` | `true` | Checks that tokens sent to the model come back unaltered. Models sometimes reformat them — brackets, casing, separators — and a mangled token cannot be unmasked. Fuzzy recovery attempts repair. |
| `pii.output_guardrails.enabled` | `true` | Scans the final unmasked response for personal data appearing verbatim — a check that masking did not miss something that came back in the output. |
| `pii.output_guardrails.block_on_detection` | `false` | Whether a detection raises an error or merely records the event. |
| `pii.audit.enabled` | `true` | Records mask/unmask operations — entity types and counts, never original values at INFO level. This is what answers "what did this system actually send out?" |

**Output guardrails cannot block streaming responses.** By the time the complete
answer exists to be scanned, tokens have already been sent to the client. On the
streaming path the guardrail is audit-only, regardless of `block_on_detection`. If
blocking matters, do not use the streaming endpoint.

---

## Verifying it yourself

Do not take the configuration's word for it. Four checks, in order of effort:

**1. Confirm the boot check bites.** Set `pii.enabled: true` alongside a cloud
embedding model and start the stack. It should refuse to boot with a clear message.
If it starts, you may be editing a `config.yml` that is not the one being mounted.

**2. Watch the audit log.** Run a query containing a name and an email address:

```bash
docker compose logs rag-server | grep -i "pii"
```

You should see mask and unmask operations with entity counts. Zero detections on
text you know contains PII means detection is not working.

**3. Test against your own content.** Take a genuinely representative sample of
your documents — real names, real formatting — and check what is detected. This is
the only test that tells you about *your* corpus. Synthetic examples using
obviously-fake names overstate coverage, because common Western first names are the
easy case.

**4. Look for what got through.** The failure that matters is a name appearing in
neither the audit log nor as a token. Read a masked payload if you can, and check
names in unusual positions: inside tables, in headers, in signature blocks,
hyphenated, or non-Western.

---

## What it costs you

**Latency.** Detection runs over the query, chat history, and every retrieved chunk
on every request. With spaCy the per-call cost is small; with GLiNER it is roughly
an order of magnitude higher. There is no measured end-to-end figure in this
repository — measure it on your hardware using the latency metrics from chapter 4,
comparing runs with masking on and off.

**Quality.** The cost people underestimate. The model sees `[[[PERSON_0]]]` where a
name was:

- Questions *about* a person become harder — the entity is now opaque.
- Coreference across turns can break when token numbering shifts between requests.
- The model may comment on the tokens, refuse, or phrase awkwardly around them.
- **False positives are the worst case:** a masked product name or technical term
  the detector mistook for a person removes information the model needed, and you
  get a worse answer for no privacy benefit at all.

**This is measurable, and you should measure it.** Run your golden set with
`pii.enabled: false`, again with `true`, and compare faithfulness and correctness.
Chapter 6 covers doing that comparison properly.

**Ingestion cost**, if contextual retrieval is on: masking now also runs on every
chunk preview during ingestion.

---

## Practices worth adopting

Not RAGBench behaviours — general practice, listed separately so they are not
mistaken for features.

- **Treat the local-model posture as the default for sensitive corpora**, and the
  masking tier as a considered exception for specific high-value queries.
- **Tune `score_threshold` toward false positives** when the cost of a leak exceeds
  the cost of a degraded answer. 0.5 is a starting point, not a recommendation.
- **Keep a small adversarial test set** — documents containing the name formats
  your detector handles worst — and re-check it whenever you change the spaCy
  model, the entity list, or the threshold.
- **Review the audit log periodically**, not only after an incident. Detection
  counts dropping is a signal worth having.

---

**Next:** [9. Reading the dashboard](09-reading-the-dashboard.md).

Engineering detail: [`docs/internal/pii-masking.md`](../internal/pii-masking.md).
Presidio documentation: <https://presidio.dataprivacystack.org/>
