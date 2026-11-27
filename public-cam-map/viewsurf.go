package main

// Viewsurf (France's largest public HD webcam network). Cameras are discovered from
// Viewsurf's public category pages and played with Viewsurf's own embeddable live player,
// resolved fresh each time a camera is opened (/api/vs). Results are cached on disk.

import (
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
	"unicode"

	"golang.org/x/text/unicode/norm"
)

const vsBase = "https://m.viewsurf.com"

var (
	reRegion = regexp.MustCompile(`region/([^"'/?#]+)['"]`)
	reCity   = regexp.MustCompile(`ville/([^"'/?#]+)['"]`)
	reVue    = regexp.MustCompile(`href="(/univers/[a-z]+/vue/(\d+)-[a-z0-9-]+)"(?:[^>]*alt="([^"]*)")?`)
	reEmbed  = regexp.MustCompile(`src="(https://[^"]+/embeded/embeded\.html\?[^"]+)"`)
)

type vsCam struct {
	ID, Path, View, City, Region, Univers string
	Lat, Lon                              float64
}

var (
	vsMu      sync.Mutex
	vsCams    []vsCam
	vsAt      time.Time
	vsRunning bool
	vsErr     string
)

func vsCacheFile() string {
	d, err := os.UserCacheDir()
	if err != nil {
		d = os.TempDir()
	}
	d = filepath.Join(d, "QuietLens")
	os.MkdirAll(d, 0o755)
	return filepath.Join(d, "viewsurf.json")
}

func init() {
	sources = append([]Source{{"fr-viewsurf", "France — Viewsurf HD webcams (live player)", "FR", "Viewsurf", "Viewsurf public player", "https://www.viewsurf.com", loadViewsurf, 20 * time.Second}}, sources...)
	if b, err := os.ReadFile(vsCacheFile()); err == nil {
		var c struct {
			At   time.Time `json:"at"`
			Cams []vsCam   `json:"cams"`
		}
		if json.Unmarshal(b, &c) == nil {
			vsCams, vsAt = c.Cams, c.At
		}
	}
}

func loadViewsurf() ([]Cam, error) {
	vsMu.Lock()
	stale := time.Since(vsAt) > 24*time.Hour
	if stale && !vsRunning {
		vsRunning = true
		go crawlViewsurf()
	}
	list := append([]vsCam(nil), vsCams...)
	errS := vsErr
	vsMu.Unlock()
	var out []Cam
	for _, c := range list {
		if c.Lat == 0 && c.Lon == 0 {
			continue
		}
		kind := map[string]string{"plage": "tourism", "surf": "tourism", "montagne": "tourism", "trafic": "traffic", "ville": "city"}[c.Univers]
		out = append(out, Cam{ID: "vs-" + c.ID, Lat: c.Lat, Lon: c.Lon, Name: c.City + " — " + c.View, Video: "https://www.viewsurf.com" + c.Path, VType: "window", NoEmbed: true,
			Page: "https://www.viewsurf.com" + c.Path, Kind: kind, CC: "FR", City: c.City + ", " + c.Region, Info: "Viewsurf " + c.Univers + " webcam"})
	}
	if len(out) == 0 && errS != "" {
		return nil, fmt.Errorf("%s", errS)
	}
	return out, nil
}

func vsGet(p string) (string, error) {
	time.Sleep(250 * time.Millisecond) // be gentle with their servers
	b, err := fetch(vsBase+p, nil)
	return string(b), err
}

func unq(s string) string {
	u, err := url.PathUnescape(s)
	if err != nil {
		return s
	}
	return u
}

func crawlViewsurf() {
	defer func() { vsMu.Lock(); vsRunning = false; vsMu.Unlock() }()
	seen := map[string]bool{}
	var found []vsCam
	publish := func() {
		vsMu.Lock()
		vsCams = append([]vsCam(nil), found...)
		vsMu.Unlock()
	}
	for _, u := range []string{"plage", "surf", "ville", "montagne", "trafic"} {
		page, err := vsGet("/univers/" + u + "/pays/France")
		if err != nil {
			vsMu.Lock()
			vsErr = "Viewsurf: " + err.Error()
			vsMu.Unlock()
			continue
		}
		regions := uniq(reRegion.FindAllStringSubmatch(page, -1))
		for _, r := range regions {
			rp, err := vsGet("/univers/" + u + "/pays/France/region/" + r)
			if err != nil {
				continue
			}
			for _, c := range uniq(reCity.FindAllStringSubmatch(rp, -1)) {
				cp, err := vsGet("/univers/" + u + "/pays/France/region/" + r + "/ville/" + c)
				if err != nil {
					continue
				}
				city, region := unq(c), unq(r)
				lat, lon := geocodeFR(city, region)
				i := 0
				for _, m := range reVue.FindAllStringSubmatch(cp, -1) {
					if seen[m[2]] {
						continue
					}
					seen[m[2]] = true
					view := m[3]
					if view == "" {
						view = "Webcam " + m[2]
					}
					// spread views of the same town around its centre so they don't stack
					a := float64(i) * 2.4
					d := 0.0009 * math.Sqrt(float64(i))
					found = append(found, vsCam{ID: m[2], Path: m[1], View: view, City: city, Region: region, Univers: u, Lat: lat + d*math.Sin(a), Lon: lon + d*math.Cos(a)*1.5})
					i++
				}
			}
			publish()
		}
	}
	publish()
	vsMu.Lock()
	if len(found) > 0 {
		vsAt, vsErr = time.Now(), ""
		if b, err := json.Marshal(map[string]any{"at": vsAt, "cams": found}); err == nil {
			os.WriteFile(vsCacheFile(), b, 0o644)
		}
	} else {
		vsAt = time.Now().Add(-23 * time.Hour) // retry in ~1 h
	}
	vsMu.Unlock()
}

