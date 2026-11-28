"""GeoLens analysis pipeline.

Stages
  1. Image prep       EXIF · orientation · mirror detection (selfies) · person masking · scene crops
  2. Text             multi-pass OCR (normal/mirrored, zoomed tiles) → linguistic + venue/brand clues
  3. Vision           StreetCLIP country model on masked views · worldwide landmark & skyline match ·
                      12 clue-probe families · city refinement
  4. Online           Yandex on every scene crop + sign crops · Google Lens · TinEye · Nominatim · Wikipedia
  5. Fusion           country posterior (log-linear) + spatial clustering of every location candidate
  6. Explain          attention maps, sun geometry, reasoning text, full teaching log
"""
from __future__ import annotations

import base64
import io
import math
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from . import exif as exif_mod
from . import gazetteer as gz
from . import landmarks as lm
from . import landscape as ls
from . import ocr as ocr_mod
from . import person as person_mod
from . import reverse as rev
from . import sun as sun_mod
from .knowledge import PROBES
from .log import AnalysisLog

DEFAULT_SETTINGS = {"model": "streetclip", "online": True, "reverse_auto": True, "ocr": True,
                    "attention": True, "geocode_ocr": True, "lens_auto": True, "semi_manual": False}

OCR_TEACH = {
    "phone": "Dialling prefixes are assigned per country by the ITU.",
    "domain": "ccTLDs (.de, .br, .jp) are assigned per country; local businesses use them.",
    "street-word": "The generic part of a street name is in the local language.",
    "script": "Writing systems are tied to languages and countries.",
    "currency": "Prices reveal the local currency.",
    "diacritic": "Accented letters are orthography-specific.",
    "place-name": "A readable toponym is a strong clue — check it is a location sign, not a brand named after a city.",
    "word": "Everyday shop/street vocabulary reveals the language.",
    "landmark": lm.TEACH,
}


def _b64(img: Image.Image, side: int = 1400, q: int = 86) -> str:
    im = img.copy()
    im.thumbnail((side, side))
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=q)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _image_stats(img: Image.Image) -> dict:
    a = np.asarray(img.convert("RGB").resize((256, 256))).astype(np.float32)
    lum = (0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2])
    return {"brightness": round(float(lum.mean()), 1), "contrast": round(float(lum.std()), 1),
            "night": bool(lum.mean() < 70 and np.percentile(lum, 98) > 150),
            "green_ratio": round(float(((a[..., 1] > a[..., 0] + 10) & (a[..., 1] > a[..., 2])).mean()), 3)}


def _alpha_ratio(t: str) -> float:
    s = t.replace(" ", "")
    return sum(ch.isalpha() for ch in s) / max(1, len(s))


