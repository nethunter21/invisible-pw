# GeoLens: automated GEOINT image geolocation

GeoLens is a Windows desktop app (`GeoLens.exe`). Drop in a photo and it estimates where the photo was taken. It shows the answer on a map with a confidence score, and it explains **how** it got there, so you also learn the techniques.

It needs **no API keys and no accounts**. Everything except the optional web lookups runs locally on your PC.

![layout](assets/geolens.png)

## What it does

| Technique | How | Online? |
|---|---|---|
| **Visual geolocation** | [StreetCLIP](https://huggingface.co/geolocal/StreetCLIP) (CLIP ViT-L/14@336, fine-tuned on 1.1M street-level images) scores 230+ countries zero-shot. It looks at the whole image and at 5–7 overlapping crops, then weights each crop by how confident it is (entropy). After that it refines the guess against roughly 15k GeoNames cities. | local |
| **Pattern recognition (teachable clues)** | 12 probe families with about 120 hypotheses: driving side, writing system, architecture (Soviet panel blocks, Haussmann, Dutch gables, favela brick, Indian rooftop water tanks…), roof material, vegetation and biome, road markings, utility poles, vehicles, road-sign conventions, soil and terrain, light and climate. Each clue comes with an explanation of how analysts use it. | local |
| **Attention maps** | Grad-CAM for Vision Transformers (gradient × activation of the last block). It shows which pixels pushed the model towards the country and towards key clues, plus 3×3 region shares. | local |
| **OCR + linguistics** | RapidOCR (PP-OCRv4, ONNX) reads the text in the image. Rule-based analysis then checks phone prefixes, ccTLD domains, street-type words (Straße, Rua, Jalan, Soi…), shop and street vocabulary, diacritics, currency symbols, Unicode scripts and place names (offline gazetteer with local spellings such as Lisboa, München, Moskva). | local |
| **Metadata** | EXIF GPS, capture time, UTC offset, camera, heading. GPS overrides the visual guess, and the visual clues are then used as a cross-check. | local |
| **Sun & shadows** | NOAA solar-position algorithm. You click an object and its shadow on the image to get the sun elevation. GeoLens then plots the **circle of equal altitude** (every place on Earth where the sun stood at that angle at that moment), or does **chronolocation** (the time of day at the pinned spot). It also checks that EXIF time and image brightness agree. | local |
| **Reverse image search** | Yandex (automatic upload, parses results, extracts place names), TinEye (exact copies), plus one-click Google Lens and Bing uploads that open in your browser. | yes |
| **Geocoding** | OpenStreetMap Nominatim (1 request/s, no key) for street names read in the image. | yes |
| **Evidence fusion** | Log-linear fusion: `log P(country) = log P_visual + Σ weight × [country ∈ clue]`. The pin uses the most specific reliable evidence, in this order: GPS → geocoded sign → repeated reverse-search places → place name read in the image → visual city similarity. | – |

### The Log button

**Log** (or press `L`) opens a timeline of every step. For each step it shows:
- the technique and algorithm used (for example "CLIP zero-shot probe (23 hypotheses)" or "Grad-CAM for ViT")
- what it found, with timing and the raw data
- a **"How analysts use this"** box that teaches the pattern
- a summary of **which part of the image mattered most** (the share each crop contributed to the winning country, plus attention hot-spots) and a ranked bar chart of **the evidence used in the final decision**

## Download / run

1. Download `GeoLens-windows-x64.zip` from the GitHub Actions artifact (workflow **Build GeoLens (Windows .exe)**), or from a Release if you push a `geolens-v*` tag.
2. Unzip it and run `GeoLens\GeoLens.exe`.
3. On first run the vision model downloads once (StreetCLIP ≈ 1.7 GB) to `%LOCALAPPDATA%\GeoLens\models`. After that it works offline.
   - In **Settings** you can switch to *CLIP ViT-B/32* (≈ 600 MB, faster on weak CPUs) and turn the online techniques off for sensitive images.

The window uses Microsoft Edge WebView2, which is preinstalled on Windows 10/11. Command-line options:

```
GeoLens.exe --browser      # use your default browser instead of the native window
GeoLens.exe --no-vision    # metadata + OCR + reverse search only
```

## Build it yourself

```bat
build_windows.bat          :: creates .venv, installs CPU torch + deps, runs PyInstaller
dist\GeoLens\GeoLens.exe
```

Or from source on any OS: `pip install -r requirements.txt && python GeoLens.py --browser`.

Tests: `python tests/make_tiny_clip.py %TEMP%\tiny && python tests/test_pipeline.py %TEMP%\tiny`. This builds a tiny random CLIP so the tests need no downloads.

## Honest notes

- **Accuracy.** Commercial tools like GeoSpy/Raven are trained on far larger proprietary datasets. StreetCLIP is the strongest open, key-less model for this job, and it is very good at country and region level for outdoor street scenes. City-level answers are reliable mainly when text, reverse search or metadata supports them. Indoor photos and close-ups carry little signal, and the confidence score drops to reflect that.
- **Reverse search** uses the engines' public web upload forms. Engines change their markup and sometimes show captchas. When that happens GeoLens falls back to opening the result page in your browser. Respect each site's terms and rate limits.
- **Privacy.** Online techniques upload the image to the engine you use. Turn them off in Settings when that matters.
- **Data.** City and country data come from GeoNames (CC-BY 4.0, via `geonamescache`). Map tiles are from Esri, OpenStreetMap and OpenTopoMap.
