
## Quick Start

Log in once — the sso-session is shared by all four profiles:

```bash
aws sso login --sso-session kiluna
```

From there, use `mgmt-admin` for anything at the account or OU level, and the
per-environment profiles (`prod-admin`, `demo-admin`, `sdlc-admin`) for work
inside an account — EC2, VPC, RDS and the rest.

## The vocabulary

The pieces, from outside in. Each level below is contained by the one above it.

**Organization**
- One tree, one management account at its Root
- Owns consolidated billing and the SCPs
- Ours: `Kiluna`, management account `573051819426`

**OU (Organizational Unit)**
- Groups accounts so a policy can be written once
- **Carries the SCPs** — this is the only reason to create one
- Can hold one or many accounts, and can nest

**Account**
- Belongs to exactly one OU
- The hard boundary: security, quotas, billing line item
- Owns a **network CIDR** range (10.10/16 sdlc, 10.20/16 demo, 10.30/16 prod).
  The sdlc account holds two VPCs, so its /16 splits: `10.10.0.0/17` dev,
  `10.10.128.0/17` staging. Allocations live in `ENV_CIDRS`, `infra/lib/config.ts`.
- Is pinned to its environments in `ENVIRONMENTS` (`infra/lib/config.ts`), which
  `loadConfig` checks the live credentials against — deploying `-c envName=prod`
  with the wrong profile fails at synth instead of building prod-named resources
  in the wrong account. The mapping is many-to-one: dev and staging share sdlc.
  See `infra/README.md` § Environments for the full table.
- Holds one or more **VPCs**

**VPC**
- Provides **network isolation** inside one account and one region
- One per account per region here; the default VPC is deleted

**SCP (Service Control Policy)**
- A *ceiling*, not a grant. It can only take permissions away.
- Overrides IAM: if the SCP denies it, no role, user or admin in that account
  can do it — including the account's own administrator
- Attached to an OU (or Root) and inherited by every account beneath
- **Does not apply to the management account.** That account is unguarded by
  design, which is why no workloads run there.

Examples in this setup:

| SCP | Where | Effect |
|---|---|---|
| Deny `organizations:LeaveOrganization` | Root | An account cannot detach itself from the org |
| Deny disabling CloudTrail / Config | Root | Control Tower's mandatory controls; audit trail can't be switched off |
| Deny all regions except `ap-southeast-2` | Root | Nothing gets provisioned in a region nobody is watching |
| Deny `iam:CreateUser`, `iam:CreateAccessKey` | Workloads | Forces every human through Identity Center; no long-lived keys |
| Deny public S3 / open security groups | Demo | The account outsiders can reach is the one most tightly fenced |
| Deny deleting RDS snapshots or S3 buckets | Prod | Guards real data against a fat-fingered admin |

**Identity Center user → group → permission set → IAM role**
- A **user** lives once, at org level, and is *assigned* to many accounts
- A **group** is what assignments should target, never a user directly
- A **permission set** is a policy template; assigning it creates an IAM role
  named `AWSReservedSSO_<PermissionSet>_<suffix>` in the target account
- Signing in issues temporary credentials for that role — nothing long-lived

**Control Tower / Account Factory**
- The governed way to create accounts and register OUs
- Creating either directly in the Organizations console skips the guardrails

## OU and account layout

```
Root
├─ Security              (OU)
│  ├─ Log Archive        425882540333
│  └─ Audit              452131377392
├─ Workloads             (OU)
│  ├─ Prod               (OU)  ← strict SCPs
│  │  └─ ragbench-prod   730406060579
│  ├─ Demo               (OU)  ← internet-facing SCPs
│  │  └─ ragbench-demo   364769971558
│  └─ SDLC               (OU)  ← relaxed SCPs
│     └─ ragbench-sdlc   011356579819   (dev + staging)
├─ Suspended             (OU)  ← keep UNREGISTERED in Control Tower
└─ Management            573051819426   (at Root, cannot be moved)
```

Home region `ap-southeast-2`, the only enabled one. Landing zone 3.3, automatic
account enrollment on.

