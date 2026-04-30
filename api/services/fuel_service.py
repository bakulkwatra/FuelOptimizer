import csv
import math
import os
import logging
from functools import lru_cache
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import urllib.request
import json

logger = logging.getLogger(__name__)

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))



STATE_CENTERS: Dict[str, Tuple[float, float]] = {
    'AL': (32.806671, -86.791130), 'AK': (61.370716, -152.404419),
    'AZ': (33.729759, -111.431221), 'AR': (34.969704, -92.373123),
    'CA': (36.116203, -119.681564), 'CO': (39.059811, -105.311104),
    'CT': (41.597782, -72.755371), 'DE': (39.318523, -75.507141),
    'FL': (27.766279, -81.686783), 'GA': (33.040619, -83.643074),
    'HI': (21.094318, -157.498337), 'ID': (44.240459, -114.478828),
    'IL': (40.349457, -88.986137), 'IN': (39.849426, -86.258278),
    'IA': (42.011539, -93.210526), 'KS': (38.526600, -96.726486),
    'KY': (37.668140, -84.670067), 'LA': (31.169960, -91.867805),
    'ME': (44.693947, -69.381927), 'MD': (39.063946, -76.802101),
    'MA': (42.230171, -71.530106), 'MI': (43.326618, -84.536095),
    'MN': (45.694454, -93.900192), 'MS': (32.741646, -89.678696),
    'MO': (38.456085, -92.288368), 'MT': (46.921925, -110.454353),
    'NE': (41.125370, -98.268082), 'NV': (38.313515, -117.055374),
    'NH': (43.452492, -71.563896), 'NJ': (40.298904, -74.521011),
    'NM': (34.840515, -106.248482), 'NY': (42.165726, -74.948051),
    'NC': (35.630066, -79.806419), 'ND': (47.528912, -99.784012),
    'OH': (40.388783, -82.764915), 'OK': (35.565342, -96.928917),
    'OR': (44.572021, -122.070938), 'PA': (40.590752, -77.209755),
    'RI': (41.680893, -71.511780), 'SC': (33.856892, -80.945007),
    'SD': (44.299782, -99.438828), 'TN': (35.747845, -86.692345),
    'TX': (31.054487, -97.563461), 'UT': (40.150032, -111.862434),
    'VT': (44.045876, -72.710686), 'VA': (37.769337, -78.169968),
    'WA': (47.400902, -121.490494), 'WV': (38.491226, -80.954453),
    'WI': (44.268543, -89.616508), 'WY': (42.755966, -107.302490),
    'DC': (38.897438, -77.026817),
}


_CITY_COORDS: Dict[str, Tuple[float, float]] = {}
_CITY_DB_LOADED = False


def _load_city_db():
    
    global _CITY_COORDS, _CITY_DB_LOADED
    if _CITY_DB_LOADED:
        return

    
    cache_path = Path(__file__).parent.parent / 'us_cities_cache.json'

    if cache_path.exists():
        with open(cache_path) as f:
            _CITY_COORDS = json.load(f)
        _CITY_DB_LOADED = True
        logger.info(f"Loaded {len(_CITY_COORDS)} city coordinates from cache")
        return

    
    try:
        url = "https://simplemaps.com/static/data/us-cities/1.79/basic/simplemaps_uscities_basicv1.79.zip"
        
        _build_fallback_city_db(cache_path)
    except Exception as e:
        logger.warning(f"Could not load city DB: {e}. Using state centroids.")
        _CITY_DB_LOADED = True


def _build_fallback_city_db(cache_path: Path):
    
    global _CITY_COORDS, _CITY_DB_LOADED

    fuel_csv = Path(__file__).parent.parent / 'fuel_data.csv'
    unique_cities = set()

    with open(fuel_csv, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            city = row['City'].strip()
            state = row['State'].strip()
            if city and state:
                unique_cities.add((city, state))

    logger.info(f"Geocoding {len(unique_cities)} unique city+state pairs...")

    from geopy.geocoders import Nominatim
    from geopy.extra.rate_limiter import RateLimiter

    geolocator = Nominatim(user_agent="fuel_optimizer_v1")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)

    coords = {}
    for city, state in unique_cities:
        key = f"{city},{state}"
        try:
            location = geocode(f"{city}, {state}, USA")
            if location:
                coords[key] = (location.latitude, location.longitude)
            else:
                
                coords[key] = STATE_CENTERS.get(state, (39.5, -98.35))
        except Exception:
            coords[key] = STATE_CENTERS.get(state, (39.5, -98.35))

    _CITY_COORDS = coords
    _CITY_DB_LOADED = True

   
    with open(cache_path, 'w') as f:
        json.dump(coords, f)
    logger.info(f"City DB cached to {cache_path}")


def get_city_coords(city: str, state: str) -> Tuple[float, float]:
    """Return (lat, lon) for a city+state. Falls back to state center."""
    _load_city_db()
    key = f"{city.strip()},{state.strip()}"
    if key in _CITY_COORDS:
        return tuple(_CITY_COORDS[key])
    return STATE_CENTERS.get(state.strip(), (39.5, -98.35))




_STATIONS: Optional[List[Dict]] = None


def load_stations() -> List[Dict]:

    global _STATIONS
    if _STATIONS is not None:
        return _STATIONS

    fuel_csv = Path(__file__).parent.parent / 'fuel_data.csv'
    raw = []

    with open(fuel_csv, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                price = float(row['Retail Price'])
                city = row['City'].strip()
                state = row['State'].strip()
                lat, lon = get_city_coords(city, state)
                raw.append({
                    'id': row['OPIS Truckstop ID'],
                    'name': row['Truckstop Name'].strip(),
                    'address': row['Address'].strip(),
                    'city': city,
                    'state': state,
                    'price': price,
                    'lat': lat,
                    'lon': lon,
                })
            except (ValueError, KeyError):
                continue

    seen = {}
    for s in raw:
        key = s['id']
        if key not in seen or s['price'] < seen[key]['price']:
            seen[key] = s

    _STATIONS = list(seen.values())
    logger.info(f"Loaded {len(_STATIONS)} unique fuel stations")
    return _STATIONS




def stations_near_point(
    lat: float,
    lon: float,
    radius_miles: float,
    stations: List[Dict]
) -> List[Dict]:
    """Return all stations within radius_miles of a point, sorted by price."""
    nearby = []
    for s in stations:
        d = haversine(lat, lon, s['lat'], s['lon'])
        if d <= radius_miles:
            nearby.append({**s, 'distance_from_point': round(d, 2)})
    return sorted(nearby, key=lambda x: x['price'])


def stations_near_route(
    route_coords: List[Tuple[float, float]],
    corridor_miles: float,
    stations: List[Dict]
) -> List[Dict]:

    if not route_coords:
        return []


    lats = [c[0] for c in route_coords]
    lons = [c[1] for c in route_coords]
    
    deg_buffer = corridor_miles / 69.0

    min_lat = min(lats) - deg_buffer
    max_lat = max(lats) + deg_buffer
    min_lon = min(lons) - deg_buffer
    max_lon = max(lons) + deg_buffer

    
    candidates = [
        s for s in stations
        if min_lat <= s['lat'] <= max_lat and min_lon <= s['lon'] <= max_lon
    ]

    
    result = []
    
    sampled = route_coords[::5] or route_coords
    for s in candidates:
        min_dist = min(haversine(s['lat'], s['lon'], p[0], p[1]) for p in sampled)
        if min_dist <= corridor_miles:
            result.append({**s, 'distance_from_route': round(min_dist, 2)})

    return result
