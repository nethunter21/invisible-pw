"""Key-less reverse image search: Yandex (automated + parsed), Google Lens, Bing, TinEye.

All engines are used through their public web upload endpoints — no API keys.
They are best-effort: engines change their markup and may show captchas, so every
engine also returns a URL the user can open in the browser.
"""
from __future__ import annotations

import html
import io
import json
import re
import time
from typing import Any
from urllib.parse import quote

import requests
from PIL import Image

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
HDR = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
TIMEOUT = 25


def _jpeg(img: Image.Image, max_side: int = 1280) -> bytes:
    im = img.convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _walk(o: Any, out: list[dict], depth: int = 0) -> None:
    if depth > 40:
        return
    if isinstance(o, dict):
        keys = set(o)
        if ("title" in keys or "snippet" in keys) and ("url" in keys or "originalUrl" in keys or "domain" in keys):
            t = o.get("title")
            if isinstance(t, dict):
                t = t.get("text") or t.get("value")
            u = o.get("url") or o.get("originalUrl") or ""
            if isinstance(u, dict):
                u = u.get("url", "")
            d = o.get("description") or o.get("snippet") or o.get("text") or ""
            if isinstance(d, dict):
                d = d.get("text", "")
            if isinstance(t, str) and isinstance(u, str):
                out.append({"title": html.unescape(t)[:200], "url": u, "snippet": html.unescape(str(d))[:400],
                            "domain": o.get("domain") if isinstance(o.get("domain"), str) else ""})
        for v in o.values():
            _walk(v, out, depth + 1)
    elif isinstance(o, list):
        for v in o:
            _walk(v, out, depth + 1)


def _parse_yandex(page: str) -> dict:
    results: list[dict] = []
    for m in re.finditer(r"data-state=(?:\"([^\"]+)\"|'([^']+)')", page):
        raw = html.unescape(m.group(1) or m.group(2))
        if not raw.startswith("{"):
            continue
        try:
            _walk(json.loads(raw), results)
        except Exception:
            continue
    # markup fallback
    for m in re.finditer(r'class="CbirSites-ItemTitle"[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        results.append({"title": re.sub("<[^>]+>", "", html.unescape(m.group(2)))[:200], "url": html.unescape(m.group(1)),
                        "snippet": "", "domain": ""})
    tags = []
    for m in re.finditer(r'class="(?:CbirTags|Tags)[^"]*"[^>]*>(.*?)</(?:div|section)>', page, re.S):
        tags += [html.unescape(t) for t in re.findall(r"<span[^>]*>([^<]{2,60})</span>", m.group(1))]
    for m in re.finditer(r'"tags":\s*(\[[^\]]{0,4000}\])', page):
        try:
            for t in json.loads(html.unescape(m.group(1))):
                if isinstance(t, dict) and isinstance(t.get("text"), str):
                    tags.append(t["text"])
        except Exception:
            pass
    seen, uniq = set(), []
    for r in results:
        k = r["url"] or r["title"]
        if k and k not in seen and r["title"]:
            seen.add(k)
            uniq.append(r)
    captcha = "showcaptcha" in page or "captcha" in page[:5000].lower() and not uniq
    return {"results": uniq[:40], "tags": list(dict.fromkeys(tags))[:20], "captcha": captcha}


def yandex(img: Image.Image, domain: str = "yandex.com") -> dict:
    s = requests.Session()
    s.headers.update(HDR)
    params = {"rpt": "imageview", "format": "json",
              "request": json.dumps({"blocks": [{"block": "b-page_type_search-by-image__link"}]})}
    r = s.post(f"https://{domain}/images/search", params=params,
               files={"upfile": ("image.jpg", _jpeg(img), "image/jpeg")}, timeout=TIMEOUT)
    r.raise_for_status()
    try:
        q = r.json()["blocks"][0]["params"]["url"]
    except Exception:
        raise RuntimeError("Yandex did not return a search id (captcha or format change)")
    url = f"https://{domain}/images/search?{q}"
    out = {"engine": "Yandex", "url": url, "results": [], "tags": []}
    for page_kind in ("", "&cbir_page=sites"):
        try:
            p = s.get(url + page_kind, timeout=TIMEOUT)
            parsed = _parse_yandex(p.text)
            out["results"] += parsed["results"]
            out["tags"] += parsed["tags"]
            out["captcha"] = parsed["captcha"]
        except Exception as e:
            out["error"] = str(e)
        time.sleep(0.5)
    dedup, seen = [], set()
    for x in out["results"]:
        if x["url"] not in seen:
            seen.add(x["url"])
            dedup.append(x)
    out["results"] = dedup[:40]
    out["tags"] = list(dict.fromkeys(out["tags"]))[:20]
    out["sites_url"] = url + "&cbir_page=sites"
    return out


