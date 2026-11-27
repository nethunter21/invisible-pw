"""GEOINT knowledge base.

Each *probe group* is a family of visual clues that human geolocators use. The vision
engine scores every option with CLIP zero-shot matching; detected options push the
country posterior towards the listed countries and the `teach` text is shown in the UI
so the user learns the pattern.

Country lists may contain continent tokens: @EU @AS @AF @NA @SA @OC.
"""
from __future__ import annotations

LEFT_DRIVING = ("GB IE MT CY IN PK BD LK NP BT MV JP TH MY SG BN ID TL AU NZ PG FJ ZA LS SZ BW NA ZW ZM "
                "MZ MW TZ KE UG MU SC JM TT BB BS GY SR HK MO KY").split()

EX_USSR = "RU UA BY KZ UZ KG TJ TM AM AZ GE MD LT LV EE MN".split()
LATAM = "MX GT HN SV NI CR PA CO VE EC PE BO CL AR UY PY BR CU DO PR".split()
SEA = "TH VN KH LA MM MY ID PH SG".split()
MENA = "MA DZ TN LY EG SA AE QA KW BH OM YE JO IQ SY LB IL PS IR TR".split()

PROBES: list[dict] = [
    {
        "id": "scene", "title": "Scene type", "weight": 0.0,
        "teach": "First an analyst classifies the scene. Urban scenes give signage, architecture and street "
                 "furniture; rural scenes give vegetation, soil and road construction; indoor photos usually "
                 "give very little and should lower confidence.",
        "options": [
            {"label": "Urban street", "prompt": "a photo of a city street with buildings", "countries": []},
            {"label": "Rural road", "prompt": "a photo of a rural road in the countryside", "countries": []},
            {"label": "Highway", "prompt": "a photo of a multi-lane highway", "countries": []},
            {"label": "Coastline / beach", "prompt": "a photo of a beach or coastline", "countries": []},
            {"label": "Mountains", "prompt": "a photo of mountains", "countries": []},
            {"label": "Indoors", "prompt": "a photo taken indoors inside a room", "countries": []},
            {"label": "Aerial / satellite", "prompt": "an aerial or satellite photo of the ground", "countries": []},
            {"label": "Landmark / monument", "prompt": "a tourist photo of a famous landmark", "countries": []},
        ],
    },
    {
        "id": "driving", "title": "Driving side", "weight": 1.2,
        "teach": "About 75 countries drive on the left — mostly former British territories plus Japan, Thailand "
                 "and Indonesia. Look at which side parked cars face, which side of the car the driver sits, "
                 "and which lane oncoming traffic uses. This single clue removes roughly 2/3 of the world.",
        "options": [
            {"label": "Traffic drives on the LEFT", "prompt": "cars driving on the left side of the road",
             "countries": LEFT_DRIVING},
            {"label": "Traffic drives on the RIGHT", "prompt": "cars driving on the right side of the road",
             "countries": ["!LEFT"]},
            {"label": "No traffic visible", "prompt": "an empty place with no cars", "countries": []},
        ],
    },
    {
        "id": "script", "title": "Writing system on signs", "weight": 1.6,
        "teach": "Scripts are one of the strongest clues: Cyrillic narrows to the ex-USSR, Balkans and Mongolia; "
                 "Hangul is Korea; Thai script is Thailand; Georgian and Armenian alphabets are unique to one "
                 "country each. Even if you cannot read it, recognising the script's shapes is enough.",
        "options": [
            {"label": "Latin alphabet", "prompt": "a sign with text in the Latin alphabet",
             "countries": ["@EU", "@NA", "@SA", "@OC", "TR", "VN", "ID", "MY", "PH"]},
            {"label": "Cyrillic", "prompt": "a sign with Cyrillic text in Russian",
             "countries": EX_USSR + ["RS", "BG", "MK", "ME", "BA"]},
            {"label": "Arabic script", "prompt": "a sign with Arabic writing",
             "countries": MENA + ["PK", "AF"]},
            {"label": "Chinese characters", "prompt": "a sign with Chinese characters",
             "countries": ["CN", "TW", "HK", "MO", "SG"]},
            {"label": "Japanese (kana + kanji)", "prompt": "a sign with Japanese text", "countries": ["JP"]},
            {"label": "Korean Hangul", "prompt": "a sign with Korean hangul text", "countries": ["KR", "KP"]},
            {"label": "Thai script", "prompt": "a sign with Thai script", "countries": ["TH"]},
            {"label": "Devanagari (Hindi/Nepali)", "prompt": "a sign with Hindi Devanagari text",
             "countries": ["IN", "NP"]},
            {"label": "Hebrew", "prompt": "a sign with Hebrew text", "countries": ["IL"]},
            {"label": "Greek", "prompt": "a sign with Greek letters", "countries": ["GR", "CY"]},
            {"label": "Georgian", "prompt": "a sign with Georgian script", "countries": ["GE"]},
            {"label": "Bengali", "prompt": "a sign with Bengali script", "countries": ["BD", "IN"]},
            {"label": "Ethiopic (Ge'ez)", "prompt": "a sign with Amharic Ethiopic script", "countries": ["ET", "ER"]},
            {"label": "Khmer / Lao / Burmese", "prompt": "a sign with Khmer or Burmese script",
             "countries": ["KH", "LA", "MM"]},
            {"label": "No readable text", "prompt": "a photo with no text or signs", "countries": []},
        ],
    },
    {
        "id": "architecture", "title": "Architecture", "weight": 0.9,
        "teach": "Buildings encode climate, history and building codes. Steep roofs mean snow; flat roofs mean "
                 "dry climates; Soviet prefab panel blocks survive from Berlin to Vladivostok; whitewashed "
                 "cubes are Mediterranean; rooftop water tanks and exposed rebar are typical of South Asia and "
                 "the Middle East. Look at roof shape, wall material, window style and balcony design.",
        "options": [
            {"label": "Soviet prefab panel blocks", "prompt": "Soviet era concrete panel apartment blocks",
             "countries": EX_USSR + ["PL", "CZ", "SK", "HU", "RO", "BG", "RS", "DE"],
             "explain": "Khrushchyovka / panelák blocks were mass-produced across the Eastern Bloc 1955–1990."},
            {"label": "Mediterranean whitewashed houses", "prompt": "whitewashed Mediterranean houses with blue doors",
             "countries": ["GR", "ES", "IT", "PT", "MA", "TN", "CY", "MT", "HR"],
             "explain": "Lime-washed walls reflect heat; common on Aegean islands, Andalusia and the Maghreb."},
            {"label": "Haussmann-style stone apartments", "prompt": "Parisian Haussmann style stone apartment buildings",
             "countries": ["FR", "BE", "ES", "AR"],
             "explain": "Cream stone, wrought-iron balconies, mansard zinc roofs — Paris, copied in Brussels and Buenos Aires."},
            {"label": "British brick terraced houses", "prompt": "British red brick terraced houses",
             "countries": ["GB", "IE"],
             "explain": "Rows of identical brick houses with chimneys and bay windows are a UK/Ireland hallmark."},
            {"label": "Dutch gabled houses", "prompt": "Dutch canal houses with gabled facades",
             "countries": ["NL", "BE"], "explain": "Narrow brick houses with step/neck gables and hoist beams."},
            {"label": "Scandinavian painted wooden houses", "prompt": "red painted wooden houses in Scandinavia",
             "countries": ["SE", "NO", "FI", "DK", "IS"],
             "explain": "Falu-red or white timber houses with white trim dominate rural Sweden and Norway."},
            {"label": "Alpine chalets", "prompt": "alpine wooden chalets with balconies and flowers",
             "countries": ["CH", "AT", "DE", "IT", "FR", "SI"],
             "explain": "Wide overhanging roofs and wooden balconies — Alps of Switzerland, Austria, Bavaria, Tyrol."},
            {"label": "German half-timbered", "prompt": "German half-timbered houses",
             "countries": ["DE", "FR", "GB", "DK", "CH"], "explain": "Fachwerk: exposed timber frame with plaster infill."},
            {"label": "North-American suburban houses", "prompt": "American suburban houses with siding and front lawns",
             "countries": ["US", "CA"],
             "explain": "Vinyl/wood siding, attached garages, no fences, wide driveways — USA and Canada."},
            {"label": "Spanish-colonial / Latin American", "prompt": "colorful Spanish colonial buildings in Latin America",
             "countries": LATAM + ["PH"],
             "explain": "Bright stucco façades, grilles on windows, central plazas — Mexico to Peru, also the Philippines."},
            {"label": "Unfinished brick / favela", "prompt": "unfinished red brick houses in a favela",
             "countries": ["BR", "CO", "VE", "PE", "BO", "MX"],
             "explain": "Exposed hollow clay bricks with concrete frames, built incrementally — informal Latin American settlements."},
            {"label": "Middle-Eastern flat-roof concrete", "prompt": "beige concrete buildings with flat roofs in the Middle East",
             "countries": MENA + ["PK", "AF"],
             "explain": "Sand-coloured concrete, flat roofs, small windows — hot arid climates."},
            {"label": "Indian multi-storey with water tanks", "prompt": "Indian buildings with black water tanks on the roof",
             "countries": ["IN", "PK", "BD", "NP", "LK"],
             "explain": "Black Sintex water tanks, exposed rebar on roofs, colourful paint — South Asia."},
            {"label": "Southeast-Asian shophouses", "prompt": "southeast asian shophouses with tangled power lines",
             "countries": SEA + ["CN", "TW"],
             "explain": "Narrow 2–4 storey shophouses with ground-floor shops and arcades."},
            {"label": "Vietnamese tube houses", "prompt": "narrow tall Vietnamese tube houses", "countries": ["VN"],
             "explain": "Extremely narrow, tall, colourful façades because frontage width was taxed."},
            {"label": "Japanese houses", "prompt": "Japanese residential houses with tiled roofs", "countries": ["JP"],
             "explain": "Small detached houses, grey tiled roofs, tiny gaps between houses, vending machines."},
            {"label": "Chinese high-rise estates", "prompt": "Chinese high-rise residential towers",
             "countries": ["CN", "HK", "TW", "SG", "KR"],
             "explain": "Dense identical 25–40 storey towers in gated estates."},
            {"label": "Korean apartment towers", "prompt": "Korean apartment buildings with large numbers painted on the side",
             "countries": ["KR"], "explain": "Apartment blocks with huge complex numbers painted on the façade."},
            {"label": "Ottoman / Turkish", "prompt": "Turkish buildings with mosques and minarets",
             "countries": ["TR", "BA", "AL", "MK", "CY", "AZ"],
             "explain": "Pencil minarets, domed mosques, bay-windowed wooden upper floors."},
            {"label": "Andean adobe", "prompt": "adobe houses in the Andes mountains",
             "countries": ["PE", "BO", "EC", "AR", "CL"], "explain": "Mud-brick houses with tin or tile roofs at altitude."},
            {"label": "African corrugated-roof houses", "prompt": "African houses with corrugated metal roofs",
             "countries": ["@AF"], "explain": "Single-storey block houses with iron sheet roofs, common across sub-Saharan Africa."},
            {"label": "Australian suburban", "prompt": "Australian suburban house with metal roof and veranda",
             "countries": ["AU", "NZ"], "explain": "Corrugated 'Colorbond' roofs, verandas, red brick or weatherboard."},
            {"label": "Modern glass skyscrapers", "prompt": "modern glass skyscrapers in a business district",
             "countries": [], "explain": "Generic globally — low location value on its own."},
        ],
    },
    {
        "id": "roofs", "title": "Roof material", "weight": 0.4,
        "teach": "Roofs are visible even in aerial imagery. Terracotta tiles are Mediterranean/Latin; slate is "
                 "north-western Europe; corrugated iron is the tropics and Australia; flat concrete roofs mean "
                 "low rainfall; glazed curved tiles suggest East Asia.",
        "options": [
            {"label": "Terracotta tile roofs", "prompt": "houses with orange terracotta tile roofs",
             "countries": ["ES", "PT", "IT", "FR", "HR", "GR", "MX", "BR", "CL", "AR", "UY", "SI", "HU", "PL", "DE"]},
            {"label": "Corrugated metal roofs", "prompt": "houses with corrugated metal roofs",
             "countries": ["@AF", "AU", "NZ", "IN", "BD", "PH", "ID", "PG", "HT", "BR", "IS"]},
            {"label": "Flat concrete roofs", "prompt": "buildings with flat concrete roofs",
             "countries": MENA + ["IN", "PK", "MX", "EG"]},
            {"label": "Thatched roofs", "prompt": "huts with thatched straw roofs",
             "countries": ["@AF", "PG", "MG", "KH", "LA"]},
            {"label": "Slate / dark tile roofs", "prompt": "houses with dark grey slate roofs",
             "countries": ["GB", "IE", "FR", "DE", "BE", "NL", "LU", "JP"]},
            {"label": "Coloured metal roofs", "prompt": "houses with green and red painted metal roofs",
             "countries": ["RU", "UA", "BY", "KZ", "NO", "FI", "IS", "CL"]},
        ],
    },
    {
        "id": "vegetation", "title": "Vegetation & biome", "weight": 0.6,
        "teach": "Plants map to climate (Köppen zones). Birch and spruce mean boreal north; eucalyptus suggests "
                 "Australia (or plantations in Brazil, Portugal, South Africa); palms mean tropics or "
                 "subtropics; rice paddies point to monsoon Asia; savanna acacias point to East/Southern Africa.",
        "options": [
            {"label": "Tropical rainforest / palms", "prompt": "lush tropical vegetation with palm trees",
             "countries": SEA + ["BR", "CO", "EC", "PE", "VE", "CR", "PA", "NG", "GH", "CM", "LK", "IN", "PR", "DO"]},
            {"label": "Boreal conifer & birch forest", "prompt": "a boreal forest of birch and spruce trees",
             "countries": ["RU", "FI", "SE", "NO", "CA", "EE", "LV", "US"]},
            {"label": "Temperate deciduous forest", "prompt": "a green temperate deciduous forest",
             "countries": ["@EU", "US", "CA", "JP", "KR", "CN"]},
            {"label": "Mediterranean scrub & olive trees", "prompt": "dry Mediterranean landscape with olive trees",
             "countries": ["ES", "PT", "IT", "GR", "TR", "HR", "MA", "TN", "IL", "CY", "AL"]},
            {"label": "Desert", "prompt": "a sandy desert landscape",
             "countries": MENA + ["US", "MX", "CL", "PE", "AU", "NA", "MN", "KZ", "UZ", "TM"]},
            {"label": "Savanna with acacias", "prompt": "African savanna with acacia trees",
             "countries": ["KE", "TZ", "UG", "ZA", "BW", "NA", "ZW", "ZM", "ET", "SN"]},
            {"label": "Eucalyptus / gum trees", "prompt": "eucalyptus gum trees along a road",
             "countries": ["AU", "PT", "ES", "BR", "UY", "ZA", "CL", "ET"]},
            {"label": "Rice paddies", "prompt": "green rice paddy fields",
             "countries": SEA + ["CN", "IN", "BD", "LK", "JP", "KR", "NP"]},
            {"label": "Steppe grassland", "prompt": "flat open steppe grassland",
             "countries": ["KZ", "MN", "RU", "UA", "AR", "US"]},
            {"label": "Tundra / barren", "prompt": "barren tundra with no trees",
             "countries": ["IS", "NO", "RU", "CA", "GL", "FO"]},
        ],
    },
    {
        "id": "roads", "title": "Road markings & surface", "weight": 0.6,
        "teach": "Road lines are standardised per country. A yellow centre line means the Americas (also Japan, "
                 "Korea and a few others for no-passing). Europe uses white centre lines; Nordic countries "
                 "use yellow centre lines too. Red-dirt roads point to Brazil, sub-Saharan Africa or Australia.",
        "options": [
            {"label": "Yellow centre line", "prompt": "a road with a yellow center line",
             "countries": ["US", "CA", "MX", "BR", "AR", "CL", "PE", "CO", "NO", "SE", "FI", "IS", "JP", "KR", "ZA", "TH"]},
            {"label": "White centre line", "prompt": "a road with white dashed center lines",
             "countries": ["@EU", "RU", "TR", "AU", "NZ", "IN", "ID", "MY", "PH", "CN"]},
            {"label": "Red dirt road", "prompt": "an unpaved red dirt road",
             "countries": ["BR", "AU", "@AF", "PY", "BO"]},
            {"label": "Cobblestone street", "prompt": "an old cobblestone street",
             "countries": ["PT", "BE", "NL", "DE", "PL", "CZ", "FR", "IT", "BR", "LT", "UY"]},
            {"label": "Unmarked rural road", "prompt": "a narrow road with no lane markings",
             "countries": []},
        ],
    },
    {
        "id": "poles", "title": "Utility poles & wires", "weight": 0.4,
        "teach": "Pole material and wiring are surprisingly country-specific. Wooden poles with transformers are "
                 "North America, Japan and Australia; perforated concrete poles are Eastern Europe and Latin "
                 "America; chaotic bundles of cables are South/Southeast Asia; no overhead lines at all suggests "
                 "Western Europe where cables are buried.",
        "options": [
            {"label": "Wooden utility poles", "prompt": "wooden utility poles with power lines along a street",
             "countries": ["US", "CA", "JP", "AU", "NZ", "GB", "IE", "FI", "SE", "NO", "PH"]},
            {"label": "Concrete utility poles", "prompt": "concrete electricity poles along a road",
             "countries": EX_USSR + ["PL", "RO", "BG", "HU", "MX", "AR", "CL", "BR", "TH", "VN", "TR"]},
            {"label": "Tangled overhead cables", "prompt": "a messy tangle of electrical wires on poles",
             "countries": SEA + ["IN", "BD", "PK", "BR", "PE", "MX", "EG", "JP"]},
            {"label": "No overhead lines", "prompt": "a clean street with no power lines",
             "countries": ["DE", "NL", "BE", "FR", "CH", "AT", "DK", "SG", "GB"]},
        ],
    },
    {
        "id": "vehicles", "title": "Vehicles", "weight": 0.6,
        "teach": "The vehicle mix reflects income, import rules and culture: tuk-tuks in South/Southeast Asia, "
                 "swarms of scooters in Vietnam and Taiwan, kei-cars in Japan, pickup trucks in the US, "
                 "marshrutka minibuses in the ex-USSR, matatus and boda-bodas in East Africa.",
        "options": [
            {"label": "Auto-rickshaws / tuk-tuks", "prompt": "auto rickshaws tuk tuks on the street",
             "countries": ["IN", "TH", "LK", "PK", "BD", "KH", "EG", "PE", "NP"]},
            {"label": "Many motor scooters", "prompt": "a street full of motor scooters",
             "countries": ["VN", "TW", "ID", "TH", "IN", "MY", "PH", "KH", "IT"]},
            {"label": "Japanese kei cars", "prompt": "small boxy Japanese kei cars", "countries": ["JP"]},
            {"label": "Pickup trucks / large SUVs", "prompt": "large american pickup trucks",
             "countries": ["US", "CA", "MX", "AU"]},
            {"label": "Yellow taxis", "prompt": "yellow taxi cabs", "countries": ["US", "IN", "MX", "BR", "CO", "AR"]},
            {"label": "Minibus taxis", "prompt": "crowded minibus taxis",
             "countries": EX_USSR + ["ZA", "KE", "NG", "GH", "TZ", "UG", "SN"]},
            {"label": "No vehicles", "prompt": "a scene with no vehicles", "countries": []},
        ],
    },
    {
        "id": "signs", "title": "Road-sign style", "weight": 0.5,
        "teach": "The Vienna Convention (most of Europe, Asia, Africa) uses red-bordered triangles and circles; "
                 "the Americas, Australia and parts of Asia use yellow diamond warning signs; green highway "
                 "signs are US/Latin America/Australia, blue motorway signs are much of Europe.",
        "options": [
            {"label": "Yellow diamond warning signs", "prompt": "a yellow diamond shaped road warning sign",
             "countries": ["US", "CA", "MX", "AU", "NZ", "BR", "AR", "CO", "CL", "PE", "JP", "TH", "MY", "PH", "ID", "IE"]},
            {"label": "European red-bordered triangle signs", "prompt": "a white triangular road sign with a red border",
             "countries": ["@EU", "RU", "TR", "CN", "IL", "MA", "ZA"]},
            {"label": "Green highway direction signs", "prompt": "a green highway direction sign",
             "countries": ["US", "CA", "MX", "AU", "NZ", "BR", "CL", "CN", "JP", "TH", "IT", "CH"]},
            {"label": "Blue motorway signs", "prompt": "a blue motorway direction sign",
             "countries": ["FR", "DE", "ES", "GB", "NL", "BE", "PL", "PT", "SE", "RU", "JP", "KR", "IN"]},
            {"label": "No road signs", "prompt": "no road signs", "countries": []},
        ],
    },
    {
        "id": "terrain", "title": "Soil & terrain", "weight": 0.35,
        "teach": "Soil colour comes from geology: red laterite (iron oxide) dominates Brazil, central Africa, India "
                 "and Australia; black volcanic soil suggests Iceland, Canaries, Hawaii, Indonesia; snow and "
                 "high mountains narrow latitude and altitude.",
        "options": [
            {"label": "Red laterite soil", "prompt": "bright red soil on the ground",
             "countries": ["BR", "AU", "@AF", "IN", "PY"]},
            {"label": "Black volcanic ground", "prompt": "black volcanic rock and lava fields",
             "countries": ["IS", "ES", "US", "ID", "JP", "IT", "CR", "NZ"]},
            {"label": "Snow-covered", "prompt": "snow covered ground", "countries": ["RU", "CA", "FI", "SE", "NO", "IS", "US", "JP", "KZ", "MN"]},
            {"label": "Rugged high mountains", "prompt": "high rugged snowy mountains",
             "countries": ["CH", "AT", "IT", "FR", "NP", "PE", "BO", "CL", "AR", "KG", "TJ", "CN", "US", "CA", "NZ", "NO"]},
            {"label": "Flat farmland", "prompt": "flat agricultural farmland",
             "countries": ["US", "CA", "UA", "RU", "AR", "FR", "DE", "PL", "HU", "NL", "AU"]},
        ],
    },
    {
        "id": "sky", "title": "Light & climate", "weight": 0.25,
        "teach": "Haze, light quality and sky colour hint at climate. Harsh overhead light with short shadows "
                 "means low latitude or midday; long warm shadows mean high latitude, winter or early/late day. "
                 "Grey overcast is typical of oceanic north-west Europe.",
        "options": [
            {"label": "Overcast grey sky", "prompt": "a grey overcast cloudy sky",
             "countries": ["GB", "IE", "NL", "BE", "DE", "DK", "NO", "SE", "PL", "RU", "FR"]},
            {"label": "Harsh bright sun", "prompt": "harsh bright midday sun with short shadows",
             "countries": MENA + LATAM + SEA + ["@AF", "IN", "AU"]},
            {"label": "Humid hazy air", "prompt": "hazy humid polluted air", "countries": ["IN", "CN", "BD", "PK", "VN", "TH", "ID", "EG"]},
            {"label": "Night time", "prompt": "a photo taken at night", "countries": []},
        ],
    },
]


