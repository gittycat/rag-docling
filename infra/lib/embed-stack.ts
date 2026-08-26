/**
 * The burst GPU stack: `just embed-up` before a bulk re-ingest, `just embed-down`
 * once it is done. Nothing here holds state — the corpus lives in Postgres, and
 * TEI's Qwen3-Embedding-0.6B weights are pulled fresh from HuggingFace on every
 * boot — so a teardown costs nothing but the minutes to redeploy and re-pull.
 *
 * Deliberately NOT wired into `RagbenchDemoStack`: bulk re-ingestion is a
 * one-shot operator action, not part of the always-on demo path, and the query
 * embedder stays the CPU TEI container in docker-compose.aws.yml.
 */
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import { RagbenchConfig, ssmPrefix } from './config';

// CUDA build for L4 (sm89), per the verified image table in the migration
// decision sheet — there is no versioned arm64 CPU tag, but the CUDA tags are
// published per-arch and this one exists.
const TEI_IMAGE = 'ghcr.io/huggingface/text-embeddings-inference:89-1.9';
const MODEL_ID = 'Qwen/Qwen3-Embedding-0.6B';

// Matches INGEST_BATCH_SIZE in services/rag_server (Phase 5 of the migration) —
// the ingester issues batches of 32 chunks, so the server should accept batches
// of exactly that size rather than silently splitting or queuing them.
const MAX_CLIENT_BATCH_SIZE = 32;

// TEI's default --max-batch-tokens (16384) is sized for a shared/smaller GPU.
// Qwen3-Embedding-0.6B is tiny (~1.2 GB of fp16 weights) against the L4's 24 GB,
// and embedding is prefill-only — there is no growing KV cache to budget
// against, unlike text generation — so the default leaves most of the card
// idle. Ingestion issues MAX_CLIENT_BATCH_SIZE-chunk batches concurrently
// against this endpoint; a higher ceiling lets TEI's batcher coalesce more of
// those concurrent requests into one forward pass instead of queuing them,
// which is the point of paying for the GPU at all. 65536 (4x default) is a
// conservative multiple given the memory headroom, not a measured optimum —
// tune it against real throughput once Phase 5 numbers exist.
const MAX_BATCH_TOKENS = 65536;

export interface RagbenchEmbedStackProps extends cdk.StackProps {
  readonly config: RagbenchConfig;
  readonly vpc: ec2.IVpc;
  /** `RagbenchDemoStack.instanceSg` — the only allowed source for inbound 8080. */
  readonly demoInstanceSg: ec2.ISecurityGroup;
}

export class RagbenchEmbedStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: RagbenchEmbedStackProps) {
    super(scope, id, props);
    const cfg = props.config;
    const endpointParameterName = `${ssmPrefix(cfg)}/embed-endpoint`;

