# 8. Privacy and PII masking

RAGBench offers two privacy postures. They are not equivalent, and conflating
them is the mistake this chapter exists to prevent.

**Posture one: keep everything local.** Set `active.inference` and
`active.embedding` to Ollama-backed models. Nothing leaves your network. This is a
structural guarantee — there is no request to get intercepted, no provider to
trust, no masking to get wrong.

**Posture two: use cloud models, and mask what you send.** Detected personal
identifiers are replaced with tokens before text leaves the perimeter, and
restored in the response. This is the PII tier, and it is what the rest of this
chapter is about.

The second posture is strictly weaker than the first. If your corpus is genuinely
sensitive, use a local model. The masking tier exists for the case where you have
decided the capability of a frontier model is worth the exposure, and you want to
reduce that exposure rather than eliminate it.

---

## What this protects against, and what it does not

**It reduces** the volume of directly identifying information reaching a cloud
provider in query text, chat history, retrieved passages, and generated session
titles.

**It does not** make your data anonymous. This is **pseudonymisation** — a
reversible substitution, with the mapping held by your system. The underlying
content still goes to the provider. A document about a specific person, with the
name masked, is often still about an identifiable person: the surrounding facts,
dates, and relationships frequently make re-identification straightforward.

**It is not a compliance control.** Nothing here makes transmitting personal data
to a third party lawful under any particular regime. If you have a regulatory
obligation, this feature does not discharge it. Treat it as defence in depth, not
as a legal basis.

**It cannot catch what it does not recognize.** Detection is a machine-learning
model with a confidence threshold. It misses things. Any claim of complete
coverage would be false, and the system makes no such claim — nor do the tools it
is built on. Presidio's own documentation states plainly that there is "no
guarantee that Presidio will find all sensitive information" and that no automated
system can guarantee complete recall or precision, recommending it be treated as
one layer of a defence-in-depth strategy rather than a solution.

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
| Correctly identifying that a document concerns a specific person | **No** — this is the fundamental limit |

---

## Turning it on

```yaml
pii:
  enabled: true
```

Then restart. The system validates its privacy posture at boot and **refuses to
start** in two configurations:

**Non-local embedding provider.** If `pii.enabled` is true and
`active.embedding` points at a cloud provider, boot fails. This is deliberate:
masking covers the generation path, so shipping raw document text to a cloud
embedding API would render the whole exercise pointless. The error names the
provider and tells you what is required.

**GLiNER enabled without the package.** If `pii.gliner.enabled` is true but the
optional `gliner` package is not installed, boot fails rather than silently
falling back to weaker spaCy-only detection. You asked for stronger detection; you
get an error rather than a quiet downgrade.

A third refusal lives in the eval service: with `pii.enabled` set, it will not
start against a cloud judge unless `pii.allow_cloud_judge` is explicitly true.
Judge prompts embed retrieved chunks and generated answers **verbatim and
unmasked**, so a cloud judge would leak exactly what masking was protecting. Only
set that flag when your evaluation data contains no real PII.

---

## What gets masked, and where

Masking applies at these points:

- **The user's query**, before it reaches the model.
- **Chat history**, before it is folded into a condensed question.
- **Retrieved context**, before it is placed in the prompt.
- **Session-title generation**, which is a separate LLM call.
- **The contextual-prefix call during ingestion** — the document name and chunk
  preview are masked before that LLM call, and the returned prefix is unmasked
  before storage.

That last item is worth flagging, because the repository contradicts itself about
it. The `config.yml` comment and the docstring on the boot-time privacy check both
state that contextual enrichment is never masked. A second docstring, on the PII
configuration class, correctly says the document name and chunk preview *are*
masked — which is what the code actually does.

So the behaviour is safe and the description is inconsistent. The code masks it;
one of the two docstrings and the config comment are wrong. This is recorded in
[`docs/suggestions.md`](../suggestions.md).

### What is never masked

**Embeddings.** Chunk text is embedded unmasked. This is safe only because a
local embedding provider is enforced at boot — the text never leaves your
network. It is why that boot check is not negotiable.

**The reranker.** It scores original text, deliberately: masked text would rank
worse, so masking before reranking would trade quality for a privacy benefit that
does not exist. The reranker is a local cross-encoder; nothing is transmitted.

**Sources returned to the user.** Source excerpts are always unmasked before they
reach you. You see real text, never `[[[PERSON_0]]]`.

**Judge prompts.** As above — verbatim and unmasked, which is why the eval service
refuses a cloud judge.

**Data at rest.** Documents, chunks, and chat history are stored unmasked in
PostgreSQL. Masking is a transmission-time transformation, not storage
encryption.

---

## How masking works

Detection uses **Microsoft Presidio**, combining pattern-based recognizers for
structured identifiers with a spaCy NER model (`en_core_web_md` by default) for
names and similar entities.

Seven entity types are detected by default:

`PERSON` · `EMAIL_ADDRESS` · `PHONE_NUMBER` · `CREDIT_CARD` · `US_SSN` ·
`IBAN_CODE` · `IP_ADDRESS`

Anything scoring above `pii.score_threshold` (default `0.5`) is replaced with a
token of the form `[[[PERSON_0]]]`. The bracket format is chosen to be
distinctive enough that a model is unlikely to alter it in passing.

The mapping from token to original value is held **in memory, per session, and
never persisted**. It is bounded by both an idle TTL and a session cap. Losing a
mapping is safe: the next turn re-masks from stored history, and only the token
numbering changes.

### Structured identifiers versus names

This distinction predicts most of your results.

Credit cards, SSNs, IBANs, IP addresses, and emails have rigid formats. Pattern
recognizers catch them reliably.

