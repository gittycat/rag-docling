# RAGBench AWS infrastructure

Three CDK stacks that host RAGBench on AWS for pre-planned demos, provisioned on
demand and destroyed afterwards so idle cost is roughly the price of a coffee per
month.

| Stack | Lifecycle | What it holds |
|---|---|---|
| `RagbenchBaseStack` | permanent, `terminationProtection: true` | VPC (no NAT), Route53 zone, ACM cert, Cognito user pool, 4 ECR repos, 7 secrets |
| `RagbenchImageStack` | permanent | EC2 Image Builder pipeline that bakes the golden AMI |
| `RagbenchDemoStack` | ephemeral — deploy before a demo, destroy after | one `m7g.xlarge`, ALB + Cognito auth, A record |

The split is by **lifecycle**, not by function: anything slow to create (ACM
issuance, DNS delegation) or holding state that must survive a teardown (Cognito
users, ECR images, secrets) lives in the base stack.

## Why a golden AMI

A cold `docker pull` of 4–6 GB of images plus a 1.3 GB model download costs 15+
minutes on every provision. The Image Builder pipeline bakes the images, the
HuggingFace cache (reranker + Docling), the Ollama model **and an
already-ingested corpus** into the AMI, so `just aws-up` is a boot, not an
install. The cost is ~$2.20/month of snapshot storage, which is the largest
single idle line item and the right trade.

## One-time setup

Do these once, by hand, before anything else. They are not CDK.

1. **Create the account.** In AWS Organizations, use **Control Tower Account
   Factory** (never the plain Organizations console — that skips the guardrails)
   to create `ragbench-sdlc` in the **SDLC** OU. The demo infrastructure lives there;
   there is no separate demo account.
2. **Delete the default VPC** in `ragbench-sdlc`, region `ap-southeast-2`.
3. **Bootstrap CDK:** `cdk bootstrap aws://011356579819/ap-southeast-2`
4. **Point the shell at the account.** Create `.envrc` at the repo root (it is
   gitignored) and run `direnv allow`:
   ```bash
   export AWS_PROFILE=sdlc-admin
   export AWS_REGION=ap-southeast-2
   export AWS_ACCOUNT_ID=011356579819   # used by `just ecr-push` to derive REGISTRY
   ```
5. **Deploy the base stack:**
   ```
   cd infra && npx cdk deploy RagbenchBaseStack
   ```
6. **Delegate DNS.** The stack output `HostedZoneNameServers` lists four NS
   records. Add them for `demo.<yourdomain>` at your existing DNS provider. ACM
   validation will not complete until this is live — expect a few minutes.
7. **Fill in the two API keys** (everything else is generated):
   ```
   aws secretsmanager put-secret-value --secret-id ragbench/demo/OPENAI_API_KEY    --secret-string 'sk-...'
   aws secretsmanager put-secret-value --secret-id ragbench/demo/ANTHROPIC_API_KEY --secret-string 'sk-ant-...'
   ```
8. **Create the demo logins.** Sign-up is disabled, so add each viewer:
   ```
   aws cognito-idp admin-create-user --user-pool-id <UserPoolId output> \
     --username someone@example.com --user-attributes Name=email,Value=someone@example.com
   ```
9. **Deploy the image pipeline:** `npx cdk deploy RagbenchImageStack`
10. **Push the images and bake:** `just ecr-push && just aws-bake` (~15 min).

`cdk.context.json` is not committed yet — the first successful synth against a
real account writes it. Commit it then, so AZ lookups stay deterministic.

## Per-demo

```
just aws-up      # cdk deploy RagbenchDemoStack, prints the URL
...
just aws-down    # cdk destroy RagbenchDemoStack
```

Re-bake (`just ecr-push && just aws-bake`) only when the images or the corpus
change. Because the schema is created by `services/postgres/init.sql` on first
boot and nothing runs migrations, **a schema change needs a re-bake** — see
`docs/suggestions.md`.

## Registry

Four private ECR repositories, created by `RagbenchBaseStack` and named
`ragbench/<image>`:

| Repository | Used by |
|---|---|
| `ragbench/webapp` | `webapp` |
| `ragbench/rag-server` | `rag-server` **and** `task-worker` |
| `ragbench/postgres` | `postgres` |
| `ragbench/evals` | `evals` |

Each keeps the last 5 images, scans on push, and is `RETAIN`ed so a teardown
never deletes them.

```
just ecr-push          # tags with the short git SHA + latest
just ecr-push v1.2.0   # or an explicit tag
```

Builds are `linux/arm64` only, matching the `m7g.xlarge` demo instance — native
on an Apple Silicon machine, no emulation. The recipe checks the repositories
exist before building, so a missing `RagbenchBaseStack` fails in seconds rather
than after ten minutes of builds.

Two names that are easy to conflate: `REGISTRY_HOST`
(`<account>.dkr.ecr.<region>.amazonaws.com`) is what `docker login` takes, and
`REGISTRY` (`$REGISTRY_HOST/ragbench`) is the repository namespace images are
tagged into. `docker-compose.aws.yml` and both shell scripts use `REGISTRY`; only
the login uses the host.

Pull rights are granted per repository with `grantPull()` — to the demo instance
role and to the Image Builder role, which pulls all four during a bake.

## The secrets shim

`services/rag_server/app/settings.py` and `services/evals/infrastructure/settings.py`
both override `settings_customise_sources()` to return `(file_secret_settings,)`
only. Environment variables are deliberately ignored, on the OWASP rationale in
`secrets/README.md`. So the usual "inject secrets as env vars" pattern does not
work here.

Instead `infra/assets/fetch-secrets.sh` (run from user data at every boot, and
once during the bake) writes each Secrets Manager value to `secrets/<NAME>` on
the host, which compose mounts at `/run/secrets/<NAME>`. No application change
needed. The bake deletes those files again before the snapshot, so nothing
sensitive lands in the AMI.

## Access

There is no SSH key, no bastion and no port 22. Get a shell with Session
Manager:

```
aws ssm start-session --target <InstanceId output>
```

The application has **no authentication of its own**. The ALB's
`authenticate-cognito` action is the only gate, and the instance security group
accepts port 8000 from the ALB security group and nothing else. `evals` (8002)
and `rag-server` (8001) are not published by `docker-compose.aws.yml` at all.

## Layout

```
infra/
  bin/ragbench.ts       app entrypoint, wires the three stacks
  lib/config.ts         every value the stacks agree on; override with -c key=value
  lib/base-stack.ts     persistent resources
  lib/image-stack.ts    Image Builder pipeline (all L1 — there is no L2)
  lib/demo-stack.ts     ephemeral instance + ALB + DNS
  lib/bundle.ts         assembles the repo files the instance needs, as one S3 asset
  assets/bake.sh        runs inside Image Builder to produce the AMI
  assets/boot.sh        EC2 user data
  assets/fetch-secrets.sh
  test/ragbench.test.ts
```

Configuration is context-driven; the defaults are in `lib/config.ts`:

```
npx cdk deploy -c domainName=demo.example.com -c instanceType=m7i.xlarge
```
