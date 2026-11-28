"""Blind geolocation benchmark on low-information landscape photos.

* Ground-truth photos come from Wikimedia Commons (geotagged files near ~40 rural / natural points on every
  continent). Captions, filenames and EXIF are discarded — the pipeline sees only pixels.
* All online techniques (reverse search, geocoding) are DISABLED, so an exact web match is impossible:
  the score measures pure visual / landscape reasoning.
* Metrics: country accuracy (top-1 / top-3), median error, share within 25 / 200 / 750 / 2500 km,
  GeoGuessr-style score (5000·e^(−d/1492.7)), and whether the true spot falls inside the top-5 heat regions.

usage: python tools/benchmark.py --out bench.json [--n 40] [--model streetclip] [--cache DIR]
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import random
import re
import statistics
import sys
import time

import requests
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from geolens import gazetteer as gz  # noqa: E402
from geolens.log import AnalysisLog  # noqa: E402
from geolens.pipeline import Analyzer  # noqa: E402
from geolens.vision import VisionEngine  # noqa: E402

UA = {"User-Agent": "GeoLensBenchmark/1.0 (open-source geolocation research; contact via GitHub)"}
API = "https://commons.wikimedia.org/w/api.php"

# Rural / natural points — deliberately avoiding famous landmarks.
POINTS = [
    (47.35, 1.30, "Loire valley countryside, FR"), (45.95, 4.95, "Ain river plain, FR"), (43.30, 11.40, "Tuscan hills, IT"),
    (48.90, 12.90, "Bavarian forest, DE"), (52.60, 6.40, "Overijssel farmland, NL"), (57.10, -4.70, "Scottish Highlands, GB"),
    (52.90, -8.20, "Irish midlands, IE"), (61.20, 8.30, "Norwegian mountains, NO"), (62.20, 25.80, "Finnish lakeland, FI"),
    (58.70, 15.30, "Swedish forest, SE"), (52.10, 21.90, "Masovian plain, PL"), (49.50, 32.00, "Ukrainian steppe, UA"),
    (37.80, -4.30, "Andalusian olive country, ES"), (41.20, -7.60, "Douro valley, PT"), (39.60, 22.00, "Thessaly plain, GR"),
    (38.90, 33.50, "Anatolian plateau, TR"), (31.20, -7.80, "High Atlas foothills, MA"), (-1.40, 35.10, "Maasai Mara, KE"),
    (-32.30, 22.50, "Karoo, ZA"), (-22.60, 15.00, "Namib edge, NA"), (9.60, 76.40, "Kerala backwaters, IN"),
    (26.90, 75.20, "Rajasthan countryside, IN"), (15.20, 104.00, "Isan rice fields, TH"), (21.30, 105.40, "Red river delta, VN"),
    (36.30, 138.30, "Nagano countryside, JP"), (36.70, 128.60, "Gyeongbuk hills, KR"), (-33.80, 147.00, "NSW wheatbelt, AU"),
    (-43.90, 170.50, "Canterbury high country, NZ"), (-45.50, -70.90, "Patagonian steppe, AR"), (-15.80, -47.60, "Cerrado, BR"),
    (-13.30, -72.00, "Sacred valley, PE"), (17.00, -96.60, "Oaxaca valleys, MX"), (41.50, -93.50, "Iowa farmland, US"),
    (34.20, -111.50, "Arizona rim country, US"), (44.10, -73.00, "Vermont forest, US"), (51.10, -115.50, "Alberta foothills, CA"),
    (64.00, -20.50, "South Iceland, IS"), (47.50, 106.50, "Mongolian steppe, MN"), (57.00, 60.50, "Ural taiga, RU"),
    (-25.30, -57.30, "Paraguayan chaco edge, PY"),
]

BAD = re.compile(r"map|diagram|logo|svg|plan|coat.of.arms|flag|sign|plaque|church|cathedral|station|museum|interior|"
                 r"portrait|statue|monument|bridge|castle|tower|stadium|airport|aerial|satellite|panorama.*stitch", re.I)


def find_photo(lat, lon, cache_dir, rng):
    key = f"{lat:.2f}_{lon:.2f}"
    meta_p = os.path.join(cache_dir, key + ".json")
    if os.path.exists(meta_p):
        m = json.load(open(meta_p))
        if m and os.path.exists(m["path"]):
            return m
    r = requests.get(API, headers=UA, timeout=30, params={
        "action": "query", "list": "geosearch", "gscoord": f"{lat}|{lon}", "gsradius": 10000, "gslimit": 50,
        "gsnamespace": 6, "format": "json"}).json()
    hits = [h for h in r.get("query", {}).get("geosearch", []) if h["title"].lower().endswith((".jpg", ".jpeg"))
            and not BAD.search(h["title"])]
    rng.shuffle(hits)
    for h in hits[:12]:
        ii = requests.get(API, headers=UA, timeout=30, params={
            "action": "query", "titles": h["title"], "prop": "imageinfo", "iiprop": "url|mime|size",
            "iiurlwidth": 1280, "format": "json"}).json()
        page = next(iter(ii["query"]["pages"].values()))
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") != "image/jpeg" or info.get("width", 0) < 900 or info.get("height", 0) < 500:
            continue
        url = info.get("thumburl") or info.get("url")
        img = requests.get(url, headers=UA, timeout=60)
        if img.status_code != 200:
            continue
        im = Image.open(io.BytesIO(img.content)).convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)  # re-encode: drops EXIF/GPS and any embedded caption
        path = os.path.join(cache_dir, key + ".jpg")
        open(path, "wb").write(buf.getvalue())
        m = {"path": path, "lat": h["lat"], "lon": h["lon"], "title": h["title"]}
        json.dump(m, open(meta_p, "w"))
        time.sleep(0.5)
        return m
    json.dump(None, open(meta_p, "w"))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="bench.json")
    ap.add_argument("--n", type=int, default=len(POINTS))
    ap.add_argument("--model", default="streetclip")
    ap.add_argument("--cache", default=os.path.expanduser("~/.geolens_bench"))
    ap.add_argument("--models-dir", default=os.path.expanduser("~/.geolens_models"))
    args = ap.parse_args()
    os.makedirs(args.cache, exist_ok=True)
    rng = random.Random(42)
    engine = VisionEngine(args.model, args.models_dir)
    assert engine.load(), engine.error
    settings = {"online": False, "reverse_auto": False, "geocode_ocr": False, "attention": False, "lens_auto": False}
    rows = []
    for lat, lon, name in POINTS[: args.n]:
        try:
            m = find_photo(lat, lon, args.cache, rng)
        except Exception as e:
            print(f"[skip] {name}: {e}", flush=True)
            continue
        if not m:
            print(f"[skip] {name}: no suitable photo", flush=True)
            continue
        truth_cc = (gz.nearest_city(m["lat"], m["lon"]) or {}).get("cc")
        t0 = time.time()
        log = AnalysisLog()
        res = Analyzer(engine, settings).run(open(m["path"], "rb").read(), os.path.basename(m["path"]), log)
        L = res["location"]
        d = gz.haversine_km(m["lat"], m["lon"], L["lat"], L["lon"])
        top3 = [c["iso"] for c in res["countries"][:3]]
        regs = (res.get("heat") or {}).get("regions", [])[:5]
        in_heat = any(gz.haversine_km(m["lat"], m["lon"], r["lat"], r["lon"]) <= 300 for r in regs)
        row = {"name": name, "truth": [m["lat"], m["lon"]], "truth_cc": truth_cc, "pred": [L["lat"], L["lon"]],
               "pred_cc": L["iso"], "km": round(d, 1), "top3": top3, "conf": L["confidence"], "in_top5_regions": in_heat,
               "scene": (res.get("landscape") or {}).get("composition", {}).get("family_label"),
               "species": [s["label"] for s in (res.get("landscape") or {}).get("species", [])][:3],
               "climate": [c["code"] for c in (res.get("landscape") or {}).get("climate", [])][:2],
               "secs": round(time.time() - t0, 1), "title": m["title"]}
        rows.append(row)
        print(f"{name:34s} truth {truth_cc} pred {L['iso']} top3 {top3} {d:8.0f} km  heat {'Y' if in_heat else '-'}  "
              f"scene={row['scene']} species={row['species']} climate={row['climate']} ({row['secs']}s)", flush=True)

    km = [r["km"] for r in rows]
    n = len(rows)
    if not n:
        print("no rows")
        return
    summ = {
        "n": n,
        "country_top1": round(sum(r["truth_cc"] == r["pred_cc"] for r in rows) / n, 3),
        "country_top3": round(sum(r["truth_cc"] in r["top3"] for r in rows) / n, 3),
        "median_km": round(statistics.median(km), 1),
        "within_25km": round(sum(k <= 25 for k in km) / n, 3), "within_200km": round(sum(k <= 200 for k in km) / n, 3),
        "within_750km": round(sum(k <= 750 for k in km) / n, 3), "within_2500km": round(sum(k <= 2500 for k in km) / n, 3),
        "truth_in_top5_regions": round(sum(r["in_top5_regions"] for r in rows) / n, 3),
        "geoguessr_mean": round(statistics.mean(5000 * math.exp(-k / 1492.7) for k in km)),
    }
    json.dump({"summary": summ, "rows": rows}, open(args.out, "w"), indent=2)
    md = ["## GeoLens blind landscape benchmark", "", "Online techniques OFF (no reverse search) · EXIF stripped · Commons photos near rural points", "",
          "| metric | value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in summ.items()] + [
          "", "| place | truth | pred | top-3 | km | heat top-5 | scene | species | climate |", "|---|---|---|---|---|---|---|---|---|"] + [
          f"| {r['name']} | {r['truth_cc']} | {r['pred_cc']} | {' '.join(r['top3'])} | {r['km']:.0f} | {'✓' if r['in_top5_regions'] else ''} | "
          f"{r['scene']} | {', '.join(r['species'])} | {', '.join(r['climate'])} |" for r in rows]
    text = "\n".join(md)
    print("\n" + text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write(text + "\n")
    print("SUMMARY_JSON " + json.dumps(summ))


if __name__ == "__main__":
    main()
