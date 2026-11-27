package main

// Multi-source tropical cyclone aggregation. Each source is independent: if one fails
// (e.g. GDACS bot protection), the others still populate the tracker, and the failing
// source is reported in the response so the UI can show it as unavailable.

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"encoding/xml"
	"fmt"
	"io"
	"math"
	"net/http"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

type TrackPt struct {
	T   time.Time `json:"t"`
	Lat float64   `json:"lat"`
	Lon float64   `json:"lon"`
	Kt  float64   `json:"kt,omitempty"`
}

type Storm struct {
	ID       string          `json:"id"`
	Name     string          `json:"name"`
	Sources  []string        `json:"sources"`
	Current  bool            `json:"current"`
	Lat      float64         `json:"lat"`
	Lon      float64         `json:"lon"`
	WindKt   float64         `json:"windKt,omitempty"`
	WindKmh  float64         `json:"windKmh,omitempty"`
	Pressure string          `json:"pressure,omitempty"`
	Class    string          `json:"class,omitempty"`
	Alert    string          `json:"alert,omitempty"`
	Country  string          `json:"country,omitempty"`
	Region   string          `json:"region,omitempty"`
	Movement string          `json:"movement,omitempty"`
	Start    time.Time       `json:"start"`
	Updated  time.Time       `json:"updated"`
	Link     string          `json:"link,omitempty"`
	Graphics string          `json:"graphics,omitempty"`
	GEventID int             `json:"gdacsEventId,omitempty"`
	GEpisode int             `json:"gdacsEpisode,omitempty"`
	Exposure string          `json:"exposure,omitempty"`
	Track    []TrackPt       `json:"track,omitempty"`
	Forecast json.RawMessage `json:"forecast,omitempty"` // GeoJSON from NHC KMZ (official)
	Assets   []Asset         `json:"assets,omitempty"`
	Level    string          `json:"level"`
	Score    int             `json:"score"`
}

type cySource struct {
	Name  string `json:"name"`
	OK    bool   `json:"ok"`
	Items int    `json:"items"`
	Error string `json:"error,omitempty"`
}

func normName(s string) string {
	s = strings.ToUpper(s)
	s = regexp.MustCompile(`(?i)tropical cyclone|tropical storm|tropical depression|hurricane|typhoon|super|cyclone|storm|-\d{2}$`).ReplaceAllString(s, "")
	s = regexp.MustCompile(`[^A-Z0-9]`).ReplaceAllString(s, "")
	return s
}

func kmhToKt(v float64) float64 { return v / 1.852 }

func gdacsJSONStorms() ([]Storm, error) {
	const u = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH?eventlist=TC"
	b, _, err := cached("gdacs-tc-json", 5*time.Minute, func() ([]byte, error) { return fetch(u) })
	setStatus("GDACS cyclone API", u, "GDACS — EC JRC / UN", 0, err)
	if b == nil {
		return nil, err
	}
	var d struct {
		Features []struct {
			Geometry struct {
				C []float64 `json:"coordinates"`
			} `json:"geometry"`
			P struct {
				EventID   int    `json:"eventid"`
				EpisodeID int    `json:"episodeid"`
				Name      string `json:"eventname"`
				Alert     string `json:"alertlevel"`
				Current   string `json:"iscurrent"`
				Country   string `json:"country"`
				From      string `json:"fromdate"`
				To        string `json:"todate"`
				Mod       string `json:"datemodified"`
				Source    string `json:"source"`
				Sev       struct {
					V    float64 `json:"severity"`
					Text string  `json:"severitytext"`
				} `json:"severitydata"`
				URL struct {
					Report string `json:"report"`
				} `json:"url"`
			} `json:"properties"`
		} `json:"features"`
	}
	if e := json.Unmarshal(b, &d); e != nil {
		return nil, e
	}
	var out []Storm
	for _, f := range d.Features {
		p := f.P
		if len(f.Geometry.C) < 2 {
			continue
		}
		st := Storm{ID: fmt.Sprintf("gdacs-%d", p.EventID), Name: p.Name, Sources: []string{"GDACS" + srcSuffix(p.Source)}, Current: p.Current == "true",
			Lat: f.Geometry.C[1], Lon: f.Geometry.C[0], WindKmh: math.Round(p.Sev.V), WindKt: math.Round(kmhToKt(p.Sev.V)), Class: p.Sev.Text, Alert: p.Alert,
			Country: p.Country, Start: parseRFC(p.From), Updated: parseRFC(p.Mod), Link: p.URL.Report, GEventID: p.EventID, GEpisode: p.EpisodeID}
		if st.Updated.IsZero() {
			st.Updated = parseRFC(p.To)
		}
		out = append(out, st)
	}
	setStatus("GDACS cyclone API", u, "GDACS — EC JRC / UN", len(out), nil)
	return out, nil
}

