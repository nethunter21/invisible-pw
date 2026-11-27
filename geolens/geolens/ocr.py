"""OCR (RapidOCR / PP-OCR, ONNX, offline) + linguistic & numeric clue extraction."""
from __future__ import annotations

import re
import threading
import unicodedata
from typing import Any

import numpy as np
from PIL import Image

from . import gazetteer as gz
from .knowledge import CURRENCY, DIACRITICS, STREET_WORDS, WORDS_LANG, expand

_engine = None
_lock = threading.Lock()

SCRIPTS = [  # (name, ranges, countries)
    ("Chinese (Han)", [(0x4E00, 0x9FFF)], ["CN", "TW", "HK", "MO", "SG"]),
    ("Japanese kana", [(0x3040, 0x30FF)], ["JP"]),
    ("Korean Hangul", [(0xAC00, 0xD7AF), (0x1100, 0x11FF)], ["KR", "KP"]),
    ("Cyrillic", [(0x0400, 0x04FF)], ["RU", "UA", "BY", "KZ", "KG", "BG", "RS", "MK", "MN", "TJ", "ME", "BA"]),
    ("Arabic", [(0x0600, 0x06FF)], ["SA", "AE", "EG", "MA", "DZ", "TN", "IQ", "JO", "IR", "PK", "AF", "SY", "LB", "OM", "QA", "KW"]),
    ("Thai", [(0x0E00, 0x0E7F)], ["TH"]),
    ("Devanagari", [(0x0900, 0x097F)], ["IN", "NP"]),
    ("Hebrew", [(0x0590, 0x05FF)], ["IL"]),
    ("Greek", [(0x0370, 0x03FF)], ["GR", "CY"]),
    ("Georgian", [(0x10A0, 0x10FF)], ["GE"]),
    ("Armenian", [(0x0530, 0x058F)], ["AM"]),
]

GENERIC_TLDS = {"io", "tv", "me", "co", "ai", "ly", "fm", "cc", "to", "gg", "ws", "la", "eu", "us"}


def _get_engine():
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR()
        return _engine


def run_ocr(img: Image.Image) -> list[dict]:
    eng = _get_engine()
    arr = np.asarray(img.convert("RGB"))
    result, _ = eng(arr)
    items = []
    for box, text, score in result or []:
        score = float(score)
        text = text.strip()
        if score < 0.5 or len(text) < 2:
            continue
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        items.append({"text": text, "score": round(score, 3),
                      "box": [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]})
    return items


def _tiles(w: int, h: int) -> list[tuple[int, int, int, int]]:
    """Overlapping 2-col × 3-row grid (portrait) or 3×2 (landscape)."""
    cols, rows = (2, 3) if h > w else (3, 2)
    tw, th = w / cols, h / rows
    out = []
    for r in range(rows):
        for c in range(cols):
            x0, y0 = max(0, c * tw - tw * 0.2), max(0, r * th - th * 0.2)
            out.append((int(x0), int(y0), int(min(w, (c + 1) * tw + tw * 0.2)), int(min(h, (r + 1) * th + th * 0.2))))
    return out


def _quality(items: list[dict]) -> float:
    q = 0.0
    for i in items:
        alnum = sum(ch.isalnum() for ch in i["text"])
        vowels = sum(ch.lower() in "aeiouy" for ch in i["text"])
        wordlike = 1.0 if alnum >= 4 and 0.2 <= vowels / max(1, alnum) <= 0.7 else 0.4
        q += i["score"] ** 2 * alnum * wordlike
    return q


def _dedupe(items: list[dict]) -> list[dict]:
    items = sorted(items, key=lambda i: -i["score"] * len(i["text"]))
    keep: list[dict] = []
    for it in items:
        b = it["box"]
        dup = False
        for k in keep:
            c = k["box"]
            ix = max(0, min(b[2], c[2]) - max(b[0], c[0]))
            iy = max(0, min(b[3], c[3]) - max(b[1], c[1]))
            inter = ix * iy
            a = max(1, (b[2] - b[0]) * (b[3] - b[1]))
            if inter / a > 0.5 or (it["text"].lower() == k["text"].lower() and inter > 0):
                dup = True
                break
        if not dup:
            keep.append(it)
    return keep


def run_ocr_multi(img: Image.Image, log=None) -> tuple[list[dict], dict]:
    """OCR in both orientations (selfies are mirrored) and on zoomed overlapping tiles (small signs).

    Returns items in the coordinates of `img` *as it should be displayed* (un-mirrored if
    the image turned out to be mirrored) and info {mirrored, quality_normal, quality_mirrored, passes}.
    """
    from PIL import ImageOps
    w, h = img.size
    results = {}
    passes = 0
    for flip in (False, True):
        im = ImageOps.mirror(img) if flip else img
        items = run_ocr(im)
        passes += 1
        for (x0, y0, x1, y1) in _tiles(w, h):
            crop = im.crop((x0, y0, x1, y1))
            f = min(2.5, 1400 / max(crop.size))
            if f > 1.1:
                crop = crop.resize((int(crop.size[0] * f), int(crop.size[1] * f)), Image.BICUBIC)
            else:
                f = 1.0
            for it in run_ocr(crop):
                bx = it["box"]
                it["box"] = [int(x0 + bx[0] / f), int(y0 + bx[1] / f), int(x0 + bx[2] / f), int(y0 + bx[3] / f)]
                items.append(it)
            passes += 1
        results[flip] = _dedupe(items)
    qn, qm = _quality(results[False]), _quality(results[True])
    mirrored = qm > 1.35 * qn and qm > 8
    return results[mirrored], {"mirrored": mirrored, "quality_normal": round(qn, 1),
                               "quality_mirrored": round(qm, 1), "passes": passes}


