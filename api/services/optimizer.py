import logging
from typing import Dict, List, Tuple, Optional

from api.services.fuel_service import haversine, stations_near_point
from api.services.route_service import annotate_route_with_distances

logger = logging.getLogger(__name__)


def find_optimal_fuel_stops(
    route_data: Dict,
    nearby_stations: List[Dict],
    vehicle_range: float = 500.0,
    mpg: float = 10.0,
    start_fuel_fraction: float = 1.0,
) -> Dict:

    coordinates = route_data['coordinates']
    total_miles = route_data['distance_miles']

    annotated = annotate_route_with_distances(coordinates)

    current_miles = 0.0
    fuel_remaining_miles = vehicle_range * start_fuel_fraction
    fuel_stops = []
    total_fuel_cost = 0.0
    total_gallons = 0.0

    iteration = 0
    max_iterations = 100

    while iteration < max_iterations:
        iteration += 1
        miles_to_destination = total_miles - current_miles

        if fuel_remaining_miles >= miles_to_destination:
            logger.debug(f"Can reach destination from mile {current_miles:.1f}")
            break

        current_point = _get_point_at_mile(annotated, current_miles)
        if not current_point:
            logger.warning("Could not find route point — stopping optimization")
            break

        max_reachable_miles = current_miles + fuel_remaining_miles

        reachable_stations = _find_reachable_stations(
            annotated=annotated,
            nearby_stations=nearby_stations,
            from_mile=current_miles,
            to_mile=min(max_reachable_miles, total_miles),
            current_lat=current_point['lat'],
            current_lon=current_point['lon'],
        )

        if not reachable_stations:
            raise ValueError(
                f"No fuel stations found between mile {current_miles:.1f} "
                f"and mile {max_reachable_miles:.1f}. "
                f"This might mean the route corridor is too narrow or "
                f"the dataset doesn't cover this area."
            )

        chosen_stop = _select_best_stop(
            reachable_stations=reachable_stations,
            current_miles=current_miles,
            max_reachable_miles=max_reachable_miles,
            vehicle_range=vehicle_range,
        )

        miles_driven = chosen_stop['route_mile'] - current_miles
        gallons_consumed = miles_driven / mpg
        total_gallons += gallons_consumed

        fuel_on_arrival = fuel_remaining_miles - miles_driven
        gallons_filled = (vehicle_range - fuel_on_arrival) / mpg
        cost_at_stop = gallons_filled * chosen_stop['price']
        total_fuel_cost += cost_at_stop
        total_gallons += gallons_filled - gallons_consumed

        fuel_stops.append({
            'stop_number': len(fuel_stops) + 1,
            'name': chosen_stop['name'],
            'address': chosen_stop['address'],
            'city': chosen_stop['city'],
            'state': chosen_stop['state'],
            'lat': chosen_stop['lat'],
            'lon': chosen_stop['lon'],
            'price_per_gallon': round(chosen_stop['price'], 3),
            'gallons_filled': round(gallons_filled, 2),
            'cost_at_stop': round(cost_at_stop, 2),
            'miles_from_start': round(chosen_stop['route_mile'], 1),
            'fuel_on_arrival_miles': round(fuel_on_arrival, 1),
        })

        logger.info(
            f"Stop {len(fuel_stops)}: {chosen_stop['name']} at mile "
            f"{chosen_stop['route_mile']:.1f} — ${chosen_stop['price']:.3f}/gal — "
            f"cost ${cost_at_stop:.2f}"
        )

        current_miles = chosen_stop['route_mile']
        fuel_remaining_miles = vehicle_range

    return {
        'fuel_stops': fuel_stops,
        'total_fuel_cost': round(total_fuel_cost, 2),
        'total_gallons_purchased': round(sum(s['gallons_filled'] for s in fuel_stops), 2),
        'num_stops': len(fuel_stops),
        'route_miles': round(total_miles, 1),
        'avg_price_per_gallon': round(
            total_fuel_cost / max(sum(s['gallons_filled'] for s in fuel_stops), 1), 3
        ),
    }


def _get_point_at_mile(annotated: List[Dict], target_mile: float) -> Optional[Dict]:
    if not annotated:
        return None
    closest = min(annotated, key=lambda p: abs(p['miles'] - target_mile))
    return closest


def _find_reachable_stations(
    annotated: List[Dict],
    nearby_stations: List[Dict],
    from_mile: float,
    to_mile: float,
    current_lat: float,
    current_lon: float,
    corridor_miles: float = 300.0,
) -> List[Dict]:

    from api.services.fuel_service import haversine

    reachable = []

    for station in nearby_stations:
        nearest_point = min(
            annotated,
            key=lambda p: haversine(station['lat'], station['lon'], p['lat'], p['lon'])
        )
        route_mile = nearest_point['miles']

        if route_mile <= from_mile + 10:
            continue
        if route_mile > to_mile:
            continue

        dist_to_station = haversine(current_lat, current_lon, station['lat'], station['lon'])

        reachable.append({
            **station,
            'route_mile': route_mile,
            'dist_to_station': round(dist_to_station, 2),
        })

    return sorted(reachable, key=lambda x: x['price'])


def _select_best_stop(
    reachable_stations: List[Dict],
    current_miles: float,
    max_reachable_miles: float,
    vehicle_range: float,
    lookahead_threshold: float = 0.08,
) -> Dict:

    if not reachable_stations:
        raise ValueError("No reachable stations provided")

    range_span = max_reachable_miles - current_miles
    near_half_cutoff = current_miles + (range_span * 0.5)
    safety_cutoff = current_miles + (range_span * 0.8)

    cheapest = reachable_stations[0]

    stations_before_safety = [
        s for s in reachable_stations if s['route_mile'] <= safety_cutoff
    ]
    if not stations_before_safety:
        return min(reachable_stations, key=lambda s: s['route_mile'])

    cheapest_before_safety = min(stations_before_safety, key=lambda s: s['price'])

    if cheapest['route_mile'] <= near_half_cutoff:
        return cheapest

    near_stations = [s for s in reachable_stations if s['route_mile'] <= near_half_cutoff]

    if near_stations:
        cheapest_near = min(near_stations, key=lambda s: s['price'])
        price_diff_fraction = (cheapest_near['price'] - cheapest['price']) / cheapest['price']

        if price_diff_fraction <= lookahead_threshold:
            return cheapest_near
        else:
            return cheapest

    return cheapest_before_safety