func srcSuffix(s string) string {
	if s == "" {
		return ""
	}
	return " / " + s
}

func eonetStorms() ([]Storm, error) {
	const u = "https://eonet.gsfc.nasa.gov/api/v3/events?category=severeStorms&days=45"
	b, _, err := cached("eonet-storms", 10*time.Minute, func() ([]byte, error) { return fetch(u) })
	setStatus("NASA EONET storm tracks", u, "NASA EONET", 0, err)
	if b == nil {
		return nil, err
	}
	var d struct {
		Events []struct {
			ID      string `json:"id"`
			Title   string `json:"title"`
			Closed  any    `json:"closed"`
			Sources []struct {
				URL string `json:"url"`
			} `json:"sources"`
			Geometry []struct {
				Date string    `json:"date"`
				Mag  float64   `json:"magnitudeValue"`
				C    []float64 `json:"coordinates"`
			} `json:"geometry"`
		} `json:"events"`
	}
	if e := json.Unmarshal(b, &d); e != nil {
		return nil, e
	}
	tc := regexp.MustCompile(`(?i)tropical|typhoon|hurricane|cyclone`)
	var out []Storm
	for _, e := range d.Events {
		if !tc.MatchString(e.Title) || len(e.Geometry) == 0 {
			continue
		}
		st := Storm{ID: "eonet-" + e.ID, Name: e.Title, Sources: []string{"NASA EONET"}, Current: e.Closed == nil}
		for _, g := range e.Geometry {
			if len(g.C) < 2 {
				continue
			}
			st.Track = append(st.Track, TrackPt{T: parseRFC(g.Date), Lat: g.C[1], Lon: g.C[0], Kt: g.Mag})
		}
		if len(st.Track) == 0 {
			continue
		}
		sort.Slice(st.Track, func(i, j int) bool { return st.Track[i].T.Before(st.Track[j].T) })
		last := st.Track[len(st.Track)-1]
		st.Lat, st.Lon, st.WindKt, st.Updated, st.Start = last.Lat, last.Lon, last.Kt, last.T, st.Track[0].T
		st.WindKmh = math.Round(last.Kt * 1.852)
		// EONET leaves storms "open" for a while; treat as current only if updated in the last 36h
		if time.Since(last.T) > 36*time.Hour {
			st.Current = false
		}
		if len(e.Sources) > 0 {
			st.Link = e.Sources[0].URL
		}
		out = append(out, st)
	}
	setStatus("NASA EONET storm tracks", u, "NASA EONET", len(out), nil)
	return out, nil
}

type jtwcItem struct {
	Title string `json:"title"`
	Link  string `json:"link"`
	Desc  string `json:"desc"`
}

