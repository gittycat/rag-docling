#!/usr/bin/env node
/**
 * Four stacks, split by lifecycle:
 *
 *   RagbenchBaseStack   persistent — network, DNS, cert, Cognito, ECR, secrets
 *   RagbenchImageStack  the golden AMI pipeline
 *   RagbenchDemoStack   ephemeral — deployed before a demo, destroyed after
 *   RagbenchEmbedStack  ephemeral burst GPU embedder — opt-in only, see below
 */
import * as cdk from 'aws-cdk-lib';
import { loadConfig, stackName } from '../lib/config';
import { RagbenchBaseStack } from '../lib/base-stack';
import { RagbenchImageStack } from '../lib/image-stack';
import { RagbenchDemoStack } from '../lib/demo-stack';
import { RagbenchEmbedStack } from '../lib/embed-stack';

const app = new cdk.App();
const config = loadConfig(app);
const env = { account: config.account, region: config.region };

const base = new RagbenchBaseStack(app, 'RagbenchBaseStack', {
  env,
  config,
  stackName: stackName(config, 'RagbenchBaseStack'),
  description: 'RAGBench — persistent resources (never destroyed between demos)',
});

const image = new RagbenchImageStack(app, 'RagbenchImageStack', {
  env,
  config,
  stackName: stackName(config, 'RagbenchImageStack'),
  vpc: base.vpc,
  repositories: base.repositories,
  secrets: base.secrets,
  description: 'RAGBench — EC2 Image Builder pipeline for the golden AMI',
});
image.addStackDependency(base);

const demo = new RagbenchDemoStack(app, 'RagbenchDemoStack', {
  env,
  config,
  stackName: stackName(config, 'RagbenchDemoStack'),
  vpc: base.vpc,
  hostedZone: base.hostedZone,
  certificate: base.certificate,
  userPool: base.userPool,
  userPoolClient: base.userPoolClient,
  userPoolDomain: base.userPoolDomain,
  repositories: base.repositories,
  secrets: base.secrets,
  description: 'RAGBench — ephemeral demo environment (cdk deploy / cdk destroy per demo)',
});
demo.addStackDependency(base);

// Opt-in only: a bare `cdk deploy --all` / `cdk synth --all` must never bring up
// a billed GPU instance. Unlike the other three stacks, this one is not added
// to the app tree at all unless explicitly requested with `-c embedStack=true`
// — `just embed-up` / `just embed-down` pass that flag; a plain `cdk deploy` or
// `--all` in any other invocation cannot reach it.
const embedStackEnabled = String(app.node.tryGetContext('embedStack') ?? 'false') === 'true';
if (embedStackEnabled) {
  const embed = new RagbenchEmbedStack(app, 'RagbenchEmbedStack', {
    env,
    config,
    stackName: stackName(config, 'RagbenchEmbedStack'),
    vpc: base.vpc,
    demoInstanceSg: demo.instanceSg,
    description: 'RAGBench — ephemeral burst GPU embedder for bulk re-ingestion (opt-in: -c embedStack=true)',
  });
  embed.addStackDependency(base);
  // Needs demo.instanceSg to scope its ingress rule, not because it needs the
  // demo instance to exist first at runtime.
  embed.addStackDependency(demo);
}

cdk.Tags.of(app).add('Project', config.project);
cdk.Tags.of(app).add('Environment', config.envName);
cdk.Tags.of(app).add('ManagedBy', 'cdk');
