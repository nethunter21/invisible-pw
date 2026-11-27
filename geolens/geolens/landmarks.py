"""Landmark / brand / venue knowledge base.

Used three ways:
  1. fuzzy-matched against OCR text (signs, rooftop logos — also mirrored ones),
  2. fuzzy-matched against reverse-image-search page titles,
  3. as zero-shot prompts for the vision model ("a photo of Bellagio, Las Vegas").

Coordinates are venue-level (≈100 m). Multi-site brands list every site; the site
closest to the other evidence wins during fusion.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from functools import lru_cache

# name, aliases, lat, lon, city, cc, kind
_L = [
    # ---------------------------------------------------------------- Las Vegas
    ("Bellagio", ["bellagio las vegas"], 36.1129, -115.1765, "Las Vegas", "US", "casino"),
    ("Caesars Palace", ["caesars"], 36.1162, -115.1745, "Las Vegas", "US", "casino"),
    ("The Venetian", ["venetian resort", "venetian"], 36.1212, -115.1697, "Las Vegas", "US", "casino"),
    ("The Palazzo", ["palazzo"], 36.1240, -115.1684, "Las Vegas", "US", "casino"),
    ("Wynn Las Vegas", ["wynn"], 36.1265, -115.1657, "Las Vegas", "US", "casino"),
    ("Encore Las Vegas", ["encore"], 36.1290, -115.1650, "Las Vegas", "US", "casino"),
    ("The Cosmopolitan", ["cosmopolitan of las vegas", "cosmopolitan"], 36.1097, -115.1740, "Las Vegas", "US", "casino"),
    ("Aria Resort", ["aria"], 36.1073, -115.1766, "Las Vegas", "US", "casino"),
    ("Vdara", [], 36.1094, -115.1777, "Las Vegas", "US", "hotel"),
    ("Waldorf Astoria Las Vegas", ["waldorf astoria"], 36.1081, -115.1736, "Las Vegas", "US", "hotel"),
    ("MGM Grand", ["mgm grand las vegas"], 36.1024, -115.1695, "Las Vegas", "US", "casino"),
    ("The Signature at MGM Grand", ["signature at mgm"], 36.1066, -115.1655, "Las Vegas", "US", "hotel"),
    ("Mandalay Bay", ["mandalay"], 36.0909, -115.1750, "Las Vegas", "US", "casino"),
    ("Delano Las Vegas", ["delano"], 36.0921, -115.1771, "Las Vegas", "US", "hotel"),
    ("Luxor Las Vegas", ["luxor"], 36.0955, -115.1761, "Las Vegas", "US", "casino"),
    ("Excalibur", ["excalibur hotel"], 36.0988, -115.1754, "Las Vegas", "US", "casino"),
    ("New York-New York", ["new york new york hotel", "nyny"], 36.1023, -115.1745, "Las Vegas", "US", "casino"),
    ("Park MGM", ["nomad las vegas"], 36.1047, -115.1749, "Las Vegas", "US", "casino"),
    ("Paris Las Vegas", ["paris las vegas"], 36.1125, -115.1707, "Las Vegas", "US", "casino"),
    ("Planet Hollywood", ["planet hollywood"], 36.1100, -115.1717, "Las Vegas", "US", "casino"),
    ("Horseshoe Las Vegas", ["ballys las vegas", "bally's"], 36.1143, -115.1688, "Las Vegas", "US", "casino"),
    ("Flamingo Las Vegas", ["flamingo"], 36.1162, -115.1708, "Las Vegas", "US", "casino"),
    ("The LINQ", ["linq hotel", "linq promenade"], 36.1176, -115.1709, "Las Vegas", "US", "casino"),
    ("High Roller", ["high roller wheel"], 36.1175, -115.1680, "Las Vegas", "US", "landmark"),
    ("Harrah's Las Vegas", ["harrahs"], 36.1195, -115.1715, "Las Vegas", "US", "casino"),
    ("Hard Rock Las Vegas", ["the mirage", "mirage"], 36.1212, -115.1741, "Las Vegas", "US", "casino"),
    ("Treasure Island", ["ti hotel", "treasure island las vegas"], 36.1247, -115.1721, "Las Vegas", "US", "casino"),
    ("Resorts World Las Vegas", ["resorts world", "crockfords", "conrad las vegas"], 36.1340, -115.1650, "Las Vegas", "US", "casino"),
    ("Fontainebleau Las Vegas", ["fontainebleau"], 36.1366, -115.1603, "Las Vegas", "US", "casino"),
    ("Sahara Las Vegas", ["sahara"], 36.1418, -115.1563, "Las Vegas", "US", "casino"),
    ("The STRAT", ["stratosphere", "strat tower"], 36.1475, -115.1566, "Las Vegas", "US", "landmark"),
    ("Circus Circus", [], 36.1370, -115.1640, "Las Vegas", "US", "casino"),
    ("Tropicana Las Vegas", ["tropicana"], 36.0997, -115.1707, "Las Vegas", "US", "casino"),
    ("Westgate Las Vegas", ["westgate"], 36.1361, -115.1520, "Las Vegas", "US", "casino"),
    ("Trump International Hotel Las Vegas", ["trump international", "trump hotel"], 36.1295, -115.1720, "Las Vegas", "US", "hotel"),
    ("Rio Las Vegas", ["rio all suite"], 36.1173, -115.1872, "Las Vegas", "US", "casino"),
    ("Palms Casino Resort", ["palms"], 36.1142, -115.1956, "Las Vegas", "US", "casino"),
    ("Sphere", ["msg sphere", "sphere las vegas"], 36.1207, -115.1621, "Las Vegas", "US", "landmark"),
    ("Allegiant Stadium", [], 36.0909, -115.1833, "Las Vegas", "US", "landmark"),
    ("T-Mobile Arena", ["tmobile arena"], 36.1028, -115.1784, "Las Vegas", "US", "landmark"),
    ("Las Vegas Convention Center", ["lvcc"], 36.1314, -115.1517, "Las Vegas", "US", "landmark"),
    ("Virgin Hotels Las Vegas", ["virgin hotels"], 36.1093, -115.1560, "Las Vegas", "US", "hotel"),
    ("Polo Towers", [], 36.1050, -115.1717, "Las Vegas", "US", "hotel"),
    ("Jockey Club Las Vegas", ["jockey club"], 36.1115, -115.1735, "Las Vegas", "US", "hotel"),
    ("Marriott's Grand Chateau", ["grand chateau"], 36.1100, -115.1655, "Las Vegas", "US", "hotel"),
    ("Platinum Hotel Las Vegas", [], 36.1117, -115.1628, "Las Vegas", "US", "hotel"),
    ("Hilton Grand Vacations Club Elara", ["elara", "hilton elara"], 36.1093, -115.1689, "Las Vegas", "US", "hotel"),
    ("Hilton Grand Vacations Club Paradise", ["hgv paradise"], 36.1362, -115.1540, "Las Vegas", "US", "hotel"),
    ("Hilton Grand Vacations Club on the Boulevard", ["hgv boulevard"], 36.1385, -115.1594, "Las Vegas", "US", "hotel"),
    ("Fremont Street Experience", ["fremont street"], 36.1708, -115.1439, "Las Vegas", "US", "landmark"),
    ("Golden Nugget Las Vegas", ["golden nugget"], 36.1704, -115.1453, "Las Vegas", "US", "casino"),
    ("Welcome to Fabulous Las Vegas sign", ["welcome to fabulous las vegas"], 36.0820, -115.1728, "Las Vegas", "US", "landmark"),
    ("Las Vegas Strip", ["the strip", "las vegas boulevard", "las vegas blvd"], 36.1147, -115.1728, "Las Vegas", "US", "district"),
    # ---------------------------------------------------------------- multi-site brands (hotel signs are frequent rooftop text)
    ("Hilton Grand Vacations", ["hilton grand vacations club", "hgv"], 36.1093, -115.1689, "Las Vegas", "US", "brand"),
    ("Hilton Grand Vacations", ["hilton grand vacations club"], 28.3878, -81.4826, "Orlando", "US", "brand"),
    ("Hilton Grand Vacations", ["hilton grand vacations club"], 21.2840, -157.8380, "Honolulu", "US", "brand"),
    ("Hilton Grand Vacations", ["hilton grand vacations club"], 40.7655, -73.9775, "New York", "US", "brand"),
    ("Atlantis The Palm", ["atlantis dubai"], 25.1304, 55.1171, "Dubai", "AE", "hotel"),
    ("Atlantis Paradise Island", ["atlantis bahamas"], 25.0866, -77.3233, "Nassau", "BS", "hotel"),
    # ---------------------------------------------------------------- USA
    ("Statue of Liberty", [], 40.6892, -74.0445, "New York", "US", "landmark"),
    ("Empire State Building", [], 40.7484, -73.9857, "New York", "US", "landmark"),
    ("Times Square", [], 40.7580, -73.9855, "New York", "US", "landmark"),
    ("One World Trade Center", ["freedom tower", "one wtc"], 40.7127, -74.0134, "New York", "US", "landmark"),
    ("Chrysler Building", [], 40.7516, -73.9755, "New York", "US", "landmark"),
    ("Brooklyn Bridge", [], 40.7061, -73.9969, "New York", "US", "landmark"),
    ("Central Park", [], 40.7829, -73.9654, "New York", "US", "landmark"),
    ("Flatiron Building", [], 40.7411, -73.9897, "New York", "US", "landmark"),
    ("Golden Gate Bridge", [], 37.8199, -122.4783, "San Francisco", "US", "landmark"),
    ("Transamerica Pyramid", [], 37.7952, -122.4028, "San Francisco", "US", "landmark"),
    ("Hollywood Sign", [], 34.1341, -118.3215, "Los Angeles", "US", "landmark"),
    ("Hollywood Walk of Fame", ["hollywood boulevard"], 34.1016, -118.3267, "Los Angeles", "US", "landmark"),
    ("Santa Monica Pier", [], 34.0083, -118.4988, "Santa Monica", "US", "landmark"),
    ("Space Needle", [], 47.6205, -122.3493, "Seattle", "US", "landmark"),
    ("Willis Tower", ["sears tower"], 41.8789, -87.6359, "Chicago", "US", "landmark"),
    ("Cloud Gate", ["the bean"], 41.8827, -87.6233, "Chicago", "US", "landmark"),
    ("Gateway Arch", [], 38.6247, -90.1848, "St. Louis", "US", "landmark"),
    ("United States Capitol", ["us capitol"], 38.8899, -77.0091, "Washington", "US", "landmark"),
    ("Washington Monument", [], 38.8895, -77.0353, "Washington", "US", "landmark"),
    ("Lincoln Memorial", [], 38.8893, -77.0502, "Washington", "US", "landmark"),
    ("White House", [], 38.8977, -77.0365, "Washington", "US", "landmark"),
    ("Cinderella Castle", ["magic kingdom"], 28.4195, -81.5812, "Orlando", "US", "landmark"),
    ("Miami Beach Ocean Drive", ["ocean drive"], 25.7814, -80.1300, "Miami Beach", "US", "landmark"),
    ("Hoover Dam", [], 36.0160, -114.7377, "Boulder City", "US", "landmark"),
    ("Grand Canyon", [], 36.0544, -112.1401, "Grand Canyon Village", "US", "landmark"),
    ("Mount Rushmore", [], 43.8791, -103.4591, "Keystone", "US", "landmark"),
    ("Alamo", ["the alamo"], 29.4260, -98.4861, "San Antonio", "US", "landmark"),
    ("Reunion Tower", [], 32.7755, -96.8089, "Dallas", "US", "landmark"),
    ("French Quarter", ["bourbon street"], 29.9584, -90.0644, "New Orleans", "US", "district"),
    ("Waikiki Beach", ["waikiki"], 21.2793, -157.8292, "Honolulu", "US", "landmark"),
    # ---------------------------------------------------------------- Canada / Latin America
    ("CN Tower", [], 43.6426, -79.3871, "Toronto", "CA", "landmark"),
    ("Niagara Falls", [], 43.0828, -79.0742, "Niagara Falls", "CA", "landmark"),
    ("Chateau Frontenac", ["château frontenac"], 46.8119, -71.2050, "Quebec City", "CA", "landmark"),
    ("Christ the Redeemer", ["cristo redentor"], -22.9519, -43.2105, "Rio de Janeiro", "BR", "landmark"),
    ("Sugarloaf Mountain", ["pao de acucar"], -22.9492, -43.1545, "Rio de Janeiro", "BR", "landmark"),
    ("Copacabana", [], -22.9711, -43.1822, "Rio de Janeiro", "BR", "landmark"),
    ("Obelisco de Buenos Aires", ["obelisco"], -34.6037, -58.3816, "Buenos Aires", "AR", "landmark"),
    ("Machu Picchu", [], -13.1631, -72.5450, "Machu Picchu", "PE", "landmark"),
    ("Chichen Itza", [], 20.6843, -88.5678, "Chichén Itzá", "MX", "landmark"),
    ("Angel de la Independencia", ["angel of independence"], 19.4270, -99.1677, "Mexico City", "MX", "landmark"),
    ("Palacio de Bellas Artes", [], 19.4352, -99.1412, "Mexico City", "MX", "landmark"),
    ("Panama Canal Miraflores", ["miraflores locks"], 8.9966, -79.5913, "Panama City", "PA", "landmark"),
    # ---------------------------------------------------------------- Europe
    ("Eiffel Tower", ["tour eiffel", "eiffel"], 48.8584, 2.2945, "Paris", "FR", "landmark"),
    ("Arc de Triomphe", [], 48.8738, 2.2950, "Paris", "FR", "landmark"),
    ("Louvre", ["musee du louvre"], 48.8606, 2.3376, "Paris", "FR", "landmark"),
    ("Notre-Dame de Paris", ["notre dame"], 48.8530, 2.3499, "Paris", "FR", "landmark"),
    ("Sacre-Coeur", ["sacre coeur", "montmartre"], 48.8867, 2.3431, "Paris", "FR", "landmark"),
    ("Mont Saint-Michel", [], 48.6361, -1.5115, "Mont-Saint-Michel", "FR", "landmark"),
    ("Big Ben", ["elizabeth tower", "palace of westminster"], 51.5007, -0.1246, "London", "GB", "landmark"),
    ("London Eye", [], 51.5033, -0.1196, "London", "GB", "landmark"),
    ("Tower Bridge", [], 51.5055, -0.0754, "London", "GB", "landmark"),
    ("The Shard", [], 51.5045, -0.0865, "London", "GB", "landmark"),
    ("30 St Mary Axe", ["the gherkin", "gherkin"], 51.5145, -0.0803, "London", "GB", "landmark"),
    ("Buckingham Palace", [], 51.5014, -0.1419, "London", "GB", "landmark"),
    ("St Paul's Cathedral", ["st pauls cathedral"], 51.5138, -0.0984, "London", "GB", "landmark"),
    ("Piccadilly Circus", [], 51.5100, -0.1347, "London", "GB", "landmark"),
    ("Edinburgh Castle", [], 55.9486, -3.1999, "Edinburgh", "GB", "landmark"),
    ("Colosseum", ["colosseo"], 41.8902, 12.4922, "Rome", "IT", "landmark"),
    ("Trevi Fountain", ["fontana di trevi"], 41.9009, 12.4833, "Rome", "IT", "landmark"),
    ("St. Peter's Basilica", ["vatican", "basilica di san pietro"], 41.9022, 12.4539, "Vatican City", "VA", "landmark"),
    ("Leaning Tower of Pisa", ["torre di pisa"], 43.7230, 10.3966, "Pisa", "IT", "landmark"),
    ("Milan Cathedral", ["duomo di milano"], 45.4642, 9.1916, "Milan", "IT", "landmark"),
    ("Florence Cathedral", ["duomo di firenze", "santa maria del fiore"], 43.7731, 11.2560, "Florence", "IT", "landmark"),
    ("Rialto Bridge", ["ponte di rialto"], 45.4380, 12.3359, "Venice", "IT", "landmark"),
    ("St Mark's Square", ["piazza san marco"], 45.4341, 12.3388, "Venice", "IT", "landmark"),
    ("Sagrada Familia", [], 41.4036, 2.1744, "Barcelona", "ES", "landmark"),
    ("Park Guell", ["park güell"], 41.4145, 2.1527, "Barcelona", "ES", "landmark"),
    ("Alhambra", [], 37.1761, -3.5881, "Granada", "ES", "landmark"),
    ("Puerta del Sol", ["plaza mayor madrid"], 40.4169, -3.7035, "Madrid", "ES", "landmark"),
    ("Plaza de Espana Sevilla", ["plaza de españa"], 37.3772, -5.9869, "Seville", "ES", "landmark"),
    ("Belem Tower", ["torre de belem"], 38.6916, -9.2160, "Lisbon", "PT", "landmark"),
    ("Brandenburg Gate", ["brandenburger tor"], 52.5163, 13.3777, "Berlin", "DE", "landmark"),
    ("Berlin TV Tower", ["fernsehturm"], 52.5208, 13.4094, "Berlin", "DE", "landmark"),
    ("Reichstag", [], 52.5186, 13.3762, "Berlin", "DE", "landmark"),
    ("Cologne Cathedral", ["kölner dom", "koelner dom"], 50.9413, 6.9583, "Cologne", "DE", "landmark"),
    ("Neuschwanstein Castle", ["schloss neuschwanstein"], 47.5576, 10.7498, "Schwangau", "DE", "landmark"),
    ("Marienplatz", [], 48.1374, 11.5755, "Munich", "DE", "landmark"),
    ("Atomium", [], 50.8949, 4.3415, "Brussels", "BE", "landmark"),
    ("Grand Place", ["grote markt brussel"], 50.8467, 4.3525, "Brussels", "BE", "landmark"),
    ("Rijksmuseum", [], 52.3600, 4.8852, "Amsterdam", "NL", "landmark"),
    ("Amsterdam Centraal", [], 52.3791, 4.9003, "Amsterdam", "NL", "landmark"),
    ("Prague Castle", ["prazsky hrad"], 50.0911, 14.4016, "Prague", "CZ", "landmark"),
    ("Charles Bridge", ["karluv most"], 50.0865, 14.4114, "Prague", "CZ", "landmark"),
    ("Hungarian Parliament", ["orszaghaz"], 47.5071, 19.0456, "Budapest", "HU", "landmark"),
    ("Schonbrunn Palace", ["schloss schönbrunn"], 48.1845, 16.3122, "Vienna", "AT", "landmark"),
    ("Saint Basil's Cathedral", ["st basils cathedral", "red square"], 55.7525, 37.6231, "Moscow", "RU", "landmark"),
    ("Moscow City", ["moscow international business center"], 55.7494, 37.5378, "Moscow", "RU", "landmark"),
    ("Hagia Sophia", ["ayasofya"], 41.0086, 28.9802, "Istanbul", "TR", "landmark"),
    ("Blue Mosque", ["sultan ahmed mosque"], 41.0054, 28.9768, "Istanbul", "TR", "landmark"),
    ("Galata Tower", ["galata kulesi"], 41.0256, 28.9741, "Istanbul", "TR", "landmark"),
    ("Acropolis", ["parthenon"], 37.9715, 23.7257, "Athens", "GR", "landmark"),
    ("Oia Santorini", ["santorini"], 36.4618, 25.3753, "Oia", "GR", "landmark"),
    ("Little Mermaid", ["nyhavn"], 55.6929, 12.5993, "Copenhagen", "DK", "landmark"),
    ("Stockholm City Hall", ["stadshuset"], 59.3275, 18.0547, "Stockholm", "SE", "landmark"),
    # ---------------------------------------------------------------- Middle East / Africa
    ("Burj Khalifa", [], 25.1972, 55.2744, "Dubai", "AE", "landmark"),
    ("Burj Al Arab", [], 25.1412, 55.1853, "Dubai", "AE", "landmark"),
    ("Museum of the Future", [], 25.2192, 55.2820, "Dubai", "AE", "landmark"),
    ("Dubai Frame", [], 25.2354, 55.3003, "Dubai", "AE", "landmark"),
    ("Ain Dubai", [], 25.0806, 55.1236, "Dubai", "AE", "landmark"),
    ("Dubai Marina", ["jbr"], 25.0805, 55.1403, "Dubai", "AE", "district"),
    ("Sheikh Zayed Grand Mosque", [], 24.4128, 54.4749, "Abu Dhabi", "AE", "landmark"),
    ("Kingdom Centre", ["kingdom tower riyadh"], 24.7114, 46.6744, "Riyadh", "SA", "landmark"),
    ("Al Faisaliyah Center", [], 24.6903, 46.6853, "Riyadh", "SA", "landmark"),
    ("Abraj Al Bait", ["makkah clock tower", "clock royal tower"], 21.4189, 39.8256, "Mecca", "SA", "landmark"),
    ("Masjid al-Haram", ["kaaba"], 21.4225, 39.8262, "Mecca", "SA", "landmark"),
    ("Doha Corniche", ["museum of islamic art"], 25.2948, 51.5390, "Doha", "QA", "landmark"),
    ("Western Wall", ["dome of the rock"], 31.7767, 35.2345, "Jerusalem", "IL", "landmark"),
    ("Petra", ["al khazneh", "treasury petra"], 30.3285, 35.4444, "Petra", "JO", "landmark"),
    ("Pyramids of Giza", ["great pyramid"], 29.9792, 31.1342, "Giza", "EG", "landmark"),
    ("Table Mountain", [], -33.9628, 18.4098, "Cape Town", "ZA", "landmark"),
    ("Jemaa el-Fnaa", ["jemaa el fna"], 31.6258, -7.9892, "Marrakesh", "MA", "landmark"),
    # ---------------------------------------------------------------- Asia / Oceania
    ("Petronas Towers", ["petronas twin towers", "klcc"], 3.1579, 101.7116, "Kuala Lumpur", "MY", "landmark"),
    ("Marina Bay Sands", [], 1.2834, 103.8607, "Singapore", "SG", "landmark"),
    ("Gardens by the Bay", ["supertree grove"], 1.2816, 103.8636, "Singapore", "SG", "landmark"),
    ("Merlion", [], 1.2868, 103.8545, "Singapore", "SG", "landmark"),
    ("Tokyo Tower", [], 35.6586, 139.7454, "Tokyo", "JP", "landmark"),
    ("Tokyo Skytree", [], 35.7101, 139.8107, "Tokyo", "JP", "landmark"),
    ("Shibuya Crossing", ["shibuya scramble"], 35.6595, 139.7005, "Tokyo", "JP", "landmark"),
    ("Senso-ji", ["sensoji", "kaminarimon"], 35.7148, 139.7967, "Tokyo", "JP", "landmark"),
    ("Fushimi Inari", [], 34.9671, 135.7727, "Kyoto", "JP", "landmark"),
    ("Osaka Castle", [], 34.6873, 135.5262, "Osaka", "JP", "landmark"),
    ("Dotonbori", ["glico man"], 34.6687, 135.5013, "Osaka", "JP", "landmark"),
    ("Oriental Pearl Tower", [], 31.2397, 121.4998, "Shanghai", "CN", "landmark"),
    ("Shanghai Tower", ["the bund"], 31.2335, 121.5056, "Shanghai", "CN", "landmark"),
    ("Forbidden City", ["tiananmen"], 39.9163, 116.3972, "Beijing", "CN", "landmark"),
    ("Great Wall Badaling", ["great wall of china"], 40.3594, 116.0201, "Beijing", "CN", "landmark"),
    ("Canton Tower", [], 23.1065, 113.3245, "Guangzhou", "CN", "landmark"),
    ("Victoria Harbour", ["ifc hong kong", "tsim sha tsui"], 22.2930, 114.1694, "Hong Kong", "HK", "landmark"),
    ("Taipei 101", [], 25.0340, 121.5645, "Taipei", "TW", "landmark"),
    ("Lotte World Tower", [], 37.5126, 127.1025, "Seoul", "KR", "landmark"),
    ("N Seoul Tower", ["namsan tower"], 37.5512, 126.9882, "Seoul", "KR", "landmark"),
    ("Gyeongbokgung", [], 37.5796, 126.9770, "Seoul", "KR", "landmark"),
    ("Taj Mahal", [], 27.1751, 78.0421, "Agra", "IN", "landmark"),
    ("Gateway of India", [], 18.9220, 72.8347, "Mumbai", "IN", "landmark"),
    ("India Gate", [], 28.6129, 77.2295, "New Delhi", "IN", "landmark"),
    ("Golden Temple", ["harmandir sahib"], 31.6200, 74.8765, "Amritsar", "IN", "landmark"),
    ("Wat Arun", [], 13.7437, 100.4888, "Bangkok", "TH", "landmark"),
    ("Grand Palace Bangkok", ["wat phra kaew"], 13.7500, 100.4913, "Bangkok", "TH", "landmark"),
    ("Angkor Wat", [], 13.4125, 103.8670, "Siem Reap", "KH", "landmark"),
    ("Sydney Opera House", [], -33.8568, 151.2153, "Sydney", "AU", "landmark"),
    ("Sydney Harbour Bridge", [], -33.8523, 151.2108, "Sydney", "AU", "landmark"),
    ("Flinders Street Station", [], -37.8183, 144.9671, "Melbourne", "AU", "landmark"),
    ("Sky Tower", ["skytower auckland"], -36.8485, 174.7622, "Auckland", "NZ", "landmark"),
]

# Extra cities for worldwide skyline recognition (beyond the population threshold)
TOURIST_CITIES = [
    ("Las Vegas", "US", 36.1716, -115.1391), ("Orlando", "US", 28.5383, -81.3792), ("Honolulu", "US", 21.3069, -157.8583),
    ("Miami", "US", 25.7617, -80.1918), ("Atlantic City", "US", 39.3643, -74.4229), ("New Orleans", "US", 29.9511, -90.0715),
    ("Reno", "US", 39.5296, -119.8138), ("Macau", "MO", 22.1987, 113.5439), ("Monaco", "MC", 43.7384, 7.4246),
    ("Venice", "IT", 45.4408, 12.3155), ("Dubrovnik", "HR", 42.6507, 18.0944), ("Santorini", "GR", 36.3932, 25.4615),
    ("Cancun", "MX", 21.1619, -86.8515), ("Benidorm", "ES", 38.5411, -0.1225), ("Gold Coast", "AU", -28.0167, 153.4000),
    ("Pattaya", "TH", 12.9236, 100.8825), ("Doha", "QA", 25.2854, 51.5310), ("Abu Dhabi", "AE", 24.4539, 54.3773),
    ("Panama City", "PA", 8.9824, -79.5199), ("Batumi", "GE", 41.6168, 41.6367), ("Benalmadena", "ES", 36.5988, -4.5167),
]


def _compact(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]", "", s)


@lru_cache(maxsize=1)
def entries() -> list[dict]:
    out = []
    for i, (name, aliases, lat, lon, city, cc, kind) in enumerate(_L):
        keys = {_compact(name)} | {_compact(a) for a in aliases}
        out.append({"id": i, "name": name, "aliases": aliases, "lat": lat, "lon": lon, "city": city, "cc": cc,
                    "kind": kind, "keys": sorted(k for k in keys if len(k) >= 4)})
    return out


def unique_prompt_entries() -> list[dict]:
    """One entry per distinct name (multi-site brands collapsed) for vision prompts."""
    seen, out = set(), []
    for e in entries():
        if e["kind"] == "brand" or e["name"] in seen:
            continue
        seen.add(e["name"])
        out.append(e)
    return out


def match_text(text: str, min_ratio: float = 0.84) -> list[dict]:
    """Fuzzy-match landmark/brand names inside free text (OCR is noisy: 'HiltonGrandVacatious')."""
    comp = _compact(text)
    if len(comp) < 4:
        return []
    hits: dict[int, dict] = {}
    for e in entries():
        best = 0.0
        for k in e["keys"]:
            if len(k) < 5 and k not in comp:
                continue
            if k in comp:
                q = 1.0
            elif len(k) >= 8:
                # slide a window of len(k) over the compact text and take the best ratio
                L = len(k)
                q = 0.0
                for i in range(0, max(1, len(comp) - L + 1)):
                    r = difflib.SequenceMatcher(None, k, comp[i:i + L + 2]).ratio()
                    if r > q:
                        q = r
                        if q > 0.97:
                            break
            else:
                q = 0.0
            # short generic aliases ("aria", "palms", "rio") need an exact word to count
            if q == 1.0 and len(k) <= 5 and not re.search(rf"\b{re.escape(k)}\b", re.sub(r"[^a-z0-9 ]", " ", text.lower())):
                q = 0.0
            best = max(best, q)
        if best >= min_ratio:
            hits[e["id"]] = dict(e, quality=round(best, 3))
    return sorted(hits.values(), key=lambda h: -h["quality"])


TEACH = ("Named venues are the fastest route to an exact location: hotel and casino rooftop signs, stadiums, "
         "towers and brand logos. OCR output is noisy (and selfies are mirrored), so names are fuzzy-matched; "
         "brands with several sites (e.g. a hotel chain) are resolved by picking the site that agrees with the "
         "other evidence — skyline, vegetation, reverse-search hits.")
