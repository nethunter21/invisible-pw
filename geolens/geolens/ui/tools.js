/* GeoLens manual investigation toolkit.
   {lat} {lon} {q} {date} {time} are filled from the current pin / picked point / selected text. */
"use strict";
const OVERPASS = {
  "Bridges": 'way["bridge"="yes"]({{bbox}});',
  "Water towers": 'nwr["man_made"="water_tower"]({{bbox}});',
  "Churches / mosques / temples": 'nwr["amenity"="place_of_worship"]({{bbox}});',
  "Wind turbines": 'node["generator:source"="wind"]({{bbox}});',
  "Power-line towers": 'node["power"="tower"]({{bbox}});',
  "Railway lines": 'way["railway"="rail"]({{bbox}});',
  "Rivers & canals": 'way["waterway"~"river|canal"]({{bbox}});',
  "Lakes & ponds": 'nwr["natural"="water"]({{bbox}});',
  "Peaks": 'node["natural"="peak"]({{bbox}});',
  "Viewpoints": 'node["tourism"="viewpoint"]({{bbox}});',
  "Tree rows (e.g. poplar lines)": 'way["natural"="tree_row"]({{bbox}});',
  "Stadiums": 'nwr["leisure"="stadium"]({{bbox}});',
  "Lighthouses": 'nwr["man_made"="lighthouse"]({{bbox}});',
  "Fuel stations": 'nwr["amenity"="fuel"]({{bbox}});',
};
const overpassURL = (body) => "https://overpass-turbo.eu/?Q=" + encodeURIComponent(`[out:json][timeout:60];\n(\n  ${body}\n);\nout geom;`) + "&R";