def expand(tokens: list[str], all_isos: list[str]) -> set[str]:
    from .gazetteer import by_continent
    out: set[str] = set()
    for t in tokens:
        if t.startswith("@"):
            out |= set(by_continent(t[1:]))
        elif t == "!LEFT":
            out |= set(all_isos) - set(LEFT_DRIVING)
        else:
            out.add(t)
    return out & set(all_isos)


# --- Text-clue knowledge (OCR) -------------------------------------------------------

STREET_WORDS: dict[str, tuple[list[str], str]] = {
    "strasse": (["DE", "AT", "CH"], "German 'Straße' (street)"),
    "straße": (["DE", "AT", "CH"], "German 'Straße' (street)"),
    "gasse": (["AT", "CH", "DE"], "German 'Gasse' (lane), common in Austria/Switzerland"),
    "platz": (["DE", "AT", "CH"], "German 'Platz' (square)"),
    "rue": (["FR", "BE", "CH", "CA", "LU"], "French 'rue' (street)"),
    "avenue": (["FR", "US", "CA", "BE", "GB"], "'avenue'"),
    "calle": (["ES", "MX", "AR", "CO", "CL", "PE", "VE", "CU", "UY"], "Spanish 'calle' (street)"),
    "avenida": (["ES", "MX", "BR", "AR", "PT", "CO", "VE", "CL", "PE"], "Spanish/Portuguese 'avenida'"),
    "carrera": (["CO"], "'Carrera' numbered streets are typically Colombian"),
    "rua": (["BR", "PT"], "Portuguese 'rua' (street)"),
    "travessa": (["BR", "PT"], "Portuguese 'travessa' (alley)"),
    "via": (["IT", "CH"], "Italian 'via' (street)"),
    "piazza": (["IT", "CH"], "Italian 'piazza' (square)"),
    "ulica": (["PL", "HR", "SI", "RS", "SK"], "Slavic 'ulica' (street)"),
    "ul": (["PL", "RU", "UA", "BY"], "'ul.' abbreviation of ulica/ulitsa"),
    "utca": (["HU"], "Hungarian 'utca' (street)"),
    "ulice": (["CZ"], "Czech 'ulice'"),
    "straat": (["NL", "BE"], "Dutch 'straat' (street)"),
    "weg": (["NL", "DE", "BE", "CH"], "Dutch/German 'weg' (road)"),
    "gatan": (["SE"], "Swedish '-gatan' (the street)"),
    "gata": (["SE"], "Swedish 'gata'"),
    "gate": (["NO"], "Norwegian '-gate' (street)"),
    "vej": (["DK"], "Danish '-vej' (road)"),
    "vei": (["NO"], "Norwegian 'vei' (road)"),
    "katu": (["FI"], "Finnish '-katu' (street)"),
    "tie": (["FI"], "Finnish '-tie' (road)"),
    "iela": (["LV"], "Latvian 'iela' (street)"),
    "gatve": (["LT"], "Lithuanian 'gatvė'"),
    "tanav": (["EE"], "Estonian 'tänav'"),
    "sokak": (["TR"], "Turkish 'sokak' (street)"),
    "cadde": (["TR"], "Turkish 'cadde' (avenue)"),
    "caddesi": (["TR"], "Turkish 'caddesi'"),
    "odos": (["GR", "CY"], "Greek 'odos' (street) in Latin transliteration"),
    "jalan": (["ID", "MY"], "Malay/Indonesian 'jalan' (road)"),
    "jl": (["ID"], "'Jl.' — Indonesian street abbreviation"),
    "lorong": (["MY", "SG"], "Malay 'lorong' (lane)"),
    "soi": (["TH"], "Thai 'soi' (side street)"),
    "thanon": (["TH"], "Thai 'thanon' (road)"),
    "duong": (["VN"], "Vietnamese 'đường' (road)"),
    "pho": (["VN"], "Vietnamese 'phố' (street)"),
    "marg": (["IN", "NP"], "Hindi 'marg' (road)"),
    "nagar": (["IN"], "Hindi 'nagar' (town/colony)"),
    "chowk": (["IN", "PK", "NP"], "'chowk' (crossroads)"),
    "barangay": (["PH"], "Philippine 'barangay' (district)"),
    "brgy": (["PH"], "Philippine 'Brgy.' abbreviation"),
    "sharia": (["EG"], "Arabic 'shari' (street) transliteration, Egypt"),
    "boulevard": (["FR", "US", "BE", "CA"], "'boulevard'"),
    "piata": (["RO"], "Romanian 'piața' (square)"),
    "strada": (["RO", "IT"], "'strada' (street) — Romania or Italy"),
    "plaza": (["ES", "MX", "US", "AR", "PH"], "Spanish 'plaza'"),
    "carretera": (["ES", "MX"], "Spanish 'carretera' (highway)"),
    "rodovia": (["BR"], "Portuguese 'rodovia' (highway), Brazil"),
    "autostrada": (["IT", "PL"], "'autostrada' (motorway)"),
    "autobahn": (["DE", "AT"], "German 'Autobahn'"),
    "autoroute": (["FR", "BE", "CH", "CA"], "French 'autoroute'"),
    "snelweg": (["NL"], "Dutch motorway"),
    "motorway": (["GB", "IE", "NZ"], "British English 'motorway'"),
    "freeway": (["US", "AU", "ZA"], "'freeway'"),
    "interstate": (["US"], "US Interstate highway system"),
    "highway": (["US", "CA", "AU", "NZ", "PH", "IN"], "'highway'"),
    "drive": (["US", "CA", "AU", "NZ", "GB"], "English 'Drive' street suffix"),
    "close": (["GB", "AU", "NZ", "ZA"], "'Close' cul-de-sac suffix — British usage"),
    "crescent": (["GB", "AU", "NZ", "CA", "IE"], "'Crescent' — Commonwealth street suffix"),
}

