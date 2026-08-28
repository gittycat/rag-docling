/**
 * Ephemeral private inference for the AWS demo.  It is intentionally separate
 * from the CPU demo instance: the two vLLM servers share one L40S inside the
 * VPC and are destroyed after a demo, so an idle environment has no GPU cost.
 */
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import { RagbenchConfig, ssmPrefix } from './config';

const VLLM_IMAGE = 'vllm/vllm-openai:v0.28.0';
const INFERENCE_MODEL = 'Qwen/Qwen3.5-9B';
const JUDGE_MODEL = 'Qwen/Qwen3.8-27B-FP8';
const INFERENCE_GPU_MEMORY_UTILIZATION = '0.30';
const JUDGE_GPU_MEMORY_UTILIZATION = '0.65';
const MODEL_START_TIMEOUT_SECONDS = 1800;

export interface RagbenchLlmStackProps extends cdk.StackProps {
  readonly config: RagbenchConfig;
  readonly vpc: ec2.IVpc;
  /** `RagbenchDemoStack.instanceSg` — the only allowed source for vLLM traffic. */
  readonly demoInstanceSg: ec2.ISecurityGroup;
}

export class RagbenchLlmStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: RagbenchLlmStackProps) {
    super(scope, id, props);
    const cfg = props.config;
    const inferenceEndpointParameterName = `${ssmPrefix(cfg)}/llm-endpoint`;
    const judgeEndpointParameterName = `${ssmPrefix(cfg)}/judge-endpoint`;

    const instanceRole = new iam.Role(this, 'InstanceRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      description: 'RAGBench private LLM instance',
      managedPolicies: [iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore')],
    });
    instanceRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ['ssm:PutParameter'],
        resources: [inferenceEndpointParameterName, judgeEndpointParameterName].map(
          (name) => `arn:${this.partition}:ssm:${this.region}:${this.account}:parameter${name}`,
        ),
      }),
    );

    const llmSg = new ec2.SecurityGroup(this, 'LlmSg', {
      vpc: props.vpc,
      description: 'RAGBench private vLLM inference from the demo instance only',
      allowAllOutbound: true,
    });
    llmSg.addIngressRule(props.demoInstanceSg, ec2.Port.tcp(8000), 'Inference vLLM from demo instance only');
    llmSg.addIngressRule(props.demoInstanceSg, ec2.Port.tcp(8001), 'Judge vLLM from demo instance only');

    const userData = ec2.UserData.forLinux();
    userData.addCommands(
      'set -euo pipefail',
      'exec > >(tee -a /var/log/ragbench-llm-boot.log) 2>&1',
      'echo "[llm-boot $(date -u +%FT%TZ)] starting"',
      'systemctl is-active --quiet docker || systemctl start docker',
      // Both processes deliberately receive the whole GPU.  vLLM enforces the
      // split below; no partitioning layer is involved, so they can coexist on
      // the L40S while keeping their models resident for end_to_end evals.
      [
        'docker run -d --name ragbench-inference --restart unless-stopped --gpus all -p 8000:8000',
        VLLM_IMAGE,
        `--model ${INFERENCE_MODEL}`,
        '--port 8000',
        `--served-model-name ${INFERENCE_MODEL}`,
        `--gpu-memory-utilization ${INFERENCE_GPU_MEMORY_UTILIZATION}`,
        '--quantization fp8',
        '--language-model-only',
      ].join(' \\\n+  '),
      [
        'docker run -d --name ragbench-judge --restart unless-stopped --gpus all -p 8001:8001',
        VLLM_IMAGE,
        `--model ${JUDGE_MODEL}`,
        '--port 8001',
        `--served-model-name ${JUDGE_MODEL}`,
        `--gpu-memory-utilization ${JUDGE_GPU_MEMORY_UTILIZATION}`,
        '--language-model-only',
      ].join(' \\\n+  '),
      // A first boot downloads about 50 GB of weights. The stack intentionally
      // does not retain a volume or GPU AMI: it is used one or two times a
      // month, and the accepted cold-start budget is under 30 minutes.
      `if ! timeout ${MODEL_START_TIMEOUT_SECONDS} bash -c 'until curl -sf http://localhost:8000/health >/dev/null && curl -sf http://localhost:8001/health >/dev/null; do sleep 5; done'; then`,
      '  echo "[llm-boot $(date -u +%FT%TZ)] FAILED: vLLM servers did not become healthy"',
      '  docker logs ragbench-inference --tail 200 || true',
      '  docker logs ragbench-judge --tail 200 || true',
      '  exit 1',
      'fi',
      'TOKEN=$(curl -sX PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60")',
      'PRIVATE_IP=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/local-ipv4)',
      `aws ssm put-parameter --region ${this.region} --name "${inferenceEndpointParameterName}" ` +
        '--type String --overwrite --value "$PRIVATE_IP" > /dev/null',
      `aws ssm put-parameter --region ${this.region} --name "${judgeEndpointParameterName}" ` +
        '--type String --overwrite --value "$PRIVATE_IP" > /dev/null',
      'echo "[llm-boot $(date -u +%FT%TZ)] inference at ${PRIVATE_IP}:8000 and judge at ${PRIVATE_IP}:8001"',
    );

    const launchTemplate = new ec2.LaunchTemplate(this, 'LaunchTemplate', {
      launchTemplateName: `${cfg.project}-${cfg.envName}-llm`,
      instanceType: new ec2.InstanceType(cfg.llmInstanceType),
      machineImage: ec2.MachineImage.fromSsmParameter(cfg.embedGpuAmiSsmParameter, {
        os: ec2.OperatingSystemType.LINUX,
      }),
      userData,
      role: instanceRole,
      securityGroup: llmSg,
      requireImdsv2: true,
      detailedMonitoring: false,
      // The 19.3 GB BF16 source checkpoint and 30.9 GB FP8 judge checkpoint
      // are downloaded into Docker's host cache. A 100 GiB ephemeral root
      // disk prevents a cold launch from exhausting the DLAMI default volume.
      blockDevices: [
        {
          deviceName: '/dev/sda1',
          volume: ec2.BlockDeviceVolume.ebs(100, {
            encrypted: true,
            volumeType: ec2.EbsDeviceVolumeType.GP3,
            deleteOnTermination: true,
          }),
        },
      ],
      spotOptions: {
        requestType: ec2.SpotRequestType.ONE_TIME,
        interruptionBehavior: ec2.SpotInstanceInterruption.TERMINATE,
      },
    });

    const instance = new ec2.CfnInstance(this, 'Instance', {
      launchTemplate: {
        launchTemplateId: launchTemplate.launchTemplateId,
        version: launchTemplate.latestVersionNumber,
      },
      subnetId: props.vpc.publicSubnets[0].subnetId,
    });
    cdk.Tags.of(instance).add('Name', `${cfg.project}-${cfg.envName}-llm`);

    new cdk.CfnOutput(this, 'InstanceId', {
      value: instance.ref,
      description: 'aws ssm start-session --target <this>',
    });
    new cdk.CfnOutput(this, 'InferenceEndpointParameter', {
      value: inferenceEndpointParameterName,
      description: 'Private inference IP, written after vLLM /health succeeds.',
    });
    new cdk.CfnOutput(this, 'JudgeEndpointParameter', {
      value: judgeEndpointParameterName,
      description: 'Private judge IP, written after vLLM /health succeeds.',
    });
  }
}