### Why the boundaries sit where they do

**The account is the only boundary that carries an SCP.** That single fact drives
every split below. Two environments that need different guardrails cannot share
an account, no matter how cleanly they are separated by stack, VPC or tag.
Everything else — cost attribution, naming, blast radius — has a cheaper
solution than a new account.

**prod is isolated** because it holds real data and real users. Strict SCPs,
nothing else in the account.

**dev and staging share `ragbench-sdlc`.** They want the same relaxed guardrails
and have the same audience (us), so an account boundary between them would buy
nothing and cost a duplicated baseline — NAT gateway, endpoints, budget alarms,
quota requests, permission-set assignments, all per account per region. They are
separated by CDK stack and VPC instead, with `Environment=dev|staging` tags for
Cost Explorer. Deliberately *not* one account per environment.

**demo gets its own account and OU** because it is reachable by people outside
the team. That flips two things at once: it needs hardened internet-facing SCPs
that would strangle dev, and a compromise there must not reach dev's roles,
artifacts and buckets. It is not prod — different guardrails, different OU — so
folding it into Prod would muddy what Prod means.

**The management account runs no workloads.** It owns the org-level APIs
(`organizations`, `account`, SCPs, Control Tower) and nothing else.

One documented exception: three S3 Glacier vaults — `negatives`, `scans` and
`scanner-ICC-profiling`, ~612 GB created in 2021 — predate the landing zone and
stay put. Glacier has no cross-account transfer, so moving them would mean
retrieving all 612 GB and re-uploading, at real cost, for cold archives nobody
reads. The rule is therefore *no compute or application workloads*; these are
grandfathered storage. They carry no vault access or lock policy, so access is
plain IAM and runs through Identity Center like everything else.

### Multiple demos

Several demos for different audiences live as separate stacks *inside*
`ragbench-demo`, not as separate accounts — they share guardrails, so the
argument that earned demo its own account does not repeat between them. Audience
isolation is enforced at the app layer: separate domain, ALB and Cognito pool per
demo.

Give a demo its own account only when one of these is true: it carries real or
NDA'd data; it needs guardrails the others do not (a different region, a blocked
service); it might be handed to someone else to own; or it falls inside a
compliance scope the others do not.

### When to revisit

Split `ragbench-sdlc` only on a concrete trigger, not on principle:

- staging needs to rehearse against prod's actual account-level config (SCPs,
  quotas, IAM boundaries) — the strongest of the three
- one environment's usage starves another's quotas
- a non-prod environment starts holding real data

Migration cost is bounded — non-prod state is disposable, so it is a CDK redeploy
into a new account, not a data migration.

### Naming

OUs stay bare (`Prod`, `SDLC`, `Demo`) because they are always read in the org
tree next to their parent. Accounts get a `<workload>-<env>` prefix because
account names appear alone on invoices, in Cost Explorer, the SSO portal and
CloudTrail. `Management` follows AWS's own term for the role; `Admin` was
rejected as ambiguous with admin *access*.

If a second product ever arrives, it gets its own account set (`appB-prod`,
`appB-demo`, `appB-sdlc`) under the same OUs rather than sharing ragbench's
accounts — the OU is the policy boundary, the account is the workload boundary.

### Conventions

- One VPC per account per region, built by CDK. Delete both VPCs a new account
  ships with — the AWS default and `aws-controltower-VPC` (teardowns below).
- Non-overlapping CIDRs per account so peering or Transit Gateway stays possible.
- Create OUs and accounts through Control Tower Account Factory, never directly
  in the Organizations console — ungoverned OUs skip guardrails.
- AWS profiles are named per account+role (`mgmt-admin`, `prod-admin`,
  `demo-admin`, `sdlc-admin`), never per project. A shell selects one
  explicitly with `setenv <env>`; nothing selects one automatically.
- Humans reach AWS only through Identity Center. No IAM users, no access keys.

## Signing in to the console