def _strip(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)).lower()


def extract_clues(items: list[dict], all_isos: list[str]) -> list[dict]:
    text = "  ".join(i["text"] for i in items)
    if not text.strip():
        return []
    clues: list[dict] = []
    low = text.lower()
    norm = _strip(text)

    def add(kind: str, match: str, countries, weight: float, explain: str):
        cs = sorted(expand(list(countries), all_isos)) if countries else []
        clues.append({"source": "ocr", "kind": kind, "text": match, "countries": cs, "weight": weight, "explain": explain})

    # Scripts
    for name, ranges, cs in SCRIPTS:
        n = sum(1 for ch in text if any(a <= ord(ch) <= b for a, b in ranges))
        if n >= 2:
            add("script", name, cs, 1.6, f"{n} characters in {name} script were read by OCR.")
    # Phone numbers
    codes = {}
    for iso, c in gz.countries().items():
        for p in str(c["phone"]).replace("+", "").split(" and "):
            p = p.split("-")[0].strip()
            if p.isdigit():
                codes.setdefault(p, []).append(iso)
    for m in re.finditer(r"(?:\+|00)\s?(\d[\d\s\-]{5,})", text):
        digits = re.sub(r"\D", "", m.group(1))
        for L in (3, 2, 1):
            if digits[:L] in codes:
                add("phone", "+" + digits[:L] + "…", codes[digits[:L]], 1.4,
                    f"International dialling prefix +{digits[:L]} belongs to {', '.join(gz.country_name(x) for x in codes[digits[:L]][:4])}.")
                break
    # Domains / TLDs
    for m in re.finditer(r"\b[\w\-]+\.(?:com?\.|org\.|gov\.|net\.)?([a-z]{2})\b", low):
        tld = m.group(1)
        if tld in GENERIC_TLDS:
            continue
        isos = [iso for iso, c in gz.countries().items() if c["tld"] == "." + tld]
        if isos:
            add("domain", m.group(0), isos, 1.3, f"Country-code top-level domain .{tld} → {gz.country_name(isos[0])}.")
    # Street / place vocabulary
    toks = set(re.findall(r"[a-zß\-]+", norm)) | set(re.findall(r"[a-zß\-]+", low))
    for w, (cs, ex) in STREET_WORDS.items():
        if (len(w) <= 3 and re.search(rf"\b{re.escape(w)}\.?\s", norm + " ")) or (len(w) > 3 and any(t == w or t.endswith(w) and len(t) > len(w) + 2 for t in toks)):
            add("street-word", w, cs, 1.0, ex + ". Street-type words are local language vocabulary on street signs.")
    for w, (cs, ex) in WORDS_LANG.items():
        if cs and (w in toks or (" " in w and w in norm)):
            add("word", w, cs, 0.9, ex + ".")
    # Diacritics & currency
    for ch, (cs, ex) in DIACRITICS.items():
        if ch in low:
            add("diacritic", ch, cs, 0.8, f"The letter '{ch}' ({ex}) only exists in a few orthographies.")
    for sym, (cs, ex) in CURRENCY.items():
        if re.search(rf"(?<![A-Za-z]){re.escape(sym)}(?![A-Za-z])", text):
            add("currency", sym, cs, 1.0, f"Price shown with {ex}.")
    # Named venues / landmarks / brands (fuzzy, OCR-noise tolerant)
    from .landmarks import match_text
    seen_lm: set[str] = set()
    for src in [i["text"] for i in items] + [text]:
        ms = match_text(src)
        by_name: dict[str, list[dict]] = {}
        for m in ms:
            by_name.setdefault(m["name"], []).append(m)
        for name, sites in by_name.items():
            if name in seen_lm:
                continue
            seen_lm.add(name)
            q = max(m["quality"] for m in sites)
            multi = len(sites) > 1 or sites[0]["kind"] == "brand"
            where = ", ".join(f"{m['city']} {m['cc']}" for m in sites[:5])
            add("landmark", name, sorted({m["cc"] for m in sites}), (1.6 if multi else 2.6) * q,
                f"Text '{src[:40]}' matches '{name}' (similarity {q:.2f}) — " +
                (f"a brand with sites in {where}; the site agreeing with the other evidence is chosen." if multi
                 else f"located in {where}."))
            clues[-1]["sites"] = sites
    # Place names in the gazetteer
    places = gz.find_places(text)[:6]
    same = {}
    for p in places:  # one word matching several cities (Augusta, US / Augsburg, DE) is ambiguous
        same[p.get("match", p["name"])] = same.get(p.get("match", p["name"]), 0) + 1
    for p in places:
        n = same[p.get("match", p["name"])]
        add("place-name", p["name"], [p["cc"]], (1.5 if p["type"] == "city" else 1.1) / n,
            f"'{p['name']}' matches a {'city' if p['type']=='city' else 'country'} in the offline GeoNames gazetteer.")
        clues[-1]["place"] = p
    return clues


TEACH = ("OCR turns every readable sign into text. Text is the richest GEOINT signal: phone prefixes, web "
         "domains, currencies, street-type words (Straße, Rua, Jalan, Soi…) and diacritics (ø, ł, ñ, ğ) each "
         "point to a handful of countries, and a readable place name can pin the city directly. Even "
         "shop-name fragments help, because business vocabulary is language-specific.")
