#!/bin/sh

aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "${CONTAINER_REGISTRY}"
docker build --platform=linux/amd64 -t mta-feed-fetcher .
docker tag mta-feed-fetcher:latest "${CONTAINER_REGISTRY}/mta-feed-fetcher:latest"
docker push "${CONTAINER_REGISTRY}/mta-feed-fetcher:latest"