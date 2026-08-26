/**
 * Single source of truth for everything the three stacks need to agree on.
 *
 * Values are overridable from the CLI with `-c key=value`, e.g.
 *   AWS_PROFILE=prod-admin npx cdk deploy -c envName=prod -c domainName=rag.example.com
 *
 * `envName` comes from AWS_ENV (set by `setenv`, see ./setenv.zsh) or from
 * `-c envName=`. There is no default: with neither set, `loadConfig` throws.
 * It also refuses to synthesize when the active credentials point elsewhere.
 */
import { Construct } from 'constructs';

export interface RagbenchConfig {
  /** Prefix for every physical name and SSM path. */
  readonly project: string;
  /** One of the keys of ENVIRONMENTS: dev, staging, demo, prod. */
  readonly envName: string;
  /** Always the account ENVIRONMENTS pins for `envName` — never inferred. */
  readonly account: string;
  /** Likewise pinned: see the comment on REGION. */
  readonly region: string;
  /** Delegated subdomain: a new public hosted zone is created for this name. */
  readonly domainName: string;
  /** This account's allocated range. Overlaps break future peering / Transit Gateway. */
  readonly vpcCidr: string;
  readonly instanceType: string;
  /** Root volume must hold every baked image plus both model caches. */
  readonly rootVolumeGiB: number;
  /** Amazon Linux 2023 arm64 — the Image Builder base. */
  readonly parentImageSsmPath: string;
  /** Git tag / image tag the golden AMI is baked from. */
  readonly imageTag: string;
  /** RagbenchEmbedStack's instance type. g6.xlarge = one NVIDIA L4, 24GB. */
  readonly embedInstanceType: string;
  /**
   * Public SSM parameter that resolves to the current Deep Learning Base OSS
   * Nvidia Driver GPU AMI (Ubuntu 24.04) — ships Docker, the NVIDIA driver and
   * nvidia-container-toolkit, so RagbenchEmbedStack needs no Image Builder bake.
   */
  readonly embedGpuAmiSsmParameter: string;
}

/** Secrets the app reads as files under /run/secrets. Order is not significant. */
export const SECRET_NAMES = [
  'OPENAI_API_KEY',
  'ANTHROPIC_API_KEY',
  'POSTGRES_SUPERUSER',
  'POSTGRES_SUPERPASSWORD',
  'RAG_SERVER_DB_USER',
  'RAG_SERVER_DB_PASSWORD',
  'RAG_SERVER_AUTH_TOKEN',
] as const;

/** The two secrets a human must fill in by hand; the rest are generated. */
export const MANUAL_SECRET_NAMES: readonly string[] = ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY'];

/** ECR repositories. `rag-server` backs both the API and the task worker. */
export const IMAGE_NAMES = ['webapp', 'rag-server', 'postgres', 'evals'] as const;

/**
 * Per-environment CIDR allocation — see `docs/AWS.md`. One /16 per account;
 * dev and staging share the sdlc account, so they split its /16 in half.
 * Never reuse a range: peering and Transit Gateway both refuse overlaps.
 */
/**
 * The one region everything lives in. Pinned per environment rather than left to
 * the profile because region is not a free choice here: `just ecr-push` and
 * `just aws-bake` hardcode it, cdk.context.json caches AZs for it alone, and a
 * profile configured elsewhere would otherwise push images and write the
 * golden-AMI parameter in one region while the stacks are built in another.
 */
const REGION = 'ap-southeast-2';

/**
 * Which account and region each environment lives in, and the profile that reaches it.
 * Deliberately many-to-one: dev and staging share the sdlc account, so the
 * account id alone cannot identify an environment. This is what `loadConfig`
 * checks the live credentials against.
 */
interface EnvSpec {
  readonly account: string;
  readonly region: string;
  readonly profile: string;
  readonly domainName: string;
}

const ENVIRONMENTS: Record<string, EnvSpec> = {
  dev: { account: '011356579819', region: REGION, profile: 'sdlc-admin', domainName: 'dev.kiluna.com' },
  staging: { account: '011356579819', region: REGION, profile: 'sdlc-admin', domainName: 'staging.kiluna.com' },
  demo: { account: '364769971558', region: REGION, profile: 'demo-admin', domainName: 'demo.kiluna.com' },
  prod: { account: '730406060579', region: REGION, profile: 'prod-admin', domainName: 'prod.kiluna.com' },
};

const ENV_CIDRS: Record<string, string> = {
  dev: '10.10.0.0/17',
  staging: '10.10.128.0/17',
  demo: '10.20.0.0/16',
  prod: '10.30.0.0/16',
};

