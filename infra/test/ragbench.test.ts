import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { loadConfig } from '../lib/config';
import { RagbenchBaseStack } from '../lib/base-stack';
import { RagbenchImageStack } from '../lib/image-stack';
import { RagbenchDemoStack } from '../lib/demo-stack';

const ACCOUNT = '111122223333';
const REGION = 'ap-southeast-2';

function synth() {
  const app = new cdk.App({
    context: {
      account: ACCOUNT,
      region: REGION,
      domainName: 'demo.example.com',
      // Supplied so the VPC does not attempt a live AZ lookup during tests.
      [`availability-zones:account=${ACCOUNT}:region=${REGION}`]: [
        `${REGION}a`,
        `${REGION}b`,
        `${REGION}c`,
      ],
    },
  });
  const config = loadConfig(app);
  const env = { account: ACCOUNT, region: REGION };

  const base = new RagbenchBaseStack(app, 'RagbenchBaseStack', { env, config });
  const image = new RagbenchImageStack(app, 'RagbenchImageStack', {
    env,
    config,
    vpc: base.vpc,
    repositories: base.repositories,
    secrets: base.secrets,
  });
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
  });

  return {
    base: Template.fromStack(base),
    image: Template.fromStack(image),
    demo: Template.fromStack(demo),
    baseStack: base,
  };
}

describe('RagbenchDemoStack', () => {
  test('the instance is reachable only from the ALB, never from the internet', () => {
    const { demo } = synth();

    // Inline ingress: every open rule must belong to the ALB's own group.
    const groups = demo.findResources('AWS::EC2::SecurityGroup');
    for (const [logicalId, group] of Object.entries(groups)) {
      const ingress = (group as any).Properties?.SecurityGroupIngress ?? [];
      for (const rule of ingress) {
        if (rule.CidrIp === '0.0.0.0/0' || rule.CidrIpv6 === '::/0') {
          expect(logicalId).toMatch(/^AlbSg/);
          expect([80, 443]).toContain(rule.FromPort);
        }
      }
    }

    // Standalone ingress resources must be source-security-group based only.
    const standalone = demo.findResources('AWS::EC2::SecurityGroupIngress');
    for (const rule of Object.values(standalone)) {
      const props = (rule as any).Properties;
      expect(props.CidrIp).toBeUndefined();
      expect(props.SourceSecurityGroupId).toBeDefined();
      expect(props.FromPort).toBe(8000);
    }
  });

  test('no SSH anywhere — access is Session Manager only', () => {
    const { demo } = synth();
    const json = JSON.stringify(demo.toJSON());
    expect(json).not.toContain('"FromPort":22');
    demo.hasResourceProperties('AWS::EC2::Instance', Match.objectLike({
      KeyName: Match.absent(),
    }));
  });

  test('the HTTPS listener authenticates with Cognito before forwarding', () => {
    const { demo } = synth();
    demo.hasResourceProperties('AWS::ElasticLoadBalancingV2::Listener', {
      Port: 443,
      Protocol: 'HTTPS',
      DefaultActions: Match.arrayWith([
        Match.objectLike({ Type: 'authenticate-cognito', Order: 1 }),
        Match.objectLike({ Type: 'forward', Order: 2 }),
      ]),
    });
  });

  test('port 80 only redirects', () => {
    const { demo } = synth();
    demo.hasResourceProperties('AWS::ElasticLoadBalancingV2::Listener', {
      Port: 80,
      DefaultActions: [Match.objectLike({ Type: 'redirect' })],
    });
  });

  test('the AMI comes from the golden-AMI SSM parameter, resolved at deploy time', () => {
    const { demo } = synth();
    const params = demo.toJSON().Parameters ?? {};
    const amiParam = Object.values(params).find(
      (p: any) => p.Default === '/ragbench/demo/golden-ami-id',
    ) as any;
    expect(amiParam).toBeDefined();
    expect(amiParam.Type).toBe('AWS::SSM::Parameter::Value<AWS::EC2::Image::Id>');
  });

  test('the instance can pull from ECR and read every secret', () => {
    const { demo } = synth();
    const statements = Object.values(demo.findResources('AWS::IAM::Policy'))
      .flatMap((p: any) => p.Properties.PolicyDocument.Statement);
    const actions = JSON.stringify(statements.map((st: any) => st.Action));
    expect(actions).toContain('ecr:BatchGetImage');
    expect(actions).toContain('secretsmanager:GetSecretValue');

    const secretReads = statements.filter((st: any) =>
      JSON.stringify(st.Action).includes('secretsmanager:GetSecretValue'),
    );
    expect(secretReads).toHaveLength(7);
  });

  test('the root volume is encrypted', () => {
    const { demo } = synth();
    demo.hasResourceProperties('AWS::EC2::Instance', {
      BlockDeviceMappings: Match.arrayWith([
        Match.objectLike({ Ebs: Match.objectLike({ Encrypted: true, VolumeType: 'gp3' }) }),
      ]),
    });
  });

  test('IMDSv2 is required', () => {
    const { demo } = synth();
    demo.hasResourceProperties('AWS::EC2::LaunchTemplate', {
      LaunchTemplateData: Match.objectLike({
        MetadataOptions: Match.objectLike({ HttpTokens: 'required' }),
      }),
    });
  });
});

