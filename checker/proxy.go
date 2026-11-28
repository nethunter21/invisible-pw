package main

import (
	"bufio"
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

type Proxy struct {
	addr   string
	client *http.Client
	fails  int
	direct bool
}

type Pool struct {
	ch                       chan *Proxy
	raw, prio                chan *url.URL
	alive                    atomic.Int64
	scraped, tested, working atomic.Int64
	mu                       sync.Mutex
	seen                     map[string]bool
}

func newPool() *Pool {
	return &Pool{ch: make(chan *Proxy, 600000), raw: make(chan *url.URL, 900000),
		prio: make(chan *url.URL, 100000), seen: map[string]bool{}}
}

// ---- SOCKS4 dialer (Go has no built-in socks4) ----
var dnsCache sync.Map

func resolve4(ctx context.Context, host string) (net.IP, error) {
	if ip := net.ParseIP(host); ip != nil && ip.To4() != nil {
		return ip.To4(), nil
	}
	if v, ok := dnsCache.Load(host); ok {
		return v.(net.IP), nil
	}
	ips, err := net.DefaultResolver.LookupIP(ctx, "ip4", host)
	if err != nil || len(ips) == 0 {
		return nil, errors.New("dns fail")
	}
	dnsCache.Store(host, ips[0].To4())
	return ips[0].To4(), nil
}

func socks4Dial(proxyAddr string, timeout time.Duration) func(ctx context.Context, network, addr string) (net.Conn, error) {
	return func(ctx context.Context, network, addr string) (net.Conn, error) {
		host, ps, err := net.SplitHostPort(addr)
		if err != nil {
			return nil, err
		}
		port, _ := strconv.Atoi(ps)
		ip, err := resolve4(ctx, host)
		if err != nil {
			return nil, err
		}
		c, err := (&net.Dialer{Timeout: timeout}).DialContext(ctx, "tcp", proxyAddr)
		if err != nil {
			return nil, err
		}
		c.SetDeadline(time.Now().Add(timeout))
		req := []byte{4, 1, 0, 0}
		binary.BigEndian.PutUint16(req[2:], uint16(port))
		req = append(append(req, ip...), 0)
		if _, err = c.Write(req); err == nil {
			resp := make([]byte, 8)
			if _, err = io.ReadFull(c, resp); err == nil && resp[1] != 0x5a {
				err = errors.New("socks4 rejected")
			}
		}
		if err != nil {
			c.Close()
			return nil, err
		}
		c.SetDeadline(time.Time{})
		return c, nil
	}
}

func newClient(pu *url.URL, timeout time.Duration) *http.Client {
	tr := &http.Transport{
		DialContext:         (&net.Dialer{Timeout: timeout}).DialContext,
		TLSHandshakeTimeout: timeout,
		MaxIdleConnsPerHost: 2,
		IdleConnTimeout:     90 * time.Second,
		ForceAttemptHTTP2:   pu == nil,
	}
	if pu != nil {
		if pu.Scheme == "socks4" {
			tr.DialContext = socks4Dial(pu.Host, timeout)
		} else {
			tr.Proxy = http.ProxyURL(pu)
		}
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
	switch u.Scheme {
	case "https":
		u.Scheme = "http"
	case "socks4a":
		u.Scheme = "socks4"
	case "http", "socks5", "socks5h", "socks4":
	default:
		return nil
	}
	return u
}

// queue for testing (deduped)
func (pl *Pool) queue(u *url.URL, prio bool) bool {
	k := u.Scheme + "://" + u.Host
	pl.mu.Lock()
	if pl.seen[k] {
		pl.mu.Unlock()
		return false
	}
	pl.seen[k] = true
	pl.mu.Unlock()
	q := pl.raw
	if prio {
		q = pl.prio
	}
	select {
	case q <- u:
		pl.scraped.Add(1)
		return true
	default:
		return false
	}
}

// addDirect puts a proxy straight into the checking pool without testing
func (pl *Pool) addDirect(u *url.URL, timeout time.Duration) {
	pl.ch <- &Proxy{addr: u.Host, client: newClient(u, timeout)}
	pl.alive.Add(1)
	pl.working.Add(1)
}

func (pl *Pool) put(p *Proxy, after time.Duration) {
	if after <= 0 {
		pl.ch <- p
		return
	}
	time.AfterFunc(after, func() { pl.ch <- p })
}

const testURL = "https://discord.com/api/v9/experiments"

func testProxy(u *url.URL, timeout time.Duration) *Proxy {
	cl := newClient(u, timeout)
	req, _ := http.NewRequest("GET", testURL, nil)
	req.Header.Set("User-Agent", ua)
	resp, err := cl.Do(req)
	if err != nil {
		cl.CloseIdleConnections()
		return nil
	}
	b, _ := io.ReadAll(io.LimitReader(resp.Body, 32<<10))
	resp.Body.Close()
	if resp.StatusCode != 200 || !strings.Contains(string(b), "fingerprint") {
		cl.CloseIdleConnections()
		return nil
	}
	return &Proxy{addr: u.Host, client: cl}
}

func (r *Run) validator() {
	for {
		var u *url.URL
		select {
		case <-r.stop:
			return
		case u = <-r.pool.prio:
		default:
			select {
			case <-r.stop:
				return
			case u = <-r.pool.prio:
			case u = <-r.pool.raw:
			}
		}
		// don't over-fill: if many proxies already idle in the pool, slow down testing
		for len(r.pool.ch) > 4*r.c.Threads+2000 {
			select {
			case <-r.stop:
				return
			case <-time.After(time.Second):
			}
		}
		p := testProxy(u, r.valTimeout)
		r.pool.tested.Add(1)
		if p == nil {
			continue
		}
		r.pool.working.Add(1)
		r.pool.alive.Add(1)
		r.pool.ch <- p
		r.saveGood(u.String())
	}
}

var goodMu sync.Mutex
var goodSeen = map[string]bool{}

func (r *Run) saveGood(s string) {
	goodMu.Lock()
	defer goodMu.Unlock()
	if goodSeen[s] {
		return
	}
	goodSeen[s] = true
	appendFile("good_proxies.txt", s)
}

func loadGood(r *Run) int {
	f, err := os.Open(filepath.Join(resDir, "good_proxies.txt"))
	if err != nil {
		return 0
	}
	defer f.Close()
	var lines []string
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		lines = append(lines, sc.Text())
	}
	if len(lines) > 20000 { // keep newest
		lines = lines[len(lines)-20000:]
	}
	n := 0
	for i := len(lines) - 1; i >= 0; i-- {
		if u := parseProxy(lines[i], "http"); u != nil && r.pool.queue(u, true) {
			n++
		}
	}
	return n
}

// ---- scraping ----

const gh = "https://raw.githubusercontent.com/"

var sources = map[string][]string{
	"http": {
		gh + "TheSpeedX/PROXY-List/master/http.txt",
		gh + "monosans/proxy-list/main/proxies/http.txt",
		gh + "monosans/proxy-list/main/proxies_anonymous/http.txt",
		gh + "proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
		gh + "ErcinDedeoglu/proxies/main/proxies/http.txt",
		gh + "ErcinDedeoglu/proxies/main/proxies/https.txt",
		gh + "vakhov/fresh-proxy-list/master/http.txt",
		gh + "vakhov/fresh-proxy-list/master/https.txt",
		gh + "zloi-user/hideip.me/main/http.txt",
		gh + "zloi-user/hideip.me/main/https.txt",
		gh + "roosterkid/openproxylist/main/HTTPS_RAW.txt",
		gh + "MuRongPIG/Proxy-Master/main/http.txt",
		gh + "MuRongPIG/Proxy-Master/main/http_checked.txt",
		gh + "officialputuid/KangProxy/KangProxy/http/http.txt",
		gh + "officialputuid/KangProxy/KangProxy/https/https.txt",
		gh + "sunny9577/proxy-scraper/master/generated/http_proxies.txt",
		gh + "sunny9577/proxy-scraper/master/proxies.txt",
		gh + "Zaeem20/FREE_PROXIES_LIST/master/http.txt",
		gh + "Zaeem20/FREE_PROXIES_LIST/master/https.txt",
		gh + "prxchk/proxy-list/main/http.txt",
		gh + "ALIILAPRO/Proxy/main/http.txt",
		gh + "mmpx12/proxy-list/master/http.txt",
		gh + "mmpx12/proxy-list/master/https.txt",
		gh + "Anonym0usWork1221/Free-Proxies/main/proxy_files/http_proxies.txt",
		gh + "Anonym0usWork1221/Free-Proxies/main/proxy_files/https_proxies.txt",
		gh + "rdavydov/proxy-list/main/proxies/http.txt",
		gh + "rdavydov/proxy-list/main/proxies_anonymous/http.txt",
		gh + "ShiftyTR/Proxy-List/master/http.txt",
		gh + "ShiftyTR/Proxy-List/master/https.txt",
		gh + "jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt",
		gh + "jetkai/proxy-list/main/online-proxies/txt/proxies-https.txt",
		gh + "clarketm/proxy-list/master/proxy-list-raw.txt",
		gh + "opsxcq/proxy-list/master/list.txt",
		gh + "yemixzy/proxy-list/main/proxies/http.txt",
		gh + "B4RC0DE-TM/proxy-list/main/HTTP.txt",
		gh + "saisuiu/Lionkings-Http-Proxys-Proxies/main/free.txt",
		gh + "elliottophellia/proxylist/master/results/http/global/http_checked.txt",
		gh + "Vann-Dev/proxy-list/main/proxies/http.txt",
		gh + "dpangestuw/Free-Proxy/main/http_proxies.txt",
		gh + "r00tee/Proxy-List/main/Https.txt",
		gh + "hendrikbgr/Free-Proxy-Repo/master/proxy_list.txt",
		gh + "almroot/proxylist/master/list.txt",
		gh + "aslisk/proxyhttps/main/https.txt",
		gh + "proxy4parsing/proxy-list/main/http.txt",
		gh + "Tsprnay/Proxy-lists/master/proxies/http.txt",
		gh + "fahimscirex/proxybd/master/proxylist/http.txt",
		gh + "mertguvencli/http-proxy-list/main/proxy-list/data.txt",
		gh + "UptimerBot/proxy-list/main/proxies/http.txt",
		gh + "casals-ar/proxy-list/main/http",
		gh + "Firmfox/Proxify/main/proxies/http.txt",
		gh + "gitrecon1455/fresh-proxy-list/main/proxylist.txt",
		gh + "BreakingTechFr/Proxy_Free/main/proxies/http.txt",
		gh + "SevenworksDev/proxy-list/main/proxies/http.txt",
		gh + "iplocate/free-proxy-list/main/protocols/http.txt",
		gh + "databay-labs/free-proxy-list/master/http.txt",
		"https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=ipport&format=text",
		"https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all",
		"https://www.proxy-list.download/api/v1/get?type=http",
		"https://www.proxy-list.download/api/v1/get?type=https",
		"https://api.openproxylist.xyz/http.txt",
		"https://openproxylist.xyz/http.txt",
		"https://spys.me/proxy.txt",
		"https://proxyspace.pro/http.txt",
		"https://proxyspace.pro/https.txt",
		"https://www.proxyscan.io/download?type=http",
		"https://www.proxyscan.io/download?type=https",
		"https://rootjazz.com/proxies/proxies.txt",
		"https://multiproxy.org/txt_all/proxy.txt",
		"https://proxy-spider.com/api/proxies.example.txt",
		"https://www.sslproxies.org/",
		"https://free-proxy-list.net/",
		"https://www.us-proxy.org/",
		"https://free-proxy-list.net/uk-proxy.html",
		"https://free-proxy-list.net/anonymous-proxy.html",
	},
	"socks4": {
		gh + "TheSpeedX/PROXY-List/master/socks4.txt",
		gh + "monosans/proxy-list/main/proxies/socks4.txt",
		gh + "proxifly/free-proxy-list/main/proxies/protocols/socks4/data.txt",
		gh + "ErcinDedeoglu/proxies/main/proxies/socks4.txt",
		gh + "vakhov/fresh-proxy-list/master/socks4.txt",
		gh + "roosterkid/openproxylist/main/SOCKS4_RAW.txt",
		gh + "MuRongPIG/Proxy-Master/main/socks4.txt",
		gh + "officialputuid/KangProxy/KangProxy/socks4/socks4.txt",
		gh + "sunny9577/proxy-scraper/master/generated/socks4_proxies.txt",
		gh + "Zaeem20/FREE_PROXIES_LIST/master/socks4.txt",
		gh + "prxchk/proxy-list/main/socks4.txt",
		gh + "mmpx12/proxy-list/master/socks4.txt",
		gh + "Anonym0usWork1221/Free-Proxies/main/proxy_files/socks4_proxies.txt",
		gh + "rdavydov/proxy-list/main/proxies/socks4.txt",
		gh + "ShiftyTR/Proxy-List/master/socks4.txt",
		gh + "jetkai/proxy-list/main/online-proxies/txt/proxies-socks4.txt",
		gh + "B4RC0DE-TM/proxy-list/main/SOCKS4.txt",
		gh + "zloi-user/hideip.me/main/socks4.txt",
		gh + "elliottophellia/proxylist/master/results/socks4/global/socks4_checked.txt",
		gh + "dpangestuw/Free-Proxy/main/socks4_proxies.txt",
		gh + "iplocate/free-proxy-list/main/protocols/socks4.txt",
		gh + "databay-labs/free-proxy-list/master/socks4.txt",
		gh + "SevenworksDev/proxy-list/main/proxies/socks4.txt",
		"https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=socks4&proxy_format=ipport&format=text",
		"https://www.proxy-list.download/api/v1/get?type=socks4",
		"https://api.openproxylist.xyz/socks4.txt",
		"https://proxyspace.pro/socks4.txt",
		"https://www.proxyscan.io/download?type=socks4",
		"https://www.socks-proxy.net/",
	},
	"socks5": {
		gh + "TheSpeedX/PROXY-List/master/socks5.txt",
		gh + "monosans/proxy-list/main/proxies/socks5.txt",
		gh + "proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt",
		gh + "ErcinDedeoglu/proxies/main/proxies/socks5.txt",
		gh + "vakhov/fresh-proxy-list/master/socks5.txt",
		gh + "roosterkid/openproxylist/main/SOCKS5_RAW.txt",
		gh + "MuRongPIG/Proxy-Master/main/socks5.txt",
		gh + "officialputuid/KangProxy/KangProxy/socks5/socks5.txt",
		gh + "sunny9577/proxy-scraper/master/generated/socks5_proxies.txt",
		gh + "Zaeem20/FREE_PROXIES_LIST/master/socks5.txt",
		gh + "prxchk/proxy-list/main/socks5.txt",
		gh + "mmpx12/proxy-list/master/socks5.txt",
		gh + "Anonym0usWork1221/Free-Proxies/main/proxy_files/socks5_proxies.txt",
		gh + "rdavydov/proxy-list/main/proxies/socks5.txt",
		gh + "ShiftyTR/Proxy-List/master/socks5.txt",
		gh + "jetkai/proxy-list/main/online-proxies/txt/proxies-socks5.txt",
		gh + "B4RC0DE-TM/proxy-list/main/SOCKS5.txt",
		gh + "hookzof/socks5_list/master/proxy.txt",
		gh + "zloi-user/hideip.me/main/socks5.txt",
		gh + "elliottophellia/proxylist/master/results/socks5/global/socks5_checked.txt",
		gh + "dpangestuw/Free-Proxy/main/socks5_proxies.txt",
		gh + "iplocate/free-proxy-list/main/protocols/socks5.txt",
		gh + "databay-labs/free-proxy-list/master/socks5.txt",
		gh + "SevenworksDev/proxy-list/main/proxies/socks5.txt",
		gh + "manuGMG/proxy-365/main/SOCKS5.txt",
		"https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=socks5&proxy_format=ipport&format=text",
		"https://www.proxy-list.download/api/v1/get?type=socks5",
		"https://api.openproxylist.xyz/socks5.txt",
		"https://proxyspace.pro/socks5.txt",
		"https://www.proxyscan.io/download?type=socks5",
	},
}

var (
	ipPortRe  = regexp.MustCompile(`(?:(https?|socks4a?|socks5h?)://)?(\d{1,3}(?:\.\d{1,3}){3})(?::|</td>\s*<td>)(\d{2,5})\b`)
	geonodeRe = regexp.MustCompile(`"ip":"([\d.]+)","[^{}]*?"port":"?(\d+)"?[^{}]*?"protocols":\["(\w+)"`)
)

func init() {
	for _, p := range []string{"http", "socks4", "socks5"} {
		for pg := 1; pg <= 8; pg++ {
			sources[p] = append(sources[p], fmt.Sprintf("https://proxylist.geonode.com/api/proxy-list?limit=500&page=%d&sort_by=lastChecked&sort_type=desc&protocols=%s", pg, p))
		}
	}
}

func (r *Run) scrape() {
	if !r.scraping.CompareAndSwap(false, true) {
		return
	}
	defer r.scraping.Store(false)
	r.lastScrape.Store(time.Now().Unix())
	types := []string{"http", "socks4", "socks5"}
	switch r.c.ProxyType {
	case "http", "socks4", "socks5":
		types = []string{r.c.ProxyType}
	}
	r.log("info", "Scraping free proxies from all sources…")
	cl := &http.Client{Timeout: 20 * time.Second}
	var wg sync.WaitGroup
	var added, okSrc, total atomic.Int64
	sem := make(chan struct{}, 40)
	for _, t := range types {
		for _, s := range sources[t] {
			wg.Add(1)
			total.Add(1)
			go func(t, s string) {
				defer wg.Done()
				sem <- struct{}{}
				defer func() { <-sem }()
				req, _ := http.NewRequest("GET", s, nil)
				req.Header.Set("User-Agent", ua)
				resp, err := cl.Do(req)
				if err != nil {
					return
				}
				defer resp.Body.Close()
				if resp.StatusCode != 200 {
					return
				}
				body, _ := io.ReadAll(io.LimitReader(resp.Body, 30<<20))
				n := 0
				for _, m := range geonodeRe.FindAllStringSubmatch(string(body), -1) {
					if u := parseProxy(m[1]+":"+m[2], m[3]); u != nil && r.pool.queue(u, false) {
						n++
					}
				}
				for _, m := range ipPortRe.FindAllStringSubmatch(string(body), -1) {
					sch := t
					if m[1] != "" {
						sch = m[1]
						if (sch == "socks4" || sch == "socks4a") && t != "socks4" && len(types) == 1 {
							continue
						}
					}
					if u := parseProxy(m[2]+":"+m[3], sch); u != nil && r.pool.queue(u, false) {
						n++
					}
				}
				if n > 0 || len(body) > 50 {
					okSrc.Add(1)
				}
				added.Add(int64(n))
			}(t, s)
		}
	}
	wg.Wait()
	r.log("info", fmt.Sprintf("Scraped %d new proxies from %d/%d sources — testing them now (%d total scraped)", added.Load(), okSrc.Load(), total.Load(), r.pool.scraped.Load()))
}
