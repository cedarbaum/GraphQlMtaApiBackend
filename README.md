# GraphQlMtaApiBackend

This is a fully serverless GraphQL backend for interacting with the NYC [MTA API](https://api.mta.info/). It runs in AWS and is deployed using CDK.

# Components

- `UpdateFeedsService`: A Fargate service that takes a periodic snapshot of the MTA's real-time data feeds and persists them to S3 for consumption by other services.
- `mtaApi`: The AppSync instance that resolves GraphQL requests.
    - `mtaNearestStation`: a Lambda function that resolves the `nearestStations` query.
    - `mtaTrainTimes`: a Lambda function that resolves the `trainTimes` query.
    - `mtaSystemMetadata`: a DynamoDB table that resolves the `systemMetadata` query (see: `mapping_templates` folder).

# Building and deploying

## Environment

The following environment variables are used:

- `CONTAINER_REGISTRY`: the address of the container registry to push/pull the `mta-feed-fetcher` Docker image.
- `OUTPUT_APPSYNC_DETAILS`: if true, output the AppSync URL and API key after deployment.

## Docker

Before deploying the infrastructure, the `mta-feed-fetcher` Docker image needs to be built and published:

1. `cd docker`
2. `./build_and_push`

This only needs to be done once initially and then subsequently when the image changes.

## AWS resources

1. `npm install && npm run build`
2. `cdk deploy --all`

# Related projects

-  [MTAPI](https://github.com/jonthornton/MTAPI)
-  [Transiter](https://github.com/jamespfennell/transiter)
