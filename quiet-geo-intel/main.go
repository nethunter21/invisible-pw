// Quiet Geo Intel — local geopolitical + weather trading intelligence terminal.
// Single binary: embedded web UI + caching data aggregation layer for free, keyless public feeds.
package main

import (
	"embed"
	"flag"
	"fmt"
	"io/fs"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sync/atomic"
	"time"
)

//go:embed web
var webFS embed.FS

var lastBeat atomic.Int64

func main() {
	port := flag.Int("port", 8787, "local port")
	noOpen := flag.Bool("noopen", false, "do not open a browser window")
	flag.Parse()

	addr := fmt.Sprintf("127.0.0.1:%d", *port)
	url := "http://" + addr + "/"

	// Single instance: if already running, just open the UI.
	if c, err := net.DialTimeout("tcp", addr, 400*time.Millisecond); err == nil {
		c.Close()
		if resp, err := http.Get(url + "api/ping"); err == nil && resp.StatusCode == 200 {
			resp.Body.Close()
			openUI(url)
			return
		}
	}

	ln, err := net.Listen("tcp", addr)
	if err != nil {
		ln, err = net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			log.Fatal(err)
		}
		url = "http://" + ln.Addr().String() + "/"
	}

	sub, _ := fs.Sub(webFS, "web")
	mux := http.NewServeMux()
	registerAPI(mux)
	mux.Handle("/", http.FileServer(http.FS(sub)))

	go warmup()
	lastBeat.Store(time.Now().Unix())

	if !*noOpen {
		go func() {
			time.Sleep(300 * time.Millisecond)
			openUI(url)
		}()
		// Auto-exit once the UI has been closed for a while (no heartbeat).
		go func() {
			for range time.Tick(30 * time.Second) {
				if time.Now().Unix()-lastBeat.Load() > 360 {
					os.Exit(0)
				}
			}
		}()
	}
	log.Printf("Quiet Geo Intel running at %s", url)
	log.Fatal(http.Serve(ln, logMW(mux)))
}

func logMW(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		h.ServeHTTP(w, r)
	})
}

func openUI(url string) {
	switch runtime.GOOS {
	case "windows":
		// Prefer a chromeless app window (Edge / Chrome), fall back to default browser.
		cands := []string{
			filepath.Join(os.Getenv("ProgramFiles(x86)"), `Microsoft\Edge\Application\msedge.exe`),
			filepath.Join(os.Getenv("ProgramFiles"), `Microsoft\Edge\Application\msedge.exe`),
			filepath.Join(os.Getenv("ProgramFiles"), `Google\Chrome\Application\chrome.exe`),
			filepath.Join(os.Getenv("ProgramFiles(x86)"), `Google\Chrome\Application\chrome.exe`),
			filepath.Join(os.Getenv("LocalAppData"), `Google\Chrome\Application\chrome.exe`),
		}
		for _, c := range cands {
			if _, err := os.Stat(c); err == nil {
				if exec.Command(c, "--app="+url, "--window-size=1600,950").Start() == nil {
					return
				}
			}
		}
		exec.Command("rundll32", "url.dll,FileProtocolHandler", url).Start()
	case "darwin":
		exec.Command("open", url).Start()
	default:
		exec.Command("xdg-open", url).Start()
	}
}