func jtwcFeed() ([]jtwcItem, error) {
	const u = "https://www.metoc.navy.mil/jtwc/rss/jtwc.rss"
	b, _, err := cached("jtwc", 10*time.Minute, func() ([]byte, error) { return fetch(u) })
	setStatus("JTWC (W. Pacific / Indian / S. Hemisphere)", u, "US Joint Typhoon Warning Center", 0, err)
	if b == nil {
		return nil, err
	}
	var out []jtwcItem
	for _, it := range parseFeed(b) {
		out = append(out, jtwcItem{strip(it.Title), it.Link, truncate(strip(it.Description), 600)})
	}
	setStatus("JTWC (W. Pacific / Indian / S. Hemisphere)", u, "US Joint Typhoon Warning Center", len(out), nil)
	return out, nil
}

// ---------- NHC KMZ (official forecast track + cone) -> GeoJSON ----------

type kmlPlacemark struct {
	Name string `xml:"name"`
	Desc string `xml:"description"`
	Pt   []struct {
		C string `xml:"coordinates"`
	} `xml:"Point"`
	Line []struct {
		C string `xml:"coordinates"`
	} `xml:"LineString"`
	Poly []struct {
		C string `xml:"outerBoundaryIs>LinearRing>coordinates"`
	} `xml:"Polygon"`
	Multi []struct {
		Poly []struct {
			C string `xml:"outerBoundaryIs>LinearRing>coordinates"`
		} `xml:"Polygon"`
		Line []struct {
			C string `xml:"coordinates"`
		} `xml:"LineString"`
	} `xml:"MultiGeometry"`
}

func parseCoords(s string) [][2]float64 {
	var out [][2]float64
	for _, tok := range strings.Fields(s) {
		p := strings.Split(tok, ",")
		if len(p) < 2 {
			continue
		}
		lo, e1 := strconv.ParseFloat(p[0], 64)
		la, e2 := strconv.ParseFloat(p[1], 64)
		if e1 == nil && e2 == nil {
			out = append(out, [2]float64{lo, la})
		}
	}
	return out
}

func kmzToFeatures(b []byte, kind string) ([]map[string]any, error) {
	zr, err := zip.NewReader(bytes.NewReader(b), int64(len(b)))
	if err != nil {
		return nil, err
	}
	var feats []map[string]any
	for _, f := range zr.File {
		if !strings.HasSuffix(strings.ToLower(f.Name), ".kml") {
			continue
		}
		rc, err := f.Open()
		if err != nil {
			continue
		}
		data, _ := io.ReadAll(io.LimitReader(rc, 10<<20))
		rc.Close()
		dec := xml.NewDecoder(bytes.NewReader(data))
		dec.Strict = false
		for {
			tok, err := dec.Token()
			if err != nil {
				break
			}
			se, ok := tok.(xml.StartElement)
			if !ok || se.Name.Local != "Placemark" {
				continue
			}
			var pm kmlPlacemark
			if dec.DecodeElement(&pm, &se) != nil {
				continue
			}
			props := map[string]any{"kind": kind, "name": strip(pm.Name), "desc": truncate(strip(pm.Desc), 400)}
			add := func(gt string, coords any) {
				feats = append(feats, map[string]any{"type": "Feature", "properties": props, "geometry": map[string]any{"type": gt, "coordinates": coords}})
			}
			for _, p := range pm.Pt {
				if c := parseCoords(p.C); len(c) > 0 {
					add("Point", c[0])
				}
			}
			lines := pm.Line
			polys := pm.Poly
			for _, m := range pm.Multi {
				lines = append(lines, m.Line...)
				polys = append(polys, m.Poly...)
			}
			for _, l := range lines {
				if c := parseCoords(l.C); len(c) > 1 {
					add("LineString", c)
				}
			}
			for _, p := range polys {
				if c := parseCoords(p.C); len(c) > 2 {
					add("Polygon", [][][2]float64{c})
				}
			}
		}
	}
	return feats, nil
}

type nhcRaw struct {
	NHCStorm
	ForecastTrack struct {
		KMZ string `json:"kmzFile"`
	} `json:"forecastTrack"`
	Cone struct {
		KMZ string `json:"kmzFile"`
	} `json:"trackCone"`
	WindField struct {
		KMZ string `json:"kmzFile"`
	} `json:"initialWindExtent"`
}

