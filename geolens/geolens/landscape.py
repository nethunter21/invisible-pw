"""Landscape / ecology reconnaissance for photos with little or no man-made information.

Techniques
  * Scene composition   CLIP labels every cell of a 4×4 grid (sky, trees, grass, water, buildings,
                        road, sand, rock, snow, …) → fractions → scene family. This replaces the old
                        single-prompt scene guess (no more "desert" for a city).
  * Spectral indices    Excess-green vegetation index, sky blueness, haze, saturation, soil hue,
                        water colour — computed from pixels, no model.
  * Species ranges      ~40 tree / plant / crop indicators, each with real-world range boxes
                        (lat/lon). Detecting Lombardy poplars or a eucalyptus stand narrows the map
                        below country level.
  * Climate zones       Köppen-style climate classes mapped to latitude/longitude regions.
  * Season → hemisphere Foliage state + EXIF month tells north vs south (or tropics).
  * Terrain & water     Landform and water-body type.
  * Region heatmap      Every gazetteer city is scored: country posterior × species ranges ×
                        climate × hemisphere × (optional) vision city similarity. The result is a
                        probability surface — honest for images that cannot be pinned to a point.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from PIL import Image

from . import gazetteer as gz

# ----------------------------------------------------------------------------------------- composition
CELL_LABELS = [
    ("sky", ["the sky", "clear blue sky", "clouds in the sky"]),
    ("trees", ["trees and forest", "green tree foliage"]),
    ("grass", ["grass and green vegetation", "a meadow"]),
    ("crops", ["farm fields and crops"]),
    ("water", ["water of a river or lake", "the sea"]),
    ("building", ["a building facade", "houses and buildings", "skyscrapers"]),
    ("road", ["an asphalt road or street", "a pavement sidewalk"]),
    ("vehicle", ["cars and vehicles"]),
    ("sand", ["sand and desert dunes", "a sandy beach"]),
    ("rock", ["bare rock and stones", "a rocky mountain slope"]),
    ("snow", ["snow and ice"]),
    ("person", ["a person", "a human face"]),
    ("interior", ["a room interior wall", "furniture indoors"]),
]

# ----------------------------------------------------------------------------------------- regions
# Boxes: (lat_min, lat_max, lon_min, lon_max)
R = {
    "W_EUROPE": (42, 56, -10, 16), "C_EUROPE": (44, 56, 5, 25), "N_EUROPE": (54, 71, 4, 32),
    "E_EUROPE": (44, 60, 20, 45), "MED": (30, 46, -10, 37), "BALKANS": (39, 47, 13, 30),
    "RUSSIA": (45, 70, 30, 180), "C_ASIA": (35, 52, 45, 90), "MIDEAST": (12, 38, 34, 62),
    "N_AFRICA": (15, 37, -17, 35), "SAHEL": (8, 18, -17, 40), "W_AFRICA": (4, 15, -17, 15),
    "C_AFRICA": (-12, 8, 8, 32), "E_AFRICA": (-12, 15, 28, 52), "S_AFRICA": (-35, -12, 11, 41),
    "INDIA": (6, 35, 66, 98), "SE_ASIA": (-11, 25, 92, 142), "CHINA": (18, 45, 98, 125),
    "JP_KR": (30, 46, 124, 146), "AUS": (-44, -10, 112, 154), "NZ": (-47, -34, 166, 179),
    "CANADA": (42, 70, -141, -52), "US_NE": (36, 48, -92, -66), "US_SE": (24, 37, -100, -75),
    "US_MW": (36, 49, -104, -80), "US_SW": (28, 38, -122, -100), "US_W": (32, 49, -125, -104),
    "US_PNW": (40, 50, -125, -116), "CALIF": (32, 42, -124.5, -114), "MEXICO": (14, 33, -118, -86),
    "C_AMERICA": (7, 18, -93, -77), "CARIB": (10, 27, -85, -59), "AMAZON": (-15, 6, -76, -44),
    "BRAZIL_SE": (-34, -15, -58, -38), "ANDES": (-40, 10, -80, -64), "S_CONE": (-56, -22, -76, -48),
    "PATAGONIA": (-56, -38, -76, -62), "TROPICS": (-23.5, 23.5, -180, 180),
    "NH_TEMPERATE": (35, 60, -180, 180), "SH_TEMPERATE": (-50, -30, -180, 180),
    "BOREAL": (50, 70, -180, 180), "ARCTIC": (63, 80, -180, 180), "ICELAND": (63, 67, -25, -13),
    "MADAGASCAR": (-26, -12, 43, 51), "ALPS": (44, 48.5, 5, 17), "HIMALAYA": (26, 37, 70, 100),
    "TIBET": (28, 38, 78, 102), "ATLAS": (29, 36, -10, 10), "LEVANT": (29, 37, 34, 43),
    "ARABIA": (12, 32, 35, 60), "PERSIA": (25, 40, 44, 63), "PATAG_STEPPE": (-52, -38, -72, -64),
}


def _boxes(*names):
    return [R[n] for n in names]


# id, label, prompts, regions (boxes), teach
SPECIES = [
    ("lombardy_poplar", "Lombardy / columnar poplars", ["tall narrow columnar Lombardy poplar trees", "a row of tall thin poplar trees"],
     _boxes("W_EUROPE", "C_EUROPE", "MED", "BALKANS", "E_EUROPE", "C_ASIA", "S_CONE"),
     "Columnar 'Lombardy' poplars are planted along rivers, canals and field edges across France, Italy, the Low Countries, "
     "the Balkans and Central Asia, and as windbreaks in Argentina and Chile. They are rare in the tropics and in East Asia."),
    ("italian_cypress", "Italian (columnar) cypress", ["dark green narrow Italian cypress trees", "Tuscan cypress trees"],
     _boxes("MED", "CALIF", "LEVANT"), "Dark, flame-shaped cypresses mark Mediterranean landscapes (Tuscany, Provence, Greece, Turkey) and California."),
    ("plane_tree", "Plane trees (mottled bark)", ["plane trees with mottled peeling bark lining a street"],
     _boxes("W_EUROPE", "MED", "C_EUROPE"), "London/oriental planes with camouflage bark line avenues and squares in France, Spain, Italy and the UK."),
    ("olive", "Olive groves", ["silver green olive trees in an olive grove"],
     _boxes("MED", "LEVANT", "CALIF", "S_CONE", "ATLAS"), "Olive groves are the signature crop of the Mediterranean climate zone."),
    ("stone_pine", "Umbrella / stone pines", ["umbrella shaped stone pine trees"],
     _boxes("MED"), "Flat-topped stone pines are iconic around Rome, the Spanish and Portuguese coasts and the Côte d'Azur."),
    ("birch", "Birch trees", ["white bark birch trees"],
     _boxes("N_EUROPE", "E_EUROPE", "RUSSIA", "CANADA", "C_EUROPE", "US_NE"), "Birch (white bark) dominates the boreal-temperate belt: Scandinavia, the Baltics, Russia, Canada."),
    ("spruce_fir", "Spruce / fir conifers", ["dense dark spruce and fir conifer forest"],
     _boxes("BOREAL", "ALPS", "CANADA", "US_PNW", "N_EUROPE", "C_EUROPE"), "Spruce/fir forests mean boreal latitudes or mountains."),
    ("pine_forest", "Pine forest", ["a pine forest with tall straight pine trunks"],
     _boxes("N_EUROPE", "E_EUROPE", "RUSSIA", "US_SE", "US_W", "MED", "CANADA", "MEXICO"), "Open pine forests: Scandinavia/Baltics/Poland, Landes (France), the US South, the Rockies."),
    ("larch", "Larch (golden in autumn)", ["golden yellow larch trees in autumn"],
     _boxes("ALPS", "RUSSIA", "CANADA"), "Larch turns gold in autumn — Alps, Siberia, Canada."),
    ("broadleaf", "Temperate broadleaf (oak, beech, maple)", ["a temperate deciduous forest of oak and beech"],
     _boxes("W_EUROPE", "C_EUROPE", "E_EUROPE", "US_NE", "US_MW", "JP_KR", "CHINA"), "Mixed oak/beech/maple woodland: Europe, eastern North America, East Asia."),
    ("willow", "Willows by water", ["weeping willow trees by the water"],
     _boxes("NH_TEMPERATE", "CHINA", "S_CONE"), "Willows grow along rivers and ponds throughout the northern temperate zone."),
    ("red_maple", "Red/orange maple autumn colour", ["bright red maple trees in autumn"],
     _boxes("US_NE", "CANADA", "JP_KR"), "Vivid red autumn colour is typical of eastern North America, Japan and Korea."),
    ("cherry_blossom", "Cherry blossom", ["pink cherry blossom trees"],
     _boxes("JP_KR", "CHINA", "US_NE"), "Ornamental cherry blossom: Japan, Korea, China (and planted in Washington DC)."),
    ("eucalyptus", "Eucalyptus / gum trees", ["tall eucalyptus gum trees with peeling bark"],
     _boxes("AUS", "CALIF", "BRAZIL_SE", "S_AFRICA", "E_AFRICA") + [(36, 44, -10, -6), (-40, -30, -73, -56)],
     "Native to Australia; plantations in Portugal/Galicia, California, Brazil, Uruguay, South Africa, Ethiopia."),
    ("coconut_palm", "Coconut palms", ["leaning coconut palm trees on a tropical coast"],
     _boxes("TROPICS"), "Coconut palms are confined to the humid tropics (≈ 23° N–23° S)."),
    ("date_palm", "Date palms", ["date palm trees in a dry oasis"],
     _boxes("MIDEAST", "N_AFRICA", "ARABIA", "PERSIA", "US_SW"), "Date palms: Arabia, the Maghreb, Egypt, Iran, oases; also the US South-West."),
    ("fan_palm", "Ornamental fan / Washingtonia palms", ["tall thin palm trees lining a boulevard"],
     _boxes("CALIF", "US_SE", "MED", "MIDEAST", "MEXICO", "AUS"), "Tall skinny Washingtonia palms: Los Angeles, Florida, Mediterranean resorts, the Gulf."),
    ("baobab", "Baobab", ["a massive baobab tree"],
     _boxes("SAHEL", "E_AFRICA", "S_AFRICA", "MADAGASCAR") + [(-20, -12, 120, 130)], "Baobabs: savanna Africa, Madagascar, north-west Australia."),
    ("acacia", "Umbrella acacia", ["flat topped umbrella acacia trees in a savanna"],
     _boxes("E_AFRICA", "S_AFRICA", "SAHEL", "ARABIA"), "Umbrella thorn acacias define East and Southern African savanna."),
    ("banana", "Banana / plantain", ["banana plants with large leaves"],
     _boxes("TROPICS"), "Banana plants mean humid tropics/subtropics."),
    ("bamboo", "Bamboo", ["a dense bamboo grove"],
     _boxes("CHINA", "JP_KR", "SE_ASIA", "INDIA", "AMAZON"), "Bamboo groves: East and South-East Asia, tropical South America."),
    ("rice", "Rice paddies", ["flooded green rice paddy terraces"],
     _boxes("SE_ASIA", "CHINA", "INDIA", "JP_KR") + [(42, 46, 7, 10)], "Rice paddies: monsoon Asia (and the Po plain in Italy)."),
    ("tea", "Tea plantation", ["rows of tea bushes on a hillside plantation"],
     _boxes("INDIA", "CHINA", "E_AFRICA") + [(5, 10, 79, 82)], "Tea estates: Darjeeling/Assam/Nilgiris, Sri Lanka, Kenya, China."),
    ("oil_palm", "Oil palm plantation", ["an oil palm plantation"],
     _boxes("SE_ASIA", "W_AFRICA", "C_AFRICA"), "Oil palm: Malaysia, Indonesia, West Africa."),
    ("saguaro", "Saguaro / columnar cacti", ["tall saguaro cactus in the desert"],
     [(23, 35, -116, -106)], "Saguaro and columnar cacti: Sonoran desert (Arizona, Sonora)."),
    ("opuntia", "Prickly pear (Opuntia)", ["prickly pear cactus"],
     _boxes("MEXICO", "MED", "US_SW", "ANDES", "S_AFRICA"), "Opuntia: Mexico/US South-West, naturalised around the Mediterranean and South Africa."),
    ("joshua", "Joshua trees", ["joshua trees in the mojave desert"], [(33.5, 37.5, -118.5, -113)], "Joshua trees exist only in the Mojave desert."),
    ("araucaria", "Araucaria (monkey-puzzle / Paraná pine)", ["araucaria pine trees with candelabra shape"],
     [(-30, -20, -55, -48), (-42, -36, -74, -70)], "Araucaria: southern Brazil highlands, Chile/Argentina Andes."),
    ("redwood", "Redwood / sequoia", ["giant redwood sequoia trees"], [(35, 42.5, -124.5, -118)], "Coast redwoods and giant sequoias: California."),
    ("mangrove", "Mangroves", ["mangrove trees in shallow coastal water"], _boxes("TROPICS"), "Mangroves line tropical coasts."),
    ("cedar", "Cedars (Atlas / Lebanon)", ["large spreading cedar trees on a mountain"], _boxes("ATLAS", "LEVANT", "HIMALAYA"), "True cedars: Atlas mountains, Lebanon/Taurus, Himalaya."),
    ("vineyard", "Vineyards", ["rows of grape vines in a vineyard"],
     _boxes("W_EUROPE", "MED", "CALIF", "S_CONE", "S_AFRICA", "AUS", "NZ"), "Vineyards follow wine climates: France, Iberia, Italy, Germany's rivers, California, Chile, Argentina, South Africa, Australia."),
    ("lavender", "Lavender fields", ["purple lavender fields"], [(43, 45, 4, 7.5), (36, 45, -5, 30)], "Lavender fields: Provence above all."),
    ("sunflower", "Sunflower fields", ["a field of sunflowers"], _boxes("E_EUROPE", "W_EUROPE", "RUSSIA", "S_CONE", "US_MW"), "Sunflowers: Ukraine, Russia, France, Spain, Argentina, US Plains."),
    ("tundra_shrub", "Tundra / heath", ["low tundra shrubs and moss with no trees"], _boxes("ARCTIC", "ICELAND", "PATAGONIA"), "Treeless heath/tundra: Arctic, Iceland, Scottish highlands, Patagonia."),
    ("none", "No distinctive species", ["a generic view with no distinctive plants"], [], ""),
]

CLIMATES = [
    ("Cfb", "Temperate oceanic", ["a mild green temperate landscape with deciduous trees"], _boxes("W_EUROPE", "NZ", "US_PNW") + [(-44, -36, 140, 152), (-40, -36, -74, -71)]),
    ("Dfb", "Humid continental", ["a continental landscape with mixed forest and farmland"], _boxes("C_EUROPE", "E_EUROPE", "US_NE", "US_MW", "CANADA", "RUSSIA") + [(38, 50, 120, 135)]),
    ("Csa", "Mediterranean (dry summer)", ["a dry mediterranean landscape with yellow grass and scrub"], _boxes("MED", "CALIF", "LEVANT") + [(-36, -30, -72, -70), (-35, -31, 17, 22), (-36, -31, 114, 140)]),
    ("Cfa", "Humid subtropical", ["a humid subtropical landscape with lush trees"], _boxes("US_SE", "CHINA", "BRAZIL_SE") + [(30, 36, 129, 141), (-34, -25, 148, 154)]),
    ("Af", "Tropical rainforest", ["dense tropical rainforest jungle"], _boxes("AMAZON", "SE_ASIA", "C_AFRICA") + [(5, 10, 76, 78)]),
    ("Aw", "Tropical savanna", ["a tropical savanna with scattered trees and dry grass"], _boxes("E_AFRICA", "W_AFRICA", "SAHEL", "INDIA", "S_AFRICA") + [(-20, -5, -60, -40), (-20, -11, 120, 145)]),
    ("BWh", "Hot desert", ["a hot sandy desert"], _boxes("ARABIA", "N_AFRICA", "MIDEAST", "US_SW") + [(-30, -20, 115, 140), (-27, -18, -71, -69), (-28, -17, 12, 20)]),
    ("BSk", "Semi-arid steppe", ["a dry semi-arid steppe with sparse bushes"], _boxes("C_ASIA", "US_W", "PATAG_STEPPE", "PERSIA") + [(35, 42, -5, 0)]),
    ("Dfc", "Subarctic / boreal", ["a boreal taiga forest landscape"], _boxes("BOREAL", "CANADA", "RUSSIA", "N_EUROPE")),
    ("ET", "Tundra / alpine", ["barren alpine or arctic tundra"], _boxes("ARCTIC", "ICELAND", "TIBET", "ALPS", "PATAGONIA")),
    ("Cwb", "Subtropical highland", ["green tropical highlands with mild climate"], _boxes("ANDES", "E_AFRICA", "HIMALAYA") + [(15, 22, -104, -96)]),
]

SEASONS = [
    ("summer", "Full green summer foliage", ["trees in full green summer foliage"]),
    ("autumn", "Autumn colours", ["trees with orange and yellow autumn leaves"]),
    ("winter", "Bare winter trees", ["bare leafless trees in winter"]),
    ("snow", "Snow cover", ["a snowy winter landscape"]),
    ("spring", "Spring blossom", ["fresh spring blossom on trees"]),
    ("dry", "Dry season (brown grass)", ["dry brown grass in the dry season"]),
]

WATER = [
    ("river", "River", ["a wide river"]), ("canal", "Canal", ["a straight canal"]), ("lake", "Lake / pond", ["a calm lake or pond"]),
    ("sea", "Sea / ocean", ["the ocean with waves"]), ("none", "No water", ["dry land with no water"]),
]

LANDFORM = [
    ("flat", "Flat plain", ["a flat plain"]), ("hills", "Rolling hills", ["rolling green hills"]),
    ("mountains", "Mountains", ["high mountains"]), ("coast", "Coastline", ["a coastline"]), ("valley", "River valley", ["a river valley between hills"]),
]


# ----------------------------------------------------------------------------------------- pixels
def spectral(img: Image.Image) -> dict:
    a = np.asarray(img.convert("RGB").resize((320, 320))).astype(np.float32) / 255
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    s = r + g + b + 1e-6
    exg = 2 * g / s - r / s - b / s  # excess-green index
    veg = float((exg > 0.08).mean())
    top = a[:96]
    tr, tg, tb = top[..., 0], top[..., 1], top[..., 2]
    sky_mask = (tb > tr) & (tb > 0.45)
    sky_blue = float(((tb - tr)[sky_mask]).mean()) if sky_mask.any() else 0.0
    mx, mn = a.max(-1), a.min(-1)
    sat = float(((mx - mn) / (mx + 1e-6)).mean())
    haze = float(1 - (top.max(-1) - top.min(-1)).mean()) if sky_mask.any() else None
    brown = float(((r > g) & (g > b) & (r - b > 0.12) & (exg < 0.02)).mean())
    yellow_grass = float(((r > 0.45) & (g > 0.4) & (b < 0.35) & (np.abs(r - g) < 0.12)).mean())
    return {"vegetation_index": round(veg, 3), "sky_blueness": round(sky_blue, 3), "saturation": round(sat, 3),
            "haze": None if haze is None else round(haze, 3), "bare_soil": round(brown, 3),
            "dry_grass": round(yellow_grass, 3)}


def scene_from_composition(comp: dict) -> tuple[str, str]:
    f = comp
    built = f.get("building", 0) + f.get("road", 0) + f.get("vehicle", 0)
    nature = f.get("trees", 0) + f.get("grass", 0) + f.get("crops", 0) + f.get("water", 0)
    if f.get("interior", 0) > 0.3:
        return "indoor", "Indoors"
    if f.get("person", 0) > 0.45:
        return "portrait", "Portrait / selfie (background analysed)"
    if built >= 0.3 and f.get("building", 0) >= 0.18 and built >= 0.8 * nature:
        return "urban", "Urban / built-up"
    if f.get("sand", 0) + f.get("rock", 0) >= 0.35 and nature < 0.2:
        return "arid", "Arid / desert terrain"
    if f.get("snow", 0) >= 0.3:
        return "snow", "Snow landscape"
    if f.get("water", 0) >= 0.2 and nature >= 0.35:
        return "waterside", "Natural waterside"
    if f.get("road", 0) >= 0.12 and nature >= 0.25:
        return "rural_road", "Rural road"
    if nature >= 0.35:
        return "natural", "Natural landscape"
    return "mixed", "Mixed scene"


# ----------------------------------------------------------------------------------------- geography
def _inside(lat, lon, boxes) -> np.ndarray:
    m = np.zeros_like(lat, dtype=bool)
    for la0, la1, lo0, lo1 in boxes:
        m |= (lat >= la0) & (lat <= la1) & (lon >= lo0) & (lon <= lo1)
    return m


def species_countries(boxes, isos) -> list[str]:
    out = []
    for iso in isos:
        c = gz.countries().get(iso)
        if not c:
            continue
        cities = gz.cities_of(iso, 8) or [{"lat": c["lat"], "lon": c["lon"]}]
        lat = np.array([x["lat"] for x in cities])
        lon = np.array([x["lon"] for x in cities])
        if _inside(lat, lon, boxes).mean() >= 0.25:
            out.append(iso)
    return out


def region_heat(country_post: dict[str, float], factors: list[dict], hemisphere: str | None,
                city_sim: dict[tuple[str, str], float] | None = None, top_n: int = 1200) -> dict:
    """Probability over every gazetteer city. factors: [{boxes, p, alpha}]"""
    rows = gz.all_cities()
    lat = np.array([c["lat"] for c in rows])
    lon = np.array([c["lon"] for c in rows])
    cc = [c["cc"] for c in rows]
    pc = np.array([country_post.get(x, 0.0) for x in cc])
    # spread each country's mass over its places (∝ √population). Countries with more/larger places get a mild
    # base-rate bonus S^0.3 — photos are taken where people are — and no single-city country can hog the map.
    pop = np.sqrt(np.array([max(c["pop"], 1000) for c in rows], dtype=np.float64))
    tot: dict[str, float] = {}
    for x, p in zip(cc, pop):
        tot[x] = tot.get(x, 0.0) + p
    S = np.array([tot[x] for x in cc])
    w = pc * (pop / S) * (S / 1000.0) ** 0.3
    for f in factors:
        if not f["boxes"]:
            continue
        ins = _inside(lat, lon, f["boxes"])
        a = f.get("alpha", 0.85) * f["p"]
        w = w * np.where(ins, 1.0, 1.0 - a)
    if hemisphere == "north":
        w = w * np.where(lat > 0, 1.0, 0.15)
    elif hemisphere == "south":
        w = w * np.where(lat < 0, 1.0, 0.15)
    if city_sim:
        boost = np.array([city_sim.get((c["name"], c["cc"]), 0.0) for c in rows])
        if boost.max() > 0:
            w = w * (1 + 6 * boost / boost.max())
    if w.sum() <= 0:
        return {"points": [], "regions": []}
    w = w / w.sum()
    order = np.argsort(-w)[:top_n]
    pts = [[round(float(lat[i]), 3), round(float(lon[i]), 3), float(w[i])] for i in order if w[i] > 0]
    # regions: greedy clustering of top cities within 200 km
    regs: list[dict] = []
    for i in order[:400]:
        for r in regs:
            if gz.haversine_km(r["lat"], r["lon"], lat[i], lon[i]) < 200:
                r["p"] += float(w[i])
                r["n"] += 1
                break
        else:
            regs.append({"lat": float(lat[i]), "lon": float(lon[i]), "p": float(w[i]), "n": 1,
                         "name": rows[i]["name"], "cc": rows[i]["cc"]})
    regs.sort(key=lambda r: -r["p"])
    return {"points": pts, "regions": regs[:10]}


def month_hemisphere(season: str, month: int | None) -> tuple[str | None, str]:
    if not month or season not in ("summer", "autumn", "winter", "snow", "spring"):
        return None, ""
    north_seasons = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
                     6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}
    ns = north_seasons[month]
    s = "winter" if season == "snow" else season
    flip = {"winter": "summer", "summer": "winter", "spring": "autumn", "autumn": "spring"}
    if s == ns:
        return "north", f"{s} foliage in month {month} matches the northern hemisphere"
    if s == flip.get(ns):
        return "south", f"{s} foliage in month {month} matches the southern hemisphere"
    return None, ""


TEACH = {
    "composition": "Before guessing a place, analysts decompose the frame: how much is sky, vegetation, water, "
                   "buildings, road? A 4×4 grid is labelled cell by cell, which also stops errors like calling a "
                   "city 'desert' because of one beige wall.",
    "spectral": "Pixel statistics carry climate information: the excess-green index measures vegetation vigour "
                "(humid vs. dry), sky blueness and haze relate to humidity, altitude and pollution, yellow grass "
                "signals a dry summer (Mediterranean) or dry season (savanna).",
    "species": "Plants have mapped natural and cultivated ranges. One reliably identified species can remove whole "
               "continents; two or three overlapping ranges can narrow the search to a region.",
    "climate": "The Köppen system groups places by temperature and rainfall regime; vegetation and light reveal the "
               "class, and each class covers specific latitude belts.",
    "season": "Foliage state combined with the capture month reveals the hemisphere: green summer trees in July "
              "mean north; in January they mean south (or the tropics).",
    "heat": "With no unique landmark, an honest answer is a probability surface, not a pin. Every known populated "
            "place is scored by country likelihood × species ranges × climate × hemisphere (× vision similarity) "
            "and the hottest regions are listed.",
}
