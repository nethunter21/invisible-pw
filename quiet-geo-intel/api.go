package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

// ---------- HTTP client with retry ----------

var client = &http.Client{Timeout: 20 * time.Second}

const ua = "Mozilla/5.0 (compatible; QuietGeoIntel/1.0)"

func fetch(u string) ([]byte, error) { return fetchT(u, client, 3) }

var fastClient = &http.Client{Timeout: 8 * time.Second}

func fetchT(u string, client *http.Client, tries int) ([]byte, error) {
	var lastErr error
	for attempt := 0; attempt < tries; attempt++ {
		if attempt > 0 {
			time.Sleep(time.Duration(attempt*700) * time.Millisecond)
		}
		req, _ := http.NewRequest("GET", u, nil)
		req.Header.Set("User-Agent", ua)
		req.Header.Set("Accept", "*/*")
		resp, err := client.Do(req)
		if err != nil {
			lastErr = err
			continue
		}
		b, err := io.ReadAll(io.LimitReader(resp.Body, 30<<20))
		resp.Body.Close()
		if err != nil {
			lastErr = err
			continue
		}
		if resp.StatusCode == 429 {
			return nil, fmt.Errorf("rate limited (HTTP 429)")
		}
		if resp.StatusCode >= 400 {
			lastErr = fmt.Errorf("HTTP %d", resp.StatusCode)
			if resp.StatusCode < 500 {
				return nil, lastErr
			}
			continue
		}
		if looksHTML(b) {
			// An HTML page where XML/JSON was expected (e.g. a site's anti-bot page):
			// report it as unavailable instead of parsing it as data.
			return nil, fmt.Errorf("source returned a web page instead of data (access blocked)")
		}
		return b, nil
	}
	return nil, lastErr
}

func looksHTML(b []byte) bool {
	head := bytes.ToLower(bytes.TrimSpace(bytes.TrimPrefix(b, []byte("\xef\xbb\xbf"))))
	if len(head) > 300 {
		head = head[:300]
	}
	return bytes.HasPrefix(head, []byte("<!doctype html")) || bytes.HasPrefix(head, []byte("<html"))
}

// ---------- cache (stale-while-error) ----------

type entry struct {
	data    []byte
	at      time.Time
	err     error
	errAt   time.Time
	loading sync.Mutex
}

var (
	cacheMu sync.Mutex
	cache   = map[string]*entry{}
)

func cached(key string, ttl time.Duration, loader func() ([]byte, error)) ([]byte, time.Time, error) {
	cacheMu.Lock()
	e, ok := cache[key]
	if !ok {
		e = &entry{}
		cache[key] = e
	}
	cacheMu.Unlock()

	e.loading.Lock()
	defer e.loading.Unlock()
	if e.data != nil && time.Since(e.at) < ttl {
		return e.data, e.at, nil
	}
	// back-off after a recent failure
	if e.err != nil && time.Since(e.errAt) < 45*time.Second {
		return e.data, e.at, e.err
	}
	b, err := loader()
	if err != nil {
		e.err, e.errAt = err, time.Now()
		return e.data, e.at, err // stale data (may be nil) + error
	}
	e.data, e.at, e.err = b, time.Now(), nil
	return b, e.at, nil
}

// ---------- source status registry ----------

type SourceStatus struct {
	Name        string    `json:"name"`
	URL         string    `json:"url"`
	OK          bool      `json:"ok"`
	LastOK      time.Time `json:"lastOk"`
	LastTry     time.Time `json:"lastTry"`
	Error       string    `json:"error,omitempty"`
	Items       int       `json:"items"`
	Attribution string    `json:"attribution"`
}

var (
	statusMu sync.Mutex
	statuses = map[string]*SourceStatus{}
)

func setStatus(name, u, attr string, n int, err error) {
	statusMu.Lock()
	defer statusMu.Unlock()
	s, ok := statuses[name]
	if !ok {
		s = &SourceStatus{Name: name, URL: u, Attribution: attr}
		statuses[name] = s
	}
	s.LastTry = time.Now()
	if err != nil {
		s.OK = false
		s.Error = err.Error()
		return
	}
	s.OK, s.Error, s.LastOK, s.Items = true, "", time.Now(), n
}

// ---------- helpers ----------

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	json.NewEncoder(w).Encode(v)
}