func nhcStorms() ([]Storm, error) {
	const u = "https://www.nhc.noaa.gov/CurrentStorms.json"
	b, _, err := cached("nhc", 5*time.Minute, func() ([]byte, error) { return fetch(u) })
	if b == nil {
		setStatus("NOAA NHC (Atlantic/E-Pacific)", u, "NOAA National Hurricane Center — public domain", 0, err)
		return nil, err
	}
	var d struct {
		Active []nhcRaw `json:"activeStorms"`
	}
	json.Unmarshal(b, &d)
	setStatus("NOAA NHC (Atlantic/E-Pacific)", u, "NOAA National Hurricane Center — public domain", len(d.Active), nil)
	var out []Storm
	for _, s := range d.Active {
		kt, _ := strconv.ParseFloat(s.Intensity, 64)
		st := Storm{ID: "nhc-" + s.ID, Name: s.Name, Sources: []string{"NOAA NHC"}, Current: true, Lat: s.LatNum, Lon: s.LonNum,
			WindKt: kt, WindKmh: math.Round(kt * 1.852), Pressure: s.Pressure, Class: s.Classification,
			Movement: fmt.Sprintf("%.0f° at %.0f kt", s.MovementDir, s.MovementSpeed), Updated: parseRFC(s.LastUpdate),
			Link: s.PublicAdvisory.URL, Graphics: s.ForecastGraphics.URL}
		var feats []map[string]any
		for _, k := range []struct{ url, kind string }{{s.Cone.KMZ, "cone"}, {s.ForecastTrack.KMZ, "forecast"}, {s.WindField.KMZ, "windfield"}} {
			if k.url == "" {
				continue
			}
			kb, _, kerr := cached("kmz:"+k.url, 20*time.Minute, func() ([]byte, error) { return fetch(k.url) })
			if kb == nil {
				_ = kerr
				continue
			}
			if fs, e := kmzToFeatures(kb, k.kind); e == nil {
				feats = append(feats, fs...)
			}
		}
		if len(feats) > 0 {
			gj, _ := json.Marshal(map[string]any{"type": "FeatureCollection", "features": feats})
			st.Forecast = gj
		}
		out = append(out, st)
	}
	return out, nil
}

// ---------- merge & handler ----------

func nearby(a, b Storm) bool {
	return math.Abs(a.Lat-b.Lat) < 6 && math.Abs(math.Mod(a.Lon-b.Lon+540, 360)-180) < 8
}

var (
	cyMu   sync.Mutex
	cyLast []byte
	cyAt   time.Time
)