Use the AWS access portal — <https://kiluna.awsapps.com/start> — and sign in as
the IAM Identity Center user (`bernard@kiluna.com`), then pick the account and
permission set. Same identity as `aws sso login --sso-session kiluna`. For
Control Tower and Account Factory, choose **Management (573051819426)** →
`KilunaOrgAdmin`.

The sign-in page at `console.aws.amazon.com` offers a different door — "Root
user" or "IAM user" — and neither is the one to take:

| Sign-in | Use it for |
|---|---|
| **Access portal** (`kiluna.awsapps.com/start`) | Everything, every day |
| **Root user** (account email + password) | Only the handful of tasks that require it — closing an account from within it, changing the root email or password, some support-plan and tax settings |
| **IAM user** (`bernard`) | Nothing. Legacy, predates Identity Center. |

Every account has its own root user, tied to the plus-addressed email in
`describe-account`. That mailbox must stay reachable — password resets and the
primary-email OTP go there — even though nobody signs in with it. Root should
have MFA on and no access keys.

Nothing in this document needs root: account closure, renames and OU moves all
run from the management account through the Organizations and Account
Management APIs as `mgmt-admin`.

### IAM users versus Identity Center users

Two separate directories, easy to conflate:

- **IAM users** are scoped to a single account and appear in ARNs as
  `arn:aws:iam::<account-id>:user/<name>`. They have no email attribute.
- **Identity Center users** live in one org-level identity store and are
  *assigned* to accounts many-to-many through permission sets. They do have an
  email.

Identity Center does not replace IAM, it drives it: assigning a permission set
creates an IAM role named `AWSReservedSSO_<PermissionSet>_<suffix>` in the
target account, and signing in issues temporary credentials for that role.

That mechanism also explains the Account Factory error "Your AWS IAM identity
does not have access to the AWS Control Tower Account Factory portfolio":
Service Catalog only understands IAM principals, and Control Tower grants the
portfolio to the groups it created, not to every administrator. The supported
fix is to join `AWSAccountFactory` — which is why `bernard@kiluna.com` is a
member of it.

Associating the generated role with the portfolio directly also works, but the
`_<suffix>` is regenerated whenever the permission set is re-provisioned, which
silently breaks it. Use `--principal-type IAM_PATTERN` with
`arn:aws:iam:::role/aws-reserved/sso.amazonaws.com/*/AWSReservedSSO_<name>_*`
if you ever need that route.

## Who has access

Two Identity Center users, and only two.

| User | Role | Billing |
|---|---|---|
| `admin@kiluna.com` | Break-glass. Full admin on all four accounts. Used a few times a year, MFA mandatory. | Yes |
| `bernard@kiluna.com` | Daily driver. Admin everywhere, and Account Factory. | No |

| Group | Members | Grants |
|---|---|---|
| `KilunaBreakGlass` | `admin` | `AWSAdministratorAccess` on all 4 accounts |
| `KilunaAdministrator` | `bernard` | `KilunaOrgAdmin` on mgmt; `AWSAdministratorAccess` on prod/demo/sdlc |
| `AWSAccountFactory` | `admin`, `bernard` | `AWSServiceCatalogEndUserAccess` on mgmt — provisioning new accounts |
| `AWSControlTowerAdmins` | `admin` | `AWSAdministratorAccess` on mgmt + `AWSOrganizationsFullAccess` on workloads |
| `AWSServiceCatalogAdmins` | `admin` | Service Catalog admin on mgmt |

Control Tower's five audit groups (`AWSSecurityAuditors`,
`AWSSecurityAuditPowerUsers`, `AWSAuditAccountAdmins`, `AWSLogArchiveAdmins`,
`AWSLogArchiveViewers`) exist but are deliberately empty. Leave them — Control
Tower expects them.

### The billing carve-out

Billing lives in the management account, and `AWSAdministratorAccess` there
grants it. So daily work uses a separate permission set, **`KilunaOrgAdmin`** —
`AdministratorAccess` plus an explicit `Deny` on:

```
billing:*  payments:*  invoicing:*  tax:*  ce:*  cur:*
consolidatedbilling:*  freetier:*  purchase-orders:*  aws-portal:*
```