def _parse_lens(page: str) -> list[dict]:
    """Best-effort extraction of (url, title) pairs from a Lens result page's embedded data."""
    out, seen = [], set()
    for m in re.finditer(r'"(https?://(?![^"]*(?:google|gstatic|googleapis|youtube\.com/s/))[^"\\]{8,300})"\s*,\s*"([^"\\]{6,160})"', page):
        url, title = m.group(1), html.unescape(m.group(2))
        if url in seen or title.startswith("http") or len(title.split()) < 2:
            continue
        seen.add(url)
        dom = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        out.append({"title": title, "url": url, "snippet": "", "domain": dom})
    return out[:40]


def google_lens(img: Image.Image, parse: bool = True) -> dict:
    s = requests.Session()
    s.headers.update(HDR)
    s.cookies.set("CONSENT", "YES+", domain=".google.com")
    ms = int(time.time() * 1000)
    r = s.post(f"https://lens.google.com/v3/upload?hl=en&re=df&st={ms}&ep=gsbubb",
               files={"encoded_image": ("image.jpg", _jpeg(img), "image/jpeg")}, timeout=TIMEOUT,
               allow_redirects=True)
    url = r.url if "lens.google.com/search" in r.url or "google.com/search" in r.url else None
    if not url:
        m = re.search(r'(https://lens\.google\.com/search\?[^"\'\s<>]+)', r.text)
        url = html.unescape(m.group(1)) if m else None
    if not url:
        raise RuntimeError("Lens upload returned no result URL (consent page or format change)")
    results = _parse_lens(r.text) if parse else []
    if parse and not results and r.url != url:
        try:
            results = _parse_lens(s.get(url, timeout=TIMEOUT).text)
        except Exception:
            pass
    return {"engine": "Google Lens", "url": url, "results": results}


def bing(img: Image.Image) -> dict:
    import base64
    s = requests.Session()
    s.headers.update(HDR)
    data = {"imageBin": base64.b64encode(_jpeg(img, 1000)).decode()}
    r = s.post("https://www.bing.com/images/search?view=detailv2&iss=sbiupload&FORM=SBIHMP",
               files={"cbir": (None, "sbi")}, data=data, timeout=TIMEOUT, allow_redirects=True)
    url = r.url if "insightsToken" in r.url or "view=detailv2" in r.url else None
    if not url:
        raise RuntimeError("Bing upload did not redirect to a result page")
    return {"engine": "Bing Visual Search", "url": url, "results": []}


def tineye(img: Image.Image) -> dict:
    s = requests.Session()
    s.headers.update(HDR)
    r = s.post("https://tineye.com/api/v1/result_json/?sort=score&order=desc",
               files={"image": ("image.jpg", _jpeg(img), "image/jpeg")}, timeout=TIMEOUT)
    j = r.json()
    res = []
    for m in j.get("matches", [])[:30]:
        for b in (m.get("backlinks") or [])[:1]:
            res.append({"title": m.get("domain", ""), "url": b.get("backlink") or b.get("url", ""),
                        "snippet": b.get("image_name", ""), "domain": m.get("domain", "")})
    qh = j.get("query_hash") or j.get("query", {}).get("key")
    url = f"https://tineye.com/search/{qh}" if qh else "https://tineye.com/"
    return {"engine": "TinEye", "url": url, "results": res, "total": j.get("num_matches")}


ENGINES = {"yandex": yandex, "lens": google_lens, "bing": bing, "tineye": tineye}
MANUAL = {
    "yandex": "https://yandex.com/images/",
    "lens": "https://lens.google.com/",
    "bing": "https://www.bing.com/visualsearch",
    "tineye": "https://tineye.com/",
    "baidu": "https://graph.baidu.com/pcpage/index?tpl_from=pc",
    "pimeyes": "https://pimeyes.com/en",
}

TEACH = ("Reverse image search finds other copies of the photo or visually similar places. Yandex is the "
         "strongest engine for landscapes, buildings and Eastern Europe because it matches scene similarity, "
         "not just duplicates; Google Lens excels at landmarks and products; TinEye finds exact copies and the "
         "oldest upload. Page titles of matches often contain the place name, which is then geocoded.")


