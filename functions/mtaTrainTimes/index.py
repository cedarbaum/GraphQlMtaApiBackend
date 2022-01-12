import boto3
import json

from nyct_gtfs import NYCTFeed


def handler(event, context):
    stations = None
    if 'stations' in event['arguments']:
        stations = set(event['arguments']['stations'])

    if not 'services' in event['arguments'] or len(event['arguments']['services']) == 0:
        raise ValueError('At least 1 service must be provided')

    directions = None
    if 'directions' in event['arguments']:
        directions = set(event['arguments']['directions'])

    services = set(event['arguments']['services'])

    # Remove X suffix for express lines
    services_keys = set(map(lambda service: service[:-1] if service[-1]
                            == 'X' else service, services))
    feed_urls = set(
        map(lambda service_key: NYCTFeed._train_to_url.get(service_key), services_keys))

    if len(feed_urls) == 0:
        return {
            'stationSerivceTrips': [],
            'updatedAt': None
        }

    all_feed_data = list(map(get_feed_data, feed_urls))
    stop_dicts = list(
        map(lambda resp: resp['data'], all_feed_data))
    earliest_updated_at = min(
        map(lambda resp: resp['updated_at'], all_feed_data))

    results_by_station = {}
    for stop_dict in stop_dicts:
        for service, stations_and_trips in stop_dict.items():
            if service in services:
                for station, trips in stations_and_trips.items():
                    station_without_direction = station[:-1]
                    station_direction = 'NORTH' if station[-1] == 'N' else 'SOUTH'
                    station_matches_direction = directions is None or station_direction in directions 
                    if (stations is None or station_without_direction in stations) and station_matches_direction:
                        station_data = results_by_station.get(station, {})
                        station_data[service] = trips
                        results_by_station[station] = station_data

    return {
        'stationServiceTrips': [{'stationId': stationId,
                                 'serviceTrips': [{'service': service,
                                                   'trips': trips} for (service, trips) in servicesAndTrips.items()]}
                                for (stationId, servicesAndTrips) in results_by_station.items()],
        'updatedAt': int(earliest_updated_at)
    }


def get_feed_data(feed_url):
    FEED_URL_PREFIX = 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/'
    obj_name = feed_url[len(FEED_URL_PREFIX):]

    s3 = boto3.resource('s3')
    content_object = s3.Object('closing-doors-mta-feeds', f'{obj_name}.json')
    file_content = content_object.get()['Body'].read().decode('utf-8')

    return json.loads(file_content)
