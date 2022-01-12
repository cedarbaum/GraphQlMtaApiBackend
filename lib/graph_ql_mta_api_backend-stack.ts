import * as cdk from "@aws-cdk/core";
import * as appsync from "@aws-cdk/aws-appsync";
import * as pythonLambda from "@aws-cdk/aws-lambda-python";
import * as lambda from "@aws-cdk/aws-lambda";
import * as ecs from "@aws-cdk/aws-ecs";
import * as iam from "@aws-cdk/aws-iam";
import * as ec2 from "@aws-cdk/aws-ec2";
import * as logs from "@aws-cdk/aws-logs";
import * as s3 from "@aws-cdk/aws-s3";
import * as ddb from "@aws-cdk/aws-dynamodb";

import { Compatibility, ContainerImage, NetworkMode } from "@aws-cdk/aws-ecs";
import { Effect, PolicyStatement } from "@aws-cdk/aws-iam";
import { StackProps } from "@aws-cdk/core";
import { AttributeType, BillingMode } from "@aws-cdk/aws-dynamodb";
import { MappingTemplate } from "@aws-cdk/aws-appsync";

export class GraphQlMtaApiBackendStack extends cdk.Stack {
  constructor(scope: cdk.Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    const graphQlApi = new appsync.GraphqlApi(this, "MtaApi", {
      name: "mtaApi",
      schema: appsync.Schema.fromAsset("graphql/schema.graphql"),
      authorizationConfig: {
        defaultAuthorization: {
          authorizationType: appsync.AuthorizationType.IAM,
        },
        additionalAuthorizationModes: [
          {
            authorizationType: appsync.AuthorizationType.API_KEY,
          },
        ],
      },
    });

    if (process.env?.OUTPUT_APPSYNC_DETAILS) {
      new cdk.CfnOutput(this, "GraphQLAPIURL", {
        value: graphQlApi.graphqlUrl,
        exportName: "GraphQLAPIURL",
      });

      new cdk.CfnOutput(this, "GraphQLAPIID", {
        value: graphQlApi.apiId,
        exportName: "GraphQLAPIID",
      });

      new cdk.CfnOutput(this, "GraphQLAPIKey", {
        value: graphQlApi.apiKey ?? "",
        exportName: "GraphQLAPIKey",
      });
    }

    const feedStorageBucket = new s3.Bucket(this, "FeedsBucket", {
      bucketName: "closing-doors-mta-feeds",
    });

    const systemMetadataDdbTable = new ddb.Table(this, "MTASystemMetadata", {
      tableName: "mtaSystemMetadata",
      billingMode: BillingMode.PAY_PER_REQUEST,
      partitionKey: {
        name: "key",
        type: AttributeType.STRING,
      },
    });

    const systemMetadataDs = graphQlApi.addDynamoDbDataSource(
      "systemMetadataSource",
      systemMetadataDdbTable
    );
    systemMetadataDs.createResolver({
      typeName: "Query",
      fieldName: "systemMetadata",
      requestMappingTemplate: MappingTemplate.fromFile(
        "mapping_templates/runningRoutesInputMappingTemplate.vtl"
      ),
      responseMappingTemplate: MappingTemplate.fromFile(
        "mapping_templates/runningRoutesOutputMappingTemplate.vtl"
      ),
    });

    const nearestStationLambda = new pythonLambda.PythonFunction(
      this,
      "MTANearestStation",
      {
        entry: "functions/mtaNearestStation",
        runtime: lambda.Runtime.PYTHON_3_8,
        memorySize: 752,
        logRetention: logs.RetentionDays.ONE_WEEK,
      }
    );

    const nearestStationDs = graphQlApi.addLambdaDataSource(
      "nearestStationSource",
      nearestStationLambda
    );
    nearestStationDs.createResolver({
      typeName: "Query",
      fieldName: "nearestStations",
    });

    const trainTimesLambda = new pythonLambda.PythonFunction(
      this,
      "TrainTimes",
      {
        entry: "functions/mtaTrainTimes",
        runtime: lambda.Runtime.PYTHON_3_8,
        memorySize: 1024,
        logRetention: logs.RetentionDays.ONE_WEEK,
      }
    );
    feedStorageBucket.grantRead(trainTimesLambda);

    const trainTimesDs = graphQlApi.addLambdaDataSource(
      "trainTimesSource",
      trainTimesLambda
    );
    trainTimesDs.createResolver({
      typeName: "Query",
      fieldName: "trainTimes",
    });

    const cluster = new ecs.Cluster(this, "MTAServices", {
      clusterName: "mtaServicesCluster",
      enableFargateCapacityProviders: true,
      vpc: this.createEcsNetworkingStack(),
    });

    const execRole = new iam.Role(this, "FeedUpdateTaskExecutionRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    });
    execRole.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName(
        "service-role/AmazonECSTaskExecutionRolePolicy"
      )
    );

    const containerTaskRole = new iam.Role(this, "FeedUpdateTaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    });
    feedStorageBucket.grantWrite(containerTaskRole);
    systemMetadataDdbTable.grantWriteData(containerTaskRole);

    const secretManagerPolicyStatement = new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["secretsmanager:GetSecretValue"],
      resources: [
        `arn:aws:secretsmanager:${props?.env?.region}:${props?.env?.account}:secret:*`,
      ],
    });
    containerTaskRole.addToPolicy(secretManagerPolicyStatement);

    const updateFeedsTask = new ecs.TaskDefinition(this, "UpdateFeedsTask", {
      family: "updateFeedsTaskDefinition",
      compatibility: Compatibility.FARGATE,
      networkMode: NetworkMode.AWS_VPC,
      cpu: "256",
      memoryMiB: "512",
      executionRole: execRole,
      taskRole: containerTaskRole,
    });
    updateFeedsTask.addContainer("UpdateFeedsTaskImage", {
      image: ContainerImage.fromRegistry(`${process.env.CONTAINER_REGISTRY!}/mta-feed-fetcher:latest`),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: "ecs",
        logRetention: logs.RetentionDays.ONE_WEEK,
      }),
    });

    new ecs.FargateService(this, "UpdateFeedsService", {
      cluster: cluster,
      taskDefinition: updateFeedsTask,
      assignPublicIp: true,
    });
  }

  private createEcsNetworkingStack(): ec2.Vpc {
    const vpcName = "UpdateFeedServiceVpc";
    const vpc = new ec2.Vpc(this, vpcName, {
      cidr: "10.192.0.0/16",
      natGateways: 0,
      maxAzs: 2,
      enableDnsSupport: true,
      enableDnsHostnames: true,
      subnetConfiguration: [
        {
          name: "public-subnet",
          subnetType: ec2.SubnetType.PUBLIC,
          mapPublicIpOnLaunch: true,
          cidrMask: 24,
        },
      ],
    });

    new ec2.SecurityGroup(this, "NoIngressSg", {
      securityGroupName: "no-ingress-sg",
      vpc: vpc,
    });

    return vpc;
  }
}
