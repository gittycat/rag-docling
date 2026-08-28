# 12. Private AWS demo

Use this path only when a confidential corpus must be answered **and** judged
without sending its text to a vendor API. It is a separate AWS deployment mode,
not an extension of a laptop setup.

| Mode | Inference | Judge | Confidential corpus |
|---|---|---|---|
| Laptop Compose | OpenAI `gpt-5-mini` | OpenAI `gpt-5.2` | Refused by the data-policy gate |
| AWS private inference | `Qwen/Qwen3.5-9B` | `Qwen/Qwen3.8-27B-FP8` | Allowed inside the customer-managed VPC boundary |

The demo EC2 instance remains CPU-only. `RagbenchLlmStack` starts a separate,
spot `g6e.xlarge` with one L40S GPU. Its two unauthenticated vLLM endpoints are
reachable only from the demo instance security group; they have no public
ingress, no VPN/tunnel route, and no laptop path.

## Bring the GPU up

First bring up the normal AWS demo instance. From a shell with the intended AWS
environment selected, start the opt-in GPU stack:

```bash
just llm-up
```

The command waits until both private `/health` endpoints are ready and replaces
only the two Mode B `base_url` values in the demo instance's `/opt/ragbench/config.yml`
through SSM Run Command. This is remote administration, not an SSM tunnel or a
route from a laptop to vLLM. A cold start downloads
about 50 GB of model weights to a disposable encrypted root disk; allow up to
30 minutes. The stack deliberately retains neither an EBS model volume nor a
GPU AMI because it is expected to run only once or twice a month.

For a private run, set `active.inference: qwen35-9b` and `active.eval:
qwen38-27b-judge`. Keep the OpenAI entries active for ordinary laptop work.
Do not set a confidential corpus to use a third-party judge as a workaround for
the policy gate.

## Price a low-volume demo

Self-hosted cost is not free: an unset price excludes cost from scoring. Measure
the observed aggregate throughput for each server while both are resident, use
the actual spot or on-demand hourly price paid by the demo account, then create
the explicit mapping:

```bash
just llm-price <instance-usd-per-hour> <inference-tokens-per-second> <judge-tokens-per-second>
```

Export the printed `MODEL_PRICE_OVERRIDES` value in the shell that starts or
restarts `rag-server` and `evals`. The mapping is keyed by the served Hugging
Face repository IDs and is passed through Compose to both services. Repeat the
measurement whenever the instance rate or serving configuration changes. For a
demo with only a few dozen requests, also track the actual one-hour GPU charge
as an operating expense; a token-rate scorecard is useful for comparing evals,
but it does not make an otherwise idle GPU free.

## Tear it down

After the demo:

```bash
just llm-down
```

This restores the explicit non-routable placeholders in the two inactive Mode B
model entries before it destroys the LLM stack. Confirm the CloudFormation stack
is gone before considering the demo complete.
