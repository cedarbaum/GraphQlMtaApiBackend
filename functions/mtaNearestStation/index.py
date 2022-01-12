import os
import csv
import geopy.distance


def handler(event, context):

    lat = event["arguments"]['lat']
    lon = event["arguments"]['lon']

    numStations = None
    if 'numStations' in event['arguments']:
        numStations = event["arguments"]['numStations']

    all_stop_data = []
    script_dir = os.path.dirname(__file__)

    # stop_id,stop_name,stop_lat,stop_lon
    with open(os.path.join(script_dir, 'stops.csv')) as stops_csv:
        csv_reader = csv.reader(stops_csv, delimiter=',')
        read_header = False
        for row in csv_reader:
            if not read_header:
                read_header = True
                continue
            else:
                stop_lat = float(row[2])
                stop_lon = float(row[3])

                stop_data = {
                    'id': row[0],
                    'name': row[1],
                    'lat': stop_lat,
                    'lon': stop_lon,
                    'distance_km': geopy.distance.distance((lat, lon), (stop_lat, stop_lon)).km
                }

                all_stop_data.append(stop_data)

    all_stop_data.sort(key=lambda stop_data: stop_data['distance_km'])
    return all_stop_data[:numStations] if numStations else all_stop_data
