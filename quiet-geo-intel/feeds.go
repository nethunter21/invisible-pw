package main

import (
	"bytes"
	"crypto/sha1"
	"encoding/hex"
	"encoding/json"
	"encoding/xml"
	"fmt"
	"html"
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

// ================= NATURAL HAZARDS =================

type Event struct {
	ID       string            `json:"id"`
	Kind     string            `json:"kind"` // TC EQ FL VO DR WF ST WAR ...
	Title    string            `json:"title"`
	Summary  string            `json:"summary,omitempty"`
	Lat      float64           `json:"lat"`
	Lon      float64           `json:"lon"`
	Score    int               `json:"score"` // 0-100 severity (derived, see docs)
	Level    string            `json:"level"` // CRITICAL HIGH ELEVATED WATCH
	Alert    string            `json:"alert,omitempty"`
	Country  string            `json:"country,omitempty"`
	Time     time.Time         `json:"time"`
	Updated  time.Time         `json:"updated"`
	Link     string            `json:"link,omitempty"`
	Source   string            `json:"source"`
	Region   string            `json:"region,omitempty"`
	Themes   []string          `json:"themes,omitempty"`
	Assets   []Asset           `json:"assets,omitempty"`
	Details  map[string]string `json:"details,omitempty"`
	Strategy []string          `json:"strategies,omitempty"`
}

type Asset struct {
	S   string `json:"s"`
	D   string `json:"d"` // up / down / vol
	Why string `json:"why"`
}

func lvl(score int) string {
	switch {
	case score >= 80:
		return "CRITICAL"
	case score >= 60:
		return "HIGH"
	case score >= 35:
		return "ELEVATED"
	}
	return "WATCH"
}

func strip(s string) string {
	s = regexp.MustCompile(`(?s)<[^>]*>`).ReplaceAllString(s, " ")
	s = html.UnescapeString(s)
	return strings.Join(strings.Fields(s), " ")
}

func newDecoder(b []byte) *xml.Decoder {
	b = bytes.TrimPrefix(b, []byte("\xef\xbb\xbf"))
	d := xml.NewDecoder(bytes.NewReader(b))
	d.Strict = false
	d.CharsetReader = func(label string, in io.Reader) (io.Reader, error) { return in, nil }
	return d
}

type gdacsItem struct {
	Title       string `xml:"title"`
	Description string `xml:"description"`
	Link        string `xml:"link"`
	EventType   string `xml:"http://www.gdacs.org eventtype"`
	Alert       string `xml:"http://www.gdacs.org alertlevel"`
	AlertScore  string `xml:"http://www.gdacs.org alertscore"`
	EventID     string `xml:"http://www.gdacs.org eventid"`
	EpisodeID   string `xml:"http://www.gdacs.org episodeid"`
	EventName   string `xml:"http://www.gdacs.org eventname"`
	Country     string `xml:"http://www.gdacs.org country"`
	IsCurrent   string `xml:"http://www.gdacs.org iscurrent"`
	FromDate    string `xml:"http://www.gdacs.org fromdate"`
	Modified    string `xml:"http://www.gdacs.org datemodified"`
	Population  string `xml:"http://www.gdacs.org population"`
	Severity    struct {
		Text  string `xml:",chardata"`
		Unit  string `xml:"unit,attr"`
		Value string `xml:"value,attr"`
	} `xml:"http://www.gdacs.org severity"`
	Point struct {
		Lat string `xml:"lat"`
		Lon string `xml:"long"`
	} `xml:"http://www.w3.org/2003/01/geo/wgs84_pos# Point"`
}

func parseRFC(s string) time.Time {
	s = strings.TrimSpace(s)
	for _, f := range []string{time.RFC1123Z, time.RFC1123, "Mon, 2 Jan 2006 15:04:05 -0700", "Mon, 2 Jan 2006 15:04:05 MST", "Mon, 02 Jan 2006 15:04:05 Z", time.RFC3339, "2006-01-02T15:04:05Z07:00", "2006-01-02T15:04:05", "Mon, 2 Jan 2006 15:04:05 Z"} {
		if t, err := time.Parse(f, s); err == nil {
			return t.UTC()
		}
	}
	return time.Time{}
}

var kindNames = map[string]string{"TC": "Tropical Cyclone", "EQ": "Earthquake", "FL": "Flood", "VO": "Volcano", "DR": "Drought", "WF": "Wildfire", "ST": "Severe Storm", "SI": "Sea/Lake Ice", "LS": "Landslide", "DU": "Dust/Haze", "TE": "Extreme Temp"}

func fetchGDACS() ([]Event, error) {
	const u = "https://www.gdacs.org/xml/rss.xml"
	b, _, err := cached("gdacs", 5*time.Minute, func() ([]byte, error) { return fetch(u) })
	if b == nil {
		setStatus("GDACS (UN/EC disaster alerts)", u, "GDACS — Global Disaster Alert and Coordination System (EC JRC / UN)", 0, err)
		return nil, err
	}
	var doc struct {
		Items []gdacsItem `xml:"channel>item"`
	}
	if e := newDecoder(b).Decode(&doc); e != nil {
		setStatus("GDACS (UN/EC disaster alerts)", u, "GDACS", 0, e)
		return nil, e
	}
	var out []Event
	for _, it := range doc.Items {
		lat, _ := strconv.ParseFloat(it.Point.Lat, 64)
		lon, _ := strconv.ParseFloat(it.Point.Lon, 64)
		base := map[string]int{"Green": 25, "Orange": 62, "Red": 86}[it.Alert]
		as, _ := strconv.ParseFloat(it.AlertScore, 64)
		score := base + int(math.Min(10, as*3))
		ev := Event{
			ID: "gdacs-" + it.EventType + it.EventID, Kind: it.EventType, Title: strip(it.Title), Summary: strip(it.Description),
			Lat: lat, Lon: lon, Score: score, Level: lvl(score), Alert: it.Alert, Country: it.Country,
			Time: parseRFC(it.FromDate), Updated: parseRFC(it.Modified), Link: strings.Replace(it.Link, "http://", "https://", 1), Source: "GDACS",
			Details: map[string]string{"Severity": strip(it.Severity.Text), "Exposure": strip(it.Population), "Event ID": it.EventID, "Episode": it.EpisodeID, "Name": it.EventName, "Current": it.IsCurrent},
		}
		if (it.EventType == "EQ" || it.EventType == "WF") && it.Alert == "Green" {
			continue // USGS covers routine quakes
		}
		out = append(out, ev)
	}
	setStatus("GDACS (UN/EC disaster alerts)", u, "GDACS — Global Disaster Alert and Coordination System (EC JRC / UN)", len(out), err)
	return out, nil
}

func fetchUSGS() ([]Event, error) {
	const u = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"
	b, _, err := cached("usgs", 3*time.Minute, func() ([]byte, error) { return fetch(u) })
	if b == nil {
		setStatus("USGS (earthquakes)", u, "U.S. Geological Survey — public domain", 0, err)
		return nil, err
	}
	var g struct {
		Features []struct {
			ID         string `json:"id"`
			Properties struct {
				Mag     float64 `json:"mag"`
				Place   string  `json:"place"`
				Time    int64   `json:"time"`
				Updated int64   `json:"updated"`
				URL     string  `json:"url"`
				Tsunami int     `json:"tsunami"`
				Alert   string  `json:"alert"`
				Sig     int     `json:"sig"`
				Felt    int     `json:"felt"`
			} `json:"properties"`
			Geometry struct {
				C []float64 `json:"coordinates"`
			} `json:"geometry"`
		} `json:"features"`
	}
	json.Unmarshal(b, &g)
	var out []Event
	for _, f := range g.Features {
		p := f.Properties
		if len(f.Geometry.C) < 3 {
			continue
		}
		score := int(math.Max(10, math.Min(100, (p.Mag-4.5)*26+15)))
		switch p.Alert {
		case "orange":
			score = max(score, 70)
		case "red":
			score = max(score, 88)
		}
		if p.Tsunami == 1 {
			score += 8
		}
		score = min(score, 100)
		out = append(out, Event{
			ID: "usgs-" + f.ID, Kind: "EQ", Title: fmt.Sprintf("M%.1f earthquake — %s", p.Mag, p.Place),
			Lat: f.Geometry.C[1], Lon: f.Geometry.C[0], Score: score, Level: lvl(score), Alert: p.Alert,
			Time: time.UnixMilli(p.Time).UTC(), Updated: time.UnixMilli(p.Updated).UTC(), Link: p.URL, Source: "USGS",
			Details: map[string]string{"Magnitude": fmt.Sprintf("%.1f", p.Mag), "Depth": fmt.Sprintf("%.0f km", f.Geometry.C[2]), "Tsunami flag": map[int]string{0: "no", 1: "YES"}[p.Tsunami], "PAGER alert": nz(p.Alert, "none"), "Significance": strconv.Itoa(p.Sig)},
		})
	}
	setStatus("USGS (earthquakes)", u, "U.S. Geological Survey — public domain", len(out), nil)
	return out, nil
}

func nz(s, d string) string {
	if s == "" {
		return d
	}
	return s
}

func fetchEONET() ([]Event, error) {
	const u = "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&days=10&limit=300"
	b, _, err := cached("eonet", 10*time.Minute, func() ([]byte, error) { return fetch(u) })
	if b == nil {
		setStatus("NASA EONET (natural events)", u, "NASA Earth Observatory Natural Event Tracker", 0, err)
		return nil, err
	}
	var g struct {
		Events []struct {
			ID         string `json:"id"`
			Title      string `json:"title"`
			Link       string `json:"link"`
			Categories []struct {
				ID string `json:"id"`
			} `json:"categories"`
			Sources []struct {
				URL string `json:"url"`
			} `json:"sources"`
			Geometry []struct {
				Date   string          `json:"date"`
				Type   string          `json:"type"`
				Coords json.RawMessage `json:"coordinates"`
				Mag    float64         `json:"magnitudeValue"`
				Unit   string          `json:"magnitudeUnit"`
			} `json:"geometry"`
		} `json:"events"`
	}
	json.Unmarshal(b, &g)
	kmap := map[string]string{"wildfires": "WF", "severeStorms": "ST", "volcanoes": "VO", "floods": "FL", "drought": "DR", "seaLakeIce": "SI", "landslides": "LS", "dustHaze": "DU", "tempExtremes": "TE", "earthquakes": "EQ"}
	var out []Event
	for _, e := range g.Events {
		if len(e.Geometry) == 0 || len(e.Categories) == 0 {
			continue
		}
		k := kmap[e.Categories[0].ID]
		if k == "" || k == "EQ" || k == "SI" {
			continue
		}
		if k == "ST" && regexp.MustCompile(`(?i)tropical|typhoon|hurricane|cyclone`).MatchString(e.Title) {
			k = "TC"
		}
		last := e.Geometry[len(e.Geometry)-1]
		var pt []float64
		if json.Unmarshal(last.Coords, &pt) != nil || len(pt) < 2 {
			var poly [][][]float64
			if json.Unmarshal(last.Coords, &poly) == nil && len(poly) > 0 && len(poly[0]) > 0 {
				pt = poly[0][0]
			} else {
				continue
			}
		}
		score := 22
		if k == "ST" || k == "VO" {
			score = 40
		}
		if k == "WF" && last.Mag > 5000 {
			score = 45
		}
		link := ""
		if len(e.Sources) > 0 {
			link = e.Sources[0].URL
		}
		d := map[string]string{"Category": kindNames[k]}
		if last.Mag > 0 {
			d["Magnitude"] = fmt.Sprintf("%g %s", last.Mag, last.Unit)
		}
		d["Track points"] = strconv.Itoa(len(e.Geometry))
		out = append(out, Event{ID: "eonet-" + e.ID, Kind: k, Title: e.Title, Lat: pt[1], Lon: pt[0], Score: score, Level: lvl(score),
			Time: parseRFC(e.Geometry[0].Date), Updated: parseRFC(last.Date), Link: link, Source: "NASA EONET", Details: d})
	}
	setStatus("NASA EONET (natural events)", u, "NASA Earth Observatory Natural Event Tracker", len(out), nil)
	return out, nil
}

// ---------- NHC ----------

type NHCStorm struct {
	ID             string  `json:"id"`
	BinNumber      string  `json:"binNumber"`
	Name           string  `json:"name"`
	Classification string  `json:"classification"`
	Intensity      string  `json:"intensity"`
	Pressure       string  `json:"pressure"`
	LatNum         float64 `json:"latitudeNumeric"`
	LonNum         float64 `json:"longitudeNumeric"`
	MovementDir    float64 `json:"movementDir"`
	MovementSpeed  float64 `json:"movementSpeed"`
	LastUpdate     string  `json:"lastUpdate"`
	PublicAdvisory struct {
		URL string `json:"url"`
	} `json:"publicAdvisory"`
	ForecastGraphics struct {
		URL string `json:"url"`
	} `json:"forecastGraphics"`
	TrackCone struct {
		KMZFile string `json:"kmzFile"`
	} `json:"trackCone"`
}

func fetchNHC() ([]NHCStorm, error) {
	const u = "https://www.nhc.noaa.gov/CurrentStorms.json"
	b, _, err := cached("nhc", 5*time.Minute, func() ([]byte, error) { return fetch(u) })
	if b == nil {
		setStatus("NOAA NHC (Atlantic/E-Pacific)", u, "NOAA National Hurricane Center — public domain", 0, err)
		return nil, err
	}
	var d struct {
		Active []NHCStorm `json:"activeStorms"`
	}
	json.Unmarshal(b, &d)
	setStatus("NOAA NHC (Atlantic/E-Pacific)", u, "NOAA National Hurricane Center — public domain", len(d.Active), nil)
	return d.Active, nil
}

func nhcEvents(st []NHCStorm) []Event {
	var out []Event
	for _, s := range st {
		kt, _ := strconv.Atoi(s.Intensity)
		score := int(math.Min(100, float64(kt)*0.62+18))
		cls := map[string]string{"TD": "Tropical Depression", "TS": "Tropical Storm", "HU": "Hurricane", "MH": "Major Hurricane", "STS": "Subtropical Storm", "PTC": "Potential Tropical Cyclone", "PC": "Post-tropical"}[s.Classification]
		out = append(out, Event{ID: "nhc-" + s.ID, Kind: "TC", Title: fmt.Sprintf("%s %s — %s kt, %s mb", nz(cls, s.Classification), s.Name, s.Intensity, s.Pressure),
			Lat: s.LatNum, Lon: s.LonNum, Score: score, Level: lvl(score), Time: parseRFC(s.LastUpdate), Updated: parseRFC(s.LastUpdate),
			Link: s.PublicAdvisory.URL, Source: "NOAA NHC",
			Details: map[string]string{"Max wind": s.Intensity + " kt", "Pressure": s.Pressure + " mb", "Movement": fmt.Sprintf("%.0f° at %.0f kt", s.MovementDir, s.MovementSpeed), "Class": s.Classification, "Graphics": s.ForecastGraphics.URL}})
	}
	return out
}

var (
	natMu   sync.Mutex
	natLast []byte
	natAt   time.Time
)

func getNatural() []byte {
	natMu.Lock()
	defer natMu.Unlock()
	if natLast != nil && time.Since(natAt) < 2*time.Minute {
		return natLast
	}
	var wg sync.WaitGroup
	var a, b, c []Event
	var nhc []NHCStorm
	wg.Add(4)
	go func() { defer wg.Done(); a, _ = fetchGDACS() }()
	go func() { defer wg.Done(); b, _ = fetchUSGS() }()
	go func() { defer wg.Done(); c, _ = fetchEONET() }()
	go func() { defer wg.Done(); nhc, _ = fetchNHC() }()
	wg.Wait()
	var cur []Event
	for _, e := range a {
		if e.Details["Current"] == "true" {
			cur = append(cur, e)
		}
	}
	// keep EONET wildfires to the most recently updated 40
	var wf, other []Event
	for _, e := range c {
		if e.Kind == "WF" {
			wf = append(wf, e)
		} else {
			other = append(other, e)
		}
	}
	sort.Slice(wf, func(i, j int) bool { return wf[i].Updated.After(wf[j].Updated) })
	if len(wf) > 40 {
		wf = wf[:40]
	}
	all := append(append(append(append(cur, b...), other...), wf...), nhcEvents(nhc)...)
	for i := range all {
		enrichNatural(&all[i])
	}
	sort.Slice(all, func(i, j int) bool { return all[i].Score > all[j].Score })
	buf, _ := json.Marshal(map[string]any{"events": all, "generated": time.Now().UTC()})
	natLast, natAt = buf, time.Now()
	return buf
}

func handleNatural(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Write(getNatural())
}

func handleTCGeom(w http.ResponseWriter, r *http.Request) {
	id, ep := r.URL.Query().Get("eventid"), r.URL.Query().Get("episodeid")
	if _, e := strconv.Atoi(id); e != nil {
		http.Error(w, "bad id", 400)
		return
	}
	if _, e := strconv.Atoi(ep); e != nil {
		http.Error(w, "bad episode", 400)
		return
	}
	u := "https://www.gdacs.org/gdacsapi/api/polygons/getgeometry?eventtype=TC&eventid=" + id + "&episodeid=" + ep
	b, at, err := cached("tcg:"+id+":"+ep, 30*time.Minute, func() ([]byte, error) { return fetch(u) })
	writeRaw(w, b, at, err)
}

// ---------- natural hazard → market mapping (transparent heuristics) ----------

type box struct{ lat1, lat2, lon1, lon2 float64 }

func (b box) in(lat, lon float64) bool {
	return lat >= b.lat1 && lat <= b.lat2 && lon >= b.lon1 && lon <= b.lon2
}

var (
	gulfMexico  = box{18, 31, -98, -80}
	usEast      = box{24, 46, -82, -66}
	usWest      = box{31, 49, -125, -114}
	japan       = box{30, 46, 128, 146}
	taiwan      = box{21, 26, 119, 123}
	brazilAg    = box{-30, -5, -60, -38}
	westAfrica  = box{3, 11, -10, 3}
	usCornBelt  = box{36, 46, -100, -82}
	chinaCoast  = box{18, 35, 105, 123}
	australia   = box{-40, -10, 112, 155}
	indiaBox    = box{6, 30, 68, 92}
	europe      = box{36, 60, -10, 30}
	seAsiaPalm  = box{-8, 8, 95, 120}
	chile       = box{-45, -17, -76, -66}
	icelandBox  = box{62, 67, -25, -13}
	indonesia   = box{-11, 6, 95, 141}
	philippines = box{5, 20, 116, 127}
)

func enrichNatural(e *Event) {
	add := func(s, d, why string) { e.Assets = append(e.Assets, Asset{s, d, why}) }
	switch e.Kind {
	case "TC":
		e.Strategy = []string{"hurr-energy", "hurr-revision", "hurr-ri", "hurr-insure"}
		if gulfMexico.in(e.Lat, e.Lon) {
			e.Region = "Gulf of Mexico"
			add("NG=F", "up", "Gulf production shut-ins / LNG export disruption")
			add("CL=F", "up", "Offshore crude shut-ins")
			add("RB=F", "up", "Refinery outages on Gulf Coast")
			add("TRV", "down", "Insured-loss exposure")
			add("GNRC", "up", "Generator demand pre/post landfall")
			add("HD", "up", "Rebuild / preparation spending")
		} else if usEast.in(e.Lat, e.Lon) {
			e.Region = "US East Coast"
			add("ALL", "down", "Property insured-loss exposure")
			add("GNRC", "up", "Generator demand")
			add("HD", "up", "Rebuild demand")
			add("NG=F", "vol", "Demand destruction vs. supply")
		} else if japan.in(e.Lat, e.Lon) || taiwan.in(e.Lat, e.Lon) || chinaCoast.in(e.Lat, e.Lon) || philippines.in(e.Lat, e.Lon) {
			e.Region = "West Pacific (Asia)"
			add("TSM", "vol", "Fab / supply-chain disruption risk")
			add("ZIM", "up", "Port closures tighten container capacity")
			add("BDRY", "up", "Dry-bulk route disruption")
			add("JKS", "vol", "Regional manufacturing")
		} else if australia.in(e.Lat, e.Lon) {
			e.Region = "Australia"
			add("BHP", "vol", "Pilbara iron-ore port closures")
			add("RIO", "vol", "Iron-ore export disruption")
			add("TIO=F", "up", "Iron-ore supply interruption")
		} else if indiaBox.in(e.Lat, e.Lon) {
			e.Region = "North Indian Ocean"
			add("INDA", "vol", "Regional economic disruption")
			add("ZR=F", "up", "Rice crop/ports exposure")
		} else {
			add("BDRY", "vol", "Shipping route disruption")
		}
	case "EQ":
		e.Strategy = []string{"quake-supply"}
		if japan.in(e.Lat, e.Lon) {
			e.Region = "Japan"
			add("JPY=X", "vol", "Yen repatriation / risk-off flows")
			add("EWJ", "down", "Japanese equities")
			add("^N225", "down", "Nikkei index")
		} else if taiwan.in(e.Lat, e.Lon) {
			e.Region = "Taiwan"
			add("TSM", "down", "Fab disruption risk (wafer scrap / downtime)")
			add("SOXX", "down", "Global semiconductor supply")
			add("MU", "up", "Memory price spike if DRAM fabs hit")
		} else if chile.in(e.Lat, e.Lon) {
			e.Region = "Chile"
			add("HG=F", "up", "Copper mine disruption")
			add("SQM", "vol", "Lithium operations")
		} else if indonesia.in(e.Lat, e.Lon) {
			e.Region = "Indonesia"
			add("NICK.L", "up", "Nickel supply")
		} else {
			add("^VIX", "vol", "Risk sentiment if severe")
		}
		if e.Score >= 60 {
			add("RNR", "down", "Reinsurance catastrophe losses")
		}
	case "FL":
		e.Strategy = []string{"ag-rain", "flood-insure"}
		if usCornBelt.in(e.Lat, e.Lon) {
			add("ZC=F", "up", "Corn planting/harvest delays")
			add("ZS=F", "up", "Soy acreage risk")
		} else if brazilAg.in(e.Lat, e.Lon) {
			add("ZS=F", "vol", "Brazil soy harvest delays")
			add("SB=F", "up", "Sugar cane crush delays")
		} else if indiaBox.in(e.Lat, e.Lon) || seAsiaPalm.in(e.Lat, e.Lon) {
			add("ZR=F", "up", "Rice crop damage")
		} else if europe.in(e.Lat, e.Lon) {
			add("ZW=F", "vol", "EU wheat quality")
		}
		add("RNR", "down", "Insured flood losses")
	case "DR":
		e.Strategy = []string{"ag-drought"}
		if brazilAg.in(e.Lat, e.Lon) {
			add("KC=F", "up", "Arabica yield stress")
			add("SB=F", "up", "Cane yield stress")
			add("ZS=F", "up", "Soy yield stress")
		} else if westAfrica.in(e.Lat, e.Lon) {
			add("CC=F", "up", "Cocoa pod development stress")
		} else if usCornBelt.in(e.Lat, e.Lon) {
			add("ZC=F", "up", "Corn yield stress")
			add("ZS=F", "up", "Soy yield stress")
		} else if europe.in(e.Lat, e.Lon) {
			add("ZW=F", "up", "EU wheat yield")
		} else {
			add("DBA", "up", "Broad agriculture basket")
			add("ZW=F", "vol", "Global grain balance")
		}
	case "WF":
		e.Strategy = []string{"wildfire"}
		if usWest.in(e.Lat, e.Lon) {
			e.Region = "US West"
			add("PCG", "down", "Utility wildfire liability")
			add("EIX", "down", "Utility wildfire liability")
		}
		if e.Score >= 40 {
			add("LBS=F", "up", "Lumber supply")
		}
	case "VO":
		e.Strategy = []string{"volcano-aviation"}
		add("JETS", "down", "Ash-cloud airspace closures")
		if icelandBox.in(e.Lat, e.Lon) || europe.in(e.Lat, e.Lon) {
			add("RYAAY", "down", "European short-haul exposure")
			add("LHA.DE", "down", "European carrier exposure")
		}
	case "ST":
		e.Strategy = []string{"severe-convective"}
		add("NG=F", "vol", "Weather-driven demand swing")
	}
}

// ================= CONFLICT / GEOPOLITICAL NEWS =================

type feedDef struct{ Name, URL string }

var newsFeeds = []feedDef{
	{"BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"},
	{"Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"},
	{"Defense News", "https://www.defensenews.com/arc/outboundfeeds/rss/"},
	{"The Guardian World", "https://www.theguardian.com/world/rss"},
	{"DW World", "https://rss.dw.com/rdf/rss-en-world"},
	{"France 24", "https://www.france24.com/en/rss"},
	{"UN News", "https://news.un.org/feed/subscribe/en/news/all/rss.xml"},
	{"Ynetnews", "https://www.ynetnews.com/Integration/StoryRss3089.xml"},
	{"Kyiv Independent", "https://kyivindependent.com/news-archive/rss/"},
	{"NYT World", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"},
	{"BBC Middle East", "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"},
	{"BBC Asia", "https://feeds.bbci.co.uk/news/world/asia/rss.xml"},
	{"BBC Europe", "https://feeds.bbci.co.uk/news/world/europe/rss.xml"},
}

type term struct {
	re *regexp.Regexp
	w  int
	th string
}

func t(p string, w int, th string) term {
	return term{regexp.MustCompile(`(?i)\b(?:` + p + `)`), w, th}
}

var terms = []term{
	t(`nuclear (?:strike|attack|weapon|test|threat|war)|warhead|icbm|tactical nuke`, 30, "NUCLEAR"),
	t(`declares? war|declaration of war|full-scale (?:war|invasion)|invad(?:e|es|ed|ing)|invasion`, 30, "INVASION"),
	t(`ballistic missile|hypersonic|cruise missile`, 22, "MISSILE"),
	t(`missile|rocket(?:s)? (?:fire|attack|barrage)|barrage`, 16, "MISSILE"),
	t(`air ?strikes?|bomb(?:ing|ed|s)?\b|shelling|artillery|bombard`, 16, "STRIKE"),
	t(`(?:military|israeli|russian|ukrainian|us|u\.s\.|american|iranian|saudi|missile|drone|precision|retaliatory|deadly) strikes?|strikes? (?:on|kill|hit|against|target)|struck`, 14, "STRIKE"),
	t(`drone (?:attack|strike|swarm)|drones? (?:hit|struck)|kamikaze drone`, 16, "DRONE"),
	t(`strait of hormuz|hormuz`, 22, "ENERGY-CHOKEPOINT"),
	t(`tanker|oil (?:field|facility|terminal|refinery)|refinery|pipeline|lng terminal|gas field|energy infrastructure|power grid`, 12, "ENERGY-INFRA"),
	t(`warships?|aircraft carrier|naval|navy|destroyer|frigate|submarine|blockade`, 10, "NAVAL"),
	t(`troops|military|army|soldiers|offensive|counteroffensive|front ?line|mobili[sz]`, 8, "MILITARY"),
	t(`killed|casualties|dead|deaths|wounded`, 5, "CASUALTIES"),
	t(`retaliat|escalat|vows? revenge|red line`, 12, "ESCALATION"),
	t(`ceasefire|truce|peace (?:talks|deal|plan)|negotiat`, 7, "DE-ESCALATION"),
	t(`sanction|embargo|export (?:ban|controls)|price cap|tariff`, 9, "SANCTIONS"),
	t(`coup(?: attempt| d.?etat)?\b|martial law|junta|assassinat`, 20, "REGIME"),
	t(`cyber ?attack|hack(?:ers|ed)|ransomware`, 12, "CYBER"),
	t(`terror(?:ist|ism)? attack|suicide bomb|hostages?`, 14, "TERROR"),
	t(`air defen[cs]e|intercept(?:ed|ion)|iron dome|patriot`, 10, "AIR-DEFENSE"),
	t(`nato|pentagon|defen[cs]e (?:minister|ministry|spending|budget)|arms (?:deal|sale|package)|weapons (?:package|aid|deliveries)`, 9, "DEFENSE-SPEND"),
	t(`houthis?|red sea|bab el-mandeb|shipping lane`, 14, "SHIPPING"),
	t(`war\b|wars\b|conflict|clashes|fighting|attack(?:s|ed)?`, 6, "CONFLICT"),
}

type region struct {
	Name     string
	re       *regexp.Regexp
	Lat, Lon float64
	Boost    int
	Assets   []Asset
}

func rg(name, p string, lat, lon float64, boost int, assets ...Asset) region {
	return region{name, regexp.MustCompile(`(?i)\b(?:` + p + `)`), lat, lon, boost, assets}
}

func A(s, d, w string) Asset { return Asset{s, d, w} }

var regions = []region{
	rg("Iran / Persian Gulf", `iran|tehran|irgc|persian gulf|hormuz|isfahan|natanz`, 32.4, 53.7, 14,
		A("CL=F", "up", "Hormuz carries ~20% of global oil"), A("BZ=F", "up", "Brent risk premium"), A("XLE", "up", "Energy equities"), A("FRO", "up", "Tanker rates spike"), A("GC=F", "up", "Safe-haven bid"), A("JETS", "down", "Fuel cost + airspace closures")),
	rg("Israel / Gaza / Lebanon", `israel|israeli|gaza|hamas|hezbollah|lebanon|beirut|west bank|idf|netanyahu|tel aviv`, 31.5, 34.8, 10,
		A("CL=F", "up", "Regional escalation premium"), A("LMT", "up", "Munitions replenishment"), A("RTX", "up", "Air-defense interceptors"), A("ESLT", "up", "Israeli defense prime"), A("GC=F", "up", "Safe-haven bid")),
	rg("Red Sea / Yemen", `houthi|yemen|red sea|bab el-mandeb|aden`, 15.5, 42.5, 10,
		A("ZIM", "up", "Container rates on Suez diversion"), A("MAERSK-B.CO", "up", "Container freight rates"), A("BZ=F", "up", "Freight/insurance premium on crude"), A("FRO", "up", "Longer tanker voyages")),
	rg("Gulf States / Iraq", `saudi|riyadh|aramco|uae|emirates|abu dhabi|qatar|iraq|baghdad|kuwait|oman`, 25.0, 47.0, 8,
		A("CL=F", "up", "Supply-risk premium"), A("BZ=F", "up", "Brent"), A("NG=F", "vol", "Qatar LNG exposure")),
	rg("Syria", `syria|damascus|aleppo|idlib`, 35.0, 38.5, 4, A("GC=F", "up", "Regional risk"), A("CL=F", "vol", "Regional risk")),
	rg("Russia / Ukraine", `ukrain|kyiv|kiev|russia|russian|moscow|kremlin|putin|zelensk|crimea|donbas|donetsk|kharkiv|odesa|odessa|zaporizh|kursk|black sea|belgorod`, 49.0, 32.0, 10,
		A("RHM.DE", "up", "Rheinmetall — EU ammunition demand"), A("BA.L", "up", "BAE Systems"), A("LDO.MI", "up", "Leonardo"), A("SAAB-B.ST", "up", "Saab"), A("ZW=F", "up", "Black Sea wheat exports"), A("TTF=F", "up", "EU gas (Dutch TTF)"), A("NG=F", "up", "US LNG export demand"), A("EUFN", "down", "European financials risk-off")),
	rg("Europe / NATO flank", `poland|baltic|lithuania|latvia|estonia|finland|moldova|romania|nato`, 54.0, 23.0, 6,
		A("RHM.DE", "up", "EU rearmament"), A("SAAB-B.ST", "up", "Nordic defense"), A("HAG.DE", "up", "Hensoldt sensors"), A("EUAD", "up", "European defense ETF")),
	rg("Taiwan Strait", `taiwan|taipei|taiwan strait`, 24.0, 121.0, 14,
		A("TSM", "down", "~90% of leading-edge chips"), A("SOXX", "down", "Global semiconductor supply"), A("LMT", "up", "Pacific deterrence spend"), A("NOC", "up", "B-21 / missile defense"), A("GC=F", "up", "Safe-haven bid"), A("^VIX", "up", "Volatility")),
	rg("China / South China Sea", `china|chinese|beijing|xi jinping|pla\b|south china sea|philippines|manila|spratly|scarborough`, 15.0, 115.0, 8,
		A("FXI", "down", "China equities risk-off"), A("KWEB", "down", "China tech"), A("RTX", "up", "Indo-Pacific defense"), A("HG=F", "vol", "Copper/China demand")),
	rg("Korean Peninsula", `north korea|pyongyang|kim jong|dprk|south korea|seoul`, 38.5, 127.0, 8,
		A("EWY", "down", "Korea equities"), A("012450.KS", "up", "Hanwha Aerospace"), A("7011.T", "up", "Mitsubishi Heavy"), A("JPY=X", "vol", "Yen haven flows")),
	rg("India / Pakistan", `india|indian|pakistan|kashmir|islamabad|new delhi|modi`, 30.0, 73.0, 6,
		A("INDA", "down", "Indian equities risk-off"), A("GC=F", "up", "Haven + strong Indian gold demand")),
	rg("Sahel / Horn of Africa", `sudan|khartoum|darfur|sahel|mali|niger|burkina|somalia|ethiopia|eritrea|chad|libya`, 13.0, 25.0, 3,
		A("GC=F", "vol", "Gold mining regions"), A("CL=F", "vol", "Libyan output if affected")),
	rg("Congo / Great Lakes", `congo|drc|kinshasa|goma|rwanda|m23`, -2.0, 28.0, 3, A("HG=F", "vol", "Copper/cobalt belt")),
	rg("Venezuela / Caribbean", `venezuela|maduro|caracas|guyana|essequibo|cuba`, 8.0, -66.0, 5, A("CL=F", "vol", "Heavy-crude supply"), A("XOM", "vol", "Guyana Stabroek exposure")),
	rg("Arctic / Greenland", `greenland|arctic`, 72.0, -40.0, 2, A("ITA", "up", "Arctic defense spend")),
	rg("United States", `united states|u\.s\.|washington|white house|trump|biden|congress`, 38.9, -77.0, 0),
}

var generalDefense = []Asset{A("ITA", "up", "US aerospace & defense ETF"), A("LMT", "up", "Lockheed Martin"), A("RTX", "up", "RTX / Raytheon"), A("NOC", "up", "Northrop Grumman"), A("GD", "up", "General Dynamics")}

var themeAssets = map[string][]Asset{
	"NUCLEAR":           {A("GC=F", "up", "Max safe-haven bid"), A("^VIX", "up", "Volatility spike"), A("TLT", "up", "Flight to Treasuries"), A("SPY", "down", "Broad risk-off")},
	"ENERGY-CHOKEPOINT": {A("CL=F", "up", "Supply disruption"), A("BZ=F", "up", "Brent"), A("FRO", "up", "Tankers"), A("STNG", "up", "Product tankers")},
	"ENERGY-INFRA":      {A("CL=F", "up", "Energy supply shock"), A("XLE", "up", "Energy equities"), A("NG=F", "vol", "Gas supply")},
	"SHIPPING":          {A("ZIM", "up", "Container rates"), A("BDRY", "up", "Freight")},
	"CYBER":             {A("CRWD", "up", "Cyber demand"), A("PANW", "up", "Cyber demand"), A("CIBR", "up", "Cyber ETF")},
	"AIR-DEFENSE":       {A("RTX", "up", "Patriot interceptors"), A("LMT", "up", "PAC-3 / THAAD"), A("KTOS", "up", "Counter-drone / targets")},
	"DRONE":             {A("AVAV", "up", "AeroVironment loitering munitions"), A("KTOS", "up", "Kratos drones"), A("LHX", "up", "L3Harris EW")},
	"DEFENSE-SPEND":     {A("ITA", "up", "Defense spending"), A("PLTR", "up", "Defense software"), A("HII", "up", "Shipbuilding")},
	"SANCTIONS":         {A("CL=F", "vol", "Supply rerouting"), A("GC=F", "up", "Reserve diversification")},
	"DE-ESCALATION":     {A("ITA", "down", "Risk premium unwinds"), A("CL=F", "down", "Geopolitical premium fades"), A("SPY", "up", "Risk-on")},
}

var themeStrategies = map[string][]string{
	"NUCLEAR": {"war-haven", "war-vol"}, "INVASION": {"war-defense", "war-haven", "war-vol"}, "MISSILE": {"war-defense", "war-oil"},
	"STRIKE": {"war-defense", "war-fade"}, "DRONE": {"war-defense"}, "ENERGY-CHOKEPOINT": {"war-oil", "war-shipping"},
	"ENERGY-INFRA": {"war-oil"}, "NAVAL": {"war-shipping"}, "ESCALATION": {"war-defense", "war-vol"}, "DE-ESCALATION": {"war-fade"},
	"SANCTIONS": {"war-sanctions"}, "CYBER": {"war-cyber"}, "SHIPPING": {"war-shipping"}, "AIR-DEFENSE": {"war-defense"},
	"DEFENSE-SPEND": {"war-budget"}, "REGIME": {"war-haven"}, "TERROR": {"war-fade", "war-vol"},
}

func classify(title, summary string) (score int, themes []string, reg *region) {
	text := title + " . " + summary
	seen := map[string]bool{}
	raw := 0
	for _, tm := range terms {
		hitT := tm.re.MatchString(title)
		hitS := tm.re.MatchString(summary)
		if hitT || hitS {
			w := tm.w
			if !hitT {
				w = w / 2
			}
			raw += w
			if !seen[tm.th] {
				seen[tm.th] = true
				themes = append(themes, tm.th)
			}
		}
	}
	bestIdx, bestPos := -1, 1<<30
	for i := range regions {
		if loc := regions[i].re.FindStringIndex(text); loc != nil {
			// prefer specific hotspots over generic "United States"
			pos := loc[0]
			if regions[i].Name == "United States" {
				pos += 100000
			}
			if pos < bestPos {
				bestIdx, bestPos = i, pos
			}
		}
	}
	if bestIdx >= 0 {
		reg = &regions[bestIdx]
		if raw > 0 {
			raw += reg.Boost
		}
	}
	if seen["DE-ESCALATION"] && !seen["STRIKE"] && !seen["MISSILE"] {
		raw = raw * 2 / 3
	}
	score = int(math.Min(100, float64(raw)*1.4))
	return
}

type rssItem struct {
	Title       string `xml:"title"`
	Link        string `xml:"link"`
	Description string `xml:"description"`
	PubDate     string `xml:"pubDate"`
	DCDate      string `xml:"http://purl.org/dc/elements/1.1/ date"`
}
type atomEntry struct {
	Title   string `xml:"title"`
	Summary string `xml:"summary"`
	Updated string `xml:"updated"`
	Links   []struct {
		Href string `xml:"href,attr"`
	} `xml:"link"`
}

func parseFeed(b []byte) []rssItem {
	var doc struct {
		Items    []rssItem   `xml:"channel>item"`
		RDFItems []rssItem   `xml:"item"`
		Entries  []atomEntry `xml:"entry"`
	}
	newDecoder(b).Decode(&doc)
	items := append(doc.Items, doc.RDFItems...)
	for _, e := range doc.Entries {
		l := ""
		if len(e.Links) > 0 {
			l = e.Links[0].Href
		}
		items = append(items, rssItem{Title: e.Title, Link: l, Description: e.Summary, PubDate: e.Updated})
	}
	return items
}

type rawNews struct {
	Title, Summary, Link, Source string
	Time                         time.Time
}

func fetchFeed(f feedDef) []rawNews {
	b, _, err := cached("rss:"+f.URL, 3*time.Minute, func() ([]byte, error) { return fetchT(f.URL, fastClient, 2) })
	if b == nil {
		setStatus("News: "+f.Name, f.URL, f.Name+" RSS (headline + link only)", 0, err)
		return nil
	}
	var out []rawNews
	for _, it := range parseFeed(b) {
		tm := parseRFC(it.PubDate)
		if tm.IsZero() {
			tm = parseRFC(it.DCDate)
		}
		if tm.IsZero() {
			tm = time.Now().UTC()
		}
		out = append(out, rawNews{strip(it.Title), truncate(strip(it.Description), 320), strings.TrimSpace(it.Link), f.Name, tm})
	}
	setStatus("News: "+f.Name, f.URL, f.Name+" RSS (headline + link only)", len(out), err)
	return out
}

func truncate(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		return string(r[:n]) + "…"
	}
	return s
}

var (
	gdeltMu   sync.Mutex
	gdeltLast []rawNews
	gdeltAt   time.Time
)

func fetchGDELT() []rawNews {
	gdeltMu.Lock()
	last := gdeltLast
	stale := time.Since(gdeltAt) >= 5*time.Minute
	if stale {
		gdeltAt = time.Now()
	}
	gdeltMu.Unlock()
	if stale {
		go refreshGDELT()
	}
	return last
}

func refreshGDELT() {
	q := `(missile OR airstrike OR invasion OR "drone strike" OR "troops" OR "military" OR "naval" OR sanctions OR "nuclear") sourcelang:english`
	u := "https://api.gdeltproject.org/api/v2/doc/doc?mode=artlist&format=json&maxrecords=75&timespan=3h&sort=datedesc&query=" + urlq(q)
	b, err := fetchT(u, client, 1)
	if err != nil {
		setStatus("GDELT (global news graph)", "https://www.gdeltproject.org", "The GDELT Project — open data", 0, err)
		return
	}
	var d struct {
		Articles []struct {
			URL      string `json:"url"`
			Title    string `json:"title"`
			Seendate string `json:"seendate"`
			Domain   string `json:"domain"`
		} `json:"articles"`
	}
	if json.Unmarshal(b, &d) != nil {
		setStatus("GDELT (global news graph)", "https://www.gdeltproject.org", "The GDELT Project — open data", 0, fmt.Errorf("non-JSON reply (rate limited?)"))
		return
	}
	var out []rawNews
	for _, a := range d.Articles {
		tm, _ := time.Parse("20060102T150405Z", a.Seendate)
		out = append(out, rawNews{strip(a.Title), "", a.URL, "GDELT · " + a.Domain, tm.UTC()})
	}
	gdeltMu.Lock()
	gdeltLast = out
	gdeltMu.Unlock()
	setStatus("GDELT (global news graph)", "https://www.gdeltproject.org", "The GDELT Project — open data", len(out), nil)
}

func urlq(s string) string {
	r := strings.NewReplacer(" ", "%20", "\"", "%22", "(", "%28", ")", "%29", ":", "%3A")
	return r.Replace(s)
}

var (
	newsMu   sync.Mutex
	newsLast []byte
	newsAt   time.Time
)

func normTitle(s string) string {
	s = strings.ToLower(s)
	s = regexp.MustCompile(`[^a-z0-9 ]`).ReplaceAllString(s, "")
	f := strings.Fields(s)
	if len(f) > 9 {
		f = f[:9]
	}
	return strings.Join(f, " ")
}

func getNews() []byte {
	newsMu.Lock()
	defer newsMu.Unlock()
	if newsLast != nil && time.Since(newsAt) < 90*time.Second {
		return newsLast
	}
	var mu sync.Mutex
	var all []rawNews
	var wg sync.WaitGroup
	for _, f := range newsFeeds {
		wg.Add(1)
		go func(f feedDef) {
			defer wg.Done()
			items := fetchFeed(f)
			mu.Lock()
			all = append(all, items...)
			mu.Unlock()
		}(f)
	}
	wg.Add(1)
	go func() {
		defer wg.Done()
		items := fetchGDELT()
		mu.Lock()
		all = append(all, items...)
		mu.Unlock()
	}()
	wg.Wait()

	seen := map[string]bool{}
	var out []Event
	cutoff := time.Now().Add(-48 * time.Hour)
	for _, n := range all {
		if n.Title == "" || n.Time.Before(cutoff) {
			continue
		}
		k := normTitle(n.Title)
		if seen[k] {
			continue
		}
		seen[k] = true
		score, themes, reg := classify(n.Title, n.Summary)
		if score < 15 {
			continue
		}
		h := sha1.Sum([]byte(n.Link + n.Title))
		ev := Event{ID: "news-" + hex.EncodeToString(h[:8]), Kind: "WAR", Title: n.Title, Summary: n.Summary, Link: n.Link, Source: n.Source,
			Time: n.Time, Updated: n.Time, Score: score, Level: lvl(score), Themes: themes}
		seenA := map[string]bool{}
		addA := func(as []Asset) {
			for _, a := range as {
				if !seenA[a.S] && len(ev.Assets) < 12 {
					seenA[a.S] = true
					ev.Assets = append(ev.Assets, a)
				}
			}
		}
		stSeen := map[string]bool{}
		for _, th := range themes {
			for _, s := range themeStrategies[th] {
				if !stSeen[s] {
					stSeen[s] = true
					ev.Strategy = append(ev.Strategy, s)
				}
			}
		}
		if reg != nil {
			ev.Region = reg.Name
			ev.Lat, ev.Lon = reg.Lat, reg.Lon
			addA(reg.Assets)
		} else {
			ev.Lat, ev.Lon = math.NaN(), math.NaN()
		}
		for _, th := range themes {
			addA(themeAssets[th])
		}
		deesc := false
		for _, th := range themes {
			if th == "DE-ESCALATION" {
				deesc = true
			}
		}
		if !deesc && score >= 35 {
			addA(generalDefense)
		}
		out = append(out, ev)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Time.After(out[j].Time) })
	if len(out) > 250 {
		out = out[:250]
	}
	// NaN can't be JSON-encoded; use null via pointer-free sentinel
	type wire struct {
		Event
		Lat *float64 `json:"lat"`
		Lon *float64 `json:"lon"`
	}
	ws := make([]wire, len(out))
	for i := range out {
		ws[i].Event = out[i]
		if !math.IsNaN(out[i].Lat) {
			la, lo := out[i].Lat, out[i].Lon
			ws[i].Lat, ws[i].Lon = &la, &lo
		}
	}
	buf, _ := json.Marshal(map[string]any{"events": ws, "generated": time.Now().UTC(), "method": "Keyword + region heuristic classifier (transparent rules, not a probability)"})
	newsLast, newsAt = buf, time.Now()
	return buf
}

func handleNews(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.Write(getNews())
}
