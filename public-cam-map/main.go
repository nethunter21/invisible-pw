// Quiet Lens (global webcam intel) — a lightweight local map of PUBLIC cameras that their operators
// (road authorities, cities, tourism offices) deliberately publish. No private or
// unsecured cameras are ever listed: every source below is an official open-data feed,
// an OpenStreetMap entry pointing to a public webcam page, or the optional Windy API.
package main

import (
	"bufio"
	"bytes"
	"embed"
	"encoding/json"
	"encoding/xml"
	"errors"
	"flag"
	"fmt"
	"io"
	"io/fs"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

//go:embed web
var webFS embed.FS

const ua = "Mozilla/5.0 (compatible; QuietLens/1.0)"

const appVersion = "quietlens-2.3"

var client = &http.Client{Timeout: 30 * time.Second}

func fetch(u string, hdr map[string]string) ([]byte, error) {
	var last error
	for i := 0; i < 2; i++ {
		req, _ := http.NewRequest("GET", u, nil)
		req.Header.Set("User-Agent", ua)
		req.Header.Set("Accept-Encoding", "gzip")
		for k, v := range hdr {
			req.Header.Set(k, v)
		}
		resp, err := client.Do(req)
		if err != nil {
			last = err
			continue
		}
		var r io.Reader = resp.Body
		if resp.Header.Get("Content-Encoding") == "gzip" {
			if gz, e := gzipReader(resp.Body); e == nil {
				r = gz
			}
		}
		b, err := io.ReadAll(io.LimitReader(r, 40<<20))
		resp.Body.Close()
		if err != nil {
			last = err
			continue
		}
		if resp.StatusCode >= 400 {
			msg := strings.TrimSpace(string(b))
			if len(msg) > 160 {
				msg = msg[:160]
			}
			return nil, fmt.Errorf("HTTP %d %s", resp.StatusCode, msg)
		}
		return b, nil
	}
	return nil, last
}

// ---------------- camera model ----------------

type Cam struct {
	ID    string  `json:"id"`
	Src   string  `json:"src"` // source key
	Lat   float64 `json:"lat"`
	Lon   float64 `json:"lon"`
	Name  string  `json:"name"`
	Img   string  `json:"img,omitempty"`   // still image (refreshing snapshot)
	Video string  `json:"video,omitempty"` // mp4 clip or HLS stream
	VType string  `json:"vtype,omitempty"` // mp4 | hls | iframe
	Page  string  `json:"page,omitempty"`  // public web page of the camera
	Kind  string  `json:"kind"`            // traffic | city | weather | tourism
	CC    string  `json:"cc"`              // ISO country code
	City  string  `json:"city,omitempty"`
	Info  string  `json:"info,omitempty"`  // road / direction / description
	Every int     `json:"every,omitempty"` // seconds between image updates (as documented by source)
	Upd   string  `json:"upd,omitempty"`
	// Windy player variants (live / day / month / year timelapses)
	Players map[string]string `json:"players,omitempty"`
	// site forbids being shown inside another app → opened in a window over the player
	NoEmbed bool `json:"noembed,omitempty"`
}

type Source struct {
	Key, Name, Country, Operator, License, URL string
	Load                                       func() ([]Cam, error)
	TTL                                        time.Duration
}

type srcState struct {
	Cams  []Cam
	At    time.Time
	Err   string
	OK    bool
	Count int
}

var (
	mu     sync.Mutex
	states = map[string]*srcState{}
)

var sources = []Source{
	{"fr-lyon", "Lyon — Criter traffic cameras", "FR", "Métropole de Lyon", "Licence Ouverte 2.0", "https://data.grandlyon.com", loadLyon, 30 * time.Minute},
	{"fr-grenoble", "Grenoble — Métromobilité cameras", "FR", "SMMAG / Métromobilité", "Open data (ODbL)", "https://www.metromobilite.fr", loadGrenoble, 6 * time.Hour},
	{"uk-tfl", "London — TfL JamCams (video clips)", "GB", "Transport for London", "TfL Open Data", "https://tfl.gov.uk/info-for/open-data-users/", loadTfL, 20 * time.Minute},
	{"us-nyc", "New York City — NYC DOT", "US", "NYC Department of Transportation", "NYC Open Data", "https://webcams.nyctmc.org", loadNYC, 30 * time.Minute},
	{"us-caltrans", "California — Caltrans (live streams)", "US", "California DOT", "Public domain (CA gov)", "https://cwwp2.dot.ca.gov", loadCaltrans, 60 * time.Minute},
	{"hk-td", "Hong Kong — Transport Department", "HK", "HK Transport Department", "DATA.GOV.HK terms", "https://data.gov.hk", loadHK, 6 * time.Hour},
	{"fi-digitraffic", "Finland — Digitraffic road weather cams", "FI", "Fintraffic", "CC BY 4.0", "https://www.digitraffic.fi", loadFinland, 60 * time.Minute},
	{"sg-lta", "Singapore — LTA traffic images", "SG", "Land Transport Authority", "Singapore Open Data Licence", "https://data.gov.sg", loadSingapore, 2 * time.Minute},
	{"au-nsw", "Sydney / NSW — Live Traffic", "AU", "Transport for NSW", "CC BY 4.0", "https://opendata.transport.nsw.gov.au", loadNSW, 60 * time.Minute},
	{"nz-nzta", "New Zealand — NZTA traffic cams", "NZ", "NZ Transport Agency", "CC BY 4.0", "https://www.nzta.govt.nz", loadNZ, 6 * time.Hour},
}

func loadSource(s Source) []Cam {
	mu.Lock()
	st, ok := states[s.Key]
	if !ok {
		st = &srcState{}
		states[s.Key] = st
	}
	fresh := st.Cams != nil && time.Since(st.At) < s.TTL
	cams := st.Cams
	mu.Unlock()
	if fresh {
		return cams
	}
	c, err := s.Load()
	mu.Lock()
	defer mu.Unlock()
	if err != nil {
		st.Err, st.OK = err.Error(), false
		if st.At.IsZero() {
			st.At = time.Now().Add(-s.TTL + 2*time.Minute) // retry in 2 min
		}
		return st.Cams // keep last good list
	}
	for i := range c {
		c[i].Src = s.Key
	}
	st.Cams, st.At, st.Err, st.OK, st.Count = c, time.Now(), "", true, len(c)
	return c
}

// ---------------- sources ----------------

func loadLyon() ([]Cam, error) {
	b, err := fetch("https://download.data.grandlyon.com/wfs/grandlyon?SERVICE=WFS&VERSION=2.0.0&request=GetFeature&typename=pvo_patrimoine_voirie.pvocameracriter&outputFormat=application/json;%20subtype=geojson&SRSNAME=EPSG:4326", nil)
	if err != nil {
		return nil, err
	}
	var d struct {
		Features []struct {
			Geometry struct{ Coordinates []float64 } `json:"geometry"`
			P        struct {
				Nom, Libellelong, Observation, URL, LastUpdate string
				ID                                             int `json:"identifiant"`
			} `json:"properties"`
		} `json:"features"`
	}
	if err := json.Unmarshal(b, &d); err != nil {
		return nil, err
	}
	var out []Cam
	for _, f := range d.Features {
		if len(f.Geometry.Coordinates) < 2 {
			continue
		}
		var lu struct {
			LastUpdate string `json:"last_update"`
		}
		_ = lu
		out = append(out, Cam{ID: fmt.Sprintf("lyon-%d", f.P.ID), Lat: f.Geometry.Coordinates[1], Lon: f.Geometry.Coordinates[0],
			Name: strings.TrimSpace(f.P.Nom + " — " + f.P.Libellelong), Img: f.P.URL, Kind: "traffic", CC: "FR", City: "Lyon",
			Info: f.P.Observation, Every: 60, Page: "https://www.onlymoov.com/"})
	}
	return out, nil
}

func loadGrenoble() ([]Cam, error) {
	b, err := fetch("https://data.mobilites-m.fr/api/findType/json?types=CAM", nil)
	if err != nil {
		return nil, err
	}
	var d struct {
		Features []struct {
			Geometry struct{ Coordinates []float64 } `json:"geometry"`
			P        struct {
				Code    string `json:"CODE"`
				Libelle string `json:"LIBELLE"`
				Commune string `json:"commune"`
			} `json:"properties"`
		} `json:"features"`
	}
	if err := json.Unmarshal(b, &d); err != nil {
		return nil, err
	}
	var out []Cam
	for _, f := range d.Features {
		if len(f.Geometry.Coordinates) < 2 {
			continue
		}
		out = append(out, Cam{ID: "gre-" + f.P.Code, Lat: f.Geometry.Coordinates[1], Lon: f.Geometry.Coordinates[0], Name: f.P.Libelle,
			Kind: "traffic", CC: "FR", City: f.P.Commune, Page: "https://www.metromobilite.fr/", Info: "Image shown on the Métromobilité website"})
	}
	return out, nil
}

func loadTfL() ([]Cam, error) {
	b, err := fetch("https://api.tfl.gov.uk/Place/Type/JamCam", nil)
	if err != nil {
		return nil, err
	}
	var d []struct {
		ID, CommonName string
		Lat, Lon       float64
		Props          []struct{ Key, Value string } `json:"additionalProperties"`
	}
	if err := json.Unmarshal(b, &d); err != nil {
		return nil, err
	}
	var out []Cam
	for _, c := range d {
		cm := Cam{ID: "tfl-" + c.ID, Lat: c.Lat, Lon: c.Lon, Name: c.CommonName, Kind: "traffic", CC: "GB", City: "London", Every: 300, VType: "mp4", Page: "https://tfl.gov.uk/traffic/status/"}
		avail := true
		for _, p := range c.Props {
			switch p.Key {
			case "imageUrl":
				cm.Img = p.Value
			case "videoUrl":
				cm.Video = p.Value
			case "view":
				cm.Info = "View: " + p.Value
			case "available":
				avail = p.Value == "true"
			}
		}
		if avail && cm.Img != "" {
			out = append(out, cm)
		}
	}
	return out, nil
}

func loadNYC() ([]Cam, error) {
	b, err := fetch("https://webcams.nyctmc.org/api/cameras", nil)
	if err != nil {
		return nil, err
	}
	var d []struct {
		ID, Name, Area, IsOnline, ImageURL string
		Latitude, Longitude                float64
	}
	if err := json.Unmarshal(b, &d); err != nil {
		return nil, err
	}
	var out []Cam
	for _, c := range d {
		if c.IsOnline != "true" {
			continue
		}
		out = append(out, Cam{ID: "nyc-" + c.ID, Lat: c.Latitude, Lon: c.Longitude, Name: c.Name, Img: c.ImageURL, Kind: "traffic", CC: "US", City: "New York — " + c.Area, Every: 2, Page: "https://webcams.nyctmc.org/"})
	}
	return out, nil
}

func loadCaltrans() ([]Cam, error) {
	var mu2 sync.Mutex
	var out []Cam
	var wg sync.WaitGroup
	var errs []string
	for d := 1; d <= 12; d++ {
		wg.Add(1)
		go func(d int) {
			defer wg.Done()
			b, err := fetch(fmt.Sprintf("https://cwwp2.dot.ca.gov/data/d%d/cctv/cctvStatusD%02d.json", d, d), nil)
			if err != nil {
				mu2.Lock()
				errs = append(errs, fmt.Sprintf("D%d: %v", d, err))
				mu2.Unlock()
				return
			}
			var x struct {
				Data []struct {
					C struct {
						Index    string `json:"index"`
						InSvc    string `json:"inService"`
						Location struct {
							Name        string `json:"locationName"`
							NearbyPlace string `json:"nearbyPlace"`
							Longitude   string `json:"longitude"`
							Latitude    string `json:"latitude"`
							Direction   string `json:"direction"`
							County      string `json:"county"`
							Route       string `json:"route"`
						} `json:"location"`
						Image struct {
							Stream string `json:"streamingVideoURL"`
							Static struct {
								URL  string `json:"currentImageURL"`
								Freq string `json:"currentImageUpdateFrequency"`
							} `json:"static"`
						} `json:"imageData"`
					} `json:"cctv"`
				} `json:"data"`
			}
			if json.Unmarshal(b, &x) != nil {
				return
			}
			var loc []Cam
			for _, c := range x.Data {
				cc := c.C
				if cc.InSvc != "true" {
					continue
				}
				la, _ := strconv.ParseFloat(cc.Location.Latitude, 64)
				lo, _ := strconv.ParseFloat(cc.Location.Longitude, 64)
				fr, _ := strconv.Atoi(cc.Image.Static.Freq)
				cm := Cam{ID: fmt.Sprintf("ca-%d-%s", d, cc.Index), Lat: la, Lon: lo, Name: cc.Location.Name, Img: cc.Image.Static.URL, Kind: "traffic", CC: "US",
					City: cc.Location.NearbyPlace + ", " + cc.Location.County + " County", Info: strings.TrimSpace(cc.Location.Route + " " + cc.Location.Direction), Every: fr * 60, Page: "https://quickmap.dot.ca.gov/"}
				if cc.Image.Stream != "" {
					cm.Video, cm.VType = cc.Image.Stream, "hls"
				}
				if la != 0 && (cm.Img != "" || cm.Video != "") {
					loc = append(loc, cm)
				}
			}
			mu2.Lock()
			out = append(out, loc...)
			mu2.Unlock()
		}(d)
	}
	wg.Wait()
	if len(out) == 0 && len(errs) > 0 {
		return nil, errors.New(strings.Join(errs, "; "))
	}
	return out, nil
}

func loadHK() ([]Cam, error) {
	b, err := fetch("https://static.data.gov.hk/td/traffic-snapshot-images/code/Traffic_Camera_Locations_En.xml", nil)
	if err != nil {
		return nil, err
	}
	var d struct {
		Images []struct {
			Key         string  `xml:"key"`
			Region      string  `xml:"region"`
			District    string  `xml:"district"`
			Description string  `xml:"description"`
			URL         string  `xml:"url"`
			Latitude    float64 `xml:"latitude"`
			Longitude   float64 `xml:"longitude"`
		} `xml:"image"`
	}
	if err := xml.Unmarshal(b, &d); err != nil {
		return nil, err
	}
	var out []Cam
	for _, c := range d.Images {
		out = append(out, Cam{ID: "hk-" + c.Key, Lat: c.Latitude, Lon: c.Longitude, Name: c.Description, Img: c.URL, Kind: "traffic", CC: "HK", City: c.District + ", " + c.Region, Every: 120, Page: "https://www.td.gov.hk/en/transport_in_hong_kong/its/"})
	}
	return out, nil
}

func loadFinland() ([]Cam, error) {
	b, err := fetch("https://tie.digitraffic.fi/api/weathercam/v1/stations", map[string]string{"Digitraffic-User": "QuietLens/1.0"})
	if err != nil {
		return nil, err
	}
	var d struct {
		Features []struct {
			Geometry struct{ Coordinates []float64 } `json:"geometry"`
			P        struct {
				ID, Name, CollectionStatus string
				Presets                    []struct {
					ID           string `json:"id"`
					InCollection bool   `json:"inCollection"`
				} `json:"presets"`
			} `json:"properties"`
		} `json:"features"`
	}
	if err := json.Unmarshal(b, &d); err != nil {
		return nil, err
	}
	var out []Cam
	for _, f := range d.Features {
		if len(f.Geometry.Coordinates) < 2 || f.P.CollectionStatus != "GATHERING" {
			continue
		}
		for i, p := range f.P.Presets {
			if !p.InCollection {
				continue
			}
			// offset presets of one station slightly so they don't stack exactly
			out = append(out, Cam{ID: "fi-" + p.ID, Lat: f.Geometry.Coordinates[1] + float64(i)*0.00012, Lon: f.Geometry.Coordinates[0], Name: strings.ReplaceAll(f.P.Name, "_", " ") + fmt.Sprintf(" (view %d)", i+1),
				Img: "https://weathercam.digitraffic.fi/" + p.ID + ".jpg", Kind: "weather", CC: "FI", Every: 600, Page: "https://liikennetilanne.fintraffic.fi/"})
		}
	}
	return out, nil
}

func loadSingapore() ([]Cam, error) {
	b, err := fetch("https://api.data.gov.sg/v1/transport/traffic-images", nil)
	if err != nil {
		return nil, err
	}
	var d struct {
		Items []struct {
			Cameras []struct {
				Timestamp string `json:"timestamp"`
				Image     string `json:"image"`
				CameraID  string `json:"camera_id"`
				Location  struct {
					Lat float64 `json:"latitude"`
					Lon float64 `json:"longitude"`
				} `json:"location"`
			} `json:"cameras"`
		} `json:"items"`
	}
	if err := json.Unmarshal(b, &d); err != nil {
		return nil, err
	}
	var out []Cam
	if len(d.Items) > 0 {
		for _, c := range d.Items[0].Cameras {
			out = append(out, Cam{ID: "sg-" + c.CameraID, Lat: c.Location.Lat, Lon: c.Location.Lon, Name: "Singapore traffic camera " + c.CameraID, Img: c.Image, Kind: "traffic", CC: "SG", City: "Singapore", Every: 60, Upd: c.Timestamp, Page: "https://onemotoring.lta.gov.sg/content/onemotoring/home/driving/traffic_information/traffic-cameras.html"})
		}
	}
	return out, nil
}

func loadNSW() ([]Cam, error) {
	b, err := fetch("https://data.livetraffic.com/cameras/traffic-cam.json", nil)
	if err != nil {
		return nil, err
	}
	var d struct {
		Features []struct {
			ID       string                                                `json:"id"`
			Geometry struct{ Coordinates []float64 }                       `json:"geometry"`
			P        struct{ Region, Title, View, Direction, Href string } `json:"properties"`
		} `json:"features"`
	}
	if err := json.Unmarshal(b, &d); err != nil {
		return nil, err
	}
	var out []Cam
	for _, f := range d.Features {
		if len(f.Geometry.Coordinates) < 2 {
			continue
		}
		out = append(out, Cam{ID: "nsw-" + f.ID, Lat: f.Geometry.Coordinates[1], Lon: f.Geometry.Coordinates[0], Name: f.P.Title, Img: f.P.Href, Kind: "traffic", CC: "AU", City: strings.ReplaceAll(f.P.Region, "_", " "), Info: f.P.View, Every: 60, Page: "https://www.livetraffic.com/"})
	}
	return out, nil
}

func loadNZ() ([]Cam, error) {
	b, err := fetch("https://trafficnz.info/service/traffic/rest/4/cameras/all", nil)
	if err != nil {
		return nil, err
	}
	var d struct {
		Cams []struct {
			ID          string  `xml:"id"`
			Name        string  `xml:"name"`
			Description string  `xml:"description"`
			Direction   string  `xml:"direction"`
			Highway     string  `xml:"highway"`
			Region      string  `xml:"region>name"`
			ImageURL    string  `xml:"imageUrl"`
			Lat         float64 `xml:"latitude"`
			Lon         float64 `xml:"longitude"`
			Offline     string  `xml:"offline"`
		} `xml:"camera"`
	}
	if err := xml.Unmarshal(b, &d); err != nil {
		return nil, err
	}
	var out []Cam
	for _, c := range d.Cams {
		if c.Lat == 0 || c.Offline == "true" {
			continue
		}
		img := c.ImageURL
		if strings.HasPrefix(img, "/") {
			img = "https://trafficnz.info" + img
		}
		name := c.Name
		if name == "" {
			name = c.Description
		}
		out = append(out, Cam{ID: "nz-" + c.ID, Lat: c.Lat, Lon: c.Lon, Name: name, Img: img, Kind: "traffic", CC: "NZ", City: c.Region, Info: strings.TrimSpace(c.Highway + " " + c.Direction + " — " + c.Description), Every: 60, Page: "https://www.journeys.nzta.govt.nz/traffic-cameras"})
	}
	return out, nil
}

// ---------------- OpenStreetMap public webcams (bbox, on demand) ----------------

var overpass = []string{"https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter"}

type osmCache struct {
	b  []byte
	at time.Time
}

var (
	osmMu  sync.Mutex
	osmMem = map[string]osmCache{}
	osmErr atomic.Value
	osmOK  atomic.Int64
)

func handleOSM(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	var bb [4]float64
	for i, k := range []string{"s", "w", "n", "e"} {
		v, err := strconv.ParseFloat(q.Get(k), 64)
		if err != nil {
			http.Error(w, "bad bbox", 400)
			return
		}
		bb[i] = v
	}
	// snap to a 1° grid so panning reuses cached tiles
	s, wv, n, e := floor(bb[0]), floor(bb[1]), ceil(bb[2]), ceil(bb[3])
	if (n-s)*(e-wv) > 64 {
		http.Error(w, "zoom in", 400)
		return
	}
	key := fmt.Sprintf("%g,%g,%g,%g", s, wv, n, e)
	osmMu.Lock()
	c, ok := osmMem[key]
	osmMu.Unlock()
	if ok && time.Since(c.at) < 12*time.Hour {
		w.Header().Set("Content-Type", "application/json")
		w.Write(c.b)
		return
	}
	query := fmt.Sprintf(`[out:json][timeout:40];(nwr["contact:webcam"](%[1]g,%[2]g,%[3]g,%[4]g);nwr["webcam"](%[1]g,%[2]g,%[3]g,%[4]g);nwr["man_made"="surveillance"]["surveillance:type"="webcam"]["contact:webcam"](%[1]g,%[2]g,%[3]g,%[4]g););out center tags 2000;`, s, wv, n, e)
	var body []byte
	var err error
	for _, ep := range overpass {
		body, err = fetchOnce(ep+"?data="+url.QueryEscape(query), 25*time.Second)
		if err == nil {
			break
		}
	}
	if err != nil {
		osmErr.Store(err.Error())
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(502)
		json.NewEncoder(w).Encode(map[string]string{"error": "OpenStreetMap (Overpass) unavailable: " + err.Error()})
		return
	}
	var d struct {
		Elements []struct {
			Type   string                      `json:"type"`
			ID     int64                       `json:"id"`
			Lat    float64                     `json:"lat"`
			Lon    float64                     `json:"lon"`
			Center *struct{ Lat, Lon float64 } `json:"center"`
			Tags   map[string]string           `json:"tags"`
		} `json:"elements"`
	}
	json.Unmarshal(body, &d)
	var out []Cam
	for _, el := range d.Elements {
		la, lo := el.Lat, el.Lon
		if el.Center != nil {
			la, lo = el.Center.Lat, el.Center.Lon
		}
		t := el.Tags
		link := t["contact:webcam"]
		if link == "" {
			link = t["webcam"]
		}
		if link == "" || !strings.HasPrefix(link, "http") {
			continue
		}
		name := t["name"]
		if name == "" {
			name = t["description"]
		}
		if name == "" {
			name = "Public webcam (" + hostOf(link) + ")"
		}
		kind := "tourism"
		if t["tourism"] == "" && t["amenity"] == "" && t["natural"] == "" {
			kind = "city"
		}
		out = append(out, Cam{ID: fmt.Sprintf("osm-%s%d", el.Type[:1], el.ID), Src: "osm", Lat: la, Lon: lo, Name: name, Page: link, Kind: kind,
			City: t["addr:city"], Info: "Public webcam page: " + hostOf(link), CC: strings.ToUpper(t["addr:country"])})
	}
	osmOK.Store(time.Now().Unix())
	b, _ := json.Marshal(out)
	osmMu.Lock()
	osmMem[key] = osmCache{b, time.Now()}
	osmMu.Unlock()
	w.Header().Set("Content-Type", "application/json")
	w.Write(b)
}

func floor(v float64) float64 { return float64(int(v+1000)) - 1000 }
func ceil(v float64) float64 {
	f := floor(v)
	if f == v {
		return v
	}
	return f + 1
}
func hostOf(u string) string {
	p, err := url.Parse(u)
	if err != nil {
		return u
	}
	return strings.TrimPrefix(p.Host, "www.")
}

// ---------------- HLS proxy (Caltrans live streams; adds CORS-free playback) ----------------

func handleHLS(w http.ResponseWriter, r *http.Request) {
	u := r.URL.Query().Get("u")
	pu, err := url.Parse(u)
	if err != nil || pu.Scheme != "https" || !strings.HasSuffix(pu.Host, "dot.ca.gov") {
		http.Error(w, "not allowed", 403)
		return
	}
	req, _ := http.NewRequest("GET", u, nil)
	req.Header.Set("User-Agent", ua)
	resp, err := client.Do(req)
	if err != nil {
		http.Error(w, err.Error(), 502)
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		http.Error(w, "stream offline", resp.StatusCode)
		return
	}
	if strings.Contains(u, ".m3u8") || strings.Contains(resp.Header.Get("Content-Type"), "mpegurl") {
		var buf bytes.Buffer
		sc := bufio.NewScanner(io.LimitReader(resp.Body, 2<<20))
		for sc.Scan() {
			line := sc.Text()
			if line != "" && !strings.HasPrefix(line, "#") {
				abs, e := pu.Parse(line)
				if e == nil {
					line = "/api/hls?u=" + url.QueryEscape(abs.String())
				}
			}
			buf.WriteString(line + "\n")
		}
		w.Header().Set("Content-Type", "application/vnd.apple.mpegurl")
		w.Header().Set("Cache-Control", "no-store")
		w.Write(buf.Bytes())
		return
	}
	w.Header().Set("Content-Type", resp.Header.Get("Content-Type"))
	io.Copy(w, resp.Body)
}

// ---------------- handlers ----------------

func handleCams(w http.ResponseWriter, r *http.Request) {
	var wg sync.WaitGroup
	res := make([][]Cam, len(sources))
	for i, s := range sources {
		wg.Add(1)
		go func(i int, s Source) { defer wg.Done(); res[i] = loadSource(s) }(i, s)
	}
	wg.Wait()
	var all []Cam
	for _, c := range res {
		all = append(all, c...)
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	json.NewEncoder(w).Encode(all)
}

func handleSources(w http.ResponseWriter, r *http.Request) {
	type row struct {
		Key, Name, Country, Operator, License, URL, Error string
		OK                                                bool
		Count                                             int
		At                                                time.Time
	}
	var out []row
	mu.Lock()
	for _, s := range sources {
		st := states[s.Key]
		rw := row{Key: s.Key, Name: s.Name, Country: s.Country, Operator: s.Operator, License: s.License, URL: s.URL}
		if st != nil {
			rw.OK, rw.Count, rw.Error, rw.At = st.OK, st.Count, st.Err, st.At
		}
		out = append(out, rw)
	}
	mu.Unlock()
	oe, _ := osmErr.Load().(string)
	out = append(out, row{Key: "osm", Name: "OpenStreetMap — public webcam pages (worldwide, loads as you zoom)", Country: "World", Operator: "OpenStreetMap contributors", License: "ODbL", URL: "https://www.openstreetmap.org", OK: osmOK.Load() > 0, Error: oe})
	sort.SliceStable(out, func(i, j int) bool {
		return strings.HasPrefix(out[i].Key, "fr") && !strings.HasPrefix(out[j].Key, "fr")
	})
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(out)
}

var lastBeat atomic.Int64

func main() {
	port := flag.Int("port", 8790, "local port")
	noOpen := flag.Bool("noopen", false, "do not open a window")
	flag.Parse()
	addr := fmt.Sprintf("127.0.0.1:%d", *port)
	pageURL := "http://" + addr + "/"
	if c, err := net.DialTimeout("tcp", addr, 400*time.Millisecond); err == nil {
		c.Close()
		// Same version already running → just open it. Older build (or the former
		// "Public Cam Map") → ask it to quit so this version takes over.
		if r, err := http.Get(pageURL + "api/version"); err == nil {
			b, _ := io.ReadAll(r.Body)
			r.Body.Close()
			if strings.TrimSpace(string(b)) == appVersion {
				openUI(pageURL)
				return
			}
		}
		http.Post(pageURL+"api/quit", "text/plain", nil)
		time.Sleep(1200 * time.Millisecond)
	}
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		ln, err = net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			log.Fatal(err)
		}
		pageURL = "http://" + ln.Addr().String() + "/"
	}
	sub, _ := fs.Sub(webFS, "web")
	mux := http.NewServeMux()
	mux.HandleFunc("/api/cams", handleCams)
	mux.HandleFunc("/api/sources", handleSources)
	mux.HandleFunc("/api/osm", handleOSM)
	mux.HandleFunc("/api/windy", handleWindy)
	mux.HandleFunc("/api/windy/one", handleWindyOne)
	mux.HandleFunc("/api/windy/france", handleWindyFrance)
	mux.HandleFunc("/api/img", handleImg)
	mux.HandleFunc("/api/vs", handleVS)
	mux.HandleFunc("/api/hls", handleHLS)
	mux.HandleFunc("/api/heartbeat", func(w http.ResponseWriter, r *http.Request) { lastBeat.Store(time.Now().Unix()) })
	mux.HandleFunc("/api/quit", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			go func() { time.Sleep(200 * time.Millisecond); os.Exit(0) }()
		}
	})
	mux.HandleFunc("/api/version", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte(appVersion)) })
	fsrv := http.FileServer(http.FS(sub))
	mux.Handle("/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-cache, no-store, must-revalidate")
		fsrv.ServeHTTP(w, r)
	}))
	loadSweepCache()
	go func() { // warm the cache
		for _, s := range sources {
			go loadSource(s)
		}
	}()
	lastBeat.Store(time.Now().Unix())
	if !*noOpen {
		go func() { time.Sleep(300 * time.Millisecond); openUI(pageURL) }()
		go func() {
			for range time.Tick(30 * time.Second) {
				if time.Now().Unix()-lastBeat.Load() > 360 {
					os.Exit(0)
				}
			}
		}()
	}
	log.Printf("Quiet Lens at %s", pageURL)
	log.Fatal(http.Serve(ln, mux))
}

