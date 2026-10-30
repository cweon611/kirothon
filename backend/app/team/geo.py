"""Straight-line travel estimate used when no routing service is available (F1, F2)."""
import math

PARKING_WALK_MIN = 5


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2)
    return 6371 * 2 * math.asin(math.sqrt(min(1.0, h)))


def move_minutes(a: tuple[float, float], b: tuple[float, float], transport: str = "car") -> int:
    """Design rule: >=20km distance x1.3 at 60km/h, else x1.4 at 35km/h, +5 min per stop.

    Public transport multiplies by 1.5; callers must show '실제 배차 확인'.
    """
    km = haversine_km(a, b)
    hours = km * 1.3 / 60 if km >= 20 else km * 1.4 / 35
    minutes = hours * 60 + PARKING_WALK_MIN
    if transport == "transit":
        minutes *= 1.5
    return int(math.ceil(minutes))