func writeRaw(w http.ResponseWriter, b []byte, at time.Time, err error) {
	if b == nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(502)
		msg := "unavailable"
		if err != nil {
			msg = err.Error()
		}
		json.NewEncoder(w).Encode(map[string]string{"error": msg})
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Data-Time", at.UTC().Format(time.RFC3339))
	if err != nil {
		w.Header().Set("X-Stale", err.Error())
	}
	w.Write(b)
}

func registerAPI(mux *http.ServeMux) {
	mux.HandleFunc("/api/ping", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("ok")) })
	mux.HandleFunc("/api/heartbeat", func(w http.ResponseWriter, r *http.Request) {
		lastBeat.Store(time.Now().Unix())
		w.Write([]byte("ok"))
	})
	mux.HandleFunc("/api/quit", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" {
			http.Error(w, "POST only", 405)
			return
		}
		w.Write([]byte("bye"))
		go func() { time.Sleep(300 * time.Millisecond); os.Exit(0) }()
	})
	mux.HandleFunc("/api/status", func(w http.ResponseWriter, r *http.Request) {
		statusMu.Lock()
		list := make([]*SourceStatus, 0, len(statuses))
		for _, s := range statuses {
			c := *s
			list = append(list, &c)
		}
		statusMu.Unlock()
		sort.Slice(list, func(i, j int) bool { return list[i].Name < list[j].Name })
		writeJSON(w, list)
	})
	mux.HandleFunc("/api/natural", handleNatural)
	mux.HandleFunc("/api/cyclones", handleCyclones)
	mux.HandleFunc("/api/tcgeom", handleTCGeom)
	mux.HandleFunc("/api/news", handleNews)
	mux.HandleFunc("/api/spark", handleSpark)
	mux.HandleFunc("/api/chart", handleChart)
	mux.HandleFunc("/api/wx", handleWX)
	mux.HandleFunc("/api/geocode", handleGeocode)
	mux.HandleFunc("/api/radar", handleRadar)
	mux.HandleFunc("/api/predict", handlePredict)
}

func warmup() {
	go func() { getNatural() }()
	go func() { getNews() }()
	go func() {
		rec := httptestRecorder{}
		handleCyclones(&rec, nil)
	}()
}

// httptestRecorder is a minimal ResponseWriter used to pre-warm cached handlers at startup.
type httptestRecorder struct{ h http.Header }

func (r *httptestRecorder) Header() http.Header {
	if r.h == nil {
		r.h = http.Header{}
	}
	return r.h
}
func (r *httptestRecorder) Write(b []byte) (int, error) { return len(b), nil }
func (r *httptestRecorder) WriteHeader(int)             {}

// ---------- Markets (Yahoo Finance public chart/spark endpoints) ----------

type Quote struct {
	Symbol string    `json:"symbol"`
	Name   string    `json:"name,omitempty"`
	Price  float64   `json:"price"`
	Prev   float64   `json:"prev"`
	Chg    float64   `json:"chg"`
	ChgPct float64   `json:"chgPct"`
	Cur    string    `json:"currency"`
	Time   int64     `json:"time"`
	Closes []float64 `json:"closes"`
	Exch   string    `json:"exchange"`
}