const TOOLKIT = [
  { cat: "Street-level imagery", items: [
    ["Google Street View", "https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lon}", "Opens the nearest panorama to the point. Compare skyline, poles, kerbs and vegetation with the photo; use the time slider (clock icon) for older captures."],
    ["Mapillary", "https://www.mapillary.com/app/?lat={lat}&lng={lon}&z=15", "Crowd-sourced street imagery — covers many places Google never drove (tracks, villages, footpaths). Green lines = sequences you can walk along."],
    ["KartaView", "https://kartaview.org/map/@{lat},{lon},15z", "Another open street-level archive, strong in Eastern Europe and the US."],
    ["Yandex Panoramas", "https://yandex.com/maps/?ll={lon},{lat}&z=16&l=stv%2Csta", "Best street-level coverage for Russia, Ukraine, Belarus, Kazakhstan, Turkey and parts of the Balkans."],
    ["Bing Streetside", "https://www.bing.com/maps?cp={lat}~{lon}&lvl=17&style=x", "Microsoft's street imagery; sometimes newer or older than Google — useful for change detection."],
  ]},
  { cat: "Satellite & historical imagery", items: [
    ["Google Maps satellite", "https://www.google.com/maps/@{lat},{lon},2500m/data=!3m1!1e3", "Match river bends, tree lines, field patterns and roof layouts seen in the photo. Switch to 3D (tilt) for building heights."],
    ["Google Earth (web, 3D)", "https://earth.google.com/web/@{lat},{lon},400a,2500d,35y,0h,60t,0r", "Tilt to ground level and rotate until the skyline/ridge lines match the photo — the classic 'horizon matching' technique."],
    ["Esri Wayback", "https://livingatlas.arcgis.com/wayback/#mapCenter={lon}%2C{lat}%2C16", "Every Esri satellite release since 2014 — date a photo by when a building, road or clearing appears."],
    ["Copernicus Browser (Sentinel-2)", "https://browser.dataspace.copernicus.eu/?zoom=13&lat={lat}&lng={lon}", "Free 10 m imagery every ~5 days since 2015. Check flooding, snow, crops or fires on the photo's date."],
    ["Bing aerial / bird's eye", "https://www.bing.com/maps?cp={lat}~{lon}&lvl=17&style=h", "Different capture dates and oblique 'bird's eye' views in many cities."],
    ["Apple Maps satellite", "https://maps.apple.com/?ll={lat},{lon}&t=k&z=16", "Independent imagery provider; Look Around (Apple's street view) opens in the Maps app."],
  ]},
  { cat: "Map data & feature search", items: [
    ["OpenStreetMap", "https://www.openstreetmap.org/#map=15/{lat}/{lon}", "Inspect any object (query tool, right-click) to see tags: names, building types, tree rows, power lines."],
    ["Overpass Turbo", "OVERPASS", "Find every feature of a type in the visible map area — e.g. all bridges over rivers or all water towers around the candidate region. Pan the map to your search area, then press Run."],
    ["Wikimapia", "https://wikimapia.org/#lat={lat}&lon={lon}&z=15&m=w", "User-annotated buildings and areas — good for factories, campuses and local names."],
    ["OSM search (Nominatim)", "https://nominatim.openstreetmap.org/ui/search.html?q={q}", "Geocode a name read in the image (shop, street, village). Select text in the TEXT tab first."],
  ]},
  { cat: "Terrain, mountains & horizon", items: [
    ["PeakVisor", "https://peakvisor.com/panorama.html?lat={lat}&lng={lon}", "3D panorama with every summit labelled — match mountain silhouettes in the photo."],
    ["PeakFinder", "https://www.peakfinder.com/?lat={lat}&lng={lon}&name=GeoLens", "Renders the horizon line from any point; drag the viewpoint until the ridge profile matches."],
    ["OpenTopoMap", "https://opentopomap.org/#map=13/{lat}/{lon}", "Contours and relief — check whether the terrain in the photo (flat plain, valley, slope) fits the candidate."],
    ["Köppen climate map", "https://koppen.earth/", "Check whether the vegetation in the photo fits the climate zone of the candidate."],
  ]},
  { cat: "Sun, shadows & weather", items: [
    ["SunCalc", "https://www.suncalc.org/#/{lat},{lon},15/{date}/{time}/1/3", "Sun azimuth and elevation for any place and time — compare with shadow directions in the photo. Use the in-app SHADOW tool for the inverse problem."],
    ["Meteostat (weather history)", "https://meteostat.net/en/", "Historical weather by station — verify clouds, rain or snow on the claimed date."],
    ["Weather Underground history", "https://www.wunderground.com/history", "Hourly historical observations — useful to confirm or refute a timestamp."],
  ]},
  { cat: "Photos taken nearby", items: [
    ["Flickr map", "https://www.flickr.com/map/?fLat={lat}&fLon={lon}&zl=14", "Geotagged photos around the candidate — often the exact viewpoint has been photographed before."],
    ["Wikimedia Commons nearby", "https://commons.wikimedia.org/wiki/Special:Nearby#/coord/{lat},{lon}", "Freely-licensed, precisely geotagged photos of buildings, bridges and landscapes."],
    ["Google Maps photos", "https://www.google.com/maps/search/?api=1&query={lat},{lon}", "Open the place and browse user photos / 360° spheres."],
    ["Snap Map", "https://map.snapchat.com/@{lat},{lon},13.00z", "Recent public snaps around a location — good for current events."],
  ]},
  { cat: "Reverse image search (manual)", items: [
    ["Yandex Images", "https://yandex.com/images/", "Best for scenery, buildings and Eastern Europe. Crop to the background first (or use the crop buttons above)."],
    ["Google Lens", "https://lens.google.com/", "Best for landmarks, products, logos and text."],
    ["Bing Visual Search", "https://www.bing.com/visualsearch", "Different index from Google — try it when Lens fails."],
    ["TinEye", "https://tineye.com/", "Exact copies, sorted by oldest — finds the original upload and its caption."],
    ["Baidu Images", "https://graph.baidu.com/pcpage/index?tpl_from=pc", "Strongest index for China and Chinese-language sites."],
  ]},
  { cat: "Text, language & identification", items: [
    ["Google Translate (image)", "https://translate.google.com/?op=images", "Upload a sign crop: OCR + translation for 100+ scripts."],
    ["Yandex Translate (image)", "https://translate.yandex.com/ocr", "Strong for Cyrillic, Turkish and Central Asian languages."],
    ["DeepL", "https://www.deepl.com/translator#auto/en/{q}", "High-quality translation of text read in the image."],
    ["Google search (quoted text)", "https://www.google.com/search?q=%22{q}%22", "Search an exact phrase from a sign, shop or poster."],
    ["Plonkit country guides", "https://www.plonkit.net/guide", "Country-by-country guide to bollards, poles, plates, road lines, signs and scripts."],
    ["GeoHints", "https://geohints.com/", "Visual reference sheets: bollards, utility poles, licence plates, road markings, chevrons per country."],
    ["World licence plates", "http://www.worldlicenseplates.com/", "Identify a plate format and its country/region."],
    ["iNaturalist species map", "https://www.inaturalist.org/taxa/search?q={q}", "Look up a plant/tree and view its observed range map."],
    ["Pl@ntNet identify", "https://identify.plantnet.org/", "Upload a plant crop to identify the species, then check its range."],
  ]},
  { cat: "Metadata & forensics", items: [
    ["EXIF.tools", "https://exif.tools/", "Full metadata dump including maker notes — camera serials, lens, timezone offsets."],
    ["FotoForensics (ELA)", "https://fotoforensics.com/", "Error-level analysis and metadata — detect edits before trusting visual clues."],
    ["Forensically", "https://29a.ch/photo-forensics/", "Clone detection, noise analysis, magnifier — runs in the browser."],
  ]},
];

function fillTool(tpl, ctx) {
  return tpl.replace(/\{lat\}/g, ctx.lat.toFixed(6)).replace(/\{lon\}/g, ctx.lon.toFixed(6))
    .replace(/\{q\}/g, encodeURIComponent(ctx.q || "")).replace(/\{date\}/g, ctx.date).replace(/\{time\}/g, ctx.time);
}
