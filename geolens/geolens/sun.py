"""Solar geometry (NOAA algorithm, vectorised) for shadow geolocation & chronolocation.

Techniques implemented:
* solar_position      – sun azimuth/elevation for a place & UTC time
* shadow_locus        – every lat/lon on Earth where the sun had a given elevation
                        (and optionally azimuth) at a given UTC time  → map band
* chronolocate        – times of day at a known place where the sun had a given elevation
* elevation_from_shadow – sun elevation from object height / shadow length
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np


def _julian_century(dt: datetime) -> float:
    dt = dt.astimezone(timezone.utc)
    jd = dt.timestamp() / 86400.0 + 2440587.5
    return (jd - 2451545.0) / 36525.0


def _sun_params(dt: datetime) -> tuple[float, float]:
    """Return (declination_rad, equation_of_time_minutes)."""
    t = _julian_century(dt)
    l0 = math.radians((280.46646 + t * (36000.76983 + t * 0.0003032)) % 360)
    m = math.radians(357.52911 + t * (35999.05029 - 0.0001537 * t))
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    c = (math.sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * m) * (0.019993 - 0.000101 * t) + math.sin(3 * m) * 0.000289)
    true_long = l0 + math.radians(c)
    omega = math.radians(125.04 - 1934.136 * t)
    app_long = true_long - math.radians(0.00569 + 0.00478 * math.sin(omega))
    eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    eps = math.radians(eps0 + 0.00256 * math.cos(omega))
    decl = math.asin(math.sin(eps) * math.sin(app_long))
    y = math.tan(eps / 2) ** 2
    eot = 4 * math.degrees(y * math.sin(2 * l0) - 2 * e * math.sin(m) + 4 * e * y * math.sin(m) * math.cos(2 * l0)
                           - 0.5 * y * y * math.sin(4 * l0) - 1.25 * e * e * math.sin(2 * m))
    return decl, eot


def _az_el(lat, lon, dt: datetime):
    """Vectorised over lat/lon arrays (degrees). Returns (azimuth°, elevation°)."""
    decl, eot = _sun_params(dt)
    dt = dt.astimezone(timezone.utc)
    minutes = dt.hour * 60 + dt.minute + dt.second / 60
    lat_r = np.radians(lat)
    tst = (minutes + eot + 4 * np.asarray(lon)) % 1440
    ha = np.radians(np.where(tst / 4 < 0, tst / 4 + 180, tst / 4 - 180))
    cos_z = np.clip(np.sin(lat_r) * math.sin(decl) + np.cos(lat_r) * math.cos(decl) * np.cos(ha), -1, 1)
    zen = np.arccos(cos_z)
    el = 90 - np.degrees(zen)
    # atmospheric refraction (small, matters near horizon)
    el = el + np.where(el > -0.575, 1.02 / np.tan(np.radians(el + 10.3 / (el + 5.11))) / 60, 0)
    denom = np.cos(lat_r) * np.sin(zen)
    denom = np.where(np.abs(denom) < 1e-9, 1e-9, denom)
    az_c = np.clip((np.sin(lat_r) * np.cos(zen) - math.sin(decl)) / denom, -1, 1)
    az = np.degrees(np.arccos(az_c))
    az = np.where(ha > 0, (az + 180) % 360, (540 - az) % 360)
    return az, el


def solar_position(lat: float, lon: float, dt_utc: datetime) -> dict:
    az, el = _az_el(np.array(lat), np.array(lon), dt_utc)
    az, el = float(az), float(el)
    return {"azimuth": round(az, 2), "elevation": round(el, 2),
            "shadow_bearing": round((az + 180) % 360, 2),
            "shadow_ratio": None if el <= 0 else round(1 / math.tan(math.radians(el)), 3),
            "daylight": el > -0.833}


def sun_times(lat: float, lon: float, day: datetime) -> dict:
    """Approximate sunrise / solar noon / sunset (UTC) by scanning the day."""
    base = day.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    prev, rise, sset, noon, best = None, None, None, None, -99.0
    for m in range(0, 1441, 2):
        t = base + timedelta(minutes=m)
        el = solar_position(lat, lon, t)["elevation"]
        if el > best:
            best, noon = el, t
        if prev is not None:
            if prev < -0.833 <= el and rise is None:
                rise = t
            if prev >= -0.833 > el:
                sset = t
        prev = el
    f = lambda x: x.isoformat() if x else None
    return {"sunrise_utc": f(rise), "solar_noon_utc": f(noon), "sunset_utc": f(sset),
            "max_elevation": round(best, 2)}


def elevation_from_shadow(object_height: float, shadow_length: float) -> float:
    return math.degrees(math.atan2(object_height, shadow_length))


def shadow_locus(dt_utc: datetime, elevation: float, tol: float = 1.5,
                 azimuth: float | None = None, az_tol: float = 10.0, step: float = 1.0) -> dict:
    """All grid points where the sun stood at `elevation` (±tol) at dt_utc."""
    lats = np.arange(-80, 80.001, step)
    lons = np.arange(-180, 180, step)
    LON, LAT = np.meshgrid(lons, lats)
    az, el = _az_el(LAT, LON, dt_utc)
    mask = np.abs(el - elevation) <= tol
    if azimuth is not None:
        d = np.abs((az - azimuth + 180) % 360 - 180)
        mask &= d <= az_tol
    pts = np.column_stack([LAT[mask], LON[mask]])
    # subsolar point (sun at zenith) for reference
    i = np.unravel_index(np.argmax(el), el.shape)
    return {"points": pts.round(2).tolist(), "count": int(mask.sum()),
            "subsolar": [float(LAT[i]), float(LON[i])]}


def chronolocate(lat: float, lon: float, day: datetime, elevation: float,
                 azimuth: float | None = None) -> list[dict]:
    """Times (UTC) on `day` when sun elevation crossed `elevation` at (lat, lon)."""
    base = day.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    out, prev = [], None
    for m in range(0, 1441):
        t = base + timedelta(minutes=m)
        p = solar_position(lat, lon, t)
        if prev is not None and (prev["elevation"] - elevation) * (p["elevation"] - elevation) <= 0 \
                and prev["elevation"] != p["elevation"]:
            if azimuth is None or abs((p["azimuth"] - azimuth + 180) % 360 - 180) < 25:
                out.append({"utc": t.isoformat(), "azimuth": p["azimuth"],
                            "part": "morning" if p["elevation"] > prev["elevation"] else "afternoon"})
        prev = p
    return out


TEACH = (
    "Shadows are a clock and a compass at the same time. The sun's elevation equals "
    "atan(object height ÷ shadow length); its azimuth is the shadow bearing + 180°. For a known "
    "UTC time, only a thin ring of places on Earth sees the sun at that elevation (the 'circle of "
    "equal altitude' used in celestial navigation). Intersecting that ring with other clues "
    "(language, vegetation, driving side) collapses the search area. If the place is known instead, "
    "the same maths tells you the time of day the photo was taken (chronolocation). Shadows pointing "
    "towards the visible pole at noon tell the hemisphere: northern-hemisphere noon shadows point north "
    "(outside the tropics), southern-hemisphere ones point south."
)