func handleSpark(w http.ResponseWriter, r *http.Request) {
	syms := strings.Split(r.URL.Query().Get("symbols"), ",")
	var clean []string
	for _, s := range syms {
		s = strings.TrimSpace(s)
		if s != "" && len(s) < 24 {
			clean = append(clean, s)
		}
	}
	if len(clean) > 120 {
		clean = clean[:120]
	}
	out := map[string]*Quote{}
	var mu sync.Mutex
	var wg sync.WaitGroup
	var firstErr error
	for i := 0; i < len(clean); i += 20 {
		j := i + 20
		if j > len(clean) {
			j = len(clean)
		}
		chunk := clean[i:j]
		wg.Add(1)
		go func(chunk []string) {
			defer wg.Done()
			key := "spark:" + strings.Join(chunk, ",")
			u := "https://query1.finance.yahoo.com/v7/finance/spark?range=1d&interval=5m&symbols=" + url.QueryEscape(strings.Join(chunk, ","))
			b, _, err := cached(key, 60*time.Second, func() ([]byte, error) {
				b, err := fetch(u)
				if err != nil {
					b, err = fetch(strings.Replace(u, "query1", "query2", 1))
				}
				return b, err
			})
			setStatus("Yahoo Finance (quotes)", "https://finance.yahoo.com", "Quotes via Yahoo Finance public endpoints; may be delayed", len(chunk), err)
			if b == nil {
				mu.Lock()
				firstErr = err
				mu.Unlock()
				return
			}
			var sp struct {
				Spark struct {
					Result []struct {
						Symbol   string `json:"symbol"`
						Response []struct {
							Meta struct {
								Price    float64 `json:"regularMarketPrice"`
								Prev     float64 `json:"chartPreviousClose"`
								PrevC    float64 `json:"previousClose"`
								Cur      string  `json:"currency"`
								Time     int64   `json:"regularMarketTime"`
								Name     string  `json:"shortName"`
								LongName string  `json:"longName"`
								Exch     string  `json:"fullExchangeName"`
							} `json:"meta"`
							Indicators struct {
								Quote []struct {
									Close []*float64 `json:"close"`
								} `json:"quote"`
							} `json:"indicators"`
						} `json:"response"`
					} `json:"result"`
				} `json:"spark"`
			}
			if json.Unmarshal(b, &sp) != nil {
				return
			}
			mu.Lock()
			defer mu.Unlock()
			for _, res := range sp.Spark.Result {
				if len(res.Response) == 0 {
					continue
				}
				m := res.Response[0].Meta
				q := &Quote{Symbol: res.Symbol, Price: m.Price, Cur: m.Cur, Time: m.Time, Exch: m.Exch, Name: m.Name}
				if q.Name == "" {
					q.Name = m.LongName
				}
				q.Prev = m.PrevC
				if q.Prev == 0 {
					q.Prev = m.Prev
				}
				if len(res.Response[0].Indicators.Quote) > 0 {
					for _, c := range res.Response[0].Indicators.Quote[0].Close {
						if c != nil {
							q.Closes = append(q.Closes, *c)
						}
					}
				}
				if q.Prev > 0 {
					q.Chg = q.Price - q.Prev
					q.ChgPct = q.Chg / q.Prev * 100
				}
				out[res.Symbol] = q
			}
		}(chunk)
	}
	wg.Wait()
	if len(out) == 0 && firstErr != nil {
		writeRaw(w, nil, time.Time{}, firstErr)
		return
	}
	writeJSON(w, out)
}

func handleChart(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	sym, rng, iv := q.Get("symbol"), q.Get("range"), q.Get("interval")
	okR := map[string]bool{"1d": true, "5d": true, "1mo": true, "3mo": true, "6mo": true, "1y": true, "2y": true, "5y": true, "max": true}
	okI := map[string]bool{"1m": true, "2m": true, "5m": true, "15m": true, "30m": true, "60m": true, "1h": true, "1d": true, "1wk": true, "1mo": true}
	if sym == "" || !okR[rng] || !okI[iv] {
		http.Error(w, "bad params", 400)
		return
	}
	u := fmt.Sprintf("https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=%s&includePrePost=false", url.PathEscape(sym), rng, iv)
	ttl := 60 * time.Second
	if iv == "1d" || iv == "1wk" || iv == "1mo" {
		ttl = 10 * time.Minute
	}
	b, at, err := cached("chart:"+sym+rng+iv, ttl, func() ([]byte, error) {
		b, err := fetch(u)
		if err != nil {
			b, err = fetch(strings.Replace(u, "query1", "query2", 1))
		}
		return b, err
	})
	setStatus("Yahoo Finance (charts)", "https://finance.yahoo.com", "Charts via Yahoo Finance public endpoints", 1, err)
	writeRaw(w, b, at, err)
}

// ---------- Weather (Open-Meteo, CC BY 4.0) ----------

func passQuery(r *http.Request, allowed map[string]bool) string {
	v := url.Values{}
	for k, vals := range r.URL.Query() {
		if allowed[k] && len(vals) > 0 && len(vals[0]) < 4000 {
			v.Set(k, vals[0])
		}
	}
	return v.Encode()
}

