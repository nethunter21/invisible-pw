package main

import (
	"bytes"
	"embed"
	"encoding/json"
	"fmt"
	"io/fs"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/jchv/go-webview2"
)

//go:embed web/*
var webFS embed.FS

var store *Store

func jerr(err error) string {
	b, _ := json.Marshal(map[string]string{"error": err.Error()})
	return string(b)
}
func jok(v any) string {
	b, _ := json.Marshal(v)
	return string(b)
}

// safe wraps every synchronous bind handler so a panic anywhere in the import/
// search/parse pipeline turns into a JSON error instead of taking the whole
// process down — the app must keep running no matter how malformed a file is.
func safe(f func() string) (out string) {
	defer func() {
		if r := recover(); r != nil {
			out = jerr(fmt.Errorf("internal error: %v", r))
		}
	}()
	return f()
}

func main() {
	var err error
	store, err = openStore()
	if err != nil {
		fmt.Fprintln(os.Stderr, "store:", err)
		os.Exit(1)
	}

	// serve the embedded UI over a local loopback origin
	sub, _ := fs.Sub(webFS, "web")
	mux := http.NewServeMux()
	mux.Handle("/", http.FileServer(http.FS(sub)))
	ln := mustListen()
	go http.Serve(ln, mux)
	url := "http://" + ln.Addr().String() + "/"

	w := webview2.NewWithOptions(webview2.WebViewOptions{
		Debug: false,
		WindowOptions: webview2.WindowOptions{
			Title:  "QUIET SEARCH — DATABASES CONNECTOR SEARCHER",
			Width:  1340,
			Height: 860,
			IconId: 0,
			Center: true,
		},
	})
	if w == nil {
		fmt.Fprintln(os.Stderr, "failed to create webview (WebView2 runtime required)")
		os.Exit(1)
	}
	defer w.Destroy()

	setDarkTitlebar(uintptr(w.Window()))

	bind(w)
	w.Navigate(url)
	w.Run()
}

// emit pushes an event into the page's window.__vsEvent(payload) callback.
// Used by background import/delete jobs to report progress without ever
// blocking the UI thread.
func emit(w webview2.WebView, payload map[string]any) {
	b, err := json.Marshal(payload)
	if err != nil {
		return
	}
	s := string(b)
	// guard against raw U+2028/2029, which are valid JSON but historically
	// broke bare JS expressions in some engines.
	s = strings.ReplaceAll(s, " ", "\\u2028")
	s = strings.ReplaceAll(s, " ", "\\u2029")
	w.Dispatch(func() {
		defer func() { recover() }()
		w.Eval("window.__vsEvent && window.__vsEvent(" + s + ")")
	})
}

// ---- chunked upload buffer (for drag & drop of large files) ----
var (
	chunkMu   sync.Mutex
	chunkBufs = map[string]*bytes.Buffer{}
	chunkSeq  int64
)

func newToken() string {
	chunkMu.Lock()
	chunkSeq++
	n := chunkSeq
	chunkMu.Unlock()
	return fmt.Sprintf("u%d_%d", time.Now().UnixNano(), n)
}