**Names do not have a format.** Detecting them means a model deciding whether a
capitalized word is a person, an organization, a place, or a product. This is
where misses happen, and `PERSON` is the entity type where the shipped
configuration is weakest — the project's own configuration comments say so
directly.

Common failure cases: unusual and non-Western names, names that are also common
words, names in unusual grammatical positions, and names inside otherwise
structured content like tables.

### Improving name detection

Two options, in increasing cost:

**A larger spaCy model.** Set `pii.spacy_model: en_core_web_lg`. The
configuration file describes this as more accurate, and it is roughly fifteen
times larger on disk — but temper your expectations. spaCy's own published
evaluation tables show `en_core_web_lg` and `en_core_web_md` at nearly identical
overall NER accuracy, differing by about one point of named-entity recall. It is
not a targeted fix for weak `PERSON` detection, and the disk cost is real. Test
it rather than assuming it solves the problem.

**GLiNER.** Set `pii.gliner.enabled: true` (and install the optional package).
This registers a second recognizer *alongside* spaCy rather than replacing it,
specifically for NER-shaped entities. The project's own figures — stated in the
configuration file, not independently measured here — put it at roughly ten times
the CPU cost per call, on the order of 160 ms versus 15 ms. On an ingestion run
across a large corpus, that multiplier is significant.

---

## The safety nets

### Token validation

`pii.validation.enabled` (default true) checks that the tokens sent to the model
come back unaltered. Models sometimes reformat them — changing brackets, casing,
or separators — and a mangled token cannot be unmasked, which would leave a
`[[[PERSON_0]]]`-shaped artefact in your answer. When validation detects damage, a
fuzzy recovery routine attempts repair.

Two adjacent settings, `pii.validation.max_retries` and
`pii.validation.alert_on_failure`, are parsed but never acted on. Recovery runs
once, unconditionally, and no alerting path exists. Do not rely on them.

### Output guardrails

`pii.output_guardrails.enabled` (default true) scans the final unmasked response
for personal data appearing verbatim — a check that masking did not miss something
that then came back in the model's output.

`block_on_detection` (default false) controls whether a detection raises an error
or merely records the event.

**This cannot work for streaming responses.** By the time the complete answer
exists to be scanned, tokens have already been sent to the client. On the
streaming path the guardrail is audit-only, regardless of `block_on_detection`.
If blocking matters to you, do not use the streaming endpoint.

### Audit logging

`pii.audit.enabled` (default true) records masking and unmasking operations —
entity types and counts, never the original values at INFO level. This is what
lets you answer "what did this system actually send out?" after the fact.

---

## Verifying it yourself

Do not take the configuration's word for it. Four checks, in order of effort:

**1. Confirm the boot check bites.** Set `pii.enabled: true` alongside a cloud
embedding model and start the stack. It should refuse to boot with a clear
message. If it starts, something is wrong with your configuration path — you may
be editing a `config.yml` that is not the one being mounted.

**2. Watch the audit log.** Enable masking, run a query whose text contains a
name and an email address, and check the logs:

```bash
docker compose logs rag-server | grep -i "pii"
```

You should see mask and unmask operations with entity counts. Zero detections on
text you know contains PII means detection is not working.

**3. Test detection against your own content directly.** Take a genuinely
representative sample of your documents — real names, real formatting — and check
what is detected. This is the only test that tells you about *your* corpus.
Synthetic examples using obviously-fake names will overstate coverage, because
common Western first names are the easy case.

**4. Look for what got through.** The failure that matters is a name in the text
that appears in neither the audit log nor as a token. Read a masked payload if you
can, and specifically check names in unusual positions: inside tables, in headers,
in signature blocks, hyphenated, or non-Western.

---

## What it costs you

**Latency.** Detection runs over the query, the chat history, and every retrieved
chunk on every request. With spaCy the per-call cost is small; with GLiNER it is
roughly an order of magnitude higher per the project's own figures. There is no
measured end-to-end figure in this repository, and this guide will not invent one
— measure it on your hardware using the latency metrics from chapter 4, comparing
runs with masking on and off.

**Quality.** This is the cost people underestimate. The model sees
`[[[PERSON_0]]]` where a name was. That degrades answers in specific ways:

- Questions *about* a person become harder, since the entity is now opaque.
- Coreference across turns can break when token numbering shifts between requests.
- The model may comment on the tokens, or refuse, or produce awkward phrasing
  around them.
- False positives are the worst case: a masked product name or technical term the
  detector mistook for a person removes information the model needed, and you get
  a worse answer for no privacy benefit at all.

**This is measurable, and you should measure it.** Run your golden set with
`pii.enabled: false`, run it again with `true`, and compare faithfulness and
correctness. Chapter 6 covers doing that comparison properly, and chapter 7 has it
as a recipe. It is the only way to know what privacy is costing you rather than
guessing.

**Ingestion cost**, if contextual retrieval is on: masking now runs on every chunk
preview during ingestion as well.

---

## Recommendations (not currently implemented)

These are not RAGBench behaviours. They are general practice, listed separately so
they cannot be mistaken for features.

- **Treat the local-model posture as the default for sensitive corpora**, and the
  masking tier as a considered exception for specific high-value queries.
- **Tune `score_threshold` toward false positives** when the cost of a leak
  exceeds the cost of a degraded answer. Detection confidence is a dial, and 0.5
  is a starting point rather than a recommendation.
- **Keep a small adversarial test set** — documents containing the name formats
  your detector is worst at — and re-check it whenever you change the spaCy model,
  the entity list, or the threshold.
- **Review the audit log periodically** rather than only after an incident.
  Detection counts dropping is a signal worth having.

---

**Next:** [9. Reading the dashboard](09-reading-the-dashboard.md).

Engineering detail: [`docs/internal/pii-masking.md`](../internal/pii-masking.md).