export function loadConfig(scope: Construct): RagbenchConfig {
  const ctx = (key: string, fallback?: string): string | undefined =>
    (scope.node.tryGetContext(key) as string | undefined) ?? fallback;

  // No default. A bare `cdk deploy` used to mean demo, which is the same class
  // of mistake as an un-prefixed aws call: it picks somewhere convenient rather
  // than refusing. `setenv` (./setenv.zsh at the repo root) sets AWS_ENV and
  // AWS_PROFILE together, so the two can no longer disagree by being typed
  // separately.
  const envName = ctx('envName') ?? process.env.AWS_ENV;
  if (!envName) {
    throw new Error(
      `No environment selected. Run 'setenv <${Object.keys(ENVIRONMENTS).join('|')}>' ` +
        `to set AWS_ENV and AWS_PROFILE together, or pass -c envName=<name>.`,
    );
  }

  const spec = ENVIRONMENTS[envName];
  if (!spec) {
    throw new Error(
      `Unknown envName '${envName}'. Known: ${Object.keys(ENVIRONMENTS).join(', ')}. ` +
        `Add it to ENVIRONMENTS and ENV_CIDRS in lib/config.ts (and to docs/AWS.md).`,
    );
  }

  // The whole point of this check: nothing else ties envName to an account, so
  // a forgotten AWS_PROFILE would deploy prod-named resources — prod SSM paths,
  // prod secrets, prod CIDR — into whichever account happens to be active, and
  // succeed silently.
  const resolved = ctx('account') ?? process.env.CDK_DEFAULT_ACCOUNT;
  if (resolved && resolved !== spec.account) {
    throw new Error(
      `envName '${envName}' belongs to account ${spec.account}, but the active ` +
        `credentials resolve to ${resolved}.\n` +
        `Prefix the command: AWS_PROFILE=${spec.profile} npx cdk deploy -c envName=${envName}`,
    );
  }

  // Same failure mode as the account check, and just as silent: a profile whose
  // configured region is not the environment's builds a second, duplicate set of
  // VPC/ALB/Cognito resources somewhere the images and SSM parameters are not.
  const resolvedRegion = ctx('region') ?? process.env.CDK_DEFAULT_REGION;
  if (resolvedRegion && resolvedRegion !== spec.region) {
    throw new Error(
      `envName '${envName}' is pinned to region ${spec.region}, but the active ` +
        `credentials resolve to ${resolvedRegion}.\n` +
        `Set the region on the profile: aws configure set region ${spec.region} --profile ${spec.profile}`,
    );
  }

  const vpcCidr = ctx('vpcCidr') ?? ENV_CIDRS[envName];
  if (!vpcCidr) {
    throw new Error(
      `No CIDR allocated for envName '${envName}'. Add one to ENV_CIDRS in lib/config.ts ` +
        `(and to docs/AWS.md), or pass -c vpcCidr=10.x.0.0/16.`,
    );
  }

  return {
    project: ctx('project', 'ragbench')!,
    envName,
    account: spec.account,
    region: spec.region,
    domainName: ctx('domainName', spec.domainName)!,
    vpcCidr,
    instanceType: ctx('instanceType', 'm7g.xlarge')!,
    rootVolumeGiB: Number(ctx('rootVolumeGiB', '60')),
    parentImageSsmPath: ctx(
      'parentImageSsmPath',
      '/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64',
    )!,
    imageTag: ctx('imageTag', 'latest')!,
    embedInstanceType: ctx('embedInstanceType', 'g6.xlarge')!,
    // Verified against the AWS DLAMI docs: g6 (L4) is x86_64, and this is the
    // OSS-driver Ubuntu 24.04 base flavour — no framework preinstalled, no
    // second pipeline needed since RagbenchEmbedStack's user data is one
    // `docker run`.
    embedGpuAmiSsmParameter: ctx(
      'embedGpuAmiSsmParameter',
      '/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-24.04/latest/ami-id',
    )!,
  };
}

/**
 * CloudFormation stack name. `demo` keeps the unsuffixed names it was first
 * deployed under: renaming a live stack orphans it, and the base stack carries
 * terminationProtection plus the Cognito users, ECR images and secrets. Every
 * other environment is suffixed, which is what lets dev and staging coexist in
 * the one sdlc account. Construct ids stay bare either way, so
 * `cdk deploy RagbenchBaseStack` still selects the right stack in every env.
 */
export function stackName(cfg: RagbenchConfig, base: string): string {
  return cfg.envName === 'demo' ? base : `${base}-${cfg.envName}`;
}

/** `/ragbench/demo/...` — the namespace both the pipeline and the demo stack read. */
export function ssmPrefix(cfg: RagbenchConfig): string {
  return `/${cfg.project}/${cfg.envName}`;
}

/** Secrets Manager id, e.g. `ragbench/demo/OPENAI_API_KEY`. */
export function secretId(cfg: RagbenchConfig, name: string): string {
  return `${cfg.project}/${cfg.envName}/${name}`;
}

/**
 * ECR namespace: `ragbench` for demo, `ragbench/<envName>` everywhere else.
 * Same rule and same reason as `stackName` — demo keeps the unqualified names
 * it was first pushed under (the repositories are RETAIN and the golden AMI
 * already pulls those URIs), and every other environment is qualified, which is
 * what lets dev and staging own separate repositories in the one sdlc account.
 */
export function repoNamespace(cfg: RagbenchConfig): string {
  return cfg.envName === 'demo' ? cfg.project : `${cfg.project}/${cfg.envName}`;
}

/** ECR repository name, e.g. `ragbench/rag-server` or `ragbench/dev/rag-server`. */
export function repoName(cfg: RagbenchConfig, image: string): string {
  return `${repoNamespace(cfg)}/${image}`;
}