func handleCyclones(w http.ResponseWriter, r *http.Request) {
	cyMu.Lock()
	defer cyMu.Unlock()
	if cyLast != nil && time.Since(cyAt) < 90*time.Second {
		w.Header().Set("Content-Type", "application/json")
		w.Write(cyLast)
		return
	}
	var wg sync.WaitGroup
	var g, e, n []Storm
	var j []jtwcItem
	var gErr, eErr, nErr, jErr error
	wg.Add(4)
	go func() { defer wg.Done(); g, gErr = gdacsJSONStorms() }()
	go func() { defer wg.Done(); e, eErr = eonetStorms() }()
	go func() { defer wg.Done(); n, nErr = nhcStorms() }()
	go func() { defer wg.Done(); j, jErr = jtwcFeed() }()
	wg.Wait()

	// GDACS RSS: second GDACS path (covers green/current storms the API search omits,
	// and keeps working if only the API endpoint is unreachable)
	if rss, err := fetchGDACS(); err == nil {
		gErr = nil
		have := map[int]bool{}
		for _, s := range g {
			have[s.GEventID] = true
		}
		for _, ev := range rss {
			if ev.Kind != "TC" {
				continue
			}
			id, _ := strconv.Atoi(ev.Details["Event ID"])
			if have[id] {
				continue
			}
			{
				ep, _ := strconv.Atoi(ev.Details["Episode"])
				g = append(g, Storm{ID: fmt.Sprintf("gdacs-%d", id), Name: ev.Details["Name"], Sources: []string{"GDACS"}, Current: ev.Details["Current"] == "true",
					Lat: ev.Lat, Lon: ev.Lon, Class: ev.Details["Severity"], Alert: ev.Alert, Country: ev.Country, Start: ev.Time, Updated: ev.Updated,
					Link: ev.Link, GEventID: id, GEpisode: ep, Exposure: ev.Details["Exposure"]})
			}
		}
	}

	// merge: NHC (official, richest) > GDACS > EONET; EONET contributes history track
	all := append(append([]Storm{}, n...), g...)
	for _, es := range e {
		merged := false
		for i := range all {
			if (normName(all[i].Name) != "" && normName(all[i].Name) == normName(es.Name)) || (nearby(all[i], es) && all[i].Current == es.Current && math.Abs(all[i].Updated.Sub(es.Updated).Hours()) < 72) {
				all[i].Track = es.Track
				all[i].Sources = append(all[i].Sources, "NASA EONET")
				if all[i].Start.IsZero() {
					all[i].Start = es.Start
				}
				merged = true
				break
			}
		}
		if !merged {
			all = append(all, es)
		}
	}
	// dedupe GDACS vs NHC
	var uniq []Storm
	for _, s := range all {
		dup := false
		for i := range uniq {
			if uniq[i].ID != s.ID && normName(uniq[i].Name) == normName(s.Name) && normName(s.Name) != "" && nearby(uniq[i], s) {
				uniq[i].Sources = append(uniq[i].Sources, s.Sources...)
				if uniq[i].GEventID == 0 {
					uniq[i].GEventID, uniq[i].GEpisode, uniq[i].Alert = s.GEventID, s.GEpisode, s.Alert
				}
				dup = true
				break
			}
		}
		if !dup {
			uniq = append(uniq, s)
		}
	}
	windRe := regexp.MustCompile(`(\d+(?:\.\d+)?)\s*km/h`)
	for i := range uniq {
		s := &uniq[i]
		if s.WindKmh == 0 {
			if m := windRe.FindStringSubmatch(s.Class); m != nil {
				v, _ := strconv.ParseFloat(m[1], 64)
				s.WindKmh, s.WindKt = v, math.Round(kmhToKt(v))
			}
		}
		ev := Event{Kind: "TC", Lat: s.Lat, Lon: s.Lon}
		enrichNatural(&ev)
		s.Region, s.Assets = ev.Region, ev.Assets
		s.Score = int(math.Min(100, s.WindKt*0.62+18))
		switch s.Alert {
		case "Red":
			s.Score = max(s.Score, 86)
		case "Orange":
			s.Score = max(s.Score, 62)
		}
		s.Level = lvl(s.Score)
	}
	sort.Slice(uniq, func(i, j int) bool {
		if uniq[i].Current != uniq[j].Current {
			return uniq[i].Current
		}
		return uniq[i].Updated.After(uniq[j].Updated)
	})
	es := func(err error) string {
		if err == nil {
			return ""
		}
		return err.Error()
	}
	srcs := []cySource{
		{"NOAA NHC", nErr == nil, len(n), es(nErr)},
		{"GDACS", gErr == nil, len(g), es(gErr)},
		{"NASA EONET", eErr == nil, len(e), es(eErr)},
		{"JTWC", jErr == nil, len(j), es(jErr)},
	}
	buf, _ := json.Marshal(map[string]any{"storms": uniq, "sources": srcs, "jtwc": j, "generated": time.Now().UTC()})
	cyLast, cyAt = buf, time.Now()
	w.Header().Set("Content-Type", "application/json")
	w.Write(buf)
}
