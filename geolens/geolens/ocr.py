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
