/**
 * Single source of truth for everything the three stacks need to agree on.
 *
 * Values are overridable from the CLI with `-c key=value`, e.g.
 *   npx cdk deploy -c domainName=demo.example.com -c account=123456789012
 */
import { Construct } from 'constructs';

export interface RagbenchConfig {
  /** Prefix for every physical name and SSM path. */
  readonly project: string;
  /** Single environment for now — the demo account. */
  readonly envName: string;
  readonly account?: string;
  readonly region: string;
  /** Delegated subdomain: a new public hosted zone is created for this name. */
  readonly domainName: string;
  readonly instanceType: string;
  /** Root volume must hold every baked image plus both model caches. */
  readonly rootVolumeGiB: number;
  /** Amazon Linux 2023 arm64 — the Image Builder base. */
  readonly parentImageSsmPath: string;
  /** Git tag / image tag the golden AMI is baked from. */
  readonly imageTag: string;
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

export function loadConfig(scope: Construct): RagbenchConfig {
  const ctx = (key: string, fallback?: string): string | undefined =>
    (scope.node.tryGetContext(key) as string | undefined) ?? fallback;

  return {
    project: ctx('project', 'ragbench')!,
    envName: ctx('envName', 'demo')!,
    account: ctx('account') ?? process.env.CDK_DEFAULT_ACCOUNT,
    region: ctx('region', process.env.CDK_DEFAULT_REGION ?? 'ap-southeast-2')!,
    domainName: ctx('domainName', 'demo.kiluna.com')!,
    instanceType: ctx('instanceType', 'm7g.xlarge')!,
    rootVolumeGiB: Number(ctx('rootVolumeGiB', '60')),
    parentImageSsmPath: ctx(
      'parentImageSsmPath',
      '/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64',
    )!,
    imageTag: ctx('imageTag', 'latest')!,
  };
}

/** `/ragbench/demo/...` — the namespace both the pipeline and the demo stack read. */
export function ssmPrefix(cfg: RagbenchConfig): string {
  return `/${cfg.project}/${cfg.envName}`;
}

/** Secrets Manager id, e.g. `ragbench/demo/OPENAI_API_KEY`. */
export function secretId(cfg: RagbenchConfig, name: string): string {
  return `${cfg.project}/${cfg.envName}/${name}`;
}

/** ECR repository name, e.g. `ragbench/rag-server`. */
export function repoName(cfg: RagbenchConfig, image: string): string {
  return `${cfg.project}/${image}`;
}