func openUI(u string) {
	switch runtime.GOOS {
	case "windows":
		for _, c := range []string{
			filepath.Join(os.Getenv("ProgramFiles(x86)"), `Microsoft\Edge\Application\msedge.exe`),
			filepath.Join(os.Getenv("ProgramFiles"), `Microsoft\Edge\Application\msedge.exe`),
			filepath.Join(os.Getenv("ProgramFiles"), `Google\Chrome\Application\chrome.exe`),
			filepath.Join(os.Getenv("LocalAppData"), `Google\Chrome\Application\chrome.exe`),
		} {
			if _, err := os.Stat(c); err == nil && exec.Command(c, "--app="+u, "--window-size=1600,950").Start() == nil {
				return
			}
		}
		exec.Command("rundll32", "url.dll,FileProtocolHandler", u).Start()
	case "darwin":
		exec.Command("open", u).Start()
	default:
		exec.Command("xdg-open", u).Start()
	}
}

var shortClient = &http.Client{}

func fetchOnce(u string, timeout time.Duration) ([]byte, error) {
	c := *shortClient
	c.Timeout = timeout
	req, _ := http.NewRequest("GET", u, nil)
	req.Header.Set("User-Agent", ua)
	resp, err := c.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(io.LimitReader(resp.Body, 20<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("HTTP %d", resp.StatusCode)
	}
	return b, nil
}