`account:*` stays **allowed** — that is `put-account-name` and the primary-email
API used in the next section. An explicit Deny always beats the Allow inside
`AdministratorAccess`, and it binds only where this permission set is used.

Two consequences worth remembering:

- **`bernard` must stay out of `AWSControlTowerAdmins`.** That group carries
  `AWSAdministratorAccess` on the management account, which would hand the
  billing access straight back.
- **Account Factory writes *direct user* assignments** for the "IAM Identity
  Center user email" field on the create-account form. Convert them to group
  assignments, or every new account accumulates another per-user grant.

## config file (~/.aws/config)

One `[sso-session kiluna]` is shared by all four profiles, so a single
`aws sso login --sso-session kiluna` authenticates every one of them.

**`mgmt-admin`** — 573051819426, the management account, role `KilunaOrgAdmin`.

Admin *in the management account*, not across the org. It owns the org-level
APIs (`organizations`, `account`) used to rename accounts, move OUs and manage
SCPs — but it cannot create or read resources inside the member accounts, and it
cannot see billing.

**`prod-admin`** — 730406060579
**`demo-admin`** — 364769971558
**`sdlc-admin`** — 011356579819

Role `AWSAdministratorAccess` in each. These are the credentials that do the
actual work inside an account.

### Why keep them all

- They follow the `<account>-<role>` naming convention.
- They keep workloads out of the management account.
- They give `setenv` something to point `AWS_PROFILE` at.

## Renaming an account and changing its root email

Both are `mgmt-admin` operations, and both use the `account` API rather than
`organizations`. The management account cannot pass its own `--account-id` — to
change 573051819426 itself, omit the flag.

**Display name** — one call:

```bash
aws --profile mgmt-admin account put-account-name \
  --account-id 730406060579 --account-name ragbench-prod
```

**Root email** — two calls, because AWS mails a 6-digit OTP to the *new* address
(valid ~15 min), so you must be able to receive there. Plus-addressing works:

```bash
aws --profile mgmt-admin account start-primary-email-update \
  --account-id 730406060579 --primary-email aws+ragbench-prod@kiluna.com

aws --profile mgmt-admin account accept-primary-email-update \
  --account-id 730406060579 \
  --primary-email aws+ragbench-prod@kiluna.com --otp 123456
```

Verify either with the authoritative source:

```bash
aws --profile mgmt-admin organizations describe-account \
  --account-id 730406060579 --query 'Account.[Name,Email]' --output text
```

Both need the org to have **all features** and **trusted access for Account
Management** enabled — Control Tower gives you both.

### Gotcha: Control Tower keeps showing the old name

After a rename, two console screens disagree:

| Screen | Reads from | Shows |
|---|---|---|
| Organization → OU account list | AWS Organizations (live) | the new name |
| Breadcrumb and "Update account" form | the Service Catalog **provisioned product** written by Account Factory at creation | the original name and email, frozen |

Control Tower never refreshes its provisioning record from Organizations, and
its own form greys both fields out because Account Factory treats them as fixed
after creation — the `account` API calls above bypass that.

This is cosmetic. Invoices, Cost Explorer, the SSO portal, CloudTrail and
`describe-account` all read Organizations. The only way to clear the drift is to
update the provisioned product's `AccountName` parameter in Service Catalog,
which re-runs the Account Factory pipeline against a live account — not worth it
for a label.

A second, unrelated Control Tower dialog gotcha: the "Update account"
confirmation names the account's *current* OU, not the destination. Trust the
Organizational unit dropdown, not the dialog text.

## Deploying to AWS with the CDK (`infra/`)

Three stacks, split by lifecycle: `RagbenchBaseStack` and `RagbenchImageStack`
are permanent, `RagbenchDemoStack` is created before a demo and destroyed after.
Full detail lives in `infra/README.md`; this is the order of operations.

### One-time, org-wide: stop Account Factory creating VPCs

Do this once. It applies to every account provisioned afterwards, and it is
what AWS recommends. From the Prescriptive Guidance, *Transitioning to multiple
AWS accounts*:

