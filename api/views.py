import logging
import time

from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.services.fuel_service import load_stations, stations_near_route
from api.services.route_service import get_route
from api.services.optimizer import find_optimal_fuel_stops

logger = logging.getLogger(__name__)


@api_view(['POST'])
def plan_route(request):
    start_time = time.time()
    start = request.data.get('start', '').strip()
    end = request.data.get('end', '').strip()

    if not start or not end:
        return Response({'error': 'Both "start" and "end" are required.'}, status=400)
    if start.lower() == end.lower():
        return Response({'error': 'Start and end cannot be the same.'}, status=400)

    try:
        route_data = get_route(start, end)
    except (ConnectionError, ValueError) as e:
        return Response({'error': f'Route error: {str(e)}'}, status=503)

    all_stations = load_stations()
    corridor = getattr(settings, 'STATION_CORRIDOR_MILES', 50)
    nearby = stations_near_route(route_data['coordinates'], corridor, all_stations)

    if not nearby:
        return Response({'error': 'No stations found along route.'}, status=404)

    try:
        result = find_optimal_fuel_stops(
            route_data=route_data,
            nearby_stations=nearby,
            vehicle_range=getattr(settings, 'VEHICLE_RANGE_MILES', 500),
            mpg=getattr(settings, 'VEHICLE_MPG', 10),
        )
    except ValueError as e:
        return Response({'error': str(e)}, status=422)

    return Response({
        'query': {'start': start, 'end': end},
        'route': {
            'distance_miles': route_data['distance_miles'],
            'duration_hours': route_data['duration_hours'],
            'start_coords': route_data['start_coords'],
            'end_coords': route_data['end_coords'],
            'polyline_sample': route_data['coordinates'][::10],
        },
        'optimization': result,
        'meta': {
            'vehicle_range_miles': settings.VEHICLE_RANGE_MILES,
            'vehicle_mpg': settings.VEHICLE_MPG,
            'stations_in_corridor': len(nearby),
            'computation_seconds': round(time.time() - start_time, 3),
        },
    })


@api_view(['GET'])
def health_check(request):
    stations = load_stations()
    return Response({'status': 'ok', 'stations_loaded': len(stations)})


@api_view(['GET'])
def stations_preview(request):
    state = request.query_params.get('state', '').upper().strip()
    stations = load_stations()
    filtered = [s for s in stations if s['state'] == state] if state else stations[:50]
    return Response({'count': len(filtered), 'stations': filtered[:100]})
