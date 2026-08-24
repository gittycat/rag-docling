/**
 * Persistent resources. Nothing here is destroyed between demos.
 *
 * Split from the demo stack by *lifecycle*, not by function: everything below is
 * either slow to create (ACM issuance, hosted-zone delegation) or holds state that
 * must survive a teardown (Cognito users, ECR images, secrets).
 */
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import {
  IMAGE_NAMES,
  MANUAL_SECRET_NAMES,
  RagbenchConfig,
  SECRET_NAMES,
  repoName,
  secretId,
} from './config';

export interface RagbenchBaseStackProps extends cdk.StackProps {
  readonly config: RagbenchConfig;
}

export class RagbenchBaseStack extends cdk.Stack {
  readonly vpc: ec2.Vpc;
  readonly hostedZone: route53.PublicHostedZone;
  readonly certificate: acm.Certificate;
  readonly userPool: cognito.UserPool;
  readonly userPoolClient: cognito.UserPoolClient;
  readonly userPoolDomain: cognito.UserPoolDomain;
  readonly repositories: Record<string, ecr.Repository> = {};
  readonly secrets: Record<string, secretsmanager.Secret> = {};

  constructor(scope: Construct, id: string, props: RagbenchBaseStackProps) {
    super(scope, id, { ...props, terminationProtection: true });
    const cfg = props.config;

    // ---------------------------------------------------------------- network
    // natGateways: 0 is deliberate. A NAT gateway is ~$35/mo idle and this
    // workload has exactly one instance that can live in a public subnet.
    this.vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        // Public IPs are required, not incidental: with natGateways: 0 this is the
        // only egress path, and both the demo instance and the Image Builder
        // build instance need to reach ECR, HuggingFace and the Ollama registry.
        // Inbound exposure is controlled by security groups, not by subnet type.
        { name: 'public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24, mapPublicIpOnLaunch: true },
      ],
      restrictDefaultSecurityGroup: true,
    });

    this.vpc.addFlowLog('FlowLog', {
      destination: ec2.FlowLogDestination.toCloudWatchLogs(
        new logs.LogGroup(this, 'VpcFlowLogs', {
          retention: logs.RetentionDays.ONE_MONTH,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
      ),
      trafficType: ec2.FlowLogTrafficType.REJECT,
    });

    // -------------------------------------------------------------------- dns
    // MANUAL STEP, once: copy the four NS records in the `HostedZoneNameServers`
    // output into the parent domain at your existing DNS provider. Certificate
    // validation will not complete until that delegation is live.
    this.hostedZone = new route53.PublicHostedZone(this, 'HostedZone', {
      zoneName: cfg.domainName,
      comment: `${cfg.project} ${cfg.envName} — delegated subdomain`,
    });
    this.hostedZone.applyRemovalPolicy(cdk.RemovalPolicy.RETAIN);

    this.certificate = new acm.Certificate(this, 'Certificate', {
      domainName: cfg.domainName,
      validation: acm.CertificateValidation.fromDns(this.hostedZone),
    });

    // ------------------------------------------------------------------ auth
    // The application has no authentication of its own — the ALB's Cognito
    // action is the only gate. Retained so demo users survive a teardown.
    this.userPool = new cognito.UserPool(this, 'UserPool', {
      userPoolName: `${cfg.project}-${cfg.envName}`,
      selfSignUpEnabled: false, // invite-only: a handful of known demo viewers
      signInAliases: { email: true },
      autoVerify: { email: true },
      standardAttributes: { email: { required: true, mutable: false } },
      passwordPolicy: {
        minLength: 12,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
      },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    this.userPoolClient = this.userPool.addClient('AlbClient', {
      userPoolClientName: `${cfg.project}-${cfg.envName}-alb`,
      generateSecret: true, // required by the ALB authenticate-cognito action
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
        callbackUrls: [`https://${cfg.domainName}/oauth2/idpresponse`],
        logoutUrls: [`https://${cfg.domainName}`],
      },
      preventUserExistenceErrors: true,
    });

    this.userPoolDomain = this.userPool.addDomain('HostedUiDomain', {
      cognitoDomain: { domainPrefix: `${cfg.project}-${cfg.envName}-${this.account}` },
    });

    // ------------------------------------------------------------------- ecr
    for (const image of IMAGE_NAMES) {
      this.repositories[image] = new ecr.Repository(this, `Repo${toPascal(image)}`, {
        repositoryName: repoName(cfg, image),
        imageScanOnPush: true,
        imageTagMutability: ecr.TagMutability.MUTABLE, // `latest` is re-tagged per push
        encryption: ecr.RepositoryEncryption.AES_256,
        lifecycleRules: [{ maxImageCount: 5, description: 'Keep the last 5 images' }],
        removalPolicy: cdk.RemovalPolicy.RETAIN,
      });
    }

    // --------------------------------------------------------------- secrets
    // The app ignores environment variables by design (settings_customise_sources
    // returns file_secret_settings only), so these are fetched by user data and
    // written to files the compose stack mounts. See demo-stack.ts.
    for (const name of SECRET_NAMES) {
      const manual = MANUAL_SECRET_NAMES.includes(name);
      this.secrets[name] = new secretsmanager.Secret(this, `Secret${toPascal(name)}`, {
        secretName: secretId(cfg, name),
        description: manual
          ? `${name} — set this by hand once: aws secretsmanager put-secret-value`
          : `${name} — generated`,
        removalPolicy: cdk.RemovalPolicy.RETAIN,
        ...(manual ? {} : { generateSecretString: generatorFor(name) }),
      });
    }

    // --------------------------------------------------------------- outputs
    new cdk.CfnOutput(this, 'HostedZoneNameServers', {
      value: cdk.Fn.join(', ', this.hostedZone.hostedZoneNameServers ?? []),
      description: 'Add these NS records at your existing DNS provider, once.',
    });
    new cdk.CfnOutput(this, 'VpcId', { value: this.vpc.vpcId, exportName: `${cfg.project}-${cfg.envName}-vpc-id` });
    new cdk.CfnOutput(this, 'UserPoolId', { value: this.userPool.userPoolId });
    new cdk.CfnOutput(this, 'CognitoHostedUi', { value: this.userPoolDomain.baseUrl() });
    new cdk.CfnOutput(this, 'EcrRegistry', {
      value: `${this.account}.dkr.ecr.${this.region}.amazonaws.com`,
      description: 'REGISTRY prefix for `just ecr-push`',
    });
  }
}

/**
 * Usernames and passwords need different alphabets: a Postgres role name has to be
 * a bare identifier, and 00-roles.sh interpolates it into DDL.
 */
function generatorFor(name: string): secretsmanager.SecretStringGenerator {
  if (name.endsWith('_USER')) {
    // Lowercase letters only, so the value is always a valid bare Postgres
    // identifier and never needs quoting. Kept as a plain string, not JSON —
    // user data writes `--query SecretString` straight to a file.
    return {
      excludePunctuation: true,
      excludeUppercase: true,
      excludeNumbers: true,
      passwordLength: 12,
    };
  }
  return {
    excludePunctuation: true, // avoids quoting hazards in psql DDL and shell here-docs
    passwordLength: 40,
  };
}

function toPascal(s: string): string {
  return s
    .split(/[-_]/)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1).toLowerCase())
    .join('');
}