> Many prefer to use other services, such as AWS CloudFormation, Hashicorp
> Terraform, or Pulumi, to set up and manage their VPCs. You should customize
> the Account Factory settings to prevent creation of the additional VPC
> provisioned by AWS Control Tower.

The built-in VPC only makes sense for a SaaS giving each tenant an identical
account with no inter-account networking. We use CDK and want peering or
Transit Gateway to stay possible, so we turn it off.

**Console only** — the landing-zone manifest holds governed regions, logging
and roles, but not this. There is no CLI equivalent.

Control Tower → **Account factory** → **Network configuration** → **Edit**:

1. **Internet-accessible subnet** → disabled
2. **Maximum number of private subnets** → **0**
3. **Regions for VPC creation** → clear every region
4. **Availability Zones** → 3

Leaving public subnets *enabled* would make Account Factory create a NAT
gateway per account — around $32/month each, for a VPC nothing uses.

Existing accounts keep the VPC they were given; step 4b below removes it.

### Phase A — point the toolchain at the demo account (~10 min)

The demo infrastructure lives in **`ragbench-demo` (364769971558)**, in the Demo
OU — its own account because demo is reachable by people outside the team (see
*OU and account layout* above). `envName` stays `demo`, so secret ids and SSM
paths remain `ragbench/demo/...`.

1. Add the profile to `~/.aws/config` — the shared sso-session already exists:
   ```ini
   [profile demo-admin]
   sso_session = kiluna
   sso_account_id = 364769971558
   sso_role_name = AWSAdministratorAccess
   region = ap-southeast-2
   output = json
   ```

2. Confirm it resolves:
   ```bash
   aws sso login --sso-session kiluna
   aws --profile demo-admin sts get-caller-identity --query Account --output text
   # → 364769971558
   ```

3. Select an environment in each shell that needs one:
   ```console
   $ setenv demo
   demo → demo-admin (364769971558)
   ```
   `setenv` is a small generic shim in `~/.zshrc` that sources `./setenv.zsh`
   from the root of the current git repo; the seven lines are in that file's
   header. It names no account, profile or project, so any repo adopting the
   `./setenv.zsh` convention reuses it. The file must be sourced rather than
   executed — an executed script sets its variables in a child process that then
   exits — and it refuses to run if you execute it. Without the shim,
   `source ./setenv.zsh demo` from the repo root is equivalent.

   `setenv` exports `AWS_ENV` and `AWS_PROFILE` together, paints the background
   dark red for prod only, and shows the environment at the right of the prompt.
   `setenv none` clears it; `setenv` alone reports the current selection.

   **There is deliberately no `.envrc` and no default.** An unselected shell
   reaches no account: the CLI has no `[default]` profile to fall back on and
   `loadConfig` throws. Nothing else should export `AWS_PROFILE`,
   `AWS_ACCOUNT_ID` or `AWS_REGION` — the profile in `~/.aws/config` already
   carries the region, CDK reads `CDK_DEFAULT_ACCOUNT` from the resolved
   credentials, and `just ecr-push` calls `sts get-caller-identity`. A
   hand-maintained second copy of any of them can only drift.

