package main

// Windy Webcams API v3 (optional, free key). Free tier: 50 per page, offset ≤ 1000,
// image URLs expire after ~10 min, so the viewer re-fetches a webcam's fresh image and
// player URLs on open (/api/windy/one).

import (
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

type windyCam struct {
	ID         int64  `json:"webcamId"`
	Title      string `json:"title"`
	Status     string `json:"status"`
	LastUpdate string `json:"lastUpdatedOn"`
	Categories []struct {
		ID string `json:"id"`
	} `json:"categories"`
	Images struct {
		Current map[string]string `json:"current"`
	} `json:"images"`
	Location struct {
		Lat     float64 `json:"latitude"`
		Lon     float64 `json:"longitude"`
		City    string  `json:"city"`
		Region  string  `json:"region"`
		Country string  `json:"country"`
		CC      string  `json:"country_code"`
	} `json:"location"`
	Player map[string]string `json:"player"`
	URLs   struct {
		Detail string `json:"detail"`
	} `json:"urls"`
}

func (c windyCam) toCam() Cam {
	kind := "city"
	for _, cat := range c.Categories {
		switch cat.ID {
		case "traffic":
			kind = "traffic"
		case "beach", "mountain", "landscape", "lake", "coast", "village", "forest", "port":
			if kind == "city" {
				kind = "tourism"
			}
		}
	}
	img := c.Images.Current["preview"]
	if img == "" {
		img = c.Images.Current["thumbnail"]
	}
	live := c.Player["live"]
	if live == "" {
		live = c.Player["day"]
	}
	return Cam{ID: fmt.Sprintf("windy-%d", c.ID), Src: "windy", Lat: c.Location.Lat, Lon: c.Location.Lon, Name: c.Title, Img: img, Video: live, VType: "iframe",
		Page: c.URLs.Detail, Kind: kind, CC: c.Location.CC, City: strings.Trim(c.Location.City+", "+c.Location.Region, ", "), Upd: c.LastUpdate,
		Players: c.Player}
}

func windyGet(path string, p url.Values, key string) ([]byte, error) {
	windyThrottle()
	return fetch("https://api.windy.com/webcams/api/v3/"+path+"?"+p.Encode(), map[string]string{"x-windy-api-key": key})
}

var (
	wtMu   sync.Mutex
	wtLast time.Time
)

// keep well under Windy's rate limits
func windyThrottle() {
	wtMu.Lock()
	defer wtMu.Unlock()
	if d := 220*time.Millisecond - time.Since(wtLast); d > 0 {
		time.Sleep(d)
	}
	wtLast = time.Now()
}

func windyList(p url.Values, key string, maxN int) (int, []Cam, error) {
	p.Set("limit", "50")
	p.Set("include", "location,images,player,urls,categories")
	p.Set("lang", "fr")
	total := 0
	var out []Cam
	for off := 0; off <= 1000 && off < maxN; off += 50 {
		p.Set("offset", strconv.Itoa(off))
		b, err := windyGet("webcams", p, key)
		if err != nil {
			if len(out) > 0 {
				return total, out, nil
			}
			return 0, nil, err
		}
		var d struct {
			Total   int        `json:"total"`
			Webcams []windyCam `json:"webcams"`
		}
		if err := json.Unmarshal(b, &d); err != nil {
			return 0, nil, err
		}
		total = d.Total
		for _, c := range d.Webcams {
			if c.Status == "" || c.Status == "active" {
				out = append(out, c.toCam())
			}
		}
		if len(d.Webcams) < 50 || off+50 >= total {
			break
		}
	}
	return total, out, nil
}

var (
	wcMu  sync.Mutex
	wcMem = map[string]struct {
		b  []byte
		at time.Time
	}{}
)

func handleWindy(w http.ResponseWriter, r *http.Request) {
	key := r.Header.Get("X-Windy-Key")
	if key == "" {
		http.Error(w, `{"error":"no key"}`, 400)
		return
	}
	bb := r.URL.Query().Get("bbox")
	maxN, _ := strconv.Atoi(r.URL.Query().Get("max"))
	if maxN <= 0 || maxN > 1050 {
		maxN = 1050
	}
	ck := bb + "|" + strconv.Itoa(maxN)
	wcMu.Lock()
	c, ok := wcMem[ck]
	wcMu.Unlock()
	if ok && time.Since(c.at) < 8*time.Minute {
		w.Header().Set("Content-Type", "application/json")
		w.Write(c.b)
		return
	}
	p := url.Values{}
	if bb != "" {
		p.Set("bbox", bb)
	}
	p.Set("sortKey", "popularity")
	p.Set("sortDirection", "desc")
	total, cams, err := windyList(p, key, maxN)
	if err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(502)
		json.NewEncoder(w).Encode(map[string]string{"error": "Windy: " + err.Error()})
		return
	}
	b, _ := json.Marshal(map[string]any{"total": total, "cams": cams})
	wcMu.Lock()
	wcMem[ck] = struct {
		b  []byte
		at time.Time
	}{b, time.Now()}
	wcMu.Unlock()
	w.Header().Set("Content-Type", "application/json")
	w.Write(b)
}

