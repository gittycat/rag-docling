/**
 * The golden AMI pipeline.
 *
 * Provisioning speed is the whole point of this stack: a cold `docker pull` of
 * 4-6 GB plus a 1.3 GB model download costs 15+ minutes on every demo. Baking
 * images, both model caches and an already-ingested corpus into an AMI turns
 * `cdk deploy` into a boot.
 *
 * Every Image Builder construct is L1 — there is no L2 for this service.
 */
import * as crypto from 'crypto';
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as imagebuilder from 'aws-cdk-lib/aws-imagebuilder';
import * as s3assets from 'aws-cdk-lib/aws-s3-assets';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { RagbenchConfig, SECRET_NAMES, repoNamespace, ssmPrefix } from './config';
import { buildBundle } from './bundle';

/** Pinned so a re-bake is reproducible; bump deliberately. */
const COMPOSE_PLUGIN_VERSION = 'v2.40.3';

/**
 * major.minor of the Image Builder component and recipe versions; the patch is
 * derived from content (see `contentPatch`). Bumped off the hand-pinned 1.0.x
 * line so no derived patch can collide with a version already in the account.
 */
const VERSION_SERIES = '1.1';

/**
 * A patch number that is a pure function of everything the component document
 * resolves to. 24 bits of sha256 — Image Builder wants an integer, and the only
 * property that matters is that distinct content gets a distinct number.
 */
function contentPatch(...inputs: string[]): number {
  const digest = crypto.createHash('sha256').update(inputs.join('\u0000')).digest('hex');
  return parseInt(digest.slice(0, 6), 16);
}

export interface RagbenchImageStackProps extends cdk.StackProps {
  readonly config: RagbenchConfig;
  readonly vpc: ec2.IVpc;
  readonly repositories: Record<string, ecr.IRepository>;
  readonly secrets: Record<string, secretsmanager.Secret>;
}

export class RagbenchImageStack extends cdk.Stack {
  readonly pipelineArnParameterName: string;
  readonly goldenAmiParameterName: string;