4. Remove the VPCs you didn't ask for. A fresh Account Factory account can
   arrive with **two**, neither of them yours:

   | VPC | Where it comes from | Usually |
   |---|---|---|
   | default (`172.31.0.0/16`, unnamed) | AWS, in every new account | Already deleted — Control Tower removes it during provisioning |
   | `aws-controltower-VPC` (`172.31.0.0/16`) | Account Factory's network configuration | Present, unused, must be removed |

   Both must go before `RagbenchBaseStack` builds the real one. See *Stop
   Account Factory creating VPCs* above for how to prevent the second from
   coming back.

   **4a. The default VPC.** There is no single "delete default VPC" API —
   `delete-vpc` fails while subnets or an internet gateway are attached, so it
   is a four-step teardown. The default route table, NACL and security group go
   with the VPC.

   ```bash
   export AWS_PROFILE=demo-admin AWS_REGION=ap-southeast-2

   # 0. Confirm the account — this is destructive
   aws sts get-caller-identity --query Account --output text

   # 1. Find the default VPC
   VPC=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
         --query 'Vpcs[0].VpcId' --output text)
   echo "$VPC"

   # 2. Delete its subnets
   for S in $(aws ec2 describe-subnets --filters Name=vpc-id,Values=$VPC \
              --query 'Subnets[].SubnetId' --output text); do
     aws ec2 delete-subnet --subnet-id $S
   done

   # 3. Detach and delete the internet gateway
   IGW=$(aws ec2 describe-internet-gateways --filters Name=attachment.vpc-id,Values=$VPC \
         --query 'InternetGateways[0].InternetGatewayId' --output text)
   aws ec2 detach-internet-gateway --internet-gateway-id $IGW --vpc-id $VPC
   aws ec2 delete-internet-gateway --internet-gateway-id $IGW

   # 4. Delete the VPC
   aws ec2 delete-vpc --vpc-id $VPC
   ```

   If step 1 prints `None`, Control Tower already removed it — skip the rest.
   It is recoverable: `aws ec2 create-default-vpc` rebuilds one.

   **On regions.** AWS creates a default VPC in *every* enabled region, and only
   `ap-southeast-2` is enabled today. If Melbourne (`ap-southeast-4`) is enabled
   later, it arrives with its own default VPC that must be deleted the same way —
   re-run the block with `AWS_REGION=ap-southeast-4`, in every account, or loop:

   ```bash
   for R in $(aws ec2 describe-regions --query 'Regions[].RegionName' --output text); do
     echo "== $R"; AWS_REGION=$R aws ec2 describe-vpcs \
       --filters Name=isDefault,Values=true --query 'Vpcs[].VpcId' --output text
   done
   ```

   **4b. The Control Tower VPC.** `aws-controltower-VPC` is *not* the default
   VPC — it is created by Account Factory from the network configuration, with
   private subnets across 3 AZs and an S3 gateway endpoint. With public subnets
   disabled it has no NAT gateway, so it costs nothing, but it takes
   `172.31.0.0/16` in **every** account Account Factory provisions. That is a
   guaranteed collision with the non-overlapping-CIDR rule, and reason enough to
   remove it.

   The teardown is different from the default VPC's — there is no internet
   gateway, but there are VPC endpoints and non-main route tables:

   ```bash
   V=$(aws ec2 describe-vpcs --filters Name=tag:Name,Values=aws-controltower-VPC \
       --query 'Vpcs[0].VpcId' --output text)

   # Refuse to proceed if anything is actually attached
   aws ec2 describe-network-interfaces --filters Name=vpc-id,Values=$V \
     --query 'length(NetworkInterfaces)' --output text     # must be 0

   for E in $(aws ec2 describe-vpc-endpoints --filters Name=vpc-id,Values=$V \
              --query 'VpcEndpoints[].VpcEndpointId' --output text); do
     aws ec2 delete-vpc-endpoints --vpc-endpoint-ids $E
   done

   for S in $(aws ec2 describe-subnets --filters Name=vpc-id,Values=$V \
              --query 'Subnets[].SubnetId' --output text); do
     aws ec2 delete-subnet --subnet-id $S
   done

   for R in $(aws ec2 describe-route-tables --filters Name=vpc-id,Values=$V \
              --query 'RouteTables[?!(Associations[?Main==`true`])].RouteTableId' --output text); do
     aws ec2 delete-route-table --route-table-id $R
   done

   aws ec2 delete-vpc --vpc-id $V
   ```

   Non-default security groups and network ACLs would also block `delete-vpc`,
   but a stock Control Tower VPC has neither. Afterwards the account should list
   exactly one VPC: `RagbenchBaseStack/Vpc`.

   `ragbench-prod` and `ragbench-sdlc` still carry theirs — same teardown,
   different profile, whenever convenient.

5. Bootstrap CDK: `npx cdk bootstrap aws://364769971558/ap-southeast-2`

   On a **first** bootstrap, CDK prints `current credentials could not be used
   to assume 'arn:...cdk-hnb659fds-lookup-role-...', but are for the right
   account. Proceeding anyway.` That is expected — the role does not exist until
   this command creates it. The phrase that matters is *for the right account*.

