package main

import (
	"bufio"
	"bytes"
	_ "embed"
	"encoding/json"
	"fmt"
	"io"
	"math/rand/v2"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

//go:embed web/index.html
var indexHTML []byte

//go:embed words/en.txt
var enRaw string

//go:embed words/fr.txt
var frRaw string

var enWords, frWords []string

const (
	api     = "https://discord.com/api/v9/unique-username/username-attempt-unauthed"
	letters = "abcdefghijklmnopqrstuvwxyz"
	digits  = "0123456789"
	alnum   = letters + digits
	vowels  = "aeiouy"
	conson  = "bcdfghjklmnpqrstvwxz"
	ua      = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

var validRe = regexp.MustCompile(`^[a-z0-9_.]{2,32}$`)

type Config struct {
	Mode                      string
	MinLen, MaxLen, Count     int
	Threads, Timeout, DelayMs int
	Sep, SepPos               string
	RepType, RepChars         string
	Pattern                   string
	WordLang, WordStyle       string
	WordMin, WordMax, WordTop int
	WordDigits                int
	Prefix, Suffix, List      string
	ProxyMode, ProxyType      string
	Proxies                   string
	UseDirect, SkipChecked    bool
	SaveTaken                 bool
	Webhook                   string
	MaxFails                  int
}

// ---------------- generator ----------------

func pick(s string) byte { return s[rand.IntN(len(s))] }

func sepChar(c *Config) string {
	switch c.Sep {
	case ".", "_":
		return c.Sep
	}
	if rand.IntN(2) == 0 {
		return "."
	}
	return "_"
}

func charset(k string) string {
	switch k {
	case "letters":
		return letters
	case "digits":
		return digits
	}
	return alnum
}

func randStr(cs string, n int) string {
	b := make([]byte, n)
	for i := range b {
		b[i] = pick(cs)
	}
	return string(b)
}

func genRep(c *Config, L int) string {
	cs := charset(c.RepChars)
	t := c.RepType
	if t == "any" || t == "" {
		t = []string{"same", "alt", "blocks", "pal", "two", "triple"}[rand.IntN(6)]
	}
	a := pick(cs)
	b := pick(cs)
	for b == a {
		b = pick(cs)
	}
	o := make([]byte, L)
	switch t {
	case "same":
		for i := range o {
			o[i] = a
		}
	case "alt":
		for i := range o {
			if i%2 == 0 {
				o[i] = a
			} else {
				o[i] = b
			}
		}
	case "blocks":
		k := 1 + rand.IntN(max(L-1, 1))
		for i := range o {
			if i < k {
				o[i] = a
			} else {
				o[i] = b
			}
		}
	case "pal":
		for i := 0; i < (L+1)/2; i++ {
			ch := pick(cs)
			o[i], o[L-1-i] = ch, ch
		}
	case "triple": // one odd char among repeats: aaaba
		for i := range o {
			o[i] = a
		}
		o[rand.IntN(L)] = b
	default: // two distinct chars random
		for i := range o {
			if rand.IntN(2) == 0 {
				o[i] = a
			} else {
				o[i] = b
			}
		}
		o[0], o[L-1] = a, b
	}
	return string(o)
}

func genPattern(p string) string {
	var sb strings.Builder
	for _, r := range p {
		switch r {
		case 'L':
			sb.WriteByte(pick(letters))
		case 'D':
			sb.WriteByte(pick(digits))
		case 'X', '?':
			sb.WriteByte(pick(alnum))
		case 'V':
			sb.WriteByte(pick(vowels))
		case 'C':
			sb.WriteByte(pick(conson))
		default:
			sb.WriteRune(r)
		}
	}
	return strings.ToLower(sb.String())
}

func wordPool(c *Config) []string {
	var src [][]string
	switch c.WordLang {
	case "en":
		src = [][]string{enWords}
	case "fr":
		src = [][]string{frWords}
	default:
		src = [][]string{enWords, frWords}
	}
	var out []string
	seen := map[string]bool{}
	for _, l := range src {
		n := 0
		for _, w := range l {
			if c.WordTop > 0 && n >= c.WordTop {
				break
			}
			n++
			if len(w) >= c.WordMin && len(w) <= c.WordMax && !seen[w] {
				seen[w] = true
				out = append(out, w)
			}
		}
	}
	return out
}

type Gen struct {
	c    *Config
	pool []string
	list []string
	li   int
}

func newGen(c *Config) (*Gen, error) {
	g := &Gen{c: c}
	switch c.Mode {
	case "words":
		g.pool = wordPool(c)
		if len(g.pool) == 0 {
			return nil, fmt.Errorf("no words match these filters")
		}
	case "list":
		for _, l := range strings.Split(c.List, "\n") {
			if l = strings.ToLower(strings.TrimSpace(l)); l != "" {
				g.list = append(g.list, l)
			}
		}
		if len(g.list) == 0 {
			return nil, fmt.Errorf("username list is empty")
		}
	case "pattern":
		if strings.TrimSpace(c.Pattern) == "" {
			return nil, fmt.Errorf("pattern is empty")
		}
	}
	return g, nil
}

// next returns a candidate; ok=false when list exhausted
func (g *Gen) next() (string, bool) {
	c := g.c
	if c.Mode == "list" {
		if g.li >= len(g.list) {
			return "", false
		}
		g.li++
		return g.list[g.li-1], true
	}
	L := c.MinLen + rand.IntN(c.MaxLen-c.MinLen+1)
	var s string
	switch c.Mode {
	case "mixed":
		b := []byte(randStr(alnum, L))
		d := rand.IntN(L)
		b[d] = pick(digits)
		if L > 1 {
			l := rand.IntN(L - 1)
			if l >= d {
				l++
			}
			b[l] = pick(letters)
		}
		s = string(b)
	case "letters":
		s = randStr(letters, L)
	case "digits":
		s = randStr(digits, L)
	case "alnum":
		s = randStr(alnum, L)
	case "repeater":
		s = genRep(c, L)
	case "pattern":
		s = genPattern(c.Pattern)
	case "words":
		w := g.pool[rand.IntN(len(g.pool))]
		nd := c.WordDigits
		if nd <= 0 {
			nd = 1 + rand.IntN(3)
		}
		switch c.WordStyle {
		case "digits":
			s = w + randStr(digits, nd)
		case "digitsfront":
			s = randStr(digits, nd) + w
		case "double":
			s = w + g.pool[rand.IntN(len(g.pool))]
		case "doublesep":
			s = w + sepChar(c) + g.pool[rand.IntN(len(g.pool))]
		default:
			s = w
		}
	}
	if c.Sep != "none" && c.Sep != "" && !(c.Mode == "words" && c.WordStyle == "doublesep") {
		pos := c.SepPos
		if pos == "random" {
			pos = []string{"start", "end", "both"}[rand.IntN(3)]
		}
		switch pos {
		case "start":
			s = sepChar(c) + s
		case "both":
			s = sepChar(c) + s + sepChar(c)
		default:
			s = s + sepChar(c)
		}
	}
	return strings.ToLower(c.Prefix + s + c.Suffix), true
}

func valid(s string) bool { return validRe.MatchString(s) && !strings.Contains(s, "..") }

// ---------------- proxies ----------------

type Proxy struct {
	addr   string
	client *http.Client
	fails  int
	direct bool
}

type Pool struct {
	ch    chan *Proxy
	alive atomic.Int64
	mu    sync.Mutex
	seen  map[string]bool
}

func newClient(pu *url.URL, timeout time.Duration) *http.Client {
	tr := &http.Transport{
		DialContext:         (&net.Dialer{Timeout: timeout}).DialContext,
		TLSHandshakeTimeout: timeout,
		MaxIdleConnsPerHost: 4,
		IdleConnTimeout:     60 * time.Second,
		ForceAttemptHTTP2:   pu == nil,
	}
	if pu != nil {
		tr.Proxy = http.ProxyURL(pu)
	}
	return &http.Client{Transport: tr, Timeout: timeout}
}

func parseProxy(line, def string) *url.URL {
	line = strings.TrimSpace(line)
	if line == "" || strings.HasPrefix(line, "#") {
		return nil
	}
	if f := strings.Fields(line); len(f) > 0 {
		line = f[0]
	}
	if !strings.Contains(line, "://") {
		p := strings.Split(line, ":")
		if len(p) == 4 && !strings.Contains(line, "@") {
			line = p[2] + ":" + p[3] + "@" + p[0] + ":" + p[1]
		}
		line = def + "://" + line
	}
	u, err := url.Parse(line)
	if err != nil || u.Host == "" || u.Port() == "" {
		return nil
	}
	if u.Scheme == "https" {
		u.Scheme = "http"
	}
	if u.Scheme != "http" && u.Scheme != "socks5" && u.Scheme != "socks5h" {
		return nil
	}
	return u
}

func (pl *Pool) add(u *url.URL, timeout time.Duration) bool {
	pl.mu.Lock()
	k := u.String()
	if pl.seen[k] {
		pl.mu.Unlock()
		return false
	}
	pl.seen[k] = true
	pl.mu.Unlock()
	p := &Proxy{addr: u.Host, client: newClient(u, timeout)}
	select {
	case pl.ch <- p:
		pl.alive.Add(1)
		return true
	default:
		return false
	}
}

func (pl *Pool) put(p *Proxy, after time.Duration) {
	if after <= 0 {
		pl.ch <- p
		return
	}
	time.AfterFunc(after, func() { pl.ch <- p })
}

var sources = map[string][]string{
	"http": {
		"https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
		"https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
		"https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
		"https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/http.txt",
		"https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/http.txt",
		"https://raw.githubusercontent.com/zloi-user/hideip.me/main/http.txt",
		"https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=ipport&format=text",
		"https://www.proxy-list.download/api/v1/get?type=http",
	},
	"socks5": {
		"https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
		"https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
		"https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt",
		"https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/socks5.txt",
		"https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/socks5.txt",
		"https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=socks5&proxy_format=ipport&format=text",
		"https://www.proxy-list.download/api/v1/get?type=socks5",
	},
}

func (r *Run) scrape() {
	if !r.scraping.CompareAndSwap(false, true) {
		return
	}
	defer r.scraping.Store(false)
	types := []string{"http", "socks5"}
	if r.c.ProxyType == "http" || r.c.ProxyType == "socks5" {
		types = []string{r.c.ProxyType}
	}
	r.log("info", "Scraping free proxies…")
	cl := &http.Client{Timeout: 15 * time.Second}
	var wg sync.WaitGroup
	var added atomic.Int64
	for _, t := range types {
		for _, s := range sources[t] {
			wg.Add(1)
			go func(t, s string) {
				defer wg.Done()
				resp, err := cl.Get(s)
				if err != nil {
					return
				}
				defer resp.Body.Close()
				sc := bufio.NewScanner(io.LimitReader(resp.Body, 20<<20))
				for sc.Scan() {
					if u := parseProxy(sc.Text(), t); u != nil && r.pool.add(u, r.timeout) {
						added.Add(1)
					}
				}
			}(t, s)
		}
	}
	wg.Wait()
	r.log("info", fmt.Sprintf("Scraped %d new proxies (%d alive in pool)", added.Load(), r.pool.alive.Load()))
}

// ---------------- engine ----------------

type LogE struct {
	Seq  int64  `json:"seq"`
	Kind string `json:"kind"`
	Msg  string `json:"msg"`
	T    string `json:"t"`
}

type Run struct {
	c        *Config
	timeout  time.Duration
	stop     chan struct{}
	stopOnce sync.Once
	gen      chan string
	retry    chan string
	genDone  atomic.Bool
	pending  atomic.Int64
	pool     *Pool
	scraping atomic.Bool
	start    time.Time
	end      atomic.Int64
	attempts sync.Map

	checked, avail, taken, rate, errs, invalid, failed, generated atomic.Int64
}

var (
	cur      *Run
	curMu    sync.Mutex
	logMu    sync.Mutex
	logs     []LogE
	logSeq   int64
	availMu  sync.Mutex
	availAll []string
	fileMu   sync.Mutex
	resDir   string
)

func (r *Run) log(kind, msg string) {
	logMu.Lock()
	logSeq++
	logs = append(logs, LogE{logSeq, kind, msg, time.Now().Format("15:04:05")})
	if len(logs) > 3000 {
		logs = logs[len(logs)-2000:]
	}
	logMu.Unlock()
}

func appendFile(name, line string) {
	fileMu.Lock()
	defer fileMu.Unlock()
	f, err := os.OpenFile(filepath.Join(resDir, name), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err == nil {
		f.WriteString(line + "\n")
		f.Close()
	}
}

func (r *Run) stopped() bool {
	select {
	case <-r.stop:
		return true
	default:
		return false
	}
}

func (r *Run) Stop(msg string) {
	r.stopOnce.Do(func() {
		r.end.Store(time.Now().UnixNano())
		close(r.stop)
		r.log("info", msg)
	})
}

func (r *Run) generate(g *Gen, skip map[string]bool) {
	defer func() { r.genDone.Store(true); close(r.gen) }()
	seen := map[string]bool{}
	dup := 0
	for r.c.Count == 0 || int(r.generated.Load()) < r.c.Count {
		n, ok := g.next()
		if !ok {
			return
		}
		if !valid(n) || seen[n] || skip[n] {
			dup++
			if dup > 50000 {
				r.log("warn", "No more unique names possible with these settings")
				return
			}
			continue
		}
		dup = 0
		seen[n] = true
		r.pending.Add(1)
		r.generated.Add(1)
		select {
		case r.gen <- n:
		case <-r.stop:
			return
		}
	}
}

func (r *Run) next() (string, bool) {
	for {
		if r.stopped() {
			return "", false
		}
		select {
		case n := <-r.retry:
			return n, true
		default:
		}
		if r.genDone.Load() {
			if r.pending.Load() <= 0 {
				return "", false
			}
			select {
			case n := <-r.retry:
				return n, true
			case <-r.stop:
				return "", false
			case <-time.After(150 * time.Millisecond):
			}
			continue
		}
		select {
		case n := <-r.retry:
			return n, true
		case n, ok := <-r.gen:
			if ok {
				return n, true
			}
		case <-r.stop:
			return "", false
		}
	}
}

func (r *Run) requeue(n string) {
	v, _ := r.attempts.LoadOrStore(n, new(int32))
	if atomic.AddInt32(v.(*int32), 1) > 60 {
		r.failed.Add(1)
		r.pending.Add(-1)
		r.log("err", n+" — gave up after many retries")
		return
	}
	select {
	case r.retry <- n:
	default:
		go func() { r.retry <- n }()
	}
}

const (
	stAvail = iota
	stTaken
	stRate
	stErr
	stInvalid
)

func check(p *Proxy, name string) (int, float64) {
	req, _ := http.NewRequest("POST", api, strings.NewReader(`{"username":"`+name+`"}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("User-Agent", ua)
	req.Header.Set("Origin", "https://discord.com")
	req.Header.Set("Referer", "https://discord.com/register")
	req.Header.Set("Accept", "*/*")
	req.Header.Set("Accept-Language", "en-US,en;q=0.9")
	resp, err := p.client.Do(req)
	if err != nil {
		return stErr, 0
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	switch resp.StatusCode {
	case 200:
		var x struct {
			Taken *bool `json:"taken"`
		}
		if json.Unmarshal(data, &x) == nil && x.Taken != nil {
			if *x.Taken {
				return stTaken, 0
			}
			return stAvail, 0
		}
	case 429:
		var x struct {
			RetryAfter float64 `json:"retry_after"`
		}
		json.Unmarshal(data, &x)
		if x.RetryAfter == 0 {
			fmt.Sscanf(resp.Header.Get("Retry-After"), "%g", &x.RetryAfter)
		}
		return stRate, x.RetryAfter
	case 400:
		if bytes.Contains(data, []byte("username")) {
			return stInvalid, 0
		}
	}
	return stErr, 0
}

func (r *Run) worker() {
	for {
		name, ok := r.next()
		if !ok {
			return
		}
		var p *Proxy
		select {
		case p = <-r.pool.ch:
		case <-r.stop:
			r.requeue(name)
			return
		}
		st, ra := check(p, name)
		delay := time.Duration(r.c.DelayMs) * time.Millisecond
		switch st {
		case stAvail, stTaken, stInvalid:
			p.fails = 0
			r.pool.put(p, delay)
			r.checked.Add(1)
			r.pending.Add(-1)
			r.attempts.Delete(name)
			switch st {
			case stAvail:
				r.avail.Add(1)
				availMu.Lock()
				availAll = append(availAll, name)
				availMu.Unlock()
				r.log("avail", name)
				appendFile("available.txt", name)
				if r.c.Webhook != "" {
					go postHook(r.c.Webhook, name)
				}
			case stTaken:
				r.taken.Add(1)
				r.log("taken", name)
				if r.c.SaveTaken {
					appendFile("taken.txt", name)
				}
			default:
				r.invalid.Add(1)
				r.log("warn", name+" — invalid for Discord")
			}
			appendFile("checked.txt", name)
		case stRate:
			r.rate.Add(1)
			cd := time.Duration(ra*1000)*time.Millisecond + 200*time.Millisecond
			if cd < time.Second {
				cd = time.Second
			}
			if cd > 10*time.Minute {
				cd = 10 * time.Minute
			}
			if p.direct {
				r.log("rate", fmt.Sprintf("Direct IP rate limited — waiting %.1fs", cd.Seconds()))
			}
			r.pool.put(p, cd)
			r.requeue(name)
		default:
			r.errs.Add(1)
			p.fails++
			if p.direct {
				r.pool.put(p, 2*time.Second)
			} else if p.fails >= r.c.MaxFails {
				r.pool.alive.Add(-1)
			} else {
				r.pool.put(p, time.Second)
			}
			r.requeue(name)
		}
	}
}

func postHook(u, name string) {
	b, _ := json.Marshal(map[string]string{"content": "✅ Available: **" + name + "**"})
	resp, err := http.Post(u, "application/json", bytes.NewReader(b))
	if err == nil {
		resp.Body.Close()
	}
}

func (r *Run) monitor() {
	t := time.NewTicker(time.Second)
	defer t.Stop()
	for {
		select {
		case <-r.stop:
			return
		case <-t.C:
		}
		if r.genDone.Load() && r.pending.Load() <= 0 {
			r.Stop(fmt.Sprintf("Finished — %d available out of %d checked", r.avail.Load(), r.checked.Load()))
			return
		}
		alive := r.pool.alive.Load()
		if r.c.ProxyMode == "auto" && alive < 300 && !r.scraping.Load() {
			go r.scrape()
		}
		if alive <= 0 && r.c.ProxyMode != "auto" && !r.scraping.Load() {
			r.Stop("Stopped — no working proxies left")
			return
		}
	}
}

func startRun(c *Config) (*Run, error) {
	if c.MinLen < 1 {
		c.MinLen = 1
	}
	if c.MaxLen < c.MinLen {
		c.MaxLen = c.MinLen
	}
	if c.MaxLen > 32 {
		c.MaxLen = 32
	}
	if c.Threads < 1 {
		c.Threads = 1
	}
	if c.Threads > 3000 {
		c.Threads = 3000
	}
	if c.Timeout < 2 {
		c.Timeout = 8
	}
	if c.MaxFails < 1 {
		c.MaxFails = 2
	}
	if c.WordMax < c.WordMin {
		c.WordMax = c.WordMin
	}
	c.Prefix, c.Suffix = strings.ToLower(c.Prefix), strings.ToLower(c.Suffix)
	g, err := newGen(c)
	if err != nil {
		return nil, err
	}
	r := &Run{c: c, timeout: time.Duration(c.Timeout) * time.Second, stop: make(chan struct{}),
		gen: make(chan string, 2048), retry: make(chan string, 200000), start: time.Now(),
		pool: &Pool{ch: make(chan *Proxy, 400000), seen: map[string]bool{}}}
	if c.ProxyMode == "none" || c.UseDirect {
		r.pool.ch <- &Proxy{addr: "direct", client: newClient(nil, r.timeout), direct: true}
		r.pool.alive.Add(1)
	}
	if c.ProxyMode == "custom" {
		def := c.ProxyType
		if def != "socks5" {
			def = "http"
		}
		n := 0
		for _, l := range strings.Split(c.Proxies, "\n") {
			if u := parseProxy(l, def); u != nil && r.pool.add(u, r.timeout) {
				n++
			}
		}
		if n == 0 && !c.UseDirect {
			return nil, fmt.Errorf("no valid proxies in the list")
		}
		r.log("info", fmt.Sprintf("Loaded %d proxies", n))
	}
	if c.ProxyMode == "none" && c.Threads > 3 {
		c.Threads = 3
	}
	skip := map[string]bool{}
	if c.SkipChecked {
		if f, err := os.Open(filepath.Join(resDir, "checked.txt")); err == nil {
			sc := bufio.NewScanner(f)
			for sc.Scan() {
				skip[strings.TrimSpace(sc.Text())] = true
			}
			f.Close()
		}
	}
	r.log("info", fmt.Sprintf("Started — mode %s, %d threads", c.Mode, c.Threads))
	if c.ProxyMode == "auto" {
		go r.scrape()
	}
	go r.generate(g, skip)
	for i := 0; i < c.Threads; i++ {
		go r.worker()
	}
	go r.monitor()
	return r, nil
}

// ---------------- http ----------------

func openBrowser(u string) {
	switch runtime.GOOS {
	case "windows":
		exec.Command("rundll32", "url.dll,FileProtocolHandler", u).Start()
	case "darwin":
		exec.Command("open", u).Start()
	default:
		exec.Command("xdg-open", u).Start()
	}
}

func main() {
	enWords = strings.Split(strings.TrimSpace(enRaw), "\n")
	frWords = strings.Split(strings.TrimSpace(frRaw), "\n")
	exe, _ := os.Executable()
	resDir = filepath.Join(filepath.Dir(exe), "results")
	os.MkdirAll(resDir, 0755)

	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Write(indexHTML)
	})
	mux.HandleFunc("/api/info", func(w http.ResponseWriter, _ *http.Request) {
		json.NewEncoder(w).Encode(map[string]any{"en": len(enWords), "fr": len(frWords), "results": resDir})
	})
	mux.HandleFunc("/api/start", func(w http.ResponseWriter, q *http.Request) {
		var c Config
		if err := json.NewDecoder(q.Body).Decode(&c); err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		curMu.Lock()
		defer curMu.Unlock()
		if cur != nil && !cur.stopped() {
			http.Error(w, "already running", 400)
			return
		}
		availMu.Lock()
		availAll = nil
		availMu.Unlock()
		r, err := startRun(&c)
		if err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		cur = r
		w.Write([]byte("ok"))
	})
	mux.HandleFunc("/api/stop", func(w http.ResponseWriter, _ *http.Request) {
		curMu.Lock()
		if cur != nil {
			cur.Stop("Stopped by user")
		}
		curMu.Unlock()
		w.Write([]byte("ok"))
	})
	mux.HandleFunc("/api/preview", func(w http.ResponseWriter, q *http.Request) {
		var c Config
		json.NewDecoder(q.Body).Decode(&c)
		if c.MinLen < 1 {
			c.MinLen = 1
		}
		if c.MaxLen < c.MinLen {
			c.MaxLen = c.MinLen
		}
		g, err := newGen(&c)
		if err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		out := []string{}
		seen := map[string]bool{}
		for i := 0; i < 5000 && len(out) < 40; i++ {
			n, ok := g.next()
			if !ok {
				break
			}
			if valid(n) && !seen[n] {
				seen[n] = true
				out = append(out, n)
			}
		}
		json.NewEncoder(w).Encode(map[string]any{"names": out, "pool": len(g.pool)})
	})
	mux.HandleFunc("/api/open", func(w http.ResponseWriter, _ *http.Request) {
		if runtime.GOOS == "windows" {
			exec.Command("explorer", resDir).Start()
		} else {
			openBrowser(resDir)
		}
	})
	mux.HandleFunc("/api/quit", func(w http.ResponseWriter, _ *http.Request) {
		w.Write([]byte("bye"))
		go func() { time.Sleep(300 * time.Millisecond); os.Exit(0) }()
	})
	mux.HandleFunc("/api/events", func(w http.ResponseWriter, q *http.Request) {
		fl, _ := w.(http.Flusher)
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		var lseq int64
		logMu.Lock()
		if len(logs) > 300 {
			lseq = logs[len(logs)-300].Seq - 1
		}
		logMu.Unlock()
		var lastChecked int64
		lastT := time.Now()
		cps := 0.0
		t := time.NewTicker(400 * time.Millisecond)
		defer t.Stop()
		for {
			logMu.Lock()
			var nl []LogE
			for _, e := range logs {
				if e.Seq > lseq {
					nl = append(nl, e)
				}
			}
			logMu.Unlock()
			if len(nl) > 400 {
				nl = nl[len(nl)-400:]
			}
			if len(nl) > 0 {
				lseq = nl[len(nl)-1].Seq
			}
			st := map[string]any{"logs": nl, "running": false}
			curMu.Lock()
			r := cur
			curMu.Unlock()
			if r != nil {
				ch := r.checked.Load()
				if dt := time.Since(lastT).Seconds(); dt >= 1 {
					cps = cps*0.5 + float64(ch-lastChecked)/dt*0.5
					lastChecked, lastT = ch, time.Now()
				}
				el := time.Since(r.start)
				if e := r.end.Load(); e > 0 {
					el = time.Unix(0, e).Sub(r.start)
					cps = 0
				}
				st["running"] = !r.stopped()
				st["checked"], st["avail"], st["taken"] = ch, r.avail.Load(), r.taken.Load()
				st["rate"], st["errs"], st["invalid"] = r.rate.Load(), r.errs.Load(), r.invalid.Load()
				st["failed"], st["generated"], st["pending"] = r.failed.Load(), r.generated.Load(), r.pending.Load()
				st["alive"], st["scraping"] = r.pool.alive.Load(), r.scraping.Load()
				st["target"], st["cps"], st["elapsed"] = r.c.Count, cps, int(el.Seconds())
			}
			b, _ := json.Marshal(st)
			if _, err := fmt.Fprintf(w, "data: %s\n\n", b); err != nil {
				return
			}
			if fl != nil {
				fl.Flush()
			}
			select {
			case <-q.Context().Done():
				return
			case <-t.C:
			}
		}
	})

	ln, err := net.Listen("tcp", "127.0.0.1:7777")
	if err != nil {
		ln, err = net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			fmt.Println("cannot start:", err)
			time.Sleep(5 * time.Second)
			return
		}
	}
	u := "http://" + ln.Addr().String()
	fmt.Println("==============================================")
	fmt.Println("  NameHunter — Discord username checker")
	fmt.Println("  UI: " + u)
	fmt.Println("  Results folder: " + resDir)
	fmt.Println("  Keep this window open. Close it to exit.")
	fmt.Println("==============================================")
	go openBrowser(u)
	http.Serve(ln, mux)
}