func handleWX(w http.ResponseWriter, r *http.Request) {
	allowed := map[string]bool{"latitude": true, "longitude": true, "hourly": true, "daily": true, "current": true,
		"models": true, "forecast_days": true, "past_days": true, "timezone": true, "wind_speed_unit": true,
		"temperature_unit": true, "precipitation_unit": true, "forecast_hours": true, "cell_selection": true}
	qs := passQuery(r, allowed)
	api := "https://api.open-meteo.com/v1/forecast?"
	if r.URL.Query().Get("kind") == "marine" {
		api = "https://marine-api.open-meteo.com/v1/marine?"
	}
	if r.URL.Query().Get("kind") == "ensemble" {
		api = "https://ensemble-api.open-meteo.com/v1/ensemble?"
	}
	u := api + qs
	b, at, err := cached("wx:"+u, 15*time.Minute, func() ([]byte, error) { return fetch(u) })
	setStatus("Open-Meteo (forecast models)", "https://open-meteo.com", "Weather data by Open-Meteo.com (CC BY 4.0)", 1, err)
	writeRaw(w, b, at, err)
}

func handleGeocode(w http.ResponseWriter, r *http.Request) {
	name := r.URL.Query().Get("name")
	if len(name) < 2 || len(name) > 80 {
		http.Error(w, "bad name", 400)
		return
	}
	u := "https://geocoding-api.open-meteo.com/v1/search?count=8&language=en&format=json&name=" + url.QueryEscape(name)
	b, at, err := cached("geo:"+u, 24*time.Hour, func() ([]byte, error) { return fetch(u) })
	setStatus("Open-Meteo (geocoding)", "https://open-meteo.com", "Geocoding by Open-Meteo.com / GeoNames", 1, err)
	writeRaw(w, b, at, err)
}

func handleRadar(w http.ResponseWriter, r *http.Request) {
	u := "https://api.rainviewer.com/public/weather-maps.json"
	b, at, err := cached("radar", 5*time.Minute, func() ([]byte, error) { return fetch(u) })
	setStatus("RainViewer (radar/satellite)", "https://www.rainviewer.com/api.html", "Radar data by RainViewer.com", 1, err)
	writeRaw(w, b, at, err)
}

// ---------- Prediction markets (Polymarket public Gamma API, read-only) ----------

type pmMarket struct {
	Q      string  `json:"q"`
	Yes    float64 `json:"yes"`
	Vol    float64 `json:"vol"`
	Change float64 `json:"chg"`
}
type pmEvent struct {
	Title   string     `json:"title"`
	URL     string     `json:"url"`
	Vol24   float64    `json:"vol24"`
	Liq     float64    `json:"liq"`
	End     string     `json:"end"`
	Markets []pmMarket `json:"markets"`
}

