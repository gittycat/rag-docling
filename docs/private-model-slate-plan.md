# Plan: private inference and judge on self-hosted open-weight models

**Audience.** An implementing agent with no prior context on this conversation.
Read this file top to bottom before editing anything. Steps are ordered by real
dependency, not by preference — later steps assume earlier ones landed.

**Goal.** Give the AWS deployment a self-hosted inference and judge model served
by vLLM inside the VPC, so a confidential corpus can be answered *and* evaluated
without corpus text reaching a vendor API.

---

## Deployment modes — read this before any step

Exactly **two** modes. They do not overlap, and nothing bridges them.

**Mode A — laptop, OpenAI.** Docker Compose runs on the laptop (Postgres, TEI,
reranker, rag-server, task-worker, evals, webapp). No GPU, now or later. Every
LLM call goes to OpenAI (`third_party`): `gpt-5-mini` for inference, `gpt-5.2`
for the judge — both unchanged by this plan. Public datasets only; the
data-policy gate refuses a confidential corpus here, which is correct and must
stay that way.

**Mode B — AWS, vLLM.** The compose stack runs on the demo EC2 instance
(`docker-compose.aws.yml`, `RagbenchDemoStack`). The GPU is a *separate* instance
(`RagbenchLlmStack`, Step 3) reached across the VPC by private address. No call
reaches OpenAI in this mode.

| Mode | Inference | Judge | Boundary |
|---|---|---|---|
| A — laptop | `gpt-5-mini` (OpenAI) | `gpt-5.2` (OpenAI) | `third_party` |
| B — AWS | `Qwen/Qwen3.5-9B` on vLLM | `Qwen/Qwen3.8-27B` on vLLM | `customer_managed` |

**There is no laptop-to-AWS path.** No SSM tunnel, no VPN, no PrivateLink, no
public endpoint. If you find yourself building one, you have misread this
section. (For the record, since it gets proposed: PrivateLink connects a VPC to
an AWS service or another VPC. It has no path to a laptop and would not solve
this even if it were wanted.)

**Consequence, accepted deliberately:** a privacy demo requires Mode B. Mode A
cannot demonstrate confidential-corpus handling, because its only LLM is a vendor
API and the gate correctly refuses it. Bringing AWS up is a precondition for
demoing privacy, not an optimisation.

**Leave the existing `vllm` compose service alone.** `docker-compose.yml:156`
plus `just judge-up` serve a developer with a local Linux CUDA box. That is
neither Mode A nor Mode B. Do not extend it, do not build tooling around it, and
do not delete it — it is out of scope in both directions.

---

## Decisions already made — do not relitigate

These were settled after research. Implement them; do not re-open them.

| Slot | Model | Boundary |
|---|---|---|
| Inference (Mode B) | `Qwen/Qwen3.5-9B` | `customer_managed` |
| Judge (Mode B) | `Qwen/Qwen3.8-27B` | `customer_managed` |
| Inference + judge (Mode A) | `gpt-5-mini` / `gpt-5.2`, unchanged | `third_party` |
| Embedding (both modes) | `Qwen/Qwen3-Embedding-0.6B` via TEI, unchanged | `customer_managed` |
| Reranker (both modes) | `cross-encoder/ms-marco-MiniLM-L-6-v2`, unchanged | `customer_managed` |

- **GPU is `g6e.xlarge` (1× L40S, 48 GB), not `g6.xlarge` (1× L4, 24 GB).**
  Decode is memory-bandwidth-bound: L40S is 864 GB/s vs L4's 300 GB/s (2.88×)
  for 2.3× the hourly price, so it is cheaper *per token* despite costing more
  per hour. The instance is torn down after each run, so per-token is the metric
  that matters. The 48 GB also lets both models stay resident, which the 24 GB
  card cannot do (6.5 + 17 GB of weights leaves nothing for KV cache).
- **Both models must be resident simultaneously.** The `end_to_end` eval tier
  needs the inference model answering live queries while the judge grades them.
  A "start only the one you need" arrangement breaks that tier.
- **Stay on vLLM.** Do not switch to SGLang. `LLMProvider.VLLM` maps to
  LlamaIndex's `OpenAILike` (`services/rag_server/infrastructure/llm/factory.py:39-41`),
  so the provider already means "any OpenAI-compatible `/v1` endpoint". vLLM's
  broader hardware support is what keeps the deployment portable to a non-AWS
  host later, which is a stated project goal.
