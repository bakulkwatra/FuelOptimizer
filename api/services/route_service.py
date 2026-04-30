import hashlib
import logging
from typing import Dict, List, Tuple

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

ORS_BASE = "https://api.openrouteservice.org/v2/directions/driving-car"


def _cache_key(start: str, end: str) -> str:
    raw = f"route:{start.strip().lower()}:{end.strip().lower()}"
    return hashlib.md5(raw.encode()).hexdigest()


def geocode_location(location: str) -> Tuple[float, float]:
    cache_key = f"geocode:{hashlib.md5(location.lower().encode()).hexdigest()}"
    cached = cache.get(cache_key)
    if cached:
        return tuple(cached)

    logger.info(f"Geocoding API call for: {location}")
    url = "https://api.openrouteservice.org/geocode/search"
    params = {
        'api_key': settings.ORS_API_KEY,
        'text': location,
        'boundary.country': 'US',
        'size': 1,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        features = data.get('features', [])
        if not features:
            raise ValueError(f"Location not found: {location}")
        coords = features[0]['geometry']['coordinates']
        result = (coords[1], coords[0])
        cache.set(cache_key, result, timeout=86400)
        return result
    except requests.RequestException as e:
        raise ConnectionError(f"Geocoding failed for '{location}': {e}")


def _decode_polyline(encoded: str) -> List[Tuple[float, float]]:

    coords = []
    index = 0
    lat = 0
    lon = 0
    while index < len(encoded):
        # decode latitude
        result = 0
        shift = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat

        # decode longitude
        result = 0
        shift = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break
        dlon = ~(result >> 1) if (result & 1) else (result >> 1)
        lon += dlon

        coords.append((lat / 1e5, lon / 1e5))

    return coords


def get_route(start: str, end: str) -> Dict:
    cache_key = _cache_key(start, end)
    cached = cache.get(cache_key)
    if cached:
        logger.info(f"Route cache HIT: {start} -> {end}")
        return cached

    logger.info(f"Route cache MISS - calling ORS: {start} -> {end}")

    start_coords = geocode_location(start)
    end_coords = geocode_location(end)

    payload = {
        "coordinates": [
            [start_coords[1], start_coords[0]],
            [end_coords[1], end_coords[0]],
        ],
    }

    headers = {
        'Authorization': settings.ORS_API_KEY,
        'Content-Type': 'application/json',
    }

    try:
        resp = requests.post(ORS_BASE, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise ConnectionError(f"Route API failed: {e}")

    if 'routes' not in data:
        raise ConnectionError(f"Unexpected ORS response: {data}")

    route = data['routes'][0]
    distance_miles = route['summary']['distance'] * 0.000621371
    duration_hours = route['summary']['duration'] / 3600

    # Decode the encoded polyline geometry ORS returns
    polyline = _decode_polyline(route['geometry'])

    result = {
        'distance_miles': round(distance_miles, 2),
        'duration_hours': round(duration_hours, 2),
        'coordinates': polyline,
        'start_coords': start_coords,
        'end_coords': end_coords,
    }

    cache.set(cache_key, result, timeout=3600)
    logger.info(f"Route fetched: {distance_miles:.1f} miles")
    return result


def annotate_route_with_distances(
    coordinates: List[Tuple[float, float]]
) -> List[Dict]:
    from api.services.fuel_service import haversine

    annotated = [{'lat': coordinates[0][0], 'lon': coordinates[0][1], 'miles': 0.0}]
    cumulative = 0.0

    for i in range(1, len(coordinates)):
        prev = coordinates[i - 1]
        curr = coordinates[i]
        segment_dist = haversine(prev[0], prev[1], curr[0], curr[1])
        cumulative += segment_dist
        annotated.append({
            'lat': curr[0],
            'lon': curr[1],
            'miles': round(cumulative, 2),
        })

    return annotated