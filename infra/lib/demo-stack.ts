/**
 * The ephemeral stack: `just aws-up` before a demo, `just aws-down` after.
 *
 * Nothing here holds state worth keeping. The corpus, the model caches and the
 * images all live in the golden AMI produced by RagbenchImageStack, so a
 * teardown costs nothing but the minutes to redeploy.
 */
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as actions from 'aws-cdk-lib/aws-elasticloadbalancingv2-actions';
import * as targets from 'aws-cdk-lib/aws-elasticloadbalancingv2-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as route53targets from 'aws-cdk-lib/aws-route53-targets';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { RagbenchConfig, ssmPrefix } from './config';

export interface RagbenchDemoStackProps extends cdk.StackProps {
  readonly config: RagbenchConfig;
  readonly vpc: ec2.IVpc;
  readonly hostedZone: route53.IPublicHostedZone;
  readonly certificate: acm.ICertificate;
  readonly userPool: cognito.IUserPool;
  readonly userPoolClient: cognito.IUserPoolClient;
  readonly userPoolDomain: cognito.IUserPoolDomain;
  readonly repositories: Record<string, ecr.IRepository>;
  readonly secrets: Record<string, secretsmanager.ISecret>;
}

export class RagbenchDemoStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: RagbenchDemoStackProps) {
    super(scope, id, props);
    const cfg = props.config;
    const registry = `${this.account}.dkr.ecr.${this.region}.amazonaws.com/${cfg.project}`;

    // ------------------------------------------------------------------ roles
    const instanceRole = new iam.Role(this, 'InstanceRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      description: 'RAGBench demo instance',
      // Session Manager only. No SSH key, no bastion, no port 22 anywhere.
      managedPolicies: [iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore')],
    });
    for (const secret of Object.values(props.secrets)) {
      secret.grantRead(instanceRole);
    }
    for (const repo of Object.values(props.repositories)) {
      repo.grantPull(instanceRole);
    }

    // -------------------------------------------------------- security groups
    const albSg = new ec2.SecurityGroup(this, 'AlbSg', {
      vpc: props.vpc,
      description: 'ALB - public HTTPS',
      allowAllOutbound: true,
    });
    albSg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), 'HTTPS from the internet');
    albSg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(80), 'HTTP, redirected to 443');

    const instanceSg = new ec2.SecurityGroup(this, 'InstanceSg', {
      vpc: props.vpc,
      description: 'RAGBench demo instance - webapp from the ALB only',
      allowAllOutbound: true,
    });
    // The only inbound rule on the instance. rag-server (8001) and evals (8002)
    // are not published by the AWS overlay at all — evals has no authentication.
    instanceSg.addIngressRule(albSg, ec2.Port.tcp(8000), 'webapp, from the ALB only');

    // --------------------------------------------------------------- instance
    const userData = ec2.UserData.forLinux();
    userData.addCommands(
      'set -euo pipefail',
      `export AWS_REGION=${this.region}`,
      `export SECRET_PREFIX=${cfg.project}/${cfg.envName}`,
      `export REGISTRY=${registry}`,
      `export VERSION=${cfg.imageTag}`,
      `export WEBAPP_ORIGIN=https://${cfg.domainName}`,
      // Shipped inside the golden AMI by the bake; see infra/assets/boot.sh.
      '/opt/ragbench/scripts/boot.sh',
    );

    const instance = new ec2.Instance(this, 'Instance', {
      vpc: props.vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      instanceType: new ec2.InstanceType(cfg.instanceType),
      // Resolved at deploy time from the parameter `just aws-bake` writes, so a
      // re-bake is picked up by the next `just aws-up` with no code change.
      machineImage: ec2.MachineImage.fromSsmParameter(`${ssmPrefix(cfg)}/golden-ami-id`, {
        os: ec2.OperatingSystemType.LINUX,
        userData,
      }),
      role: instanceRole,
      securityGroup: instanceSg,
      requireImdsv2: true,
      detailedMonitoring: false,
      blockDevices: [
        {
          deviceName: '/dev/xvda',
          volume: ec2.BlockDeviceVolume.ebs(cfg.rootVolumeGiB, {
            volumeType: ec2.EbsDeviceVolumeType.GP3,
            encrypted: true,
            deleteOnTermination: true,
          }),
        },
      ],
    });
    cdk.Tags.of(instance).add('Name', `${cfg.project}-${cfg.envName}`);

    // -------------------------------------------------------------------- alb
    const alb = new elbv2.ApplicationLoadBalancer(this, 'Alb', {
      vpc: props.vpc,
      internetFacing: true,
      securityGroup: albSg,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      idleTimeout: cdk.Duration.seconds(120), // ingestion and streaming answers are slow
    });

    const targetGroup = new elbv2.ApplicationTargetGroup(this, 'WebappTargets', {
      vpc: props.vpc,
      port: 8000,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targetType: elbv2.TargetType.INSTANCE,
      targets: [new targets.InstanceTarget(instance, 8000)],
      healthCheck: {
        path: '/',
        // SvelteKit's root may redirect; anything that is not a 5xx means the
        // node server is serving.
        healthyHttpCodes: '200-399',
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(10),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 5,
      },
      deregistrationDelay: cdk.Duration.seconds(10),
    });

    alb.addListener('Https', {
      port: 443,
      protocol: elbv2.ApplicationProtocol.HTTPS,
      certificates: [props.certificate],
      sslPolicy: elbv2.SslPolicy.RECOMMENDED_TLS,
      // This is the ONLY authentication in front of the application. The app
      // itself has none — see docs/suggestions.md.
      defaultAction: new actions.AuthenticateCognitoAction({
        userPool: props.userPool,
        userPoolClient: props.userPoolClient,
        userPoolDomain: props.userPoolDomain,
        sessionTimeout: cdk.Duration.hours(8),
        onUnauthenticatedRequest: elbv2.UnauthenticatedAction.AUTHENTICATE,
        next: elbv2.ListenerAction.forward([targetGroup]),
      }),
    });

    alb.addListener('HttpRedirect', {
      port: 80,
      protocol: elbv2.ApplicationProtocol.HTTP,
      defaultAction: elbv2.ListenerAction.redirect({
        protocol: 'HTTPS',
        port: '443',
        permanent: true,
      }),
    });

    // -------------------------------------------------------------------- dns
    new route53.ARecord(this, 'AliasRecord', {
      zone: props.hostedZone,
      recordName: cfg.domainName,
      target: route53.RecordTarget.fromAlias(new route53targets.LoadBalancerTarget(alb)),
    });

    // ---------------------------------------------------------------- outputs
    new cdk.CfnOutput(this, 'DemoUrl', { value: `https://${cfg.domainName}` });
    new cdk.CfnOutput(this, 'InstanceId', {
      value: instance.instanceId,
      description: 'aws ssm start-session --target <this>',
    });
    new cdk.CfnOutput(this, 'AlbDnsName', { value: alb.loadBalancerDnsName });
  }
}
