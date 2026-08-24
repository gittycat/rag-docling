#!/usr/bin/env node
/**
 * Three stacks, split by lifecycle:
 *
 *   RagbenchBaseStack   persistent — network, DNS, cert, Cognito, ECR, secrets
 *   RagbenchImageStack  the golden AMI pipeline
 *   RagbenchDemoStack   ephemeral — deployed before a demo, destroyed after
 */
import * as cdk from 'aws-cdk-lib';
import { loadConfig } from '../lib/config';
import { RagbenchBaseStack } from '../lib/base-stack';
import { RagbenchImageStack } from '../lib/image-stack';
import { RagbenchDemoStack } from '../lib/demo-stack';

const app = new cdk.App();
const config = loadConfig(app);
const env = { account: config.account, region: config.region };

const base = new RagbenchBaseStack(app, 'RagbenchBaseStack', {
  env,
  config,
  description: 'RAGBench — persistent resources (never destroyed between demos)',
});

const image = new RagbenchImageStack(app, 'RagbenchImageStack', {
  env,
  config,
  vpc: base.vpc,
  repositories: base.repositories,
  secrets: base.secrets,
  description: 'RAGBench — EC2 Image Builder pipeline for the golden AMI',
});
image.addStackDependency(base);

const demo = new RagbenchDemoStack(app, 'RagbenchDemoStack', {
  env,
  config,
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

cdk.Tags.of(app).add('Project', config.project);
cdk.Tags.of(app).add('Environment', config.envName);
cdk.Tags.of(app).add('ManagedBy', 'cdk');