WORDS_LANG: dict[str, tuple[list[str], str]] = {
    "ausfahrt": (["DE", "AT"], "German 'exit'"), "einbahnstrasse": (["DE", "AT", "CH"], "German one-way"),
    "sortie": (["FR", "BE", "CH", "CA"], "French 'exit'"), "salida": (["ES", "MX", "AR", "CO", "CL", "PE"], "Spanish 'exit'"),
    "saida": (["BR", "PT"], "Portuguese 'exit'"), "uscita": (["IT"], "Italian 'exit'"),
    "uitrit": (["NL"], "Dutch 'exit'"), "utfart": (["SE", "NO"], "Scandinavian 'exit'"),
    "zjazd": (["PL"], "Polish 'exit'"), "farmacia": (["ES", "IT", "MX", "AR", "CO"], "'farmacia'"),
    "farmacie": (["RO"], "Romanian pharmacy"), "apotheke": (["DE", "AT", "CH"], "German pharmacy"),
    "apteka": (["PL", "RU", "UA"], "Slavic pharmacy"), "eczane": (["TR"], "Turkish pharmacy"),
    "pharmacie": (["FR", "BE", "CH", "MA", "TN", "SN"], "French pharmacy"), "drogaria": (["BR"], "Brazilian drugstore"),
    "panaderia": (["ES", "MX", "AR", "CO"], "Spanish bakery"), "boulangerie": (["FR", "BE", "CH"], "French bakery"),
    "bakkerij": (["NL", "BE"], "Dutch bakery"), "backerei": (["DE", "AT"], "German bakery"),
    "piekarnia": (["PL"], "Polish bakery"), "sklep": (["PL"], "Polish shop"), "obchod": (["CZ", "SK"], "Czech shop"),
    "warung": (["ID"], "Indonesian food stall"), "kedai": (["MY"], "Malay shop"), "sari-sari": (["PH"], "Filipino store"),
    "tienda": (["ES", "MX", "AR", "CO", "PE"], "Spanish shop"), "loja": (["BR", "PT"], "Portuguese shop"),
    "negozio": (["IT"], "Italian shop"), "magasin": (["FR"], "French shop"), "butik": (["SE", "DK", "TR"], "shop"),
    "kauppa": (["FI"], "Finnish shop"), "bolt": (["HU"], "Hungarian shop"), "vendita": (["IT"], "Italian 'for sale'"),
    "se vende": (["ES", "MX", "AR", "CO"], "Spanish 'for sale'"), "vende-se": (["BR", "PT"], "Portuguese 'for sale'"),
    "zu verkaufen": (["DE", "AT", "CH"], "German 'for sale'"), "a vendre": (["FR", "BE", "CH", "CA"], "French 'for sale'"),
    "te koop": (["NL", "BE"], "Dutch 'for sale'"), "sprzedam": (["PL"], "Polish 'for sale'"),
    "satilik": (["TR"], "Turkish 'for sale'"), "dijual": (["ID", "MY"], "Indonesian 'for sale'"),
    "stop": ([], "STOP (international)"), "pare": (["BR", "PT", "CO", "VE", "PE"], "'PARE' stop sign"),
    "alto": (["MX", "GT", "HN", "SV", "NI", "CR", "PA", "CL", "AR"], "'ALTO' stop sign"),
    "arret": (["CA"], "'ARRÊT' stop sign — Québec"), "dur": (["TR"], "Turkish stop sign 'DUR'"),
    "pulis": (["PH"], "Filipino police"), "polizei": (["DE", "AT", "CH"], "German police"),
    "politie": (["NL", "BE"], "Dutch police"), "policja": (["PL"], "Polish police"),
    "carabinieri": (["IT"], "Italian Carabinieri"), "gendarmerie": (["FR", "BE"], "French Gendarmerie"),
    "guardia civil": (["ES"], "Spanish Guardia Civil"), "garda": (["IE"], "Irish Garda"),
    "mairie": (["FR"], "French town hall"), "ayuntamiento": (["ES"], "Spanish town hall"),
    "gemeente": (["NL", "BE"], "Dutch municipality"), "rathaus": (["DE", "AT", "CH"], "German town hall"),
    "kommune": (["NO", "DK"], "Nordic municipality"), "kunta": (["FI"], "Finnish municipality"),
    "prefeitura": (["BR"], "Brazilian city hall"), "municipalidad": (["PE", "AR", "CL", "CR"], "Spanish municipality"),
    "zone 30": ([], "speed zone"), "taman": (["ID", "MY"], "Malay 'park'"), "kampung": (["MY", "ID"], "Malay village"),
    "ristorante": (["IT"], "Italian restaurant"), "trattoria": (["IT"], "Italian eatery"),
    "taqueria": (["MX", "US"], "Mexican taco shop"), "churrascaria": (["BR"], "Brazilian steakhouse"),
    "kebab": (["TR", "DE"], "kebab"), "pub": (["GB", "IE", "AU", "NZ"], "pub"),
    "chemist": (["GB", "AU", "NZ"], "British 'chemist' (pharmacy)"), "takeaway": (["GB", "IE", "AU", "NZ"], "British 'takeaway'"),
    "liquor": (["US", "CA", "AU"], "'liquor store'"), "bottle-o": (["AU"], "Australian bottle shop"),
}

