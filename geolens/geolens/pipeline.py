"""Analysis pipeline: runs every technique, fuses the evidence, writes the reasoning."""
from __future__ import annotations

import base64
import io
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from . import exif as exif_mod
from . import gazetteer as gz
from . import ocr as ocr_mod
from . import reverse as rev
from . import sun as sun_mod
from .knowledge import PROBES
from .log import AnalysisLog

DEFAULT_SETTINGS = {"model": "streetclip", "online": True, "reverse_auto": True, "ocr": True,
                    "attention": True, "geocode_ocr": True}


def _thumb_b64(img: Image.Image, side: int = 1400) -> str:
    im = img.copy()
    im.thumbnail((side, side))
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _image_stats(img: Image.Image) -> dict:
    a = np.asarray(img.convert("RGB").resize((256, 256))).astype(np.float32)
    lum = (0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2])
    sky = a[:85]
    return {"brightness": round(float(lum.mean()), 1), "contrast": round(float(lum.std()), 1),
            "sky_blue": round(float((sky[..., 2] - sky[..., 0]).mean()), 1),
            "green_ratio": round(float(((a[..., 1] > a[..., 0] + 10) & (a[..., 1] > a[..., 2])).mean()), 3)}


class Analyzer:
    def __init__(self, engine, settings: dict | None = None):
        self.engine = engine
        self.settings = dict(DEFAULT_SETTINGS, **(settings or {}))

    def run(self, data: bytes, filename: str, log: AnalysisLog) -> dict[str, Any]:
        S = self.settings
        out: dict[str, Any] = {"filename": filename, "started": datetime.now(timezone.utc).isoformat()}
        evidence: list[dict] = []  # {source, label, countries, weight, explain}

        # ---------------------------------------------------------------- load
        log.set_stage("Reading image", 0.03)
        img = Image.open(io.BytesIO(data))
        meta = exif_mod.read_metadata(img)
        img = ImageOps.exif_transpose(img).convert("RGB")
        work = img.copy()
        work.thumbnail((1280, 1280))
        out["image"] = {"w": img.size[0], "h": img.size[1], "work_w": work.size[0], "work_h": work.size[1],
                        "bytes": len(data), "src": _thumb_b64(work)}
        out["stats"] = _image_stats(work)
        log.add("input", f"Loaded {filename} ({img.size[0]}×{img.size[1]}, {len(data)//1024} KB)",
                method="Pillow decode + EXIF orientation fix", detail=f"Working copy {work.size[0]}×{work.size[1]}",
                data=out["stats"],
                teach="Large photos are downscaled for the neural models, but the full-resolution original is kept "
                      "for OCR so small text stays readable.")

        # ---------------------------------------------------------------- metadata
        log.set_stage("Reading metadata", 0.06)
        out["meta"] = meta
        if meta["gps"]:
            g = meta["gps"]
            nc = gz.nearest_city(g["lat"], g["lon"])
            log.add("metadata", f"GPS coordinates embedded in EXIF: {g['lat']:.5f}, {g['lon']:.5f}",
                    method="EXIF GPS IFD parsing", level="success",
                    detail=f"Nearest known city: {nc['name']} ({nc['cc']}), {nc['dist_km']} km" if nc else "",
                    data=g, teach="Phones write GPS coordinates into the photo unless the app strips them (most social "
                                  "networks do). Always check metadata first — it can solve the case instantly, but it "
                                  "can also be edited, so cross-check it against visual clues.")
        else:
            log.add("metadata", "No GPS in metadata" + (" (EXIF present)" if meta["has_exif"] else " (no EXIF — likely stripped by a platform or screenshot)"),
                    method="EXIF GPS IFD parsing", level="muted",
                    data={k: meta["raw"].get(k) for k in ("Make", "Model", "Software", "DateTimeOriginal") if meta["raw"].get(k)},
                    teach="Missing EXIF is normal for images downloaded from social media; the camera model, software "
                          "and timestamp, if present, are still useful (time → sun position).")
        if meta.get("datetime"):
            log.add("metadata", f"Capture time: {meta['datetime']['local']}" + (f" (UTC {meta['datetime']['utc']})" if meta['datetime'].get('utc') else " (time zone unknown)"),
                    method="EXIF DateTimeOriginal / OffsetTime", data=meta["datetime"],
                    teach="The capture time feeds the sun-position checks below. Without a time-zone offset the "
                          "clock time is local time at the (unknown) place.")

        # ---------------------------------------------------------------- vision
        vis = None
        all_isos = sorted(gz.countries())
        log.set_stage("Loading vision model", 0.1)
        if self.engine is not None:
            if not self.engine.ready:
                log.add("vision", "Loading vision model (first run downloads it once, no account needed)",
                        method=self.engine.model_key, level="muted")
            ok = self.engine.load()
            if not ok:
                log.add("vision", "Vision model unavailable — continuing with OCR, metadata and reverse search",
                        detail=self.engine.error or "", level="warn")
        if self.engine is not None and self.engine.ready:
            log.set_stage("Visual geolocation", 0.2)
            with log.timer("vision", "Vision analysis complete", method="StreetCLIP pipeline") as t:
                vis = self.engine.analyze(work, log)
            if vis:
                all_isos = self.engine.country_isos

        # ---------------------------------------------------------------- OCR
        ocr_items, ocr_clues = [], []
        if S["ocr"]:
            log.set_stage("Reading text (OCR)", 0.45)
            ocr_img = img.copy()
            ocr_img.thumbnail((2200, 2200))
            with log.timer("ocr", "Text recognition", method="RapidOCR (PP-OCRv4 detector + recogniser, ONNX)",
                           teach=ocr_mod.TEACH) as t:
                ocr_items = ocr_mod.run_ocr(ocr_img)
                sx = work.size[0] / ocr_img.size[0]
                for it in ocr_items:
                    it["box"] = [int(v * sx) for v in it["box"]]
                t.detail = f"{len(ocr_items)} text regions: " + " | ".join(i["text"] for i in ocr_items[:15])
                t.data = ocr_items[:60]
            ocr_clues = ocr_mod.extract_clues(ocr_items, all_isos)
            for c in ocr_clues:
                log.add("ocr", f"Text clue [{c['kind']}]: {c['text']}", method="Rule-based linguistic analysis",
                        detail=c["explain"], data={"countries": c["countries"][:30]}, level="success",
                        teach={"phone": "Dialling prefixes are assigned per country by the ITU.",
                               "domain": "ccTLDs (.de, .br, .jp) are assigned per country; local businesses use them.",
                               "street-word": "The generic part of a street name is in the local language.",
                               "script": "Writing systems are tied to languages and countries.",
                               "currency": "Prices reveal the local currency.",
                               "diacritic": "Accented letters are orthography-specific.",
                               "place-name": "A readable toponym is the strongest text clue — check that it is a "
                                             "location sign and not, e.g., a brand named after a city.",
                               "word": "Everyday shop/street vocabulary reveals the language."}.get(c["kind"], ""))
                evidence.append({"source": "Text (OCR)", "label": f"{c['kind']}: {c['text']}", "countries": c["countries"],
                                 "weight": c["weight"], "explain": c["explain"], "place": c.get("place")})
        out["ocr"] = {"items": ocr_items, "clues": ocr_clues}

        # ---------------------------------------------------------------- geocode OCR lines online
        geocoded: list[dict] = []
        if S["online"] and S["geocode_ocr"] and ocr_items:
            lines = [i["text"] for i in ocr_items if len(i["text"]) >= 5 and re.search(r"[A-Za-zÀ-ž]{4,}", i["text"])
                     and sum(ch.isalpha() for ch in i["text"]) >= 0.6 * len(i["text"].replace(" ", ""))]
            street_lines = [l for l in lines if any(w in ocr_mod._strip(l) for w in ("str", "rua", "rue", "calle", "via ", "road", "street", "avenue", "avenida", "jalan", "ulica", "platz", "plaza", "piazza", "straat", "gatan", "vej", "katu", "sokak", "cadde"))]
            for q in (street_lines + [l for l in lines if l not in street_lines])[:3]:
                with log.timer("geocode", f"Geocoded OCR text '{q}'", method="OpenStreetMap Nominatim (free, no key)",
                               teach="Free-text geocoding asks OpenStreetMap where a name exists. Ambiguous names "
                                     "return many places, so results are only trusted when they agree with the "
                                     "country evidence.") as t:
                    hits = rev.nominatim(q)
                    t.detail = "; ".join(f"{h['name'][:80]} ({h['lat']:.3f},{h['lon']:.3f})" for h in hits) or "no match"
                    for h in hits[:2]:
                        h["query"] = q
                        geocoded.append(h)
        out["geocoded"] = geocoded

        # ---------------------------------------------------------------- reverse image search
        reverse_out: dict[str, Any] = {"engines": {}, "manual": rev.MANUAL, "places": []}
        if S["online"] and S["reverse_auto"]:
            log.set_stage("Reverse image search (Yandex)", 0.6)
            with log.timer("reverse", "Yandex reverse image search", method="Yandex CBIR upload + result parsing (no key)",
                           teach=rev.TEACH) as t:
                y = rev.yandex(work)
                reverse_out["engines"]["yandex"] = y
                t.detail = f"{len(y['results'])} matching pages, {len(y['tags'])} tags" + (" — captcha shown, open manually" if y.get("captcha") else "")
                t.data = {"url": y["url"], "tags": y["tags"], "top": y["results"][:8]}
            y = reverse_out["engines"].get("yandex")
            if y:
                txt = " ".join(r["title"] + " " + r.get("snippet", "") for r in y["results"]) + " " + " ".join(y["tags"])
                places = gz.find_places(txt, min_pop=20000)
                reverse_out["places"] = places[:12]
                if places:
                    log.add("reverse", "Place names found in Yandex matches", method="Gazetteer matching on result titles/snippets",
                            detail=", ".join(f"{p['name']} ({p['cc']}) ×{p['hits']}" for p in places[:8]), level="success",
                            teach="When several unrelated pages that show similar images mention the same place, that "
                                  "place is very likely correct — frequency across independent sources is the signal.")
                    cc_hits = Counter()
                    for p in places[:10]:
                        cc_hits[p["cc"]] += p["hits"]
                    total = sum(cc_hits.values())
                    for cc, n in cc_hits.most_common(3):
                        evidence.append({"source": "Reverse search", "label": f"{gz.country_name(cc)} mentioned {n}× in Yandex matches",
                                         "countries": [cc], "weight": 2.2 * n / total, "explain": "Visually similar images on the web are captioned with this place."})
            log.set_stage("Reverse image search (TinEye)", 0.68)
            with log.timer("reverse", "TinEye exact-copy search", method="TinEye upload (no key)") as t:
                te = rev.tineye(work)
                reverse_out["engines"]["tineye"] = te
                t.detail = f"{te.get('total') or len(te['results'])} exact copies found"
        out["reverse"] = reverse_out

        # ---------------------------------------------------------------- fusion
        log.set_stage("Fusing evidence", 0.75)
        out.update(self._fuse(vis, evidence, meta, geocoded, reverse_out, all_isos, log))

        # ---------------------------------------------------------------- attention maps
        if vis and S["attention"]:
            log.set_stage("Computing attention maps", 0.85)
            maps = []
            top_iso = out["countries"][0]["iso"]
            from .vision import MODELS
            q = MODELS[self.engine.model_key]["prompt"].format(gz.country_name(top_iso))
            with log.timer("attention", f"Attention map for '{gz.country_name(top_iso)}'",
                           method="Grad-CAM for Vision Transformers (gradient × activation, last block)",
                           teach="The gradient of the image–text similarity with respect to each image patch shows "
                                 "which patches pushed the model towards the answer. Bright areas are what the "
                                 "model 'looked at'. Use it to verify the model relied on real clues (buildings, "
                                 "signs, vegetation) and not on artefacts like watermarks.") as t:
                m = self.engine.saliency(work, q)
                if m:
                    maps.append({"label": f"Country: {gz.country_name(top_iso)}", **m})
                    t.detail = "Most attended regions: " + ", ".join(f"{r['region']} {r['share']*100:.0f}%" for r in m["regions"][:3])
                    t.data = m["regions"]
            for p in vis["probes"]:
                if p["detected"] and p["id"] in ("architecture", "script", "vegetation") and p["countries"]:
                    opt_prompt = next(o["prompt"] for g in PROBES if g["id"] == p["id"]
                                      for o in g["options"] if o["label"] == p["label"])
                    with log.timer("attention", f"Attention map for clue '{p['label']}'",
                                   method="Grad-CAM for Vision Transformers") as t:
                        m = self.engine.saliency(work, opt_prompt)
                        if m:
                            maps.append({"label": f"{p['title']}: {p['label']}", **m})
                            t.detail = "Most attended regions: " + ", ".join(f"{r['region']} {r['share']*100:.0f}%" for r in m["regions"][:3])
            out["attention"] = maps

        # ---------------------------------------------------------------- sun
        log.set_stage("Sun & shadow checks", 0.93)
        out["sun"] = self._sun(meta, out, log)
        out["vision"] = {"views": vis["views"], "probes": vis["probes"]} if vis else None
        out["model"] = None if self.engine is None else {"key": self.engine.model_key, "status": self.engine.status,
                                                          "error": self.engine.error}
        log.set_stage("Done", 1.0)
        return out

    # =================================================================== fusion
    def _fuse(self, vis, evidence, meta, geocoded, reverse_out, all_isos, log) -> dict:
        isos = list(all_isos)
        idx = {iso: i for i, iso in enumerate(isos)}
        if vis:
            prior = np.array([vis["country_probs"].get(i, 1e-6) for i in isos])
        else:
            prior = np.ones(len(isos))
        prior = prior / prior.sum()
        logp = np.log(prior + 1e-9)
        contributions: dict[str, list] = {}

        if vis:
            for p in vis["probes"]:
                if p["detected"] and p["countries"] and p["weight"] > 0:
                    evidence.append({"source": "Visual clue", "label": f"{p['title']}: {p['label']}",
                                     "countries": p["countries"], "weight": p["weight"] * p["prob"],
                                     "explain": p["explain"] or p["teach"].split(". ")[0] + "."})
        for e in evidence:
            if not e["countries"]:
                continue
            boost = np.zeros(len(isos))
            for c in e["countries"]:
                if c in idx:
                    boost[idx[c]] = e["weight"]
            logp += boost
        post = np.exp(logp - logp.max())
        post /= post.sum()

        if meta.get("gps"):  # hard evidence
            g = meta["gps"]
            nc = gz.nearest_city(g["lat"], g["lon"])
            if nc and nc["cc"] in idx:
                post = post * 0.02
                post[idx[nc["cc"]]] += 0.98
        order = np.argsort(-post)
        countries = []
        for j in order[:8]:
            iso = isos[j]
            sup = [e["label"] for e in evidence if iso in e["countries"]]
            countries.append({"iso": iso, "name": gz.country_name(iso), "prob": float(post[j]),
                              "visual": float(prior[j]) if vis else None, "support": sup[:8]})
        log.add("fusion", "Evidence fusion → " + ", ".join(f"{c['name']} {c['prob']*100:.1f}%" for c in countries[:4]),
                method="Naïve-Bayes style log-linear fusion: log P = log P_visual + Σ weight·[country ∈ clue]",
                data=[{"source": e["source"], "label": e["label"], "weight": round(e["weight"], 2), "n_countries": len(e["countries"])} for e in evidence],
                teach="Each independent clue multiplies the odds of the countries it supports. Strong, narrow clues "
                      "(a phone prefix, a script used in one country) move the result a lot; broad clues (white "
                      "road lines, 'temperate forest') only nudge it. This mirrors how human geolocators "
                      "eliminate countries step by step.")

        # ---- location
        top = [(c["iso"], c["prob"]) for c in countries[:3] if c["prob"] > 0.03] or [(countries[0]["iso"], countries[0]["prob"])]
        extra = [e["place"] for e in evidence if e.get("place")] + reverse_out.get("places", [])
        cities = []
        if vis:
            cities = self.engine.refine_cities(vis["img_e"], top, extra, log)
        else:
            for iso, p in top:
                for c in gz.cities_of(iso, 3):
                    cities.append(dict(c, score=p / 3))
        loc = None
        method = ""
        if meta.get("gps"):
            g = meta["gps"]
            loc = {"lat": g["lat"], "lon": g["lon"], "radius_km": 0.05, "source": "EXIF GPS"}
            method = "Embedded GPS coordinates"
        else:
            # text place names / geocodes that agree with the top country are strongest
            topc = countries[0]["iso"]
            text_places = [e["place"] for e in evidence if e.get("place") and e["place"]["type"] == "city" and e["place"]["cc"] == topc]
            geo_ok = [g for g in geocoded if g["cc"] == topc]
            rev_ok = [p for p in reverse_out.get("places", []) if p["type"] == "city" and p["cc"] == topc and p["hits"] >= 2]
            if geo_ok:
                g = geo_ok[0]
                loc = {"lat": g["lat"], "lon": g["lon"], "radius_km": 5, "source": f"Geocoded sign text '{g['query']}'"}
                method = "OCR text geocoded with OpenStreetMap, consistent with country evidence"
            elif rev_ok:
                p = rev_ok[0]
                loc = {"lat": p["lat"], "lon": p["lon"], "radius_km": 25, "source": f"Reverse-search matches mention {p['name']}"}
                method = "Place named repeatedly in reverse-image-search matches"
            elif text_places:
                p = text_places[0]
                loc = {"lat": p["lat"], "lon": p["lon"], "radius_km": 30, "source": f"Place name '{p['name']}' read in the image"}
                method = "Place name read by OCR"
            elif cities:
                cc = [c for c in cities if c["cc"] == topc][:3] or cities[:1]
                w = np.array([c["score"] for c in cc])
                w = w / w.sum()
                lat = float(sum(c["lat"] * wi for c, wi in zip(cc, w)))
                lon = float(sum(c["lon"] * wi for c, wi in zip(cc, w)))
                spread = max([gz.haversine_km(lat, lon, c["lat"], c["lon"]) for c in cc] + [0])
                if spread > 600:  # candidates disagree: pick the best one instead of averaging into nowhere
                    lat, lon = cc[0]["lat"], cc[0]["lon"]
                area = gz.countries()[topc]["area"] or 1e5
                radius = min(max(60, math.sqrt(area) * 0.35 * (1.3 - countries[0]["prob"])), 1500)
                loc = {"lat": round(lat, 4), "lon": round(lon, 4), "radius_km": round(radius), "source": "Visual similarity to cities"}
                method = "Weighted centre of the most similar cities in the top country"
            else:
                c = gz.countries()[topc]
                loc = {"lat": c["lat"], "lon": c["lon"], "radius_km": 800, "source": "Country centre"}
                method = "Population-weighted centre of the most likely country"
        nc = gz.nearest_city(loc["lat"], loc["lon"])
        loc["nearest_city"] = nc
        loc["country"] = countries[0]["name"]
        loc["iso"] = countries[0]["iso"]
        loc["method"] = method
        conf = countries[0]["prob"]
        if meta.get("gps"):
            conf = 0.99
        loc["confidence"] = round(float(conf), 3)
        loc["confidence_label"] = ("Very high" if conf > 0.85 else "High" if conf > 0.6 else "Medium" if conf > 0.35 else "Low")
        log.add("fusion", f"Final estimate: {nc['name'] if nc else ''}, {loc['country']} ({loc['lat']:.4f}, {loc['lon']:.4f}) ±{loc['radius_km']} km",
                method=method, level="success", data=loc,
                teach="The pin is placed with the most specific trustworthy evidence available, in this order: "
                      "GPS metadata → geocoded sign text → places repeated across reverse-search hits → place names "
                      "read in the image → visual similarity to cities. The circle is the uncertainty radius.")
        reasoning = self._reasoning(loc, countries, evidence, vis, meta)
        return {"location": loc, "countries": countries, "cities": [
            {k: c[k] for k in ("name", "cc", "lat", "lon", "pop", "score") if k in c} for c in cities[:8]],
            "evidence": [{k: v for k, v in e.items() if k != "place"} for e in evidence], "reasoning": reasoning}

    def _reasoning(self, loc, countries, evidence, vis, meta) -> list[str]:
        out = []
        c0 = countries[0]
        city = loc["nearest_city"]["name"] if loc.get("nearest_city") else ""
        out.append(f"The image was most likely taken in {c0['name']}" + (f", near {city}" if city else "") +
                   f" — {loc['confidence_label'].lower()} confidence ({c0['prob']*100:.0f}%).")
        if meta.get("gps"):
            out.append("The photo carries GPS coordinates in its metadata, which settles the location (verify that "
                       "visual clues agree, metadata can be forged).")
        if vis:
            scene = next((p for p in vis["probes"] if p["id"] == "scene"), None)
            if scene and scene["detected"]:
                out.append(f"Scene: {scene['label'].lower()}.")
            strong = [p for p in vis["probes"] if p["detected"] and p["weight"] > 0 and p["countries"]]
            strong.sort(key=lambda p: -p["weight"] * p["prob"])
            for p in strong[:5]:
                inside = c0["iso"] in p["countries"]
                out.append(f"{p['title']}: {p['label']}" + (f" — {p['explain']}" if p["explain"] else "") +
                           (f" This is consistent with {c0['name']}." if inside else f" (Note: atypical for {c0['name']}.)"))
            best_view = max(vis["views"], key=lambda v: v.get("share_of_top", 0))
            out.append(f"The '{best_view['view']}' part of the picture contributed most to the country decision "
                       f"({best_view['share_of_top']*100:.0f}% of the weight).")
        txt = [e for e in evidence if e["source"] == "Text (OCR)"]
        if txt:
            out.append("Text in the image: " + "; ".join(e["explain"].rstrip(". ") for e in txt[:4]) + ".")
        rv = [e for e in evidence if e["source"] == "Reverse search"]
        if rv:
            out.append("Reverse image search: " + "; ".join(e["label"] for e in rv))
        if len(countries) > 1 and countries[1]["prob"] > 0.08:
            out.append(f"Alternative: {countries[1]['name']} ({countries[1]['prob']*100:.0f}%)" +
                       (f", then {countries[2]['name']} ({countries[2]['prob']*100:.0f}%)." if len(countries) > 2 else "."))
        return out

    # =================================================================== sun
    def _sun(self, meta, out, log) -> dict:
        loc = out["location"]
        res: dict[str, Any] = {"teach": sun_mod.TEACH, "location": {"lat": loc["lat"], "lon": loc["lon"]}}
        dt = meta.get("datetime")
        utc = None
        if dt and dt.get("utc"):
            utc = datetime.fromisoformat(dt["utc"])
            res["time_basis"] = "EXIF time with UTC offset"
        elif dt:
            tzname = (loc.get("nearest_city") or {}).get("tz")
            try:
                from zoneinfo import ZoneInfo
                local = datetime.fromisoformat(dt["local"]).replace(tzinfo=ZoneInfo(tzname))
                utc = local.astimezone(timezone.utc)
                res["time_basis"] = f"EXIF local time interpreted in {tzname} (estimated location's time zone)"
            except Exception:
                utc = None
        if utc:
            sp = sun_mod.solar_position(loc["lat"], loc["lon"], utc)
            times = sun_mod.sun_times(loc["lat"], loc["lon"], utc)
            res.update({"utc": utc.isoformat(), "position": sp, "times": times})
            bright = out["stats"]["brightness"]
            consistent = (sp["elevation"] > -6) == (bright > 70)
            res["consistent"] = consistent
            log.add("sun", f"Sun at capture time: elevation {sp['elevation']:.1f}°, azimuth {sp['azimuth']:.0f}°",
                    method="NOAA solar position algorithm", level="info" if consistent else "warn",
                    detail=(f"Shadows should point to bearing {sp['shadow_bearing']:.0f}° and be {sp['shadow_ratio']}× object height. "
                            if sp["shadow_ratio"] else "Sun below horizon. ") +
                           ("Image brightness is consistent with this." if consistent else
                            "Image brightness does NOT match the sun position → wrong time zone, edited timestamp, or a different location."),
                    data=res, teach=sun_mod.TEACH)
        else:
            log.add("sun", "No capture time — use the Sun & Shadow tool to measure a shadow manually",
                    method="NOAA solar position algorithm", level="muted", teach=sun_mod.TEACH)
        return res

