# RAGBench AWS infrastructure

Five CDK stacks host RAGBench on AWS for pre-planned demos and bulk
re-ingestion runs, provisioned on demand and destroyed afterwards so idle cost is
roughly the price of a coffee per month.

| Stack | Lifecycle | What it holds |
|---|---|---|
| `RagbenchBaseStack` | permanent, `terminationProtection: true` | VPC (no NAT), Route53 zone, ACM cert, Cognito user pool, 4 ECR repos, 7 secrets |
| `RagbenchImageStack` | permanent | EC2 Image Builder pipeline that bakes the golden AMI |
| `RagbenchDemoStack` | ephemeral — deploy before a demo, destroy after | one `m7g.xlarge`, ALB + Cognito auth, A record |
| `RagbenchEmbedStack` | ephemeral, **opt-in only** — deploy for a bulk re-ingest, destroy after | one spot `g6.xlarge` (L4 GPU) running TEI + Qwen3-Embedding-0.6B, for bulk re-ingestion only |
| `RagbenchLlmStack` | ephemeral, **opt-in only** — deploy before a private demo, destroy after | one spot `g6e.xlarge` (L40S GPU) running the private inference and judge vLLM servers |

The split is by **lifecycle**, not by function: anything slow to create (ACM
issuance, DNS delegation) or holding state that must survive a teardown (Cognito
users, ECR images, secrets) lives in the base stack.

`RagbenchEmbedStack` is additionally gated: it is not added to the CDK app tree
at all unless `-c embedStack=true` is passed, so a bare `cdk deploy --all` /
`cdk synth --all` can never bring up the billed GPU instance by accident. It has
no golden AMI of its own — it boots straight off AWS's public **Deep Learning
Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04)**, resolved by SSM parameter, and
its entire install is one `docker run --gpus all` in user data. Its security
group accepts TCP 8080 from `RagbenchDemoStack`'s instance security group only —
nothing on it is reachable from the internet. It writes its private IP to SSM
parameter `/ragbench/<envName>/embed-endpoint` once TEI reports healthy (from
user data, not from CloudFormation — see the comment in `embed-stack.ts` for
why), which is how the ingestion tooling finds it.

`RagbenchLlmStack` is likewise gated behind `-c llmStack=true`, so a bare CDK
deploy cannot create its billed GPU instance. Its two vLLM ports accept traffic
only from the demo instance security group; it writes the private inference and
judge endpoints to SSM after both servers are healthy. Use `just llm-up` and
`just llm-down` to manage the complete private-demo lifecycle. See
[`docs/guide/12-private-aws-demo.md`](../docs/guide/12-private-aws-demo.md).

## Environments

`envName` is the only switch. It selects the account, the CIDR, the SSM/secret
namespace and the stack names; `-c envName=<name>` on any `cdk` command.

| `envName` | Account | Profile | VPC CIDR | Stack names |
|---|---|---|---|---|
| `dev` | `011356579819` (sdlc) | `sdlc-admin` | `10.10.0.0/17` | `Ragbench*Stack-dev` |
| `staging` | `011356579819` (sdlc) | `sdlc-admin` | `10.10.128.0/17` | `Ragbench*Stack-staging` |
| `demo` | `364769971558` | `demo-admin` | `10.20.0.0/16` | `Ragbench*Stack` |
| `prod` | `730406060579` | `prod-admin` | `10.30.0.0/16` | `Ragbench*Stack-prod` |

Two environments share the sdlc account, which is why stack names carry the
environment: `dev` and `staging` would otherwise be the same CloudFormation
stack. `demo` is the exception — it was deployed before the suffix existed and
renaming a live stack orphans it rather than moving it, so it keeps the bare
names. Construct ids are bare in every environment, so `cdk deploy
RagbenchBaseStack` selects the right stack regardless.

**Nothing is selected by default.** There is no `.envrc` and no `[default]`
profile, so a fresh shell can reach no account at all:

```console
$ aws s3 ls
aws: [ERROR]: An error occurred (NoCredentials): Unable to locate credentials.
$ npx cdk synth
Error: No environment selected. Run 'setenv <dev|staging|demo|prod>' to set
AWS_ENV and AWS_PROFILE together, or pass -c envName=<name>.
```

`setenv` sets both variables at once, so the environment and the credentials
cannot be typed separately and disagree:

```console
$ setenv prod
prod → prod-admin (730406060579)     # terminal turns dark red, prompt shows prod
$ npx cdk deploy RagbenchBaseStack   # no -c flags needed
$ setenv none
cleared — AWS calls will now fail until you select an environment
```

**The account guard** is the backstop for the case `setenv` cannot cover — a
hand-passed `-c envName=`, or an `AWS_PROFILE` exported by something else.
`loadConfig` refuses to synthesize when `envName` and the live credentials
disagree, naming the profile that would have been right. Without it, prod-named
resources — prod SSM paths, prod secrets, prod CIDR — land in whichever account
happens to be active, and the deploy succeeds.

Add a new environment to `ENVIRONMENTS` **and** `ENV_CIDRS` in `lib/config.ts`,
and to `_SETENV_PROFILES` in `setenv.zsh`. An unknown `envName` is
rejected rather than silently defaulted.

## Why a golden AMI

A cold `docker pull` of 4–6 GB of images plus a 1.3 GB model download costs 15+
minutes on every provision. The Image Builder pipeline bakes the images, the
HuggingFace cache (reranker + Docling), the TEI model weights **and an
already-ingested corpus** into the AMI, so `just aws-up` is a boot, not an
install. The cost is ~$2.20/month of snapshot storage, which is the largest
single idle line item and the right trade.

## One-time setup

Do these once, by hand, before anything else. They are not CDK.

1. **Create the account.** In AWS Organizations, use **Control Tower Account
   Factory** (never the plain Organizations console — that skips the guardrails)
   to create `ragbench-demo` in the **Workloads/Demo** OU. All three stacks live
   there — account `364769971558`.
2. **Delete the default VPC** in `ragbench-demo`, region `ap-southeast-2`.
3. **Bootstrap CDK:** `cdk bootstrap aws://364769971558/ap-southeast-2`
4. **Select an environment** in each shell that needs one:
   ```console
   $ setenv demo
   demo → demo-admin (364769971558)
   ```
   `setenv` is a shim in `~/.zshrc` that sources `./setenv.zsh` from the root of
   the current git repo — see the header of that file for the seven lines. The
   file has to be sourced rather than executed, because an executed script sets
   its variables in a child process that then exits. Without the shim,
   `source ./setenv.zsh demo` from the repo root does the same thing.
   Nothing else may export `AWS_PROFILE`, `AWS_ACCOUNT_ID` or `AWS_REGION`: the
   profile already carries the region, CDK reads `CDK_DEFAULT_ACCOUNT` from the
   resolved credentials, and `just ecr-push` calls `sts get-caller-identity`. A
   hand-maintained copy of any of them can only drift. See § Environments.
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
  bin/ragbench.ts       app entrypoint, wires the stacks (embed stack is opt-in)
  lib/config.ts         every value the stacks agree on; override with -c key=value
  lib/base-stack.ts     persistent resources
  lib/image-stack.ts    Image Builder pipeline (all L1 — there is no L2)
  lib/demo-stack.ts     ephemeral instance + ALB + DNS
  lib/embed-stack.ts    ephemeral burst GPU embedder, opt-in with -c embedStack=true
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