- **Do not reject the MoE (`Qwen3.5-35B-A3B`) on VRAM grounds** — it fits in
  48 GB. It is rejected because a 3B-active MoE is a weaker judge than a dense
  27B, and the judge must be at least as capable as the answer model.
- **The boundary label for the AWS models is `customer_managed`.**
  `ExecutionBoundary` describes where the model *executes*, not who operates the
  datacentre — see `models_config.py:28` ("a host/VPC we run: local Docker, our
  EC2, our K8s") and the design-decisions entry *"Execution boundary instead of a
  local/cloud boolean"*. Do not relabel it `aws_managed`; that value is reserved
  for Bedrock and SageMaker managed endpoints, which this is not.

---

## Repo facts you must NOT "fix"

Verify each before you touch it; each of these looks like a bug and is not.

1. **The vLLM image pin is already `v0.28.0`** (`docker-compose.yml:158`, currently
   an uncommitted working-tree change from `v0.11.0`). Qwen3.5+ needs the Gated
   DeltaNet kernels that landed in vLLM 0.17. This is done. Do not re-bump it,
   and do not revert it.
2. **`services/evals/evals/pricing.py` deliberately has no entry for self-hosted
   models.** A `"vllm/*"` entry priced at zero was removed on purpose — read the
   comment at the end of `MODEL_COSTS`. Do not add one. Step 4 covers the correct
   mechanism.
3. **The `vllm` compose service is `profiles: ["judge"]` and CUDA-only.** `just
   judge-up` hard-fails on non-Linux by design. That is not a portability bug.
4. **`docker-compose.aws.yml` has no `vllm` service and must not gain one.** The
   demo instance is not a GPU instance; the GPU is a separate stack (Step 3).
5. **`pii.enabled: true` is rejected at config load if the embedding provider is
   not local** (currently only `tei`). Nothing in this plan changes the embedding
   provider, so nothing here should touch that check.
6. **`data_policy.allowed_judge_boundaries` fails closed on a missing boundary.**
   Every new model entry must declare `execution_boundary` explicitly.

---

## Step 1 — Fix the stale eval model id

`config.yml`, `models.eval.claude-sonnet` names `claude-sonnet-4-20250514` while
`models.inference.claude-sonnet` names `claude-sonnet-5`. The eval-tier id was
retired 2026-06-15 and returns 404.

1. Change `models.eval.claude-sonnet.model` to `claude-sonnet-5`.
2. In `services/evals/evals/pricing.py`, the `claude-sonnet-4-20250514` entry
   carries the comment *"still referenced by config.yml's eval tier"*. That
   becomes false. Keep the price entry (historical runs still resolve against
   it) but correct the comment to say it is retained for historical runs only.

**Do not** describe this as invalidating past baselines. `active.inference` is
`gpt5-mini` and `active.eval` is `gpt5-2`; neither Claude entry is active, so no
shipped baseline was ever graded by the stale id.

**Verify:** `just show-config` resolves without error; `rg claude-sonnet-4 config.yml`
returns nothing.

---

## Step 2 — Confirm the quantized checkpoints exist, and budget the card

Do this before writing any infrastructure. The parameter counts are known; the
exact Hugging Face repo ids for quantized builds are not, and must not be
guessed.

1. Confirm on Hugging Face that `Qwen/Qwen3.5-9B` and `Qwen/Qwen3.8-27B` exist
   and note their native dtype and file sizes.
2. Find the actual quantized repo ids you intend to serve (AWQ / GPTQ / FP8).
   If no trustworthy 4-bit checkpoint exists for a model, use vLLM's on-the-fly
   FP8 (`--quantization fp8`, supported natively on the L40S's Ada cores) rather
   than inventing a repo id.
3. Record the chosen ids and their measured on-disk sizes in this file before
   proceeding.

**Memory budget on one 48 GB L40S.** Both servers share the card, so
`--gpu-memory-utilization` must be set explicitly on **both**. vLLM defaults to
`0.9` each, and two defaulted processes will OOM on start. This is the single
most likely way to lose an afternoon on this task.

| | Weights (approx) | Suggested `--gpu-memory-utilization` |
|---|---|---|
| Inference (9B) | 6.5 GB @ 4-bit / ~9 GB @ FP8 | `0.35` (~16.8 GB) |
| Judge (27B) | 17 GB @ 4-bit / ~27 GB @ FP8 | `0.60` (~28.8 GB) |

Sum to at most `0.95`; leave the rest for the CUDA context. Qwen3.5/3.8 run
Gated DeltaNet linear attention in 48 of 64 layers with a constant recurrent
state, so per-sequence KV cache is much smaller than a dense 27B would suggest —
the remaining headroom goes further than it looks. Tune from measurement, not
from this table.

### Implementation record (2026-08-28)

- Inference: `Qwen/Qwen3.5-9B`, native BF16 checkpoint, 19.3 GB on disk. No
  official 4-bit vLLM checkpoint was selected, so the server uses vLLM's native
  `--quantization fp8` on the L40S and serves the original repository id.
- Judge: `Qwen/Qwen3.8-27B-FP8`, official FP8 checkpoint, 30.9 GB on disk.
- The source `0.35` / `0.60` split could not load the 30.9 GB judge inside its
  28.8 GB reservation. The implemented explicit split is `0.30` inference /
  `0.65` judge, still totaling `0.95`; validate it with `nvidia-smi` on the
  first deployed instance.

---

## Step 3 — Add `RagbenchLlmStack`, modelled on `embed-stack.ts`

`infra/lib/embed-stack.ts` (173 lines) is already the correct pattern: an opt-in,
ephemeral, context-gated GPU instance whose entire install is a `docker run
--gpus all` in user data, on spot, with the endpoint published to SSM. Copy it
rather than inventing a new shape.

1. New `infra/lib/llm-stack.ts` following `embed-stack.ts` closely: SSM-resolved
   Deep Learning Base AMI, `CfnInstance` + LaunchTemplate for spot support
   (`ec2.Instance` L2 has none — see the comment at `embed-stack.ts:143`),
   `SpotRequestType.ONE_TIME`, `SpotInstanceInterruption.TERMINATE`.
2. Instance type `g6e.xlarge`, sourced from `infra/lib/config.ts` the way
   `cfg.embedInstanceType` is, not hardcoded.
3. **Two `docker run` commands in user data, not one** — one per model, on
   distinct host ports (8000 inference, 8001 judge), each with its explicit
   `--gpu-memory-utilization` from Step 2 and `--served-model-name` set to the
   repo id. Both get `--gpus all`; they share the one card by budget, not by
   partition.
4. Gate it in `infra/bin/ragbench.ts` behind `-c llmStack=true`, exactly as
   `embedStack` is gated at line 60. A bare `cdk deploy --all` must never stand
   up a GPU instance.
5. Publish both endpoints to SSM: `/ragbench/${ENV_NAME}/llm-endpoint` and
   `/ragbench/${ENV_NAME}/judge-endpoint`.
6. **Keep the security group closed.** `embed-stack.ts:79` allows ingress from
   `props.demoInstanceSg` only. Copy that exactly — no CIDR rule, no public
   ingress, ever. An unauthenticated vLLM endpoint on a public IP would hand
   corpus text to anyone who portscans it, which defeats the entire point of
   this work. Nothing outside the VPC needs to reach these ports.
7. Add `just llm-up` / `just llm-down` mirroring `embed-up` / `embed-down`,
   including the `AWS_ENV` guard, the env-qualified stack name, and the
   address-range-scoped `config.yml` `base_url` rewrite with backup-and-restore
   on failure. The rewrite emits the private address read from SSM — there is
   only one form to emit, since only Mode B uses these endpoints.

**Verify:** `cd infra && npx cdk synth --all` does **not** include the stack;
`npx cdk synth -c llmStack=true` does. `npm test` in `infra/` passes. The
synthesised security group has no `0.0.0.0/0` ingress. On a deployed instance,
`nvidia-smi` shows two processes with combined memory below card capacity and
both `/health` endpoints return 200.

---

## Step 4 — Price the self-hosted models, or the scorecard silently changes

This is the step most likely to be skipped and it changes eval results.

`pricing.py` returns `None` for an unpriced model, and an unpriced model is
**excluded from cost scoring rather than counted as $0**. The `cost` objective
carries weight `0.10` in `config.yml`'s `eval.scoring.weights`, and objectives
with no data are dropped with their weight redistributed across the rest.
Swapping to unpriced self-hosted models therefore silently reweights the headline
score, and runs across the change are not comparable.

1. Measure sustained aggregate throughput for each served model under realistic
   concurrency. Do not use a single-stream number.
2. Compute the amortized rate: `usd_per_1m_tokens = instance_usd_per_hour /
   (tokens_per_second * 3600) * 1_000_000`. Use the g6e.xlarge rate you actually
   pay (on-demand ≈ $1.861/hr in us-east-1; spot and reserved differ).
3. Supply it via the `MODEL_PRICE_OVERRIDES` environment mapping, keyed by the
   HF repo id — **not** by editing `MODEL_COSTS`. Example shape is in the
   `pricing.py` module docstring.
4. If you deliberately want a zero marginal rate, set an explicit zero. Do not
   leave it unpriced and call it free.

**Verify:** a short Mode B eval run reports a non-null cost-per-query, and
`eval.scoring.weights.cost` still contributes to the weighted score.

---

## Step 5 — Cold-start policy

A fresh instance pulls tens of GB of weights before vLLM binds — the
`start_period: 900s` on the existing `vllm` healthcheck records that this was
anticipated. Fifteen minutes is not acceptable in front of an audience, and now
there are two models to pull.

The deployment is expected to run only once or twice a month for under an hour,
with very low request volume. It therefore deliberately uses a disposable 100
GiB encrypted root volume and cold-pulls the checkpoints. This avoids paying for
a retained GPU cache or a dedicated GPU AMI while down. `just llm-up` waits up to
30 minutes for both servers to become healthy before publishing their endpoints.

**Verify:** measure the first cold `just llm-up` and record it here. It must be
under 30 minutes; no five-minute target applies to this low-duty-cycle demo.

---

## Step 6 — Add the config entries

Only after Steps 2–5. Mode A needs no new entries — it keeps `gpt5-mini` and
`gpt5-2`. These two are Mode B only. No code change beyond this;
`execution_boundary` is what makes them acceptable to the judge gate, not the
provider string.

```yaml
# config.yml, under models.inference:
qwen35-9b:
  provider: vllm
  model: <exact repo id chosen in Step 2>
  base_url: <private address, written by `just llm-up` from SSM>
  timeout: 120
  execution_boundary: customer_managed

# config.yml, under models.eval:
qwen38-27b-judge:
  provider: vllm
  model: <exact repo id chosen in Step 2>
  base_url: <private address, written by `just llm-up` from SSM>
  timeout: 120
  execution_boundary: customer_managed
```

Leave `active.inference` and `active.eval` pointing at the OpenAI models until
Step 7 has produced a comparison. Switching the active models and re-baselining
in one commit makes a regression unattributable.

**Verify:** `just show-config-full` resolves both entries and reports
`customer_managed` for each; `services/evals/tests/test_privacy_posture.py`
still passes.

---

## Step 7 — Re-baseline along one axis at a time

Swapping the answer model invalidates existing comparisons. Swapping the judge
invalidates them again along a different axis. Doing both at once produces a
number nobody can attribute.

1. Run the **new judge against the stored answers from the existing baseline**.
   Difference here is judge behaviour only.
2. Then switch `active.inference` and run again with the new judge. Difference
   from (1) is answer quality only.
3. Record both in the eval dashboard with explicit run labels naming which axis
   moved.
4. Re-run `just eval-calibrate` — the judge changed, so the existing calibration
   against RAGBench TRACe ground truth no longer describes the judge in use.

---

## Step 8 — Documentation

- `docs/internal/configuration-reference.md`: the two new model entries and the
  `--gpu-memory-utilization` split.
- `docs/guide/`: bringing the GPU up and down for a demo, and the explicit
  statement that a privacy demo requires Mode B.
- `OVERVIEW.md` and `docs/guide/01-overview.md`: both describe deployment shape.
  Make sure they name the two modes as defined here and do not imply a laptop can
  run a private LLM.
- `docs/internal/design-decisions.md` already carries the boundary rationale in
  *"Self-managed inference over Bedrock, despite `aws_managed` being permitted"*.
  Add the L40S-over-L4 reasoning there only if you measure something that
  confirms or contradicts the bandwidth argument — otherwise leave it alone.

---

## Non-goals

Do not do any of these as part of this plan.

- **Any laptop-to-AWS network path** — no SSM port forwarding, no Client VPN, no
  Site-to-Site VPN, no PrivateLink, no public endpoint, no security-group rule
  for a home IP. Mode A uses OpenAI; that is the whole design.
- **Any local LLM on the laptop** — no LM Studio, `llama-server`, Ollama, MLX, or
  `host.docker.internal` entry. Considered and rejected.
- Adding a `vllm` service to `docker-compose.aws.yml`, or extending the existing
  `vllm` compose service in `docker-compose.yml`.
- Switching serving stacks (SGLang, TGI, llama.cpp).
- Changing the embedding model or the reranker.
- Changing retrieval settings, chunking, or scoring weights.
- Adding Bedrock or SageMaker model entries.
- Removing the local Docker development path.
