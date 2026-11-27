"""Offline end-to-end test: tiny random CLIP + real OCR + EXIF GPS + sun maths."""
import io, json, os, sys
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from geolens.log import AnalysisLog
from geolens.pipeline import Analyzer
from geolens.vision import VisionEngine
from geolens import sun

TINY = sys.argv[1] if len(sys.argv) > 1 else None


def make_image(gps=False):
    im = Image.new("RGB", (1200, 800), (120, 160, 210))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 450, 1200, 800], fill=(90, 90, 90))
    d.rectangle([200, 150, 1000, 330], fill="white")
    f = ImageFont.load_default(size=44)
    d.text((230, 170), "Rua Augusta - Lisboa", fill="black", font=f)
    d.text((230, 250), "Tel +351 21 555 1234  loja.pt", fill="black", font=f)
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[0x0132] = "2024:06:21 14:00:00"
    exif[0x010F] = "TestCam"
    if gps:
        exif[0x8825] = {1: "N", 2: (38.0, 42.0, 36.0), 3: "W", 4: (9.0, 8.0, 24.0)}
    im.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def run(data, engine):
    log = AnalysisLog()
    res = Analyzer(engine, {"online": False}).run(data, "test.jpg", log)
    return res, log


# sun sanity: Paris 2024-06-21 12:00 UTC ≈ elevation 64°, azimuth ~ 190°
p = sun.solar_position(48.8566, 2.3522, datetime(2024, 6, 21, 12, 0, tzinfo=timezone.utc))
assert 62 < p["elevation"] < 66 and 175 < p["azimuth"] < 205, p
loc = sun.shadow_locus(datetime(2024, 6, 21, 12, 0, tzinfo=timezone.utc), p["elevation"], 1.0)
assert any(abs(a - 49) <= 2 and abs(b - 2) <= 2 for a, b in loc["points"]), "Paris not on locus"
ch = sun.chronolocate(48.8566, 2.3522, datetime(2024, 6, 21, tzinfo=timezone.utc), 30)
assert len(ch) == 2, ch
print("sun ok", p, ch)

engine = VisionEngine(TINY, None) if TINY else None
res, log = run(make_image(), engine)
print("country:", [(c["iso"], round(c["prob"], 3)) for c in res["countries"][:4]])
print("location:", {k: res["location"][k] for k in ("lat", "lon", "radius_km", "method", "confidence")})
print("ocr clues:", [(c["kind"], c["text"]) for c in res["ocr"]["clues"]])
assert res["countries"][0]["iso"] == "PT", "text evidence should make Portugal win"
if engine:
    assert engine.ready, engine.error
    assert res["attention"] and res["attention"][0]["png"].startswith("data:image/png")
    assert res["vision"]["probes"]
for e in log.snapshot():
    if e["level"] == "error":
        print("ERROR ENTRY:", e["title"], e["detail"][:500])
assert not [e for e in log.snapshot() if e["level"] == "error"]
print("log entries:", len(log.snapshot()))
json.dumps(res, default=str)

res2, _ = run(make_image(gps=True), engine)
assert res2["location"]["source"] == "EXIF GPS", res2["location"]
assert abs(res2["location"]["lat"] - 38.71) < 0.01 and res2["location"]["lon"] < 0
print("gps ok", res2["location"]["nearest_city"]["name"], res2["sun"].get("position"))
print("ALL TESTS PASSED")
