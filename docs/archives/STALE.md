# Stale documentation archive

Superseded documentation retained on 2026-08-28 for historical context. It is
not an operating guide. The current private-model procedure is
[Chapter 12 — Private AWS demo](../guide/12-private-aws-demo.md).

## Laptop self-hosted vLLM guidance

The following guidance described a laptop or arbitrary host running its own vLLM
endpoint. It is no longer a supported deployment mode.

### `README.md`

> Option to run fully on-prem (locally). No calls outside the intranet needed.
> For decent performance, this requires a dedicated server spec'd for large open
> source models.

> Fully local generation is not out-of-the-box the way embeddings are: it
> requires pointing `active.inference` at a self-hosted vLLM endpoint you run
> separately (see the commented `qwen-vllm` example in `config.yml`); otherwise
> generation uses a cloud provider.

### `OVERVIEW.md`

> Can run 100% on-premises if the hardware needed is present.

> Answer generation: your choice, served by a self-hosted vLLM endpoint (not a
> Compose service — see `config.yml`'s commented `qwen-vllm` example).

### `docs/guide/02-getting-running.md`

> For local generation too, change `active.inference` to a self-hosted vLLM
> endpoint you run yourself (see the commented `qwen-vllm` example in
> `config.yml`).

### `docs/guide/07-experiment-cookbook.md`

> Recipe 2 — Local vs cloud generation model. Uncomment and point the
> `qwen-vllm` entry in `config.yml` at a vLLM endpoint you run yourself, then
> change `active.inference` to `qwen-vllm`.

> Local latency depends on your hardware. The cost metric records self-hosted
> vLLM API cost as zero but does not include hardware.

### `docs/internal/configuration-reference.md`

> The commented `qwen-vllm` entry (`provider: vllm`,
> `base_url: http://vllm:8000/v1`) is the documented self-hosted-inference path.

### `docs/internal/development.md` and `docs/internal/cicd-deployment.md`

> A self-hosted vLLM model, if you configure one, is a Compose service.

> Embedding inference (`tei`) and any self-hosted vLLM model are Compose
> services, gated by `depends_on: service_healthy`.

## Laptop CUDA judge procedure

The old `just judge-up` procedure was replaced by `just llm-up`, which creates a
VPC-private L40S instance hosting both inference and the judge for a demo.

### `docs/guide/08-privacy-and-pii.md`

> Point `active.eval` at an in-boundary judge (`just judge-up` starts one).

### `docs/guide/10-troubleshooting.md`

> `just judge-up` starts the in-boundary judge, then point `active.eval` at it.

### `docs/internal/eval-framework.md`

> `just judge-up` starts a self-hosted vLLM judge (profile-gated, CUDA only).
> If that judge shares a GPU with the application, judge evaluation must run
> after system traces are captured.

## Planned burst judge stack

This roadmap item is complete in a different form: the implemented
`RagbenchLlmStack` serves both private inference and judging, rather than a
judge-only stack or a Compose GPU service.

### `docs/ROADMAP.md`

> **Burst GPU Judge Stack (`RagbenchJudgeStack`)** — a CDK stack for the
> self-hosted judge, mirroring `embed-stack.ts`: an ephemeral GPU instance
> brought up with `just judge-up` and destroyed with `just judge-down`.

> The compose `vllm` service needs a CUDA host. A burst stack would make judged
> metrics possible on a confidential corpus from a machine that cannot run vLLM
> locally, at the cost of a second deployment surface.

> **Status:** Not started. The Compose service (`just judge-up`) is the shipped
> answer; this is the recorded alternative.

## Contextual-retrieval idea

### `docs/TODO.md`

> Use a faster/local model for context generation — point contextual prefix
> generation at a self-hosted vLLM model (for example, a small Qwen instruct
> model) specifically to eliminate network latency. 2–10x faster.