    // ------------------------------------------------------------------ role
    const instanceRole = new iam.Role(this, 'InstanceRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      description: 'RAGBench burst embedder instance',
      // Session Manager only, same as the demo instance — no SSH key, no bastion.
      managedPolicies: [iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore')],
    });
    // Scoped to exactly the one parameter this instance publishes itself. The
    // parameter is deliberately not a CloudFormation resource on this stack —
    // see the comment above the SSM output below — so this is the only way the
    // instance is allowed to touch it.
    instanceRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ['ssm:PutParameter'],
        resources: [`arn:${this.partition}:ssm:${this.region}:${this.account}:parameter${endpointParameterName}`],
      }),
    );

    // -------------------------------------------------------- security group
    const embedSg = new ec2.SecurityGroup(this, 'EmbedSg', {
      vpc: props.vpc,
      description: 'RAGBench burst embedder - TEI from the demo instance only',
      allowAllOutbound: true, // must reach ghcr.io and huggingface.co to pull the image and weights
    });
    // The only inbound rule. No public ingress on 8080 anywhere — the ingester
    // that calls this endpoint always runs on the demo instance.
    embedSg.addIngressRule(props.demoInstanceSg, ec2.Port.tcp(8080), 'TEI, from the demo instance only');

    // --------------------------------------------------------------- instance
    const userData = ec2.UserData.forLinux();
    userData.addCommands(
      'set -euo pipefail',
      'exec > >(tee -a /var/log/ragbench-embed-boot.log) 2>&1',
      'echo "[embed-boot $(date -u +%FT%TZ)] starting"',
      'systemctl is-active --quiet docker || systemctl start docker',
      // The AMI already has Docker, the NVIDIA driver and nvidia-container-toolkit
      // baked in, so this docker run is the entire install. --restart
      // unless-stopped means a container crash (OOM, a bad request) does not
      // strand a paid GPU instance serving nothing.
      [
        'docker run -d --restart unless-stopped --gpus all -p 8080:80',
        TEI_IMAGE,
        `--model-id ${MODEL_ID}`,
        `--max-client-batch-size ${MAX_CLIENT_BATCH_SIZE}`,
        `--max-batch-tokens ${MAX_BATCH_TOKENS}`,
      ].join(' \\\n  '),
      // Don't publish the endpoint until TEI is actually answering — publishing
      // the private IP early would hand the ingester an address that refuses
      // connections while the model is still downloading from HuggingFace.
      'if ! timeout 600 bash -c \'until curl -sf http://localhost:8080/health >/dev/null; do sleep 5; done\'; then',
      '  echo "[embed-boot $(date -u +%FT%TZ)] FAILED: TEI did not come up in 600s"',
      '  docker logs "$(docker ps -lq)" --tail 200',
      '  exit 1',
      'fi',
      // IMDSv2 token — the instance requires it (see requireImdsv2 below).
      'TOKEN=$(curl -sX PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60")',
      'PRIVATE_IP=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/local-ipv4)',
      `aws ssm put-parameter --region ${this.region} --name "${endpointParameterName}" ` +
        '--type String --overwrite --value "$PRIVATE_IP" > /dev/null',
      'echo "[embed-boot $(date -u +%FT%TZ)] TEI serving at ${PRIVATE_IP}:8080, published to SSM"',
    );

    const launchTemplate = new ec2.LaunchTemplate(this, 'LaunchTemplate', {
      launchTemplateName: `${cfg.project}-${cfg.envName}-embed`,
      instanceType: new ec2.InstanceType(cfg.embedInstanceType),
      // Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04), resolved via
      // its public SSM parameter rather than a hardcoded AMI id so a re-deploy
      // always picks up the current build and the id never needs updating by
      // hand across regions. See RagbenchConfig.embedGpuAmiSsmParameter.
      machineImage: ec2.MachineImage.fromSsmParameter(cfg.embedGpuAmiSsmParameter, {
        os: ec2.OperatingSystemType.LINUX,
        userData,
      }),
      role: instanceRole,
      securityGroup: embedSg,
      requireImdsv2: true,
      detailedMonitoring: false,
      // No blockDevices override: the AMI's own root volume mapping (gp3, per
      // the DLAMI release notes) is used as-is. Overriding the device name
      // without knowing Ubuntu's actual root device risks CloudFormation adding
      // a *second*, un-deleted volume rather than resizing the first.
      spotOptions: {
        // Bulk ingest is restartable and the task-worker already resets stuck
        // tasks after an hour, so a spot interruption costs at most an hour of
        // re-ingestion, never data. That trade is exactly what spot is for.
        requestType: ec2.SpotRequestType.ONE_TIME,
        interruptionBehavior: ec2.SpotInstanceInterruption.TERMINATE,
      },
    });

    // ec2.Instance (L2) has no spot support; CfnInstance referencing a
    // LaunchTemplate with spotOptions is the smallest construct that does.
    const instance = new ec2.CfnInstance(this, 'Instance', {
      launchTemplate: {
        launchTemplateId: launchTemplate.launchTemplateId,
        version: launchTemplate.latestVersionNumber,
      },
      // Same public subnet as the demo instance (base-stack.ts: natGateways: 0,
      // mapPublicIpOnLaunch: true). No NAT, no S3 staging, no VPC endpoints —
      // the public IP is for egress to ECR-equivalent (ghcr.io) and HuggingFace
      // only; inbound is controlled entirely by embedSg.
      subnetId: props.vpc.publicSubnets[0].subnetId,
    });
    cdk.Tags.of(instance).add('Name', `${cfg.project}-${cfg.envName}-embed`);

    // ---------------------------------------------------------------- outputs
    new cdk.CfnOutput(this, 'InstanceId', {
      value: instance.ref,
      description: 'aws ssm start-session --target <this>',
    });
    // Written by user data, not by CloudFormation — same reasoning as
    // golden-ami-id in image-stack.ts: the value (a private IP that is only
    // meaningful once TEI answers /health) cannot be known at synth time, and a
    // CFN-owned parameter would reset to nothing useful on every stack update
    // regardless of whether the container actually came up.
    new cdk.CfnOutput(this, 'EmbedEndpointParameter', {
      value: endpointParameterName,
      description: 'Private IP, written by user data once TEI is healthy. Read by `just embed-up`.',
    });
  }
}
