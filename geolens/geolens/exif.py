"""EXIF / metadata extraction (GPS, timestamps, camera, heading)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from PIL import ExifTags, Image

_TAGS = {v: k for k, v in ExifTags.TAGS.items()}
_GPS = ExifTags.GPSTAGS


def _rat(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        try:
            return x[0] / x[1]
        except Exception:
            return float("nan")


def _dms(v: Any, ref: str) -> float | None:
    try:
        d, m, s = (_rat(i) for i in v)
        val = d + m / 60 + s / 3600
        return -val if ref in ("S", "W") else val
    except Exception:
        return None


def _parse_dt(s: str | None, offset: str | None) -> dict[str, Any] | None:
    if not s:
        return None
    try:
        dt = datetime.strptime(str(s).strip("\x00 ")[:19], "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None
    out: dict[str, Any] = {"local": dt.isoformat(), "offset": None, "utc": None}
    if offset:
        try:
            sign = -1 if offset.strip()[0] == "-" else 1
            hh, mm = offset.strip().lstrip("+-").split(":")
            off = timedelta(hours=int(hh), minutes=int(mm)) * sign
            out["offset"] = offset.strip()
            out["utc"] = (dt - off).replace(tzinfo=timezone.utc).isoformat()
        except Exception:
            pass
    return out


def read_metadata(img: Image.Image) -> dict[str, Any]:
    meta: dict[str, Any] = {"has_exif": False, "gps": None, "datetime": None, "camera": None,
                            "software": None, "heading": None, "raw": {}}
    try:
        exif = img.getexif()
    except Exception:
        return meta
    if not exif:
        return meta
    meta["has_exif"] = True
    raw: dict[str, str] = {}
    for k, v in exif.items():
        name = ExifTags.TAGS.get(k, str(k))
        if isinstance(v, (bytes, bytearray)) or len(str(v)) > 120:
            continue
        raw[name] = str(v)
    try:
        sub = exif.get_ifd(0x8769)  # Exif IFD
        for k, v in sub.items():
            name = ExifTags.TAGS.get(k, str(k))
            if isinstance(v, (bytes, bytearray)) or len(str(v)) > 120:
                continue
            raw[name] = str(v)
    except Exception:
        sub = {}
    meta["raw"] = raw
    make, model = raw.get("Make", "").strip(), raw.get("Model", "").strip()
    if make or model:
        meta["camera"] = f"{make} {model}".strip()
    meta["software"] = raw.get("Software")
    meta["datetime"] = _parse_dt(raw.get("DateTimeOriginal") or raw.get("DateTime"),
                                 raw.get("OffsetTimeOriginal") or raw.get("OffsetTime"))
    try:
        g = exif.get_ifd(0x8825)
    except Exception:
        g = {}
    if g:
        gd = {_GPS.get(k, k): v for k, v in g.items()}
        lat = _dms(gd.get("GPSLatitude"), str(gd.get("GPSLatitudeRef", "N")))
        lon = _dms(gd.get("GPSLongitude"), str(gd.get("GPSLongitudeRef", "E")))
        if lat is not None and lon is not None and not (lat == 0 and lon == 0):
            meta["gps"] = {"lat": round(lat, 6), "lon": round(lon, 6)}
            if "GPSAltitude" in gd:
                meta["gps"]["alt_m"] = round(_rat(gd["GPSAltitude"]), 1)
        if "GPSImgDirection" in gd:
            meta["heading"] = round(_rat(gd["GPSImgDirection"]), 1)
        if "GPSDateStamp" in gd and "GPSTimeStamp" in gd and meta["datetime"] is not None:
            try:
                h, m, s = (_rat(x) for x in gd["GPSTimeStamp"])
                d = datetime.strptime(str(gd["GPSDateStamp"]), "%Y:%m:%d")
                utc = d + timedelta(hours=h, minutes=m, seconds=s)
                meta["datetime"]["utc"] = utc.replace(tzinfo=timezone.utc).isoformat()
                meta["datetime"]["utc_source"] = "GPS clock"
            except Exception:
                pass
    return meta
