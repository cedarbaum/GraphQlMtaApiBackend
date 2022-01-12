#!/usr/bin/env python3

import boto3
import concurrent.futures
import time
import traceback
import json

from botocore.config import Config
from datetime import datetime
from nyct_gtfs.stop_time_update import StopTimeUpdate
from nyct_gtfs.trip import Trip
from nyct_gtfs import NYCTFeed

update_interval_seconds = 15
failure_backoff_interval_seconds = 5
mta_api_key = None
tables = {}

FEED_URL_PREFIX = 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/'


def main():
    print("Starting feed update loop")

    feed_urls = set(NYCTFeed._train_to_url.values())

    last_feed_updated_at = {}
    get_mta_api_key()

    config = Config(
        connect_timeout=5, read_timeout=5,
        retries={'max_attempts': 3})
    s3 = boto3.resource('s3', config=config)
    ddb = boto3.resource('dynamodb', config=config, region_name='us-east-1')
    metadataTable = ddb.Table('mtaSystemMetadata')

    while True:
        try:
            print(f'Updating {len(feed_urls)} feeds...')
            
            num_stale_feeds = 0
            all_feed_data = []
            with concurrent.futures.ThreadPoolExecutor(len(feed_urls)) as thp:
                all_feed_data = list(
                    thp.map(get_and_process_feed_data, feed_urls, timeout=30))

            all_active_routes = set()
            min_feed_updated_at = None
            for (feed_url, stop_dict, active_routes, feed_updated_at) in all_feed_data:
                if (last_feed_updated_at.get(feed_url) == feed_updated_at):
                    num_stale_feeds += 1

                obj_name = feed_url[len(FEED_URL_PREFIX):]
                s3object = s3.Object(
                    'closing-doors-mta-feeds', f'{obj_name}.json')

                feed_data = {
                    'id': feed_url,
                    'data': stop_dict,
                    'active_routes': list(active_routes),
                    'updated_at': int(time.time()),
                    'feed_updated_at':  feed_updated_at
                }

                s3object.put(
                    Body=(bytes(json.dumps(feed_data).encode('UTF-8')))
                )

                all_active_routes.update(active_routes)
                min_feed_updated_at = feed_updated_at if not min_feed_updated_at else min(
                    min_feed_updated_at, feed_updated_at)

                last_feed_updated_at[feed_url] = feed_updated_at

            print(f'Writing MTA system metadata...')
            metadataTable.put_item(Item={
                'key': 'running_services',
                'data': all_active_routes,
                'updated_at': int(time.time()),
                'min_feed_updated_at':  min_feed_updated_at
            })

            print(
                f'Finished updating feeds ({num_stale_feeds} stale), waiting {update_interval_seconds} seconds')
            time.sleep(update_interval_seconds)

        except Exception as ex:
            print(
                f'Failed to update feeds with exception {ex}. Waiting {failure_backoff_interval_seconds} seconds.')
            print(traceback.format_exc())
            last_feed_updated_at = {}
            time.sleep(failure_backoff_interval_seconds)


def get_and_process_feed_data(feed_url):
    feed = NYCTFeed(feed_url, api_key=get_mta_api_key())
    feed_update_time = int(feed.last_generated.timestamp())
    stop_dict = process_trips(feed)

    return (feed_url, stop_dict, set(stop_dict.keys()), feed_update_time)


def process_trips(feed: NYCTFeed) -> dict:
    trips: list[Trip] = feed.trips

    stops_flat = (
        (
            trip.route_id,
            stop.stop_id,
            int(arrive_or_depart(stop).timestamp()),
            trip.trip_id,
            trip.has_delay_alert,
        )
        for trip in trips
        for stop in trip.stop_time_updates
        if arrive_or_depart(stop) is not None and arrive_or_depart(stop) >= feed.last_generated
    )

    # Sort by arrival time
    stops_flat_sorted = sorted(stops_flat, key=lambda tuple: tuple[2])

    stops_grouped = dict()
    for route_id, stop_id, eta, trip_id, delayed in stops_flat_sorted:
        if route_id not in stops_grouped:
            stops_grouped[route_id] = dict()

        if stop_id not in stops_grouped[route_id]:
            stops_grouped[route_id][stop_id] = []

        stops_grouped[route_id][stop_id].append({
            'id': trip_id,
            'arrival': eta,
        })

        if delayed:
            stops_grouped[route_id][stop_id][-1]['delayed'] = True

    return stops_grouped


def arrive_or_depart(stop_time_update: StopTimeUpdate) -> datetime:
    return stop_time_update.arrival or stop_time_update.departure


def get_mta_api_key():
    global mta_api_key
    if mta_api_key is not None:
        return mta_api_key

    print('Getting MTA API key from Secrets Manager')

    secret_name = "mta-api-key"
    region_name = "us-east-1"

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    get_secret_value_response = client.get_secret_value(
        SecretId=secret_name
    )

    mta_api_key = get_secret_value_response['SecretString']
    return mta_api_key


if __name__ == "__main__":
    main()