describe('RagbenchBaseStack', () => {
  // A replaced user pool silently wipes every demo login. Pinning the logical
  // ID turns that into a failing test instead of a surprise on deploy day.
  test('the Cognito user pool logical ID is stable', () => {
    const { base } = synth();
    const pools = Object.keys(base.findResources('AWS::Cognito::UserPool'));
    expect(pools).toEqual(['UserPool6BA7E5F2']);
  });

  test('stateful resources are retained', () => {
    const { base } = synth();
    for (const type of ['AWS::Cognito::UserPool', 'AWS::ECR::Repository', 'AWS::SecretsManager::Secret']) {
      for (const resource of Object.values(base.findResources(type))) {
        expect((resource as any).DeletionPolicy).toBe('Retain');
      }
    }
  });

  test('termination protection is on', () => {
    const { baseStack } = synth();
    expect(baseStack.terminationProtection).toBe(true);
  });

  test('there is no NAT gateway — it would cost more idle than the whole demo', () => {
    const { base } = synth();
    base.resourceCountIs('AWS::EC2::NatGateway', 0);
  });

  test('all seven application secrets exist, and only the API keys are unset', () => {
    const { base } = synth();
    const secrets = Object.values(base.findResources('AWS::SecretsManager::Secret'));
    expect(secrets).toHaveLength(7);

    // CDK always emits GenerateSecretString; the manual ones are the two with no
    // generator settings inside it.
    const unset = secrets
      .filter((s: any) => !s.Properties.GenerateSecretString?.PasswordLength)
      .map((s: any) => s.Properties.Name);
    expect(unset.sort()).toEqual(['ragbench/demo/ANTHROPIC_API_KEY', 'ragbench/demo/OPENAI_API_KEY']);
  });

  test('ECR repositories keep only the last five images', () => {
    const { base } = synth();
    base.resourceCountIs('AWS::ECR::Repository', 4);
    for (const repo of Object.values(base.findResources('AWS::ECR::Repository'))) {
      expect((repo as any).Properties.LifecyclePolicy.LifecyclePolicyText).toContain('"countNumber":5');
    }
  });
});

describe('RagbenchImageStack', () => {
  test('the pipeline builds on the same instance type the demo runs on', () => {
    const { image } = synth();
    image.hasResourceProperties('AWS::ImageBuilder::InfrastructureConfiguration', {
      InstanceTypes: ['m7g.xlarge'],
    });
  });

  test('the bake component seeds both model caches and drops its secrets', () => {
    const { image } = synth();
    const component = Object.values(image.findResources('AWS::ImageBuilder::Component'))[0] as any;
    const data = JSON.stringify(component.Properties.Data);
    expect(data).toContain('ms-marco-MiniLM-L-6-v2');
    expect(data).toContain('docling-project--docling-models');
    // Secrets are fetched during the bake so postgres can create its roles; they
    // must not survive into the snapshot.
    expect(data).toContain('test ! -e ${AppDir}/secrets');
  });

  test('the build instance can pull every image it has to bake', () => {
    const { image } = synth();
    const policies = Object.values(image.findResources('AWS::IAM::Policy'));
    const statements = policies.flatMap((p: any) => p.Properties.PolicyDocument.Statement);
    const pulls = statements.filter((st: any) =>
      JSON.stringify(st.Action).includes('ecr:BatchGetImage'),
    );
    expect(pulls.length).toBeGreaterThan(0);
    // Four repositories, referenced by ARN import from the base stack.
    const resources = JSON.stringify(pulls.map((st: any) => st.Resource));
    for (const repo of ['Webapp', 'RagServer', 'Postgres', 'Evals']) {
      expect(resources).toContain(`Repo${repo}`);
    }
  });

  test('the recipe is arm64 Amazon Linux 2023 with an encrypted root volume', () => {
    const { image } = synth();
    const recipe = Object.values(image.findResources('AWS::ImageBuilder::ImageRecipe'))[0] as any;
    // ParentImage is an Fn::Join over the partition, so match the rendered JSON.
    expect(JSON.stringify(recipe.Properties.ParentImage)).toContain('amazon-linux-2023-arm64');
    image.hasResourceProperties('AWS::ImageBuilder::ImageRecipe', {
      BlockDeviceMappings: Match.arrayWith([
        Match.objectLike({ Ebs: Match.objectLike({ Encrypted: true }) }),
      ]),
    });
  });
});