func uniq(ms [][]string) []string {
	var out []string
	s := map[string]bool{}
	for _, m := range ms {
		if !s[m[1]] {
			s[m[1]] = true
			out = append(out, m[1])
		}
	}
	return out
}

// ---------- geocoding (French government API, Open-Meteo fallback), cached on disk ----------

var (
	geoMu    sync.Mutex
	geoCache map[string][2]float64
)

func geoFile() string { return filepath.Join(filepath.Dir(vsCacheFile()), "geocode.json") }

func fold(s string) string {
	t := norm.NFD.String(strings.ToLower(s))
	var b strings.Builder
	for _, r := range t {
		if unicode.Is(unicode.Mn, r) {
			continue
		}
		if r == '-' || r == '\'' || r == '’' {
			r = ' '
		}
		b.WriteRune(r)
	}
	return strings.Join(strings.Fields(b.String()), " ")
}

func geocodeFR(city, region string) (float64, float64) {
	geoMu.Lock()
	if geoCache == nil {
		geoCache = map[string][2]float64{}
		if b, err := os.ReadFile(geoFile()); err == nil {
			json.Unmarshal(b, &geoCache)
		}
	}
	k := fold(city) + "|" + fold(region)
	if v, ok := geoCache[k]; ok {
		geoMu.Unlock()
		return v[0], v[1]
	}
	geoMu.Unlock()
	lat, lon := 0.0, 0.0
	// 1) geo.api.gouv.fr (official French communes API)
	if b, err := fetch("https://geo.api.gouv.fr/communes?fields=centre&boost=population&limit=5&nom="+url.QueryEscape(city), nil); err == nil {
		var r []struct {
			Nom    string `json:"nom"`
			Centre struct {
				Coordinates []float64 `json:"coordinates"`
			} `json:"centre"`
		}
		if json.Unmarshal(b, &r) == nil {
			for _, x := range r {
				if fold(x.Nom) == fold(city) && len(x.Centre.Coordinates) == 2 {
					lon, lat = x.Centre.Coordinates[0], x.Centre.Coordinates[1]
					break
				}
			}
			if lat == 0 && len(r) > 0 && len(r[0].Centre.Coordinates) == 2 {
				lon, lat = r[0].Centre.Coordinates[0], r[0].Centre.Coordinates[1]
			}
		}
	}
	// 2) Open-Meteo geocoding fallback
	if lat == 0 {
		if b, err := fetch("https://geocoding-api.open-meteo.com/v1/search?count=10&language=fr&name="+url.QueryEscape(city), nil); err == nil {
			var r struct {
				Results []struct {
					Name   string  `json:"name"`
					Lat    float64 `json:"latitude"`
					Lon    float64 `json:"longitude"`
					CC     string  `json:"country_code"`
					Admin1 string  `json:"admin1"`
				} `json:"results"`
			}
			if json.Unmarshal(b, &r) == nil {
				fr := map[string]bool{"FR": true, "RE": true, "GP": true, "MQ": true, "GF": true, "YT": true, "PF": true, "NC": true, "BL": true, "MF": true, "PM": true}
				for _, x := range r.Results {
					if fr[x.CC] {
						lat, lon = x.Lat, x.Lon
						break
					}
				}
			}
		}
	}
	if lat != 0 {
		geoMu.Lock()
		geoCache[k] = [2]float64{lat, lon}
		if b, err := json.Marshal(geoCache); err == nil {
			os.WriteFile(geoFile(), b, 0o644)
		}
		geoMu.Unlock()
	}
	return lat, lon
}

// ---------- resolve a Viewsurf view to its official embeddable live player ----------

var (
	vsrMu  sync.Mutex
	vsrMem = map[string]struct {
		u  string
		at time.Time
	}{}
)

func handleVS(w http.ResponseWriter, r *http.Request) {
	p := r.URL.Query().Get("p")
	if !regexp.MustCompile(`^/univers/[a-z]+/vue/\d+-[a-z0-9-]+$`).MatchString(p) {
		http.Error(w, `{"error":"bad path"}`, 400)
		return
	}
	vsrMu.Lock()
	c, ok := vsrMem[p]
	vsrMu.Unlock()
	if !ok || time.Since(c.at) > 10*time.Minute {
		b, err := fetch(vsBase+p, nil)
		if err != nil {
			http.Error(w, `{"error":"`+jsonEsc(err.Error())+`"}`, 502)
			return
		}
		m := reEmbed.FindStringSubmatch(string(b))
		if m == nil {
			http.Error(w, `{"error":"no live player published for this view"}`, 404)
			return
		}
		c.u, c.at = strings.ReplaceAll(m[1], "&amp;", "&"), time.Now()
		vsrMu.Lock()
		vsrMem[p] = c
		vsrMu.Unlock()
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"embed": c.u})
}
