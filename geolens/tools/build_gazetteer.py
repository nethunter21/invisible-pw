"""Build geolens/data/gazetteer.json from the offline geonamescache dataset (dev-time only)."""
import json, os, collections
import geonamescache

gc = geonamescache.GeonamesCache()
cities = gc.get_cities()
countries = gc.get_countries()
by_cc = collections.defaultdict(list)
for c in cities.values():
    by_cc[c["countrycode"]].append(c)

out_c, out_city, tzs = {}, [], []
for iso, co in countries.items():
    cl = sorted(by_cc.get(iso, []), key=lambda x: -x["population"])
    if not cl:
        continue
    w = sum(max(x["population"], 1) for x in cl[:30])
    lat = sum(x["latitude"] * max(x["population"], 1) for x in cl[:30]) / w
    lon = sum(x["longitude"] * max(x["population"], 1) for x in cl[:30]) / w
    out_c[iso] = dict(name=co["name"], continent=co["continentcode"], tld=co["tld"], phone=str(co["phone"]),
                      languages=[l.split("-")[0] for l in co["languages"].split(",") if l],
                      capital=co["capital"], lat=round(lat, 4), lon=round(lon, 4),
                      neighbours=[n for n in co["neighbours"].split(",") if n], area=co["areakm2"],
                      tz=cl[0].get("timezone") or "")
    for x in cl:
        if x["population"] >= 40000 or cl.index(x) < 12:
            tz = x.get("timezone") or ""
            if tz not in tzs:
                tzs.append(tz)
            row = [x["name"], iso, round(x["latitude"], 4), round(x["longitude"], 4), x["population"], tzs.index(tz)]
            if x["population"] >= 150000:  # local-language / Latin alternate spellings (Lisboa, München, Roma…)
                alts = [a for a in x.get("alternatenames", []) if a != x["name"] and 4 <= len(a) <= 30
                        and a[0].isupper() and not a.isupper() and all(ord(ch) < 0x250 for ch in a)]
                row.append(alts[:80])
            out_city.append(row)
path = os.path.join(os.path.dirname(__file__), "..", "geolens", "data", "gazetteer.json")
json.dump({"countries": out_c, "cities": out_city, "tz": tzs}, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(len(out_c), "countries", len(out_city), "cities", os.path.getsize(path) // 1024, "KB")