// fresh image + player URLs for one webcam (free-tier URLs expire)
func handleWindyOne(w http.ResponseWriter, r *http.Request) {
	key := r.Header.Get("X-Windy-Key")
	id := strings.TrimPrefix(r.URL.Query().Get("id"), "windy-")
	if key == "" || id == "" {
		http.Error(w, `{"error":"missing"}`, 400)
		return
	}
	if _, err := strconv.ParseInt(id, 10, 64); err != nil {
		http.Error(w, `{"error":"bad id"}`, 400)
		return
	}
	b, err := windyGet("webcams/"+id, url.Values{"include": {"location,images,player,urls,categories"}, "lang": {"fr"}}, key)
	if err != nil {
		http.Error(w, `{"error":"`+jsonEsc(err.Error())+`"}`, 502)
		return
	}
	var c windyCam
	json.Unmarshal(b, &c)
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(c.toCam())
}

func jsonEsc(s string) string { b, _ := json.Marshal(s); return strings.Trim(string(b), `"`) }

// ---------- France-wide sweep: every French region, up to 1,000 webcams each ----------

type sweepState struct {
	Running bool   `json:"running"`
	Done    int    `json:"done"`
	Total   int    `json:"total"`
	Cams    int    `json:"cams"`
	Region  string `json:"region"`
	Error   string `json:"error,omitempty"`
	At      string `json:"at,omitempty"`
}

var (
	swMu   sync.Mutex
	sw     sweepState
	swCams []Cam
)

func cacheFile() string {
	d, err := os.UserCacheDir()
	if err != nil {
		d = os.TempDir()
	}
	d = filepath.Join(d, "QuietLens")
	os.MkdirAll(d, 0o755)
	return filepath.Join(d, "windy-france.json")
}

func loadSweepCache() {
	b, err := os.ReadFile(cacheFile())
	if err != nil {
		return
	}
	var c struct {
		At   time.Time `json:"at"`
		Cams []Cam     `json:"cams"`
	}
	if json.Unmarshal(b, &c) == nil && len(c.Cams) > 0 {
		swMu.Lock()
		swCams = c.Cams
		sw.Cams, sw.At = len(c.Cams), c.At.Format(time.RFC3339)
		swMu.Unlock()
	}
}

func handleWindyFrance(w http.ResponseWriter, r *http.Request) {
	key := r.Header.Get("X-Windy-Key")
	if r.Method == "POST" && key != "" {
		swMu.Lock()
		if !sw.Running {
			sw = sweepState{Running: true}
			go runSweep(key)
		}
		swMu.Unlock()
	}
	swMu.Lock()
	st := sw
	var cams []Cam
	if r.URL.Query().Get("cams") == "1" {
		cams = swCams
	}
	swMu.Unlock()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]any{"state": st, "cams": cams})
}

func runSweep(key string) {
	fail := func(e string) {
		swMu.Lock()
		sw.Running, sw.Error = false, e
		swMu.Unlock()
	}
	b, err := windyGet("regions", url.Values{"lang": {"fr"}}, key)
	if err != nil {
		fail("regions: " + err.Error())
		return
	}
	var regs []struct {
		Code string `json:"code"`
		Name string `json:"name"`
	}
	json.Unmarshal(b, &regs)
	var fr []struct{ Code, Name string }
	for _, r := range regs {
		if strings.HasPrefix(r.Code, "FR.") {
			fr = append(fr, struct{ Code, Name string }{r.Code, r.Name})
		}
	}
	if len(fr) == 0 {
		fail("no French regions returned by Windy")
		return
	}
	swMu.Lock()
	sw.Total = len(fr)
	swMu.Unlock()
	seen := map[string]bool{}
	var all []Cam
	for i, rg := range fr {
		swMu.Lock()
		sw.Region, sw.Done = rg.Name, i
		swMu.Unlock()
		_, cams, err := windyList(url.Values{"regions": {rg.Code}, "sortKey": {"popularity"}, "sortDirection": {"desc"}}, key, 1050)
		if err != nil {
			continue
		}
		for _, c := range cams {
			if !seen[c.ID] {
				seen[c.ID] = true
				all = append(all, c)
			}
		}
		swMu.Lock()
		swCams = all
		sw.Cams = len(all)
		swMu.Unlock()
	}
	now := time.Now()
	if fb, err := json.Marshal(map[string]any{"at": now, "cams": all}); err == nil {
		os.WriteFile(cacheFile(), fb, 0o644)
	}
	swMu.Lock()
	sw.Running, sw.Done, sw.At, sw.Region = false, len(fr), now.Format(time.RFC3339), ""
	swMu.Unlock()
}

// ---------- image proxy (lets the viewer keep a rewind buffer of frames) ----------

// Block local/private targets. Hostnames are resolved by the HTTP client; literal IPs and
// localhost names are refused outright.
func publicHost(h string) bool {
	h = strings.ToLower(strings.Trim(h, "[]"))
	if h == "" || h == "localhost" || strings.HasSuffix(h, ".localhost") || strings.HasSuffix(h, ".local") {
		return false
	}
	if ip := net.ParseIP(h); ip != nil {
		return !(ip.IsLoopback() || ip.IsPrivate() || ip.IsLinkLocalUnicast() || ip.IsUnspecified())
	}
	return strings.Contains(h, ".")
}

func handleImg(w http.ResponseWriter, r *http.Request) {
	u := r.URL.Query().Get("u")
	pu, err := url.Parse(u)
	if err != nil || (pu.Scheme != "https" && pu.Scheme != "http") || !publicHost(pu.Hostname()) {
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
	ct := resp.Header.Get("Content-Type")
	if resp.StatusCode >= 400 || !strings.HasPrefix(ct, "image/") {
		http.Error(w, "no image", 502)
		return
	}
	w.Header().Set("Content-Type", ct)
	w.Header().Set("Cache-Control", "no-store")
	io.Copy(w, io.LimitReader(resp.Body, 12<<20))
}