### Phase B — one-time stacks (~1 hour, mostly waiting)

6. `cd infra && npx cdk deploy RagbenchBaseStack` — the default domain is
   `demo.kiluna.com`; override with `-c domainName=...`.

7. Take the `HostedZoneNameServers` output (4 NS records) and add them at your
   DNS provider. ACM issuance blocks until the delegation is live — minutes to
   an hour.

8. Fill the two manual secrets (the rest are generated):
   ```bash
   aws secretsmanager put-secret-value --secret-id ragbench/demo/OPENAI_API_KEY    --secret-string 'sk-...'
   aws secretsmanager put-secret-value --secret-id ragbench/demo/ANTHROPIC_API_KEY --secret-string 'sk-ant-...'
   ```

9. `npx cdk deploy RagbenchImageStack`, then `just ecr-push && just aws-bake`
   (~15 min for the bake; builds are `linux/arm64`, native on Apple Silicon).

10. Commit the `cdk.context.json` that the first successful synth writes, so AZ
    lookups stay deterministic.

### Gotcha: changing a VPC CIDR takes three deploys

`RagbenchBaseStack` sets `restrictDefaultSecurityGroup: true`, which makes CDK
add a `Custom::VpcRestrictDefaultSG` Lambda that strips the default security
group's rules. Its IAM role is scoped to **one specific security-group ARN** —
the current VPC's default SG.

Replacing the VPC creates a *new* default SG, so the Lambda is asked to act on a
group its own role does not cover, and the deploy fails with:

```
UnauthorizedOperation: ... not authorized to perform:
ec2:AuthorizeSecurityGroupIngress on resource: .../security-group/sg-...
```

The rollback then fails on top of it with `InvalidPermission.Duplicate` — it
tries to restore rules that were never removed — leaving the stack in
`UPDATE_ROLLBACK_FAILED`, which blocks every subsequent operation.

**If you are already stuck there**, skip the custom resource to get out:

```bash
aws --profile demo-admin cloudformation continue-update-rollback \
  --stack-name RagbenchBaseStack \
  --resources-to-skip VpcRestrictDefaultSecurityGroupCustomResourceC73DA2BE
```

**To change the CIDR cleanly**, three deploys — and they cannot be merged, because
CloudFormation may delete the custom resource *after* replacing the VPC:

```bash
# 1. Remove the custom resource, CIDR unchanged.
#    Set restrictDefaultSecurityGroup: false in lib/base-stack.ts, then:
npx cdk deploy RagbenchBaseStack -c vpcCidr=<current CIDR>

# 2. Replace the VPC. No custom resource involved.
npx cdk deploy RagbenchBaseStack

# 3. Set restrictDefaultSecurityGroup: true again and redeploy.
npx cdk deploy RagbenchBaseStack
```

Verify with 0 ingress and 0 egress on the new default SG:

```bash
aws --profile demo-admin ec2 describe-security-groups \
  --filters Name=group-name,Values=default \
  --query 'SecurityGroups[].[GroupId,VpcId,length(IpPermissions),length(IpPermissionsEgress)]' \
  --output text
```

The hosted zone, certificate, ECR repos, Cognito pool and secrets are untouched
by a VPC replacement, so no DNS re-delegation is needed.

### Per demo

```bash
just aws-up      # deploys RagbenchDemoStack, prints the URL
just aws-down    # destroys it
```

Cognito sign-up is disabled, so each viewer needs an account first:

```bash
aws cognito-idp admin-create-user --user-pool-id <UserPoolId output> \
  --username someone@example.com --user-attributes Name=email,Value=someone@example.com
```

Re-bake (`just ecr-push && just aws-bake`) only when the images or the corpus
change. A schema change also needs a re-bake — `services/postgres/init.sql` runs
only on first boot and nothing runs migrations.

### Shell access

No SSH, no bastion, no port 22:

```bash
aws ssm start-session --target <InstanceId output>
```