// Prediction markets: Polymarket first, then Kalshi, then Manifold. Polymarket is
// unreachable from some countries, so the others keep the tab working.
func handlePredict(w http.ResponseWriter, r *http.Request) {
	tag := r.URL.Query().Get("tag")
	ok := map[string]bool{"geopolitics": true, "world": true, "middle-east": true, "ukraine": true, "china": true, "weather": true, "climate": true, "economy": true, "politics": true, "commodities": true}
	if !ok[tag] {
		tag = "geopolitics"
	}
	order := []string{"polymarket", "kalshi", "manifold"}
	if src := r.URL.Query().Get("src"); src == "kalshi" || src == "manifold" || src == "polymarket" {
		order = []string{src}
	}
	var errs []string
	for _, src := range order {
		var evs []pmEvent
		var err error
		switch src {
		case "polymarket":
			evs, err = predictPolymarket(tag)
		case "kalshi":
			evs, err = predictKalshi(tag)
		case "manifold":
			evs, err = predictManifold(tag)
		}
		if err == nil && len(evs) > 0 {
			writeJSON(w, map[string]any{"source": src, "events": evs, "errors": errs})
			return
		}
		if err == nil {
			err = errors.New("no open markets for this topic")
		}
		errs = append(errs, src+": "+err.Error())
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(502)
	json.NewEncoder(w).Encode(map[string]any{"error": strings.Join(errs, " · ")})
}

func predictPolymarket(tag string) ([]pmEvent, error) {
	u := "https://gamma-api.polymarket.com/events?limit=40&active=true&closed=false&order=volume24hr&ascending=false&tag_slug=" + tag
	b, _, err := cached("pm:"+tag, 5*time.Minute, func() ([]byte, error) { return fetch(u) })
	setStatus("Polymarket (prediction markets)", "https://polymarket.com", "Polymarket public Gamma API (read-only)", 1, err)
	if b == nil {
		return nil, err
	}
	var evs []map[string]any
	if json.Unmarshal(b, &evs) != nil {
		return nil, errors.New("unexpected reply")
	}
	var out []pmEvent
	for _, e := range evs {
		x := pmEvent{Title: str(e["title"]), URL: "https://polymarket.com/event/" + url.PathEscape(str(e["slug"])), Vol24: num(e["volume24hr"]), Liq: num(e["liquidity"]), End: str(e["endDate"])}
		ms, _ := e["markets"].([]any)
		for _, mm := range ms {
			m, _ := mm.(map[string]any)
			if m == nil || m["closed"] == true {
				continue
			}
			var prices []string
			json.Unmarshal([]byte(str(m["outcomePrices"])), &prices)
			yes := 0.0
			if len(prices) > 0 {
				fmt.Sscanf(prices[0], "%g", &yes)
			}
			q := str(m["groupItemTitle"])
			if q == "" {
				q = str(m["question"])
			}
			x.Markets = append(x.Markets, pmMarket{Q: q, Yes: yes, Vol: num(m["volumeNum"]), Change: num(m["oneDayPriceChange"])})
		}
		sort.Slice(x.Markets, func(i, j int) bool { return x.Markets[i].Yes > x.Markets[j].Yes })
		if len(x.Markets) > 6 {
			x.Markets = x.Markets[:6]
		}
		if len(x.Markets) > 0 {
			out = append(out, x)
		}
	}
	return out, nil
}

var kalshiTopic = map[string]struct {
	cats []string
	kw   string
}{
	"geopolitics": {[]string{"World", "Politics"}, `(?i)war|iran|israel|russia|ukrain|china|taiwan|nato|military|strike|ceasefire|nuclear|sanction|korea|venezuela|tariff`},
	"world":       {[]string{"World"}, `.`},
	"middle-east": {[]string{"World", "Politics"}, `(?i)iran|israel|gaza|hamas|hezbollah|saudi|yemen|houthi|syria|iraq|lebanon|middle east`},
	"ukraine":     {[]string{"World", "Politics"}, `(?i)ukrain|russia|putin|zelensk|crimea`},
	"china":       {[]string{"World", "Politics", "Economics"}, `(?i)china|chinese|taiwan|xi jinping|beijing`},
	"politics":    {[]string{"Politics", "Elections"}, `.`},
	"economy":     {[]string{"Economics", "Financials"}, `.`},
	"commodities": {[]string{"Economics", "Financials"}, `(?i)oil|gold|gas|wheat|corn|copper|commodit|crude|brent|wti`},
	"weather":     {[]string{"Climate and Weather"}, `.`},
	"climate":     {[]string{"Climate and Weather"}, `.`},
}

func predictKalshi(tag string) ([]pmEvent, error) {
	b, _, err := cached("kalshi-events", 10*time.Minute, func() ([]byte, error) {
		var all []json.RawMessage
		cursor := ""
		for page := 0; page < 4; page++ {
			u := "https://api.elections.kalshi.com/trade-api/v2/events?status=open&limit=200&with_nested_markets=true"
			if cursor != "" {
				u += "&cursor=" + url.QueryEscape(cursor)
			}
			pb, err := fetch(u)
			if err != nil {
				if len(all) > 0 {
					break
				}
				return nil, err
			}
			var d struct {
				Events []json.RawMessage `json:"events"`
				Cursor string            `json:"cursor"`
			}
			if json.Unmarshal(pb, &d) != nil {
				break
			}
			all = append(all, d.Events...)
			if d.Cursor == "" {
				break
			}
			cursor = d.Cursor
			time.Sleep(400 * time.Millisecond)
		}
		return json.Marshal(all)
	})
	setStatus("Kalshi (prediction markets)", "https://kalshi.com", "Kalshi public market data (read-only)", 1, err)
	if b == nil {
		return nil, err
	}
	var evs []struct {
		Title    string `json:"title"`
		Sub      string `json:"sub_title"`
		Category string `json:"category"`
		Ticker   string `json:"event_ticker"`
		Series   string `json:"series_ticker"`
		Markets  []struct {
			Title  string `json:"title"`
			YesSub string `json:"yes_sub_title"`
			Last   string `json:"last_price_dollars"`
			Prev   string `json:"previous_price_dollars"`
			Bid    string `json:"yes_bid_dollars"`
			Ask    string `json:"yes_ask_dollars"`
			Vol24  string `json:"volume_24h_fp"`
			Vol    string `json:"volume_fp"`
			Close  string `json:"close_time"`
		} `json:"markets"`
	}
	json.Unmarshal(b, &evs)
	t := kalshiTopic[tag]
	re := regexp.MustCompile(t.kw)
	var out []pmEvent
	for _, e := range evs {
		catOK := false
		for _, c := range t.cats {
			if e.Category == c {
				catOK = true
			}
		}
		if !catOK || !re.MatchString(e.Title+" "+e.Sub) {
			continue
		}
		x := pmEvent{Title: e.Title, URL: "https://kalshi.com/markets/" + strings.ToLower(e.Series)}
		for _, m := range e.Markets {
			yes := num(m.Last)
			if yes == 0 {
				yes = (num(m.Bid) + num(m.Ask)) / 2
			}
			q := m.YesSub
			if q == "" {
				q = m.Title
			}
			x.Vol24 += num(m.Vol24)
			x.Liq += num(m.Vol)
			x.End = m.Close
			x.Markets = append(x.Markets, pmMarket{Q: q, Yes: yes, Vol: num(m.Vol), Change: yes - num(m.Prev)})
		}
		sort.Slice(x.Markets, func(i, j int) bool { return x.Markets[i].Yes > x.Markets[j].Yes })
		if len(x.Markets) > 6 {
			x.Markets = x.Markets[:6]
		}
		if len(x.Markets) > 0 {
			out = append(out, x)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Liq > out[j].Liq })
	if len(out) > 40 {
		out = out[:40]
	}
	return out, nil
}

var manifoldTerms = map[string][]string{
	"geopolitics": {"war", "nuclear", "invasion"}, "world": {"war", "ceasefire"}, "middle-east": {"iran", "israel"},
	"ukraine": {"ukraine", "russia"}, "china": {"taiwan", "china"}, "politics": {"election"}, "economy": {"recession", "inflation"},
	"commodities": {"oil", "gold"}, "weather": {"hurricane", "temperature"}, "climate": {"climate", "temperature"},
}

func predictManifold(tag string) ([]pmEvent, error) {
	var out []pmEvent
	var lastErr error
	seen := map[string]bool{}
	for _, term := range manifoldTerms[tag] {
		u := "https://api.manifold.markets/v0/search-markets?limit=20&filter=open&sort=liquidity&contractType=BINARY&term=" + url.QueryEscape(term)
		b, _, err := cached("mf:"+term, 10*time.Minute, func() ([]byte, error) { return fetch(u) })
		setStatus("Manifold (prediction markets)", "https://manifold.markets", "Manifold Markets public API (play-money, read-only)", 1, err)
		if b == nil {
			lastErr = err
			continue
		}
		var ms []struct {
			Q     string  `json:"question"`
			P     float64 `json:"probability"`
			V24   float64 `json:"volume24Hours"`
			Vol   float64 `json:"volume"`
			Liq   float64 `json:"totalLiquidity"`
			URL   string  `json:"url"`
			Close int64   `json:"closeTime"`
		}
		json.Unmarshal(b, &ms)
		for _, m := range ms {
			if seen[m.URL] {
				continue
			}
			seen[m.URL] = true
			end := ""
			if m.Close > 0 {
				end = time.UnixMilli(m.Close).UTC().Format(time.RFC3339)
			}
			out = append(out, pmEvent{Title: m.Q, URL: m.URL, Vol24: m.V24, Liq: m.Liq, End: end, Markets: []pmMarket{{Q: "Yes", Yes: m.P, Vol: m.Vol}}})
		}
	}
	if len(out) == 0 && lastErr != nil {
		return nil, lastErr
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Liq > out[j].Liq })
	return out, nil
}

func str(v any) string {
	s, _ := v.(string)
	return s
}
func num(v any) float64 {
	switch t := v.(type) {
	case float64:
		return t
	case string:
		var f float64
		fmt.Sscanf(t, "%g", &f)
		return f
	}
	return 0
}
