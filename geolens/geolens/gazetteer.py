"""Offline gazetteer: 244 countries + ~15k cities (GeoNames, CC-BY 4.0)."""
from __future__ import annotations

import json
import math
import os
import re
import sys
import unicodedata
from functools import lru_cache


def resource_path(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    if hasattr(sys, "_MEIPASS"):
        base = os.path.join(base, "geolens")
    return os.path.join(base, *parts)


@lru_cache(maxsize=1)
def _data() -> dict:
    with open(resource_path("data", "gazetteer.json"), encoding="utf-8") as f:
        d = json.load(f)
    tzs = d["tz"]
    d["city_rows"] = [
        {"name": c[0], "cc": c[1], "lat": c[2], "lon": c[3], "pop": c[4], "tz": tzs[c[5]],
         "alt": c[6] if len(c) > 6 else []}
        for c in d["cities"]
    ]
    return d


def countries() -> dict[str, dict]:
    return _data()["countries"]


def country_name(iso: str) -> str:
    c = countries().get(iso)
    return c["name"] if c else iso


def cities_of(iso: str, limit: int = 40) -> list[dict]:
    rows = [c for c in _data()["city_rows"] if c["cc"] == iso]
    rows.sort(key=lambda c: -c["pop"])
    return rows[:limit]


def all_cities() -> list[dict]:
    return _data()["city_rows"]


def by_continent(code: str) -> list[str]:
    return [iso for iso, c in countries().items() if c["continent"] == code]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def nearest_city(lat: float, lon: float) -> dict | None:
    best, bd = None, 1e18
    for c in _data()["city_rows"]:
        d = (c["lat"] - lat) ** 2 + ((c["lon"] - lon) * math.cos(math.radians(lat))) ** 2
        if d < bd:
            best, bd = c, d
    if best:
        best = dict(best, dist_km=round(haversine_km(lat, lon, best["lat"], best["lon"]), 1))
    return best


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower()


@lru_cache(maxsize=1)
def _name_index() -> tuple[dict[str, list[dict]], dict[str, str]]:
    idx: dict[str, list[dict]] = {}
    for c in _data()["city_rows"]:
        for nm in {_norm(c["name"]), *(_norm(a) for a in c["alt"])}:
            if len(nm) >= 4:
                idx.setdefault(nm, []).append(c)
    cidx = {_norm(c["name"]): iso for iso, c in countries().items()}
    return idx, cidx


# Words that are also common city names but cause false positives in free text.
_STOP = {"mobile", "split", "nice", "bath", "reading", "orange", "male", "bar", "college", "university",
         "victoria", "florida", "georgia", "jordan", "chad", "march", "may", "best", "rome", "deal",
         "most", "sale", "como", "image", "photo", "video", "street", "center", "centre", "union",
         "liberty", "independence", "hope", "paradise", "eagle", "lincoln", "jackson", "washington"}


def find_places(text: str, min_pop: int = 40000) -> list[dict]:
    """Find city / country names mentioned in free text (OCR output, page titles…)."""
    idx, cidx = _name_index()
    t = _norm(text)
    words = re.findall(r"[a-z][a-z'\-]+", t)
    found: dict[str, dict] = {}
    for n in range(3, 0, -1):
        for i in range(len(words) - n + 1):
            g = " ".join(words[i:i + n])
            if g in _STOP:
                continue
            if g in cidx:
                iso = cidx[g]
                c = countries()[iso]
                found.setdefault("C:" + iso, {"type": "country", "name": c["name"], "cc": iso,
                                              "lat": c["lat"], "lon": c["lon"], "pop": 0, "hits": 0})
                found["C:" + iso]["hits"] += 1
            elif g in idx and len(g) >= 4:
                for c in idx[g]:
                    if c["pop"] < (min_pop if len(g) >= 5 else 1_000_000):
                        continue
                    k = f"{c['name']}|{c['cc']}"
                    found.setdefault(k, dict(c, type="city", hits=0, match=g))
                    found[k]["hits"] += 1
    return sorted(found.values(), key=lambda x: (-x["hits"], -x["pop"]))