func bind(w webview2.WebView) {
	// Native multi-select file picker. Returns paths only — fast, synchronous,
	// the heavy work happens later via goImportPaths so the picker's own modal
	// blocking (expected OS behavior) is never confused with a frozen app.
	w.Bind("goPickFiles", func() string {
		return safe(func() string {
			paths, err := pickFiles()
			if err != nil {
				return jerr(err)
			}
			return jok(map[string]any{"paths": paths})
		})
	})

	// Kick off background import of one or more files already on disk
	// (bulk-safe: processed sequentially in a goroutine, never on the UI thread).
	w.Bind("goImportPaths", func(pathsJSON string) string {
		return safe(func() string {
			var paths []string
			if err := json.Unmarshal([]byte(pathsJSON), &paths); err != nil {
				return jerr(err)
			}
			srcs := make([]importSource, 0, len(paths))
			for _, p := range paths {
				srcs = append(srcs, importSource{path: p})
			}
			go runImportJob(w, srcs)
			return jok(map[string]any{"started": true, "count": len(srcs)})
		})
	})

	// Chunked drag & drop upload: the browser slices a dropped file into small
	// base64 pieces so no single bridge call ever carries a huge string
	// (which is what froze/crashed the app on one large drop before).
	w.Bind("goChunkStart", func() string {
		return safe(func() string {
			tok := newToken()
			chunkMu.Lock()
			chunkBufs[tok] = &bytes.Buffer{}
			chunkMu.Unlock()
			return jok(map[string]string{"token": tok})
		})
	})

	w.Bind("goChunkAppend", func(token string, b64 string) string {
		return safe(func() string {
			raw, err := decodeB64(b64)
			if err != nil {
				return jerr(err)
			}
			chunkMu.Lock()
			buf := chunkBufs[token]
			chunkMu.Unlock()
			if buf == nil {
				return jerr(fmt.Errorf("unknown upload token"))
			}
			buf.Write(raw)
			return jok(map[string]bool{"ok": true})
		})
	})

	w.Bind("goChunkAbort", func(token string) string {
		return safe(func() string {
			chunkMu.Lock()
			delete(chunkBufs, token)
			chunkMu.Unlock()
			return jok(map[string]bool{"ok": true})
		})
	})

	w.Bind("goChunkFinish", func(token string, name string) string {
		return safe(func() string {
			chunkMu.Lock()
			buf := chunkBufs[token]
			delete(chunkBufs, token)
			chunkMu.Unlock()
			if buf == nil {
				return jerr(fmt.Errorf("unknown upload token"))
			}
			data := buf.Bytes()
			go runImportJob(w, []importSource{{name: name, data: data}})
			return jok(map[string]bool{"started": true})
		})
	})

	w.Bind("goListDatasets", func() string {
		return safe(func() string {
			ds, err := store.listDatasets()
			if err != nil {
				return jerr(err)
			}
			if ds == nil {
				ds = []Dataset{}
			}
			return jok(ds)
		})
	})

	w.Bind("goRename", func(id float64, name string) string {
		return safe(func() string {
			if err := store.renameDataset(int64(id), name); err != nil {
				return jerr(err)
			}
			return jok(map[string]bool{"ok": true})
		})
	})

	// Deletion of a large dataset (hundreds of thousands of rows, with FTS
	// index cleanup) runs in the background too, so it can never freeze the
	// window; the UI is told when it's actually done via an event.
	w.Bind("goDelete", func(id float64) string {
		return safe(func() string {
			did := int64(id)
			go func() {
				defer func() { recover() }()
				err := store.deleteDataset(did)
				if err != nil {
					emit(w, map[string]any{"type": "dataset_delete_error", "id": did, "error": err.Error()})
					return
				}
				emit(w, map[string]any{"type": "dataset_deleted", "id": did})
			}()
			return jok(map[string]bool{"started": true})
		})
	})

	w.Bind("goSearch", func(q string, dsID float64, limit float64, offset float64) string {
		return safe(func() string {
			res, err := store.search(q, int64(dsID), int(limit), int(offset))
			if err != nil {
				return jerr(err)
			}
			return jok(res)
		})
	})

	w.Bind("goResolve", func(recID float64, depth float64) string {
		return safe(func() string {
			g, err := store.resolveEntity(int64(recID), int(depth))
			if err != nil {
				return jerr(err)
			}
			return jok(g)
		})
	})

	w.Bind("goDuplicates", func(limit float64) string {
		return safe(func() string {
			d, err := store.duplicates(int(limit))
			if err != nil {
				return jerr(err)
			}
			if d == nil {
				d = []DupCluster{}
			}
			return jok(d)
		})
	})

	w.Bind("goStats", func() string {
		return safe(func() string { return jok(store.stats()) })
	})

	w.Bind("goGetRecord", func(id float64) string {
		return safe(func() string {
			r, err := store.getRecord(int64(id))
			if err != nil {
				return jerr(err)
			}
			return jok(r)
		})
	})
}

// importSource is either a path to read from disk, or already-buffered bytes
// (from a chunked drag & drop upload).
type importSource struct {
	path string
	name string
	data []byte
}

// runImportJob processes sources one at a time in the background. Sequential
// (not parallel) on purpose: it bounds memory and avoids hammering the single
// sqlite writer with concurrent transactions, while still never touching the
// UI thread directly — every status update goes through emit().
func runImportJob(w webview2.WebView, sources []importSource) {
	total := len(sources)
	for i, src := range sources {
		label := src.name
		if label == "" {
			label = baseName(src.path)
		}
		emit(w, map[string]any{"type": "file_start", "index": i, "total": total, "name": label})
		res := processImportSource(w, src, i, total, label)
		payload := map[string]any{"type": "file_done", "index": i, "total": total, "name": label}
		if res.Error != "" {
			payload["error"] = res.Error
		} else {
			payload["dataset"] = res.Dataset
		}
		emit(w, payload)
	}
	emit(w, map[string]any{"type": "job_done", "total": total})
}

// processImportSource never panics out of the goroutine: any failure in
// parsing or detection (malformed file, unexpected encoding, corrupt sheet,
// etc.) is caught and reported as a normal per-file error.
func processImportSource(w webview2.WebView, src importSource, idx, fileTotal int, label string) (result ImportResult) {
	defer func() {
		if r := recover(); r != nil {
			result = ImportResult{Error: fmt.Sprintf("failed to import %s: %v", label, r)}
		}
	}()

	var raw []byte
	var err error
	namePathHint := src.path
	if src.path != "" {
		raw, err = os.ReadFile(src.path)
		if err != nil {
			return ImportResult{Error: err.Error()}
		}
	} else {
		raw = src.data
		namePathHint = src.name
	}

	header, rows, err := parseFile(namePathHint, raw)
	if err != nil {
		return ImportResult{Error: err.Error()}
	}
	sampleN := 200
	if len(rows) < sampleN {
		sampleN = len(rows)
	}
	cols := detectColumns(header, rows[:sampleN])

	name := label
	if name == "" {
		name = baseName(namePathHint)
	}
	lastEmit := time.Now()
	ds, err := store.saveDataset(cleanName(name), baseName(namePathHint), cols, rows, header, func(done, rowsTotal int) {
		// throttle progress events so a 1M-row file doesn't flood the bridge
		if time.Since(lastEmit) < 150*time.Millisecond && done < rowsTotal {
			return
		}
		lastEmit = time.Now()
		emit(w, map[string]any{
			"type": "row_progress", "index": idx, "fileTotal": fileTotal,
			"done": done, "rows": rowsTotal, "name": name,
		})
	})
	if err != nil {
		return ImportResult{Error: err.Error()}
	}
	return ImportResult{Dataset: ds}
}
