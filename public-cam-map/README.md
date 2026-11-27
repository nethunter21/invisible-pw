# Quiet Lens — global webcam intel

Lightweight map of **public cameras published by their operators** (road authorities, cities, tourism webcams). Double-click `QuietLens.exe`.

Keyless sources: Lyon Criter, Grenoble Métromobilité, OpenStreetMap public webcam listings (worldwide, load as you zoom), TfL London (video clips), NYC DOT, Caltrans (live HLS streams), Hong Kong TD, Fintraffic Digitraffic, Singapore LTA, Transport for NSW, NZTA.
Optional: a free Windy Webcams API key (⚙ Settings) adds thousands of public webcams with live players, especially across France.

Ethics: no private or unsecured cameras are ever listed.

Build: `GOOS=windows GOARCH=amd64 go build -ldflags "-H windowsgui -s -w" -o dist/QuietLens.exe .`
