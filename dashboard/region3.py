import json
import math
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).parent / "static" / "dashboard"
ADDRESS_FIELDS = (
    "street_address",
    "barangay",
    "municipality_city",
    "province",
    "postal_code",
    "country",
    "gps_coordinates",
)


@lru_cache(maxsize=1)
def geography():
    with (DATA_DIR / "region3_locations.json").open(encoding="utf-8") as file:
        locations = json.load(file)
    with (DATA_DIR / "region3_cities.json").open(encoding="utf-8") as file:
        cities = json.load(file)
    return locations["provinces"], cities


def ring_contains(ring, longitude, latitude):
    inside = False
    for index, (x1, y1) in enumerate(ring):
        x2, y2 = ring[index - 1]
        cross = (longitude - x1) * (y2 - y1) - (latitude - y1) * (x2 - x1)
        if (
            abs(cross) < 1e-12
            and min(x1, x2) <= longitude <= max(x1, x2)
            and min(y1, y2) <= latitude <= max(y1, y2)
        ):
            return True
        if (y1 > latitude) != (y2 > latitude):
            crossing = x1 + (latitude - y1) * (x2 - x1) / (y2 - y1)
            if longitude < crossing:
                inside = not inside
    return inside


def geometry_contains(geometry, longitude, latitude):
    polygons = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        polygons = [polygons]
    return any(
        ring_contains(polygon[0], longitude, latitude)
        and not any(ring_contains(hole, longitude, latitude) for hole in polygon[1:])
        for polygon in polygons
    )


def geometry_bounds(geometry):
    polygons = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        polygons = [polygons]
    points = (point for polygon in polygons for ring in polygon for point in ring)
    first = next(points)
    min_x = max_x = first[0]
    min_y = max_y = first[1]
    for x, y in points:
        min_x, max_x = min(min_x, x), max(max_x, x)
        min_y, max_y = min(min_y, y), max(max_y, y)
    return min_x, min_y, max_x, max_y


def bounds_contain(bounds, longitude, latitude):
    return bounds[0] <= longitude <= bounds[2] and bounds[1] <= latitude <= bounds[3]


@lru_cache(maxsize=1)
def lookup_index():
    provinces, city_boundaries = geography()
    with (DATA_DIR / "region3_barangays.json").open(encoding="utf-8") as file:
        barangay_boundaries = json.load(file)
    index = []
    for province in provinces:
        for city in province["cities"]:
            city_geometry = city_boundaries[city["code"]]
            barangays = []
            for barangay in city["barangays"]:
                geometry = barangay_boundaries[barangay["code"]]
                barangays.append((barangay, geometry, geometry_bounds(geometry)))
            index.append(
                (province, city, city_geometry, geometry_bounds(city_geometry), barangays)
            )
    return index


def parse_coordinates(latitude, longitude):
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        raise ValueError("Invalid coordinates.")
    latitude, longitude = float(latitude), float(longitude)
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise ValueError("Invalid coordinates.")
    return latitude, longitude


def locate_point(latitude, longitude):
    matches = []
    inside_city = False
    for province, city, geometry, bounds, barangays in lookup_index():
        if not bounds_contain(bounds, longitude, latitude) or not geometry_contains(
            geometry, longitude, latitude
        ):
            continue
        inside_city = True
        for barangay, geometry, bounds in barangays:
            if bounds_contain(bounds, longitude, latitude) and geometry_contains(
                geometry, longitude, latitude
            ):
                matches.append(
                    {
                        "province": province["name"],
                        "municipality_city": city["name"],
                        "barangay": barangay["name"],
                    }
                )
    if not inside_city:
        return {"status": "outside"}
    if not matches:
        return {"status": "unresolved"}
    if len(matches) > 1:
        return {"status": "ambiguous"}
    return {"status": "matched", **matches[0]}


def validate_address(address):
    if not isinstance(address, dict):
        return "Provide a complete address."
    for field in ADDRESS_FIELDS:
        if not isinstance(address.get(field), str) or not address[field].strip():
            return f"Provide {field.replace('_', ' ')} for the complete address."
    if address["country"].strip().casefold() != "philippines":
        return "Country must be Philippines."
    provinces, _ = geography()
    province = next(
        (p for p in provinces if p["name"] == address["province"].strip()), None
    )
    city = (
        next(
            (
                c
                for c in province["cities"]
                if c["name"] == address["municipality_city"].strip()
            ),
            None,
        )
        if province
        else None
    )
    if not city or not any(
        b["name"] == address["barangay"].strip() for b in city["barangays"]
    ):
        return "Select a valid Region III province, city or municipality, and barangay."
    try:
        parts = address["gps_coordinates"].split(",")
        if len(parts) != 2:
            raise ValueError
        latitude, longitude = parse_coordinates(*(part.strip() for part in parts))
    except ValueError:
        return "Confirm a valid latitude and longitude on the map."
    result = locate_point(latitude, longitude)
    if result["status"] == "outside":
        return "The pin is outside Region III."
    if result["status"] != "matched":
        return "The pin's barangay cannot be determined reliably. Choose another pin."
    if any(
        result[field] != address[field].strip()
        for field in ("province", "municipality_city", "barangay")
    ):
        return "The pin does not match the selected province, city, and barangay."
    return None