# --------------------------------------------------------------------------- geocoding
_last_nom = 0.0


def nominatim(query: str) -> list[dict]:
    """Free OpenStreetMap geocoder (max 1 request / second, no key)."""
    global _last_nom
    wait = 1.1 - (time.time() - _last_nom)
    if wait > 0:
        time.sleep(wait)
    _last_nom = time.time()
    r = requests.get("https://nominatim.openstreetmap.org/search",
                     params={"q": query, "format": "jsonv2", "limit": 3, "addressdetails": 1},
                     headers={"User-Agent": "GeoLens-desktop/1.0"}, timeout=15)
    r.raise_for_status()
    out = []
    for x in r.json():
        out.append({"name": x.get("display_name", ""), "lat": float(x["lat"]), "lon": float(x["lon"]),
                    "cc": (x.get("address", {}).get("country_code") or "").upper(),
                    "type": x.get("type"), "importance": x.get("importance", 0)})
    return out


def wikipedia_geo(query: str, limit: int = 4) -> list[dict]:
    """Search Wikipedia (no key) and return hits that carry coordinates."""
    r = requests.get("https://en.wikipedia.org/w/api.php", headers={"User-Agent": "GeoLens-desktop/1.0"}, timeout=15,
                     params={"action": "query", "format": "json", "generator": "search", "gsrsearch": query,
                             "gsrlimit": limit, "prop": "coordinates|description", "colimit": limit})
    pages = (r.json().get("query") or {}).get("pages", {})
    out = []
    for p in sorted(pages.values(), key=lambda p: p.get("index", 99)):
        co = (p.get("coordinates") or [None])[0]
        if co:
            out.append({"name": p["title"], "lat": co["lat"], "lon": co["lon"], "desc": p.get("description", ""),
                        "url": "https://en.wikipedia.org/wiki/" + quote(p["title"].replace(" ", "_"))})
    return out


_STOPW = set("""the a an of and in on at to for with from by is are was be this that your our you image images photo photos
picture pictures stock free download hd wallpaper video videos com www http https html jpg png view search results
similar more page site sites news best top new hotel hotels review reviews tripadvisor booking com night day""".split())


def frequent_phrases(titles: list[str], min_count: int = 2, max_n: int = 4) -> list[tuple[str, int]]:
    """Capitalised word n-grams that recur across independent result titles (candidate place names)."""
    from collections import Counter
    cnt: Counter = Counter()
    for t in titles:
        words = re.findall(r"[A-Za-zÀ-ž][\w'’\-]+", t)
        seen = set()
        for n in range(max_n, 0, -1):
            for i in range(len(words) - n + 1):
                g = words[i:i + n]
                if n == 1 and len(g[0]) < 5:
                    continue
                if not g[0][0].isupper() or not g[-1][0].isupper():
                    continue
                if all(w.lower() in _STOPW for w in g):
                    continue
                key = " ".join(g)
                if key.lower() not in seen:
                    seen.add(key.lower())
                    cnt[key] += 1
    res = [(k, v) for k, v in cnt.most_common(60) if v >= (min_count if " " in k else max(3, min_count + 1))]
    # drop phrases contained in a longer phrase with the same count
    out = []
    for k, v in res:
        if not any(k != k2 and k in k2 and v2 >= v for k2, v2 in res):
            out.append((k, v))
    return out[:12]


def multi_search(queries: list[tuple[str, Image.Image]], engines=("yandex",), workers: int = 3,
                 on_done=None) -> list[dict]:
    """Run reverse searches on several image variants (crops, masked, un-mirrored) in parallel."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    jobs = [(label, img, e) for label, img in queries for e in engines]
    out = []

    def run(label, img, e):
        t = time.time()
        try:
            res = ENGINES[e](img)
        except Exception as ex:
            res = {"engine": e, "error": f"{type(ex).__name__}: {ex}", "results": [], "url": MANUAL.get(e)}
        res["query"] = label
        res["secs"] = round(time.time() - t, 1)
        return res

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(run, *j) for j in jobs]
        for f in as_completed(futs):
            r = f.result()
            out.append(r)
            if on_done:
                on_done(r)
    return out


def browser_search_url(engine: str, query: str) -> str:
    return {"google": "https://www.google.com/search?q=", "yandex": "https://yandex.com/search/?text=",
            "maps": "https://www.google.com/maps/search/"}.get(engine, "https://duckduckgo.com/?q=") + quote(query)