class Analyzer:
    def __init__(self, engine, settings: dict | None = None):
        self.engine = engine
        self.search_image = None
        self._land: dict = {}
        self.focus_crops: list = []
        self.settings = dict(DEFAULT_SETTINGS, **(settings or {}))

    # ======================================================================= run
    def run(self, data: bytes, filename: str, log: AnalysisLog, focus: list | None = None,
            focus_space: str = "original") -> dict[str, Any]:
        S = self.settings
        out: dict[str, Any] = {"filename": filename, "started": datetime.now(timezone.utc).isoformat()}
        evidence: list[dict] = []
        cands: list[dict] = []  # location candidates {lat, lon, w, prec, label, source, cc}

        # ------------------------------------------------------------ 1. load + metadata
        log.set_stage("Reading image", 0.02)
        raw = Image.open(io.BytesIO(data))
        meta = exif_mod.read_metadata(raw)
        img = ImageOps.exif_transpose(raw).convert("RGB")
        original = img
        out["stats"] = _image_stats(img)
        log.add("input", f"Loaded {filename} ({img.size[0]}×{img.size[1]}, {len(data)//1024} KB)",
                method="Pillow decode + EXIF orientation", data=out["stats"],
                detail="Night scene detected — night-specific prompts will be used." if out["stats"]["night"] else "",
                teach="Large photos are downscaled for the neural models; OCR runs on a high-resolution copy and on "
                      "zoomed tiles so small rooftop signs stay readable.")
        out["meta"] = meta
        self._log_meta(meta, log, cands, evidence)

        # ------------------------------------------------------------ 2. OCR + mirror detection
        prep: dict[str, Any] = {"mirrored": False}
        ocr_items: list[dict] = []
        ocr_img = img.copy()
        ocr_img.thumbnail((2200, 2200))
        if S["ocr"]:
            log.set_stage("Reading text — normal, mirrored and zoomed tiles", 0.06)
            with log.timer("ocr", "Multi-pass OCR", method="RapidOCR PP-OCRv4 ×(2 orientations × (full + 6 zoomed tiles))",
                           teach=ocr_mod.TEACH + " Front-camera selfies are mirror images, so text is also read "
                                 "flipped; whichever orientation yields real words wins.") as t:
                ocr_items, info = ocr_mod.run_ocr_multi(ocr_img)
                prep.update(info)
                t.detail = f"{len(ocr_items)} text regions · quality normal {info['quality_normal']} vs mirrored {info['quality_mirrored']}: " \
                           + " | ".join(i["text"] for i in ocr_items[:15])
                t.data = ocr_items[:60]
        if prep.get("mirrored"):
            img = ImageOps.mirror(img)
            log.add("prep", "Mirrored image detected (front-camera selfie) — un-mirrored for all further analysis",
                    method="OCR readability comparison, normal vs. horizontally flipped", level="success",
                    detail=f"Readable-text score {prep['quality_normal']} → {prep['quality_mirrored']} when flipped.",
                    teach="Selfie cameras save a mirror image. Mirrored text breaks OCR and reverse image search, "
                          "and it flips driving side and shadow directions. Always un-mirror before analysing.")
        work = img.copy()
        work.thumbnail((1280, 1280))
        sx = work.size[0] / ocr_img.size[0]
        for it in ocr_items:
            it["box"] = [int(v * sx) for v in it["box"]]
        out["image"] = {"w": img.size[0], "h": img.size[1], "work_w": work.size[0], "work_h": work.size[1],
                        "bytes": len(data), "src": _b64(work)}

        # ------------------------------------------------------------ 2b. semi-manual focus regions
        focus_boxes: list[list[int]] = []
        for b in (focus or [])[:6]:
            try:
                x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in b)
            except Exception:
                continue
            if prep.get("mirrored") and focus_space == "original":
                x0, x1 = 1 - x1, 1 - x0
            if x1 - x0 < 0.01 or y1 - y0 < 0.01:
                continue
            focus_boxes.append([int(x0 * work.size[0]), int(y0 * work.size[1]), int(x1 * work.size[0]), int(y1 * work.size[1])])
        out["focus"] = focus_boxes
        if focus_boxes:
            log.set_stage("Deep scan of selected regions", 0.12)
            fx = img.size[0] / work.size[0]
            for k, fb in enumerate(focus_boxes, 1):
                with log.timer("focus", f"Focus region #{k}: high-resolution deep scan",
                               method="Full-resolution crop ×(up-scaling) → OCR · vision views ×3 weight · dedicated reverse searches",
                               teach="Semi-manual mode: the analyst points at the decisive detail (a sign, a building, a "
                                     "mountain ridge, a tree line). That crop is taken from the full-resolution original, "
                                     "up-scaled, read, classified and reverse-searched on its own, and its evidence is "
                                     "weighted above the rest of the frame.") as t:
                    crop = img.crop(tuple(int(v * fx) for v in fb))
                    self.focus_crops.append(crop)
                    items = ocr_mod.run_ocr_robust(crop) if S["ocr"] else []
                    sc = (fb[2] - fb[0]) / crop.size[0]
                    for it in items:
                        bx = it["box"]
                        it["box"] = [int(fb[0] + bx[0] * sc), int(fb[1] + bx[1] * sc), int(fb[0] + bx[2] * sc), int(fb[1] + bx[3] * sc)]
                        it["focus"] = k
                    ocr_items += [i for i in items if not any(i["text"].lower() == o["text"].lower() for o in ocr_items)]
                    t.detail = f"Box {fb} · {len(items)} text region(s)" + (": " + " | ".join(i["text"] for i in items[:8]) if items else "")
                    t.data = {"box": fb, "text": [i["text"] for i in items]}
                    out.setdefault("focus_crops", []).append({"index": k - 1, "box": fb, "src": _b64(crop, 600, 82),
                                                              "text": [i["text"] for i in items]})

        # ------------------------------------------------------------ 3. people
        log.set_stage("Detecting people", 0.14)
        persons = {"faces": [], "persons": [], "area": 0.0}
        with log.timer("prep", "Person / face detection", method="OpenCV Haar cascades (frontal + profile)",
                       teach=person_mod.TEACH) as t:
            persons = person_mod.detect(work)
            t.detail = (f"{len(persons['faces'])} face(s); person covers {persons['area']*100:.0f}% of the frame — "
                        "masked out of the scene" if persons["faces"] else "No prominent person — whole image is scene")
            t.data = persons
        masked = person_mod.masked(work, persons["persons"])
        self.search_image = masked  # used by the manual "open in engine" buttons
        bg_boxes = person_mod.background_boxes(work.size, persons["persons"])
        prep.update(persons=persons["persons"], faces=persons["faces"], person_area=persons["area"],
                    crops=[{"name": n, "box": b} for n, b in bg_boxes])
        if persons["faces"]:
            prep["masked_src"] = _b64(masked, 1000, 80)
        out["prep"] = prep

        # ------------------------------------------------------------ 4. vision
        vis, world = None, []
        all_isos = sorted(gz.countries())
        if self.engine is not None:
            log.set_stage("Loading vision model", 0.18)
            if not self.engine.ready:
                log.add("vision", "Loading vision model (first run downloads it once, no account needed)",
                        method=self.engine.model_key, level="muted")
            if not self.engine.load():
                log.add("vision", "Vision model unavailable — continuing with OCR, metadata and reverse search",
                        detail=self.engine.error or "", level="warn")
        if self.engine is not None and self.engine.ready:
            log.set_stage("Visual geolocation", 0.24)
            focus_views = [(f"Focus #{k}", b, 3.0) for k, b in enumerate(focus_boxes, 1)]
            with log.timer("vision", "Vision analysis complete", method="StreetCLIP on person-masked image + scene crops"
                           + (" + focus regions" if focus_views else "")):
                vis = self.engine.analyze(masked, log, extra_views=focus_views + list(bg_boxes))
            if vis:
                all_isos = self.engine.country_isos
                out["visual_top"] = [k for k, _ in sorted(vis["country_probs"].items(), key=lambda kv: -kv[1])[:5]]
                for g in (vis.get("geocells") or [])[:6]:
                    if g["p"] >= 0.03:
                        cands.append({"lat": g["lat"], "lon": g["lon"], "w": 4.0 * g["p"], "prec": 40, "cc": g["cc"],
                                      "source": "Vision · geocells", "city": g["name"], "label": f"Looks like {g['name']} area ({g['p']*100:.0f}%)"})
                log.set_stage("Matching landmarks & skylines worldwide", 0.36)
                with log.timer("vision", "World landmark pass finished", method="CLIP zero-shot"):
                    world = self.engine.world_places(vis["img_e"], log, night=out["stats"]["night"],
                                                     focus_idx=list(range(1, 1 + len(focus_boxes))))
                for w_ in world[:10]:
                    if w_["p"] < 0.03:
                        continue
                    lmk = w_["type"] == "landmark"
                    cands.append({"lat": w_["lat"], "lon": w_["lon"], "w": (7 if lmk else 5) * w_["p"],
                                  "prec": 1.5 if lmk else 15, "cc": w_["cc"], "source": "Vision · world match", "city": w_["city"],
                                  "label": f"{w_['name']} ({w_['p']*100:.0f}%)"})
                cc_p = Counter()
                for w_ in world:
                    cc_p[w_["cc"]] += w_["p"]
                for cc, p in cc_p.most_common(3):
                    if p > 0.08:
                        evidence.append({"source": "Vision · landmarks/skylines", "label": f"Looks like {gz.country_name(cc)} places ({p*100:.0f}%)",
                                         "countries": [cc], "weight": 1.2 * p,
                                         "explain": "Direct similarity to named places/skylines in that country."})
        out["world"] = [{k: w_[k] for k in ("type", "name", "city", "cc", "lat", "lon", "p")} for w_ in world]

        # ------------------------------------------------------------ 4b. landscape / ecology recon
        log.set_stage("Landscape & ecology recon", 0.4)
        self._land = self._landscape(vis, masked, meta, all_isos, evidence, log)
        out["landscape"] = {k: v for k, v in self._land.items() if k != "factors"}

        # ------------------------------------------------------------ 5. text clues
        ocr_clues = ocr_mod.extract_clues(ocr_items, all_isos) if ocr_items else []
        for c in ocr_clues:
            log.add("ocr", f"Text clue [{c['kind']}]: {c['text']}", method="Rule-based linguistic / venue matching",
                    detail=c["explain"], data={"countries": c["countries"][:30]}, level="success",
                    teach=OCR_TEACH.get(c["kind"], ""))
            evidence.append({"source": "Text (OCR)", "label": f"{c['kind']}: {c['text']}", "countries": c["countries"],
                             "weight": c["weight"], "explain": c["explain"]})
            if c.get("sites"):
                for s_ in c["sites"]:
                    q = s_["quality"]
                    cands.append({"lat": s_["lat"], "lon": s_["lon"], "w": (9 if len(c["sites"]) == 1 else 5) * q,
                                  "prec": 0.4, "cc": s_["cc"], "source": "Sign text · venue", "city": s_["city"],
                                  "label": f"{s_['name']} ({s_['city']})"})
            elif c.get("place"):
                p = c["place"]
                cands.append({"lat": p["lat"], "lon": p["lon"], "w": 2.0 if p["type"] == "city" else 0.6,
                              "prec": 12 if p["type"] == "city" else 400, "cc": p["cc"],
                              "source": "Sign text · place name", "label": p["name"]})
        out["ocr"] = {"items": ocr_items, "clues": ocr_clues}

        # ------------------------------------------------------------ 6. online: reverse search + geocoding
        reverse_out: dict[str, Any] = {"runs": [], "manual": rev.MANUAL, "places": [], "landmarks": [], "phrases": []}
        geocoded: list[dict] = []
        if S["online"]:
            log.set_stage("Reverse image search (Yandex ×N, Lens, TinEye) + geocoding", 0.45)
            geo_queries = self._geo_queries(ocr_items, ocr_clues) if S["geocode_ocr"] else []
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_rev = ex.submit(self._reverse, original, masked, work, bg_boxes, ocr_items, persons, log, focus_boxes, img) if S["reverse_auto"] else None
                f_geo = ex.submit(self._geocode, geo_queries, log) if geo_queries else None
                if f_rev:
                    reverse_out = f_rev.result() or reverse_out
                if f_geo:
                    geocoded = f_geo.result() or []
            # phrases recurring across reverse hits → geocode the best two
            extra_q = [p for p, n in reverse_out.get("phrases", [])
                       if not lm.match_text(p) and not gz.find_places(p)][:2]
            if extra_q and S["geocode_ocr"]:
                geocoded += self._geocode(extra_q, log, source="Reverse-search phrase")
            self._reverse_evidence(reverse_out, evidence, cands, log)
            for g in geocoded:
                cands.append({"lat": g["lat"], "lon": g["lon"], "w": g.get("w", 2.2), "prec": 1.0, "cc": g.get("cc", ""),
                              "source": g["source"], "label": f"{g['query']} → {g['name'][:60]}"})
        else:
            log.add("online", "Online techniques disabled in settings", level="muted")
        reverse_out["manual"] = rev.MANUAL
        out["reverse"] = reverse_out
        out["geocoded"] = geocoded

        # ------------------------------------------------------------ 7. fusion
        log.set_stage("Fusing evidence", 0.8)
        out.update(self._fuse(vis, evidence, cands, meta, all_isos, log))

        # ------------------------------------------------------------ 8. attention
        if vis and S["attention"]:
            log.set_stage("Computing attention maps", 0.88)
            out["attention"] = self._attention(masked, vis, out, world, log)

        # ------------------------------------------------------------ 9. sun
        log.set_stage("Sun & shadow checks", 0.95)
        out["sun"] = self._sun(meta, out, log)
        out["vision"] = {"views": vis["views"], "probes": vis["probes"]} if vis else None
        out["model"] = None if self.engine is None else {"key": self.engine.model_key, "status": self.engine.status,
                                                          "error": self.engine.error}
        log.set_stage("Done", 1.0)
        return out

    # ======================================================================= helpers
    def _log_meta(self, meta, log, cands, evidence):
        if meta["gps"]:
            g = meta["gps"]
            nc = gz.nearest_city(g["lat"], g["lon"])
            cands.append({"lat": g["lat"], "lon": g["lon"], "w": 100, "prec": 0.05, "cc": nc["cc"] if nc else "",
                          "source": "EXIF GPS", "label": f"{g['lat']:.5f}, {g['lon']:.5f}"})
            if nc:
                evidence.append({"source": "Metadata", "label": "EXIF GPS", "countries": [nc["cc"]], "weight": 8,
                                 "explain": "GPS coordinates embedded by the camera."})
            log.add("metadata", f"GPS coordinates embedded in EXIF: {g['lat']:.5f}, {g['lon']:.5f}",
                    method="EXIF GPS IFD parsing", level="success",
                    detail=f"Nearest known city: {nc['name']} ({nc['cc']}), {nc['dist_km']} km" if nc else "", data=g,
                    teach="Phones write GPS into photos unless the app strips it (most social networks do). It can "
                          "solve a case instantly — but it can be edited, so cross-check with visual clues.")
        else:
            log.add("metadata", "No GPS in metadata" + (" (EXIF present)" if meta["has_exif"] else " (no EXIF — stripped by a platform or a screenshot)"),
                    method="EXIF GPS IFD parsing", level="muted",
                    data={k: meta["raw"].get(k) for k in ("Make", "Model", "Software", "DateTimeOriginal") if meta["raw"].get(k)},
                    teach="Missing EXIF is normal for social-media images; camera, software and timestamp still help.")
        if meta.get("datetime"):
            log.add("metadata", f"Capture time: {meta['datetime']['local']}" + (f" (UTC {meta['datetime']['utc']})" if meta['datetime'].get('utc') else " (time zone unknown)"),
                    method="EXIF DateTimeOriginal / OffsetTime", data=meta["datetime"],
                    teach="The capture time feeds the sun-position checks.")

    def _geo_queries(self, ocr_items, ocr_clues) -> list[str]:
        qs: list[str] = []
        for c in ocr_clues:
            if c["kind"] == "landmark" and c.get("sites") and len(c["sites"]) > 1:
                qs.append(c["text"])  # multi-site brand: let OSM list every site, clustering picks one
        for it in sorted(ocr_items, key=lambda i: -i["score"] * len(i["text"])):
            t = re.sub(r"\s+", " ", it["text"]).strip()
            if len(t) >= 6 and _alpha_ratio(t) >= 0.7 and t not in qs:
                qs.append(t)
        return qs[:4]

    def _geocode(self, queries: list[str], log, source: str = "Sign text · geocoded") -> list[dict]:
        out = []
        for q in queries:
            with log.timer("geocode", f"Geocoded '{q}'", method="OpenStreetMap Nominatim + Wikipedia geosearch (no key)",
                           teach="Free-text geocoding asks OpenStreetMap and Wikipedia where a name exists. Ambiguous "
                                 "names return many places; spatial clustering keeps only the ones that agree with "
                                 "the rest of the evidence.") as t:
                hits = []
                try:
                    for h in rev.nominatim(q)[:5]:
                        hits.append(dict(h, query=q, source=source + " (OSM)", w=2.2))
                except Exception as e:
                    t.detail = f"Nominatim: {e}. "
                try:
                    for h in rev.wikipedia_geo(q)[:3]:
                        nc = gz.nearest_city(h["lat"], h["lon"])
                        hits.append(dict(h, query=q, cc=nc["cc"] if nc else "", source=source + " (Wikipedia)", w=1.8))
                except Exception as e:
                    t.detail += f"Wikipedia: {e}."
                t.detail = (t.detail or "") + ("; ".join(f"{h['name'][:70]} ({h['lat']:.3f},{h['lon']:.3f})" for h in hits) or "no match")
                out += hits
        return out

    def _reverse(self, original, masked, work, bg_boxes, ocr_items, persons, log, focus_boxes=(), full=None) -> dict:
        S = self.settings
        queries: list[tuple[str, Image.Image]] = []
        fx = (full.size[0] / work.size[0]) if full is not None else 1.0
        for k, fb in enumerate(focus_boxes, 1):
            src = full if full is not None else work
            crop = src.crop(tuple(int(v * fx) for v in fb))
            if max(crop.size) < 700:
                f = 700 / max(crop.size)
                crop = crop.resize((int(crop.size[0] * f), int(crop.size[1] * f)), Image.LANCZOS)
            queries.append((f"Focus #{k}", crop))
        if persons["faces"]:
            queries.append(("Person-masked image", masked))
            for n, b in sorted(bg_boxes, key=lambda nb: -(nb[1][2] - nb[1][0]) * (nb[1][3] - nb[1][1]))[:4]:
                queries.append((n, masked.crop(tuple(b))))
        else:
            queries.append(("Full image", work))
            w, h = work.size
            queries.append(("Upper half", work.crop((0, 0, w, h // 2))))
            queries.append(("Centre", work.crop((w // 6, h // 6, w * 5 // 6, h * 5 // 6))))
        # crops around readable signs (zoomed) — this is what a human does by hand
        signs = sorted([i for i in ocr_items if len(i["text"]) >= 4], key=lambda i: -i["score"] * len(i["text"]))[:2]
        for it in signs:
            x0, y0, x1, y1 = it["box"]
            bw, bh = x1 - x0, y1 - y0
            pad_x, pad_y = max(bw * 1.2, 120), max(bh * 4, 120)
            box = (int(max(0, x0 - pad_x)), int(max(0, y0 - pad_y)), int(min(work.size[0], x1 + pad_x)), int(min(work.size[1], y1 + pad_y * 1.5)))
            crop = masked.crop(box)
            if max(crop.size) < 700:
                f = 700 / max(crop.size)
                crop = crop.resize((int(crop.size[0] * f), int(crop.size[1] * f)), Image.LANCZOS)
            queries.append((f"Sign '{it['text'][:24]}'", crop))
        log.add("reverse", f"Reverse search plan: {len(queries)} image variants on Yandex"
                + (" + Google Lens" if S.get("lens_auto") else "") + " + TinEye (original)",
                method="Automatic multi-crop reverse image search",
                detail=", ".join(q[0] for q in queries), teach=rev.TEACH + " Searching background-only crops and "
                "zoomed sign crops separately is exactly the manual trick analysts use — GeoLens does it for every image.")

        def done(r):
            n = len(r.get("results", []))
            log.add("reverse", f"{r.get('engine', '?')} · {r['query']}: " + (f"{n} matches" if not r.get("error") else "failed"),
                    method="Key-less web upload + result parsing", detail=r.get("error") or ", ".join(x["title"][:60] for x in r.get("results", [])[:5]),
                    data={"url": r.get("url"), "tags": r.get("tags", [])[:10]}, level="warn" if r.get("error") else "info",
                    ms=r.get("secs", 0) * 1000)

        runs = rev.multi_search(queries, engines=("yandex",), workers=3, on_done=done)
        extra = []
        if S.get("lens_auto"):
            extra.append((queries[0][0], queries[0][1], "lens"))
            for label, im in queries[1:len(focus_boxes)]:
                extra.append((label, im, "lens"))
        extra.append(("Original upload", original, "tineye"))
        for label, im, e in extra:
            runs += rev.multi_search([(label, im)], engines=(e,), workers=1, on_done=done)
        return {"runs": runs}

    def _reverse_evidence(self, R, evidence, cands, log):
        runs = R.get("runs", [])
        titles = []
        for r in runs:
            for x in r.get("results", []):
                titles.append((x.get("title", "") + " " + x.get("snippet", "")).strip())
            titles += r.get("tags", [])
        if not titles:
            return
        # venues / landmarks named in titles
        lm_cnt: Counter = Counter()
        lm_obj: dict[str, list[dict]] = {}
        for t in titles:
            for m in lm.match_text(t, min_ratio=0.9):
                lm_cnt[m["name"]] += 1
                lm_obj.setdefault(m["name"], [])
                if m not in lm_obj[m["name"]]:
                    lm_obj[m["name"]].append(m)
        places = gz.find_places(" . ".join(titles), min_pop=20000)
        phrases = rev.frequent_phrases(titles)
        R["landmarks"] = [{"name": n, "count": c, "sites": [{k: s[k] for k in ("city", "cc", "lat", "lon")} for s in lm_obj[n]]}
                          for n, c in lm_cnt.most_common(10)]
        R["places"] = [{k: p[k] for k in ("name", "cc", "lat", "lon", "hits", "type")} for p in places[:12]]
        R["phrases"] = phrases
        log.add("reverse", f"Aggregated {len(titles)} result titles from {len(runs)} searches",
                method="Venue fuzzy-matching + gazetteer + recurring-phrase mining", level="success" if lm_cnt or places else "info",
                detail=("Venues: " + ", ".join(f"{n} ×{c}" for n, c in lm_cnt.most_common(5)) + ". " if lm_cnt else "")
                       + ("Places: " + ", ".join(f"{p['name']} ({p['cc']}) ×{p['hits']}" for p in places[:6]) + ". " if places else "")
                       + ("Phrases: " + ", ".join(f"“{p}” ×{n}" for p, n in phrases[:6]) if phrases else ""),
                teach="When several independent pages showing similar images name the same venue or place, that is "
                      "close to proof. Frequency across sources is the signal; a single mention is weak.")
        for n, c in lm_cnt.most_common(5):
            sites = lm_obj[n]
            evidence.append({"source": "Reverse search", "label": f"'{n}' named {c}× in matches", "countries": sorted({s['cc'] for s in sites}),
                             "weight": min(4.0, 1.3 * c), "explain": "Pages with visually similar images name this venue."})
            for s in sites:
                cands.append({"lat": s["lat"], "lon": s["lon"], "w": min(14, 3.2 * c) / len(sites), "prec": 0.5, "cc": s["cc"], "city": s["city"],
                              "source": "Reverse search · venue", "label": f"{n} ×{c}"})
        tot = sum(p["hits"] for p in places[:10]) or 1
        cc_hits: Counter = Counter()
        for p in places[:10]:
            cc_hits[p["cc"]] += p["hits"]
            if p["type"] == "city":
                cands.append({"lat": p["lat"], "lon": p["lon"], "w": min(8, 1.6 * p["hits"]), "prec": 12, "cc": p["cc"],
                              "source": "Reverse search · place", "label": f"{p['name']} ×{p['hits']}"})
        for cc, n in cc_hits.most_common(3):
            evidence.append({"source": "Reverse search", "label": f"{gz.country_name(cc)} named {n}× in matches", "countries": [cc],
                             "weight": 2.4 * n / tot, "explain": "Visually similar images on the web are captioned with this place."})

    # ======================================================================= fusion
    def _fuse(self, vis, evidence, cands, meta, all_isos, log) -> dict:
        isos = list(all_isos)
        idx = {iso: i for i, iso in enumerate(isos)}
        prior = np.array([vis["country_probs"].get(i, 1e-6) for i in isos]) if vis else np.ones(len(isos))
        prior = prior / prior.sum()
        if vis:
            for p in vis["probes"]:
                if p["detected"] and p["countries"] and p["weight"] > 0 and p["prob"] >= 0.5:
                    evidence.append({"source": "Visual clue", "label": f"{p['title']}: {p['label']}", "countries": p["countries"],
                                     "weight": 0.3 * p["weight"] * p["prob"], "explain": p["explain"] or p["teach"].split(". ")[0] + "."})

        def posterior(ev):
            logp = np.log(prior + 1e-9)  # benchmark: the visual prior deserves full weight
            for e in ev:
                for c in e["countries"]:
                    if c in idx:
                        logp[idx[c]] += e["weight"]
            post = np.exp(logp - logp.max())
            return post / post.sum()

        post = posterior(evidence)
        # --- landscape region heatmap (probability surface over ~15k places)
        heat = self._heat(vis, {iso: float(post[idx[iso]]) for iso in isos}, cands, log)
        # --- spatial clustering of location candidates
        country_lookup = {iso: float(post[idx[iso]]) for iso in isos}
        for c in cands:  # country posterior acts as a soft prior on candidates
            c["w_eff"] = c["w"] * (0.35 + 0.65 * math.sqrt(country_lookup.get(c["cc"], 0.02)))
        clusters = []
        for c in sorted(cands, key=lambda c: -c["w_eff"]):
            for cl in clusters:
                if gz.haversine_km(cl["lat"], cl["lon"], c["lat"], c["lon"]) <= 35:
                    cl["members"].append(c)
                    cl["score"] += c["w_eff"]
                    break
            else:
                clusters.append({"lat": c["lat"], "lon": c["lon"], "members": [c], "score": c["w_eff"]})
        for cl in clusters:  # bonus for independent sources agreeing
            srcs = {m["source"].split(" · ")[0] for m in cl["members"]}
            cl["sources"] = sorted(srcs)
            cl["score"] *= 1 + 0.35 * (len(srcs) - 1)
        clusters.sort(key=lambda c: -c["score"])
        total = sum(c["score"] for c in clusters) or 1
        best = clusters[0] if clusters else None
        # The winning area feeds back into the country decision ONLY when it contains hard, non-visual evidence
        # (sign text, geocodes, reverse-search venues, GPS). Benchmark round 4: letting purely visual candidates
        # (geocells, heat regions) vote again double-counted the vision model and flipped correct countries.
        hard = best and any(m["prec"] <= 2 and not m["source"].startswith(("Vision", "Landscape")) for m in best["members"])
        if hard:
            cc_best = Counter(m["cc"] for m in best["members"] if m["cc"] and not m["source"].startswith(("Vision", "Landscape"))).most_common(1)
            if cc_best:
                share = best["score"] / total
                evidence.append({"source": "Spatial agreement", "label": f"{len(best['members'])} location clue(s) agree ({', '.join(best['sources'])})",
                                 "countries": [cc_best[0][0]], "weight": min(5.0, 1.2 * len(best["sources"]) + 3 * share),
                                 "explain": "Independent techniques point to the same small area."})
                post = posterior(evidence)
        order = np.argsort(-post)
        countries = []
        for j in order[:8]:
            iso = isos[j]
            sup = [e["label"] for e in evidence if iso in e["countries"]]
            countries.append({"iso": iso, "name": gz.country_name(iso), "prob": float(post[j]),
                              "visual": float(prior[j]) if vis else None, "support": sup[:8]})
        log.add("fusion", "Country fusion → " + ", ".join(f"{c['name']} {c['prob']*100:.1f}%" for c in countries[:4]),
                method="Log-linear fusion: log P = 0.8·log P_visual + Σ weight·[country ∈ clue]",
                data=[{"source": e["source"], "label": e["label"], "weight": round(e["weight"], 2), "n_countries": len(e["countries"])} for e in evidence],
                teach="Each independent clue multiplies the odds of the countries it supports. Narrow clues (a "
                      "venue name, a phone prefix, a unique script) move the result a lot; broad ones only nudge it.")

        topc = countries[0]["iso"]
        best = next((cl for cl in clusters if any(m["cc"] == topc for m in cl["members"])), best)
        if best:
            members = [m for m in best["members"]]
            min_prec = min(m["prec"] for m in members)
            tier = [m for m in members if m["prec"] <= max(min_prec * 3, 0.5)]
            wsum = sum(m["w_eff"] for m in tier)
            lat = sum(m["lat"] * m["w_eff"] for m in tier) / wsum
            lon = sum(m["lon"] * m["w_eff"] for m in tier) / wsum
            spread = max([gz.haversine_km(lat, lon, m["lat"], m["lon"]) for m in tier] + [0])
            radius = max(min_prec, spread * 1.2, 0.3)
            share = best["score"] / total
            precise = min_prec <= 2
            conf = 0.45 * countries[0]["prob"] + 0.35 * share + (0.2 if precise and len(best["sources"]) >= 2 else 0.1 if precise else 0)
            if meta.get("gps"):
                conf = 0.99
            lead = max(members, key=lambda m: m["w_eff"])
            loc = {"lat": round(lat, 5), "lon": round(lon, 5), "radius_km": round(radius, 2),
                   "source": lead["source"], "method": f"Cluster of {len(members)} clues from {', '.join(best['sources'])}; "
                                                        f"pin = weighted centre of the most precise ones ({lead['label']})"}
        else:
            c = gz.countries()[topc]
            loc = {"lat": c["lat"], "lon": c["lon"], "radius_km": 800, "source": "Country centre",
                   "method": "Population-weighted centre of the most likely country"}
            conf = countries[0]["prob"] * 0.6
        nc = gz.nearest_city(loc["lat"], loc["lon"])
        venue = None
        if best:
            vm = [m for m in best["members"] if m["prec"] <= 1.5 and ("venue" in m["source"] or "world" in m["source"])]
            if vm:
                venue = max(vm, key=lambda m: m["w_eff"])["label"].split(" (")[0].split(" ×")[0]
        city_name = None
        if best:
            named = [m for m in best["members"] if m.get("city")]
            if named:
                city_name = max(named, key=lambda m: m["w_eff"])["city"]
        loc.update(nearest_city=nc, city=city_name or (nc["name"] if nc else ""), country=countries[0]["name"], iso=topc, venue=venue,
                   confidence=round(float(min(0.99, conf)), 3))
        c_ = loc["confidence"]
        loc["confidence_label"] = "Very high" if c_ > 0.8 else "High" if c_ > 0.6 else "Medium" if c_ > 0.35 else "Low"
        log.add("fusion", f"Final estimate: {(venue + ', ') if venue else ''}{loc['city']}, {loc['country']} "
                          f"({loc['lat']:.4f}, {loc['lon']:.4f}) ±{loc['radius_km']} km",
                method=loc["method"], level="success", data={k: v for k, v in loc.items() if k != "nearest_city"},
                teach="Every technique proposes points on the map. Points within 35 km are clustered; clusters "
                      "supported by several *independent* techniques (sign text + reverse search + vision) win. "
                      "The pin is the weighted centre of the most precise clues in the winning cluster, and the "
                      "circle reflects their precision and disagreement.")
        cl_out = [{"lat": round(c["lat"], 4), "lon": round(c["lon"], 4), "score": round(c["score"] / total, 3),
                   "sources": c["sources"], "members": [{k: m[k] for k in ("label", "source", "lat", "lon", "prec")} | {"w": round(m["w_eff"], 2)} for m in c["members"][:12]],
                   "name": (gz.nearest_city(c["lat"], c["lon"]) or {}).get("name", "")} for c in clusters[:6]]
        city_rows = []
        if vis:
            top = [(c["iso"], c["prob"]) for c in countries[:3] if c["prob"] > 0.03] or [(topc, 1.0)]
            city_rows = self.engine.refine_cities(vis["img_e"], top, [], log)
        reasoning = self._reasoning(loc, countries, evidence, vis, meta, cl_out)
        return {"location": loc, "countries": countries, "clusters": cl_out, "heat": heat,
                "cities": [{k: c[k] for k in ("name", "cc", "lat", "lon", "pop", "score") if k in c} for c in city_rows[:8]],
                "evidence": evidence, "reasoning": reasoning}

    def _landscape(self, vis, masked, meta, all_isos, evidence, log) -> dict:
        land: dict[str, Any] = {"factors": []}
        with log.timer("landscape", "Spectral analysis of the scene", method="Excess-green index, sky blueness, haze, saturation, soil & dry-grass ratios",
                       teach=ls.TEACH["spectral"]) as t:
            sp = ls.spectral(masked)
            land["spectral"] = sp
            t.detail = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in sp.items() if v is not None)
            t.data = sp
        if not vis:
            return land
        comp = vis.get("composition") or {}
        land["composition"] = comp
        fam = vis.get("family", "mixed")
        img_e = vis["img_e"]
        eng = self.engine
        # species / plant indicators
        p, _ = eng.option_probs(img_e, [x[2] for x in ls.SPECIES], "species")
        order = np.argsort(-p)
        found = []
        for rank, j in enumerate(order[:3]):
            sid, label, prompts, boxes, teach = ls.SPECIES[j]
            nxt = p[order[rank + 1]] if rank + 1 < len(order) else 0
            # calibrated: a species must be clearly above the background of 36 hypotheses (benchmark-tuned)
            if sid == "none" or p[j] < 0.18 or (rank == 0 and p[j] < 1.4 * nxt):
                continue
            found.append({"id": sid, "label": label, "p": round(float(p[j]), 3), "boxes": boxes, "teach": teach,
                          "countries": ls.species_countries(boxes, all_isos)})
        veg_share = sum(comp.get("fractions", {}).get(k, 0) for k in ("trees", "grass", "crops")) if comp else 0.5
        damp = 1.0 if veg_share >= 0.15 else 0.4  # few plants in frame → weaker species evidence
        land["species"] = found
        for f in found[:2]:
            w = 0.4 * f["p"] * damp
            land["factors"].append({"boxes": f["boxes"], "p": min(0.95, f["p"] * 1.6 * damp), "label": f["label"]})
            if f["countries"]:
                evidence.append({"source": "Landscape · species", "label": f"{f['label']} ({f['p']*100:.0f}%)", "countries": f["countries"],
                                 "weight": w, "explain": f["teach"]})
        log.add("landscape", "Plant / tree species indicators: " + (", ".join(f"{f['label']} {f['p']*100:.0f}%" for f in found) or "none distinctive"),
                method=f"CLIP prompt-ensemble over {len(ls.SPECIES)} species with mapped native/cultivated ranges",
                data=[{k: f[k] for k in ("label", "p", "boxes")} for f in found], teach=ls.TEACH["species"],
                level="success" if found else "muted")
        # climate
        pc, _ = eng.option_probs(img_e, [x[2] for x in ls.CLIMATES], "climate")
        oc = np.argsort(-pc)
        cl = [{"code": ls.CLIMATES[j][0], "label": ls.CLIMATES[j][1], "p": round(float(pc[j]), 3), "boxes": ls.CLIMATES[j][3]} for j in oc[:3]]
        land["climate"] = cl
        confident = cl[0]["p"] >= 0.35 and (len(cl) < 2 or cl[0]["p"] >= 1.4 * cl[1]["p"])
        if confident and (fam not in ("indoor", "portrait") or veg_share > 0.1):
            for c in cl[:1]:
                land["factors"].append({"boxes": c["boxes"], "p": min(0.8, c["p"] * 1.2), "label": "Climate " + c["code"], "alpha": 0.7})
                cs = ls.species_countries(c["boxes"], all_isos)
                if cs:
                    evidence.append({"source": "Landscape · climate", "label": f"Köppen {c['code']} {c['label']} ({c['p']*100:.0f}%)",
                                     "countries": cs, "weight": 0.25 * c["p"], "explain": f"Vegetation and light match a {c['label'].lower()} climate."})
        log.add("landscape", ("Climate class: " if confident else "Climate class (not decisive, ignored): ") + ", ".join(f"{c['code']} {c['label']} {c['p']*100:.0f}%" for c in cl),
                method="Köppen-style zero-shot classification → latitude/longitude belts", teach=ls.TEACH["climate"], data=[{k: c[k] for k in ("code", "label", "p")} for c in cl])
        # season → hemisphere
        ps, _ = eng.option_probs(img_e, [x[2] for x in ls.SEASONS], "season")
        js = int(np.argmax(ps))
        season = ls.SEASONS[js][0]
        land["season"] = {"id": season, "label": ls.SEASONS[js][1], "p": round(float(ps[js]), 3)}
        month = None
        dt = meta.get("datetime")
        if dt:
            try:
                month = int(dt["local"][5:7])
            except Exception:
                month = None
        hemi, why = ls.month_hemisphere(season, month) if ps[js] > 0.35 else (None, "")
        land["hemisphere"] = hemi
        if hemi:
            hs = [iso for iso in all_isos if (gz.countries()[iso]["lat"] > 0) == (hemi == "north")]
            evidence.append({"source": "Landscape · season", "label": f"{hemi.title()}ern hemisphere ({why})", "countries": hs, "weight": 1.0,
                             "explain": why + "."})
        log.add("landscape", f"Season: {ls.SEASONS[js][1]} ({ps[js]*100:.0f}%)" + (f" → {hemi}ern hemisphere" if hemi else ""),
                method="Foliage-state classification × EXIF capture month", detail=why or ("No capture month in metadata." if not month else "Season not decisive."),
                teach=ls.TEACH["season"], level="success" if hemi else "info")
        # water / landform (descriptive)
        pw, _ = eng.option_probs(img_e, [x[2] for x in ls.WATER], "water")
        pl, _ = eng.option_probs(img_e, [x[2] for x in ls.LANDFORM], "landform")
        land["water"] = {"label": ls.WATER[int(np.argmax(pw))][1], "p": round(float(pw.max()), 3)}
        land["landform"] = {"label": ls.LANDFORM[int(np.argmax(pl))][1], "p": round(float(pl.max()), 3)}
        log.add("landscape", f"Terrain: {land['landform']['label']} · water: {land['water']['label']}",
                method="Landform & water-body classification",
                teach="Landform and water type constrain where to look on a map: a wide slow river on a flat plain, a canal, "
                      "a mountain lake or a coast each match different terrain — useful when browsing satellite imagery.")
        return land

    def _heat(self, vis, country_post, cands, log) -> dict:
        land = getattr(self, "_land", {}) or {}
        city_sim = None
        if vis:
            top = sorted(country_post.items(), key=lambda kv: -kv[1])[:3]
            try:
                city_sim = self.engine.city_similarity(vis["img_e"], [iso for iso, p in top if p > 0.02])
            except Exception:
                city_sim = {}
            for g in vis.get("geocells") or []:  # worldwide city evidence lifts regions outside the top countries too
                key = (g["name"], g["cc"])
                city_sim[key] = max(city_sim.get(key, 0.0), g["p"])
        with log.timer("landscape", "Region probability heatmap", method="Country posterior × species ranges × climate belts × hemisphere × city similarity over ~15k places",
                       teach=ls.TEACH["heat"]) as t:
            heat = ls.region_heat(country_post, land.get("factors", []), land.get("hemisphere"), city_sim)
            regs = heat["regions"]
            t.detail = "Top regions: " + ", ".join(f"around {r['name']} ({r['cc']}) {r['p']*100:.0f}%" for r in regs[:5])
            t.data = regs[:8]
            precise = any(c["prec"] <= 2 for c in cands)
            for r in [r for r in regs[:3] if r["p"] >= 0.04]:
                cands.append({"lat": r["lat"], "lon": r["lon"], "w": (1.5 if precise else 6.0) * r["p"], "prec": 60, "cc": r["cc"],
                              "source": "Landscape · region model", "label": f"Region around {r['name']} ({r['p']*100:.0f}%)", "city": None})
            return heat
        return {"points": [], "regions": []}

    def _reasoning(self, loc, countries, evidence, vis, meta, clusters) -> list[str]:
        out = []
        c0 = countries[0]
        city = loc.get("city") or (loc["nearest_city"]["name"] if loc.get("nearest_city") else "")
        where = ", ".join(x for x in (loc.get("venue"), city, c0["name"]) if x)
        out.append(f"Most likely location: {where} — {loc['confidence_label'].lower()} confidence ({loc['confidence']*100:.0f}%).")
        if meta.get("gps"):
            out.append("GPS coordinates are embedded in the file's metadata (verify against the visual clues — metadata can be forged).")
        if clusters:
            b = clusters[0]
            n = len(b["members"])
            out.append(f"{n} clue{'s' if n != 1 else ''} converge on this area ({', '.join(b['sources'])}): "
                       + "; ".join(m["label"] for m in b["members"][:4]) + ".")
        for e in sorted([e for e in evidence if e["source"] in ("Text (OCR)", "Reverse search")], key=lambda e: -e["weight"])[:4]:
            out.append(f"{e['source']}: {e['explain']}")
        if vis:
            strong = sorted([p for p in vis["probes"] if p["detected"] and p["weight"] > 0 and p["countries"]],
                            key=lambda p: -p["weight"] * p["prob"])
            for p in strong[:4]:
                inside = c0["iso"] in p["countries"]
                out.append(f"{p['title']}: {p['label']}" + (f" — {p['explain']}" if p["explain"] else "") +
                           ("" if inside else f" (atypical for {c0['name']})"))
            best_view = max(vis["views"], key=lambda v: v.get("share_of_top", 0))
            out.append(f"Region that carried the most visual signal: {best_view['view']} ({best_view['share_of_top']*100:.0f}%).")
        if len(countries) > 1 and countries[1]["prob"] > 0.05:
            out.append(f"Alternative: {countries[1]['name']} ({countries[1]['prob']*100:.0f}%).")
        return out

    def _attention(self, masked, vis, out, world, log) -> list[dict]:
        from .vision import MODELS
        maps = []
        queries = []
        if world:
            w0 = world[0]
            queries.append((f"Match: {w0['name']}", f"a photo of {w0['name']}, {w0['city']}."))
        queries.append((f"Country: {out['countries'][0]['name']}",
                        MODELS[self.engine.model_key]["prompt"].format(out["countries"][0]["name"])))
        for p in vis["probes"]:
            if p["detected"] and p["id"] in ("architecture", "script", "vegetation", "roads") and p["countries"]:
                prompt = next(o["prompt"] for g in PROBES if g["id"] == p["id"] for o in g["options"] if o["label"] == p["label"])
                queries.append((f"{p['title']}: {p['label']}", prompt))
        for label, q in queries[:5]:
            with log.timer("attention", f"Attention map — {label}", method="Grad-CAM for ViT (gradient × activation, last block)",
                           teach="Bright areas are the image patches that pushed the model towards this answer. Use it "
                                 "to check the model relied on real clues (buildings, signs, vegetation) and not on "
                                 "artefacts.") as t:
                m = self.engine.saliency(masked, q)
                if m:
                    maps.append({"label": label, **m})
                    t.detail = "Most attended: " + ", ".join(f"{r['region']} {r['share']*100:.0f}%" for r in m["regions"][:3])
                    t.data = m["regions"]
        return maps

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
                utc = datetime.fromisoformat(dt["local"]).replace(tzinfo=ZoneInfo(tzname)).astimezone(timezone.utc)
                res["time_basis"] = f"EXIF local time interpreted in {tzname}"
            except Exception:
                utc = None
        if utc:
            sp = sun_mod.solar_position(loc["lat"], loc["lon"], utc)
            res.update({"utc": utc.isoformat(), "position": sp, "times": sun_mod.sun_times(loc["lat"], loc["lon"], utc)})
            consistent = (sp["elevation"] > -6) == (not out["stats"]["night"] and out["stats"]["brightness"] > 70)
            res["consistent"] = consistent
            log.add("sun", f"Sun at capture time: elevation {sp['elevation']:.1f}°, azimuth {sp['azimuth']:.0f}°",
                    method="NOAA solar position algorithm", level="info" if consistent else "warn",
                    detail=(f"Shadows should point to {sp['shadow_bearing']:.0f}° and be {sp['shadow_ratio']}× object height. "
                            if sp["shadow_ratio"] else "Sun below horizon. ") +
                           ("Image lighting is consistent." if consistent else "Lighting does NOT match → wrong time zone, edited timestamp or different place."),
                    data=res, teach=sun_mod.TEACH)
        elif out["stats"]["night"]:
            log.add("sun", "Night-time image — shadow geolocation not applicable", method="Brightness analysis", level="muted",
                    teach="At night, artificial lighting colour (sodium-orange vs LED-white streetlights) and lit "
                          "signage replace sun geometry as clues.")
        else:
            log.add("sun", "No capture time — use the shadow tool to measure a shadow manually",
                    method="NOAA solar position algorithm", level="muted", teach=sun_mod.TEACH)
        return res