CURRENCY = {
    "€": (["@EU"], "Euro sign"), "£": (["GB"], "Pound sterling"), "₹": (["IN"], "Indian rupee"),
    "₽": (["RU"], "Russian rouble"), "₺": (["TR"], "Turkish lira"), "₩": (["KR"], "Korean won"),
    "฿": (["TH"], "Thai baht"), "₫": (["VN"], "Vietnamese dong"), "₱": (["PH"], "Philippine peso"),
    "₴": (["UA"], "Ukrainian hryvnia"), "₦": (["NG"], "Nigerian naira"), "₪": (["IL"], "Israeli shekel"),
    "R$": (["BR"], "Brazilian real"), "zł": (["PL"], "Polish złoty"), "Kč": (["CZ"], "Czech koruna"),
    "Ft": (["HU"], "Hungarian forint"), "lei": (["RO", "MD"], "Romanian leu"), "RM": (["MY"], "Malaysian ringgit"),
    "Rp": (["ID"], "Indonesian rupiah"), "S/": (["PE"], "Peruvian sol"), "¥": (["JP", "CN"], "Yen / Yuan"),
}

DIACRITICS = {
    "ß": (["DE", "AT", "CH"], "German ß"), "ä": (["DE", "AT", "CH", "FI", "SE", "EE"], "a-umlaut"),
    "ö": (["DE", "AT", "CH", "FI", "SE", "TR", "HU"], "o-umlaut"), "ü": (["DE", "AT", "CH", "TR", "HU"], "u-umlaut"),
    "ñ": (["ES", "MX", "AR", "CO", "CL", "PE", "VE"], "Spanish ñ"), "ã": (["BR", "PT"], "Portuguese ã"),
    "õ": (["BR", "PT", "EE"], "õ"), "ç": (["FR", "PT", "BR", "TR", "AL"], "cedilla ç"),
    "ø": (["NO", "DK"], "Danish/Norwegian ø"), "å": (["SE", "NO", "DK", "FI"], "Nordic å"),
    "æ": (["NO", "DK", "IS"], "æ"), "ł": (["PL"], "Polish ł"), "ż": (["PL", "MT"], "Polish ż"),
    "ő": (["HU"], "Hungarian ő"), "ű": (["HU"], "Hungarian ű"), "ř": (["CZ"], "Czech ř"),
    "ě": (["CZ"], "Czech ě"), "ğ": (["TR"], "Turkish ğ"), "ı": (["TR", "AZ"], "dotless ı"),
    "ş": (["TR", "RO", "AZ"], "ş"), "ț": (["RO"], "Romanian ț"), "đ": (["VN", "HR", "RS", "BA"], "đ"),
    "ơ": (["VN"], "Vietnamese ơ"), "ư": (["VN"], "Vietnamese ư"), "þ": (["IS"], "Icelandic thorn"),
    "ð": (["IS", "FO"], "Icelandic eth"), "ė": (["LT"], "Lithuanian ė"), "ā": (["LV"], "Latvian macron"),
}
