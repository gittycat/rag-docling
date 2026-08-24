
## Quick Start

1. Log in once — the sso-session is shared by all three profiles
aws sso login --sso-session kiluna

From this point on, use the mgmt-admin when performing changes at the Accounts or OU levels, and use the ENV-admin profiles when working on the ENV Account (including EC2, VPC, and other core resources)

## Signing in to the console

Use the AWS access portal — <https://kiluna.awsapps.com/start> — and sign in as
the IAM Identity Center user (`bernard@kiluna.com`), then pick the account and
permission set. Same identity as `aws sso login --sso-session kiluna`. For
Control Tower and Account Factory, choose **Kiluna Admin (573051819426)** →
`AWSAdministratorAccess`.

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

That mechanism explains the Account Factory error "Your AWS IAM identity does
not have access to the AWS Control Tower Account Factory portfolio": Service
Catalog only understands IAM principals, and Control Tower grants the portfolio
only to the groups it created. The fix is to associate the generated role:

```bash
PORT=$(aws --profile mgmt-admin servicecatalog list-portfolios \
  --query "PortfolioDetails[?DisplayName=='AWS Control Tower Account Factory Portfolio'].Id" \
  --output text)

ROLE=$(aws --profile mgmt-admin iam list-roles --query \
  "Roles[?starts_with(RoleName,'AWSReservedSSO_AWSAdministratorAccess')].Arn" --output text)

aws --profile mgmt-admin servicecatalog associate-principal-with-portfolio \
  --portfolio-id "$PORT" --principal-arn "$ROLE" --principal-type IAM
```

The `_<suffix>` is regenerated if the permission set is ever re-provisioned,
which silently breaks the association. `--principal-type IAM_PATTERN` with
`arn:aws:iam:::role/aws-reserved/sso.amazonaws.com/*/AWSReservedSSO_AWSAdministratorAccess_*`
survives that.

## config file (~/.aws/config)

One `[sso-session kiluna]` is shared by all three profiles, so a single
`aws sso login --sso-session kiluna` authenticates every one of them.

**`mgmt-admin`** — 573051819426, the management account.

Admin *in the management account*, not across the org. It owns the
org-level APIs (`organizations`, `account`) used to rename accounts,
move OUs and manage SCPs — but it cannot create or read resources
inside the member accounts.

**`prod-admin`** — 730406060579
**`sdlc-admin`** — 011356579819

Per-account SSO permission sets. These are the credentials that do the
actual work inside each account.

### Why keep all three

- They follow the `<account>-<role>` naming convention.
- They keep workloads out of the management account.
- They give `AWS_PROFILE` in a project's `.envrc` something to point at.

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

### Phase A — point the toolchain at the SDLC account (~10 min)

The demo infrastructure lives in **`ragbench-sdlc` (011356579819)**, in the SDLC
OU. There is no separate demo account; `envName` stays `demo`, so secret ids and
SSM paths remain `ragbench/demo/...` regardless.

1. Confirm the account and that the profile resolves:
   ```bash
   aws sso login --sso-session kiluna
   aws --profile sdlc-admin sts get-caller-identity --query Account --output text
   # → 011356579819
   ```

2. No new profile needed — `sdlc-admin` already points at it:
   ```ini
   [profile sdlc-admin]
   sso_session = kiluna
   sso_account_id = 011356579819
   sso_role_name = AWSAdministratorAccess
   region = ap-southeast-2
   output = json
   ```

3. Create `.envrc` at the repo root (gitignored) and run `direnv allow`:
   ```bash
   export AWS_PROFILE=sdlc-admin
   export AWS_REGION=ap-southeast-2
   export AWS_ACCOUNT_ID=011356579819   # `just ecr-push` derives REGISTRY from this
   ```

4. Delete the default VPC in that account, `ap-southeast-2`. The stacks build
   their own, and one-VPC-per-account is the org convention.

   There is no single "delete default VPC" API — `delete-vpc` fails while
   subnets or an internet gateway are attached, so it is a four-step teardown.
   The default route table, NACL and security group go with the VPC.

   ```bash
   export AWS_PROFILE=sdlc-admin AWS_REGION=ap-southeast-2

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

5. Bootstrap CDK: `npx cdk bootstrap aws://011356579819/ap-southeast-2`

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
