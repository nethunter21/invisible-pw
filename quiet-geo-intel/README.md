# Quiet Geo Intel

Geopolitical + weather trading intelligence terminal. Single Windows executable, no API keys.

**Run:** double-click `QuietGeoIntel.exe`. It opens in an app window (Edge/Chrome) or your default browser at `http://127.0.0.1:8787`.
The app quits on its own a few minutes after you close the window, or use SOURCES → Quit.

**Data (free, keyless):** GDACS, USGS, NASA EONET, NOAA NHC, BBC / Al Jazeera / Defense News and other RSS feeds, GDELT, Yahoo Finance quotes, Open-Meteo models, RainViewer radar, NASA GIBS imagery, Polymarket (read-only).

**Build:** `GOOS=windows GOARCH=amd64 go build -ldflags "-H windowsgui -s -w" -o dist/QuietGeoIntel.exe .`

Event-to-asset mappings are historical associations, not advice.