  constructor(scope: Construct, id: string, props: RagbenchImageStackProps) {
    super(scope, id, props);
    const cfg = props.config;
    const prefix = ssmPrefix(cfg);
    this.pipelineArnParameterName = `${prefix}/image-pipeline-arn`;
    this.goldenAmiParameterName = `${prefix}/golden-ami-id`;

    // ------------------------------------------------------------- app bundle
    const bundle = new s3assets.Asset(this, 'Bundle', {
      path: buildBundle(cdk.Stage.of(this)?.outdir ?? cdk.App.of(this)!.outdir, SECRET_NAMES),
    });

    // -------------------------------------------------------- builder identity
    const builderRole = new iam.Role(this, 'BuilderRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      description: 'Role assumed by the Image Builder build instance',
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('EC2InstanceProfileForImageBuilder'),
        iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore'),
      ],
    });
    bundle.grantRead(builderRole);
    // The bake pulls all four images out of ECR before it can start anything, so
    // it needs the same pull rights the demo instance has. Granted per repository
    // rather than via the broad EC2InstanceProfileForImageBuilderECRContainerBuilds
    // managed policy, which exists for container recipes pushing to ECR.
    for (const repo of Object.values(props.repositories)) {
      repo.grantPull(builderRole);
    }
    // The bake starts the real stack and ingests a corpus, so it needs the same
    // secrets the demo instance does — postgres creates its roles from them.
    for (const secret of Object.values(props.secrets)) {
      secret.grantRead(builderRole);
    }

    const builderProfile = new iam.CfnInstanceProfile(this, 'BuilderInstanceProfile', {
      roles: [builderRole.roleName],
    });

    // --------------------------------------------------------------- component
    const componentDoc = [
      'name: RagbenchBake',
      'description: Bake the RAGBench demo stack into an AMI',
      'schemaVersion: 1.0',
      'phases:',
      '  - name: build',
      '    steps:',
      '      - name: Unpack',
      '        action: ExecuteBash',
      '        timeoutSeconds: 600',
      '        inputs:',
      '          commands:',
      '            - set -euo pipefail',
      '            - dnf install -y unzip',
      '            - install -d ${AppDir}',
      '            - aws s3 cp ${BundleUri} /tmp/ragbench-bundle.zip',
      '            - unzip -oq /tmp/ragbench-bundle.zip -d ${AppDir}',
      '            - rm -f /tmp/ragbench-bundle.zip',
      '            - chmod +x ${AppDir}/scripts/*.sh',
      '      - name: Bake',
      '        action: ExecuteBash',
      '        timeoutSeconds: 3600',
      '        inputs:',
      '          commands:',
      '            - set -euo pipefail',
      '            - export AWS_REGION=${Region}',
      '            - export APP_DIR=${AppDir}',
      '            - export REGISTRY=${Registry}',
      '            - export VERSION=${Version}',
      '            - export SECRET_PREFIX=${SecretPrefix}',
      '            - export COMPOSE_VERSION=${ComposeVersion}',
      '            - ${AppDir}/scripts/bake.sh',
      '  - name: validate',
      '    steps:',
      '      - name: CheckBakedArtifacts',
      '        action: ExecuteBash',
      '        timeoutSeconds: 300',
      '        inputs:',
      '          commands:',
      '            - set -euo pipefail',
      // A bake that silently produced nothing is worse than a failed bake:
      // it yields an AMI that boots and then fails the first query.
      '            - test "$(docker images -q | wc -l)" -ge 5',
      '            - test -d ${AppDir}/.cache/huggingface/hub/models--cross-encoder--ms-marco-MiniLM-L-6-v2',
      '            - test -d ${AppDir}/.cache/huggingface/hub/models--docling-project--docling-models',
      '            - test ! -e ${AppDir}/secrets',
      '            - docker volume inspect ragbench_postgres_data ragbench_tei_data',
    ].join('\n');

    const registry = `${this.account}.dkr.ecr.${this.region}.amazonaws.com/${repoNamespace(cfg)}`;
    const appDir = '/opt/ragbench';
    const secretPrefix = `${cfg.project}/${cfg.envName}`;

    // Components and recipes are immutable: any change to Data replaces the
    // resource, and creating one with a name+version that already exists fails.
    // Hand-bumping got that wrong in both directions — Data embeds the bundle's
    // content-hashed S3 URI, so it also changes on any edit to bake.sh, boot.sh,
    // fetch-secrets.sh, config.yml, the compose files or the corpus, none of
    // which look like "the document below". Derived instead, so the version
    // moves exactly when the thing it identifies does.
    const version = `${VERSION_SERIES}.${contentPatch(
      componentDoc,
      bundle.assetHash,
      registry,
      appDir,
      secretPrefix,
      this.region,
      cfg.imageTag,
      COMPOSE_PLUGIN_VERSION,
      String(cfg.rootVolumeGiB),
    )}`;

    const component = new imagebuilder.CfnComponent(this, 'BakeComponent', {
      name: `${cfg.project}-${cfg.envName}-bake`,
      platform: 'Linux',
      version,
      description: 'Installs Docker, pulls images and model caches, ingests the demo corpus',
      data: cdk.Fn.sub(componentDoc, {
        AppDir: appDir,
        BundleUri: bundle.s3ObjectUrl,
        Region: this.region,
        Registry: registry,
        Version: cfg.imageTag,
        SecretPrefix: secretPrefix,
        ComposeVersion: COMPOSE_PLUGIN_VERSION,
      }),
    });

    // ------------------------------------------------------------------ recipe
    const recipe = new imagebuilder.CfnImageRecipe(this, 'Recipe', {
      name: `${cfg.project}-${cfg.envName}-recipe`,
      // A new component version replaces the recipe too, so it shares the version.
      version,
      parentImage: `arn:${this.partition}:imagebuilder:${this.region}:aws:image/amazon-linux-2023-arm64/x.x.x`,
      components: [{ componentArn: component.attrArn }],
      blockDeviceMappings: [
        {
          deviceName: '/dev/xvda',
          ebs: {
            volumeSize: cfg.rootVolumeGiB,
            volumeType: 'gp3',
            encrypted: true,
            deleteOnTermination: true,
          },
        },
      ],
      additionalInstanceConfiguration: {
        // Image Builder installs its own SSM agent; AL2023 already has one.
        systemsManagerAgent: { uninstallAfterBuild: false },
      },
    });

    // --------------------------------------------------- build-time networking
    // The build instance needs outbound internet (ECR, GitHub, HuggingFace,
    // ghcr.io for the TEI image) and nothing inbound. The VPC has no NAT, so it builds in
    // a public subnet with a public IP.
    const builderSg = new ec2.SecurityGroup(this, 'BuilderSg', {
      vpc: props.vpc,
      description: 'Image Builder build instance - egress only',
      allowAllOutbound: true,
    });

    const infra = new imagebuilder.CfnInfrastructureConfiguration(this, 'Infrastructure', {
      name: `${cfg.project}-${cfg.envName}-infra`,
      instanceProfileName: builderProfile.ref,
      // A bake runs an LLM-free ingestion of the sample corpus; the same shape as
      // the demo instance so nothing is tuned for hardware it will not run on.
      instanceTypes: [cfg.instanceType],
      subnetId: props.vpc.publicSubnets[0].subnetId,
      securityGroupIds: [builderSg.securityGroupId],
      terminateInstanceOnFailure: true,
    });

    const distribution = new imagebuilder.CfnDistributionConfiguration(this, 'Distribution', {
      name: `${cfg.project}-${cfg.envName}-distribution`,
      distributions: [
        {
          region: this.region,
          amiDistributionConfiguration: {
            Name: `${cfg.project}-${cfg.envName}-{{ imagebuilder:buildDate }}`,
            Description: 'RAGBench demo golden AMI',
          },
        },
      ],
    });

    const pipeline = new imagebuilder.CfnImagePipeline(this, 'Pipeline', {
      name: `${cfg.project}-${cfg.envName}-pipeline`,
      imageRecipeArn: recipe.attrArn,
      infrastructureConfigurationArn: infra.attrArn,
      distributionConfigurationArn: distribution.attrArn,
      // Baking is on demand — a schedule would burn build minutes between demos.
      status: 'ENABLED',
      imageTestsConfiguration: { imageTestsEnabled: false },
    });

    // ---------------------------------------------------------------- pointers
    // `just aws-bake` reads this to find the pipeline, and writes the resulting
    // AMI id to the golden-ami parameter. That parameter is deliberately NOT a
    // CloudFormation resource: if it were, every base-stack deploy would reset
    // it to a placeholder and the demo stack would boot a stale AMI.
    new ssm.StringParameter(this, 'PipelineArnParameter', {
      parameterName: this.pipelineArnParameterName,
      stringValue: pipeline.attrArn,
      description: 'Image Builder pipeline that produces the golden AMI',
    });

    new cdk.CfnOutput(this, 'PipelineArn', { value: pipeline.attrArn });
    new cdk.CfnOutput(this, 'GoldenAmiParameterName', {
      value: this.goldenAmiParameterName,
      description: 'Written by `just aws-bake`, read by RagbenchDemoStack',
    });
  }
}
