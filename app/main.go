package main

import (
	"embed"
	"encoding/json"
	"fmt"
	"io/fs"
	"net/http"
	"os"

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
			Title:  "VAULTSEARCH // CLIENT INTELLIGENCE CONSOLE",
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

	bind(w)
	w.Navigate(url)
	w.Run()
}

func bind(w webview2.WebView) {
	// Open native file picker, read files, import each. Returns imported datasets.
	w.Bind("goPickAndImport", func() string {
		paths, err := pickFiles()
		if err != nil {
			return jerr(err)
		}
		var results []ImportResult
		for _, p := range paths {
			results = append(results, importPath(p, ""))
		}
		return jok(results)
	})

	// Import a file whose bytes come from the browser (drag & drop), base64.
	w.Bind("goImportBytes", func(name string, b64 string) string {
		raw, err := decodeB64(b64)
		if err != nil {
			return jerr(err)
		}
		return jok(importBytes(name, raw, name))
	})

	w.Bind("goListDatasets", func() string {
		ds, err := store.listDatasets()
		if err != nil {
			return jerr(err)
		}
		if ds == nil {
			ds = []Dataset{}
		}
		return jok(ds)
	})

	w.Bind("goRename", func(id float64, name string) string {
		if err := store.renameDataset(int64(id), name); err != nil {
			return jerr(err)
		}
		return jok(map[string]bool{"ok": true})
	})

	w.Bind("goDelete", func(id float64) string {
		if err := store.deleteDataset(int64(id)); err != nil {
			return jerr(err)
		}
		return jok(map[string]bool{"ok": true})
	})

	w.Bind("goSearch", func(q string, dsID float64, limit float64, offset float64) string {
		res, err := store.search(q, int64(dsID), int(limit), int(offset))
		if err != nil {
			return jerr(err)
		}
		return jok(res)
	})

	w.Bind("goResolve", func(recID float64, depth float64) string {
		g, err := store.resolveEntity(int64(recID), int(depth))
		if err != nil {
			return jerr(err)
		}
		return jok(g)
	})

	w.Bind("goDuplicates", func(limit float64) string {
		d, err := store.duplicates(int(limit))
		if err != nil {
			return jerr(err)
		}
		if d == nil {
			d = []DupCluster{}
		}
		return jok(d)
	})

	w.Bind("goStats", func() string {
		return jok(store.stats())
	})

	w.Bind("goGetRecord", func(id float64) string {
		r, err := store.getRecord(int64(id))
		if err != nil {
			return jerr(err)
		}
		return jok(r)
	})
}

func importPath(path, name string) ImportResult {
	raw, err := os.ReadFile(path)
	if err != nil {
		return ImportResult{Error: err.Error()}
	}
	if name == "" {
		name = baseName(path)
	}
	return importBytes(path, raw, name)
}

func importBytes(path string, raw []byte, name string) ImportResult {
	header, rows, err := parseFile(path, raw)
	if err != nil {
		return ImportResult{Error: err.Error()}
	}
	sampleN := 200
	if len(rows) < sampleN {
		sampleN = len(rows)
	}
	cols := detectColumns(header, rows[:sampleN])
	ds, err := store.saveDataset(cleanName(name), baseName(path), cols, rows, header)
	if err != nil {
		return ImportResult{Error: err.Error()}
	}
	return ImportResult{Dataset: ds}
}
