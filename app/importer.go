package main

import (
	"database/sql"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"path/filepath"
	"sort"
	"strings"

	"github.com/xuri/excelize/v2"
)

// parseFile turns a supported file into (header, rows). Auto-detects format.
func parseFile(path string, raw []byte) (header []string, rows [][]string, err error) {
	ext := strings.ToLower(filepath.Ext(path))
	switch ext {
	case ".csv":
		return parseDelimited(raw, ',')
	case ".tsv", ".tab":
		return parseDelimited(raw, '\t')
	case ".json", ".ndjson":
		return parseJSON(raw)
	case ".xlsx", ".xlsm", ".xls":
		return parseXLSX(path, raw)
	case ".db", ".sqlite", ".sqlite3":
		return parseSQLite(path)
	default:
		// sniff: try json, then comma, then tab
		if h, r, e := parseJSON(raw); e == nil && len(h) > 0 {
			return h, r, nil
		}
		if h, r, e := parseDelimited(raw, ','); e == nil && len(h) > 1 {
			return h, r, nil
		}
		return parseDelimited(raw, '\t')
	}
}

func parseDelimited(raw []byte, sep rune) ([]string, [][]string, error) {
	r := csv.NewReader(strings.NewReader(string(raw)))
	r.Comma = sep
	r.FieldsPerRecord = -1
	r.LazyQuotes = true
	recs, err := r.ReadAll()
	if err != nil && len(recs) == 0 {
		return nil, nil, err
	}
	if len(recs) == 0 {
		return nil, nil, fmt.Errorf("empty file")
	}
	header := dedupeHeader(recs[0])
	return header, recs[1:], nil
}

func parseJSON(raw []byte) ([]string, [][]string, error) {
	var arr []map[string]any
	if err := json.Unmarshal(raw, &arr); err != nil {
		// try ndjson
		var items []map[string]any
		for _, line := range strings.Split(string(raw), "\n") {
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			var m map[string]any
			if json.Unmarshal([]byte(line), &m) == nil {
				items = append(items, m)
			}
		}
		if len(items) == 0 {
			return nil, nil, fmt.Errorf("not json records")
		}
		arr = items
	}
	keySet := map[string]bool{}
	var header []string
	for _, m := range arr {
		for k := range m {
			if !keySet[k] {
				keySet[k] = true
				header = append(header, k)
			}
		}
	}
	sort.Strings(header)
	rows := make([][]string, 0, len(arr))
	for _, m := range arr {
		row := make([]string, len(header))
		for i, h := range header {
			row[i] = toStr(m[h])
		}
		rows = append(rows, row)
	}
	return header, rows, nil
}

func parseXLSX(path string, raw []byte) ([]string, [][]string, error) {
	f, err := excelize.OpenReader(strings.NewReader(string(raw)))
	if err != nil {
		return nil, nil, err
	}
	defer f.Close()
	sheets := f.GetSheetList()
	if len(sheets) == 0 {
		return nil, nil, fmt.Errorf("no sheets")
	}
	recs, err := f.GetRows(sheets[0])
	if err != nil || len(recs) == 0 {
		return nil, nil, fmt.Errorf("empty sheet")
	}
	return dedupeHeader(recs[0]), recs[1:], nil
}

func parseSQLite(path string) ([]string, [][]string, error) {
	db, err := sql.Open("sqlite", path+"?mode=ro")
	if err != nil {
		return nil, nil, err
	}
	defer db.Close()
	var table string
	// pick the largest user table
	trows, err := db.Query(`SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'`)
	if err != nil {
		return nil, nil, err
	}
	best := -1
	for trows.Next() {
		var n string
		trows.Scan(&n)
		var c int
		db.QueryRow(`SELECT COUNT(*) FROM "` + n + `"`).Scan(&c)
		if c > best {
			best = c
			table = n
		}
	}
	trows.Close()
	if table == "" {
		return nil, nil, fmt.Errorf("no tables found")
	}
	rows, err := db.Query(`SELECT * FROM "` + table + `"`)
	if err != nil {
		return nil, nil, err
	}
	defer rows.Close()
	cols, _ := rows.Columns()
	var out [][]string
	for rows.Next() {
		vals := make([]any, len(cols))
		ptrs := make([]any, len(cols))
		for i := range vals {
			ptrs[i] = &vals[i]
		}
		rows.Scan(ptrs...)
		row := make([]string, len(cols))
		for i, v := range vals {
			row[i] = toStr(v)
		}
		out = append(out, row)
	}
	return cols, out, nil
}

func dedupeHeader(h []string) []string {
	seen := map[string]int{}
	out := make([]string, len(h))
	for i, c := range h {
		c = strings.TrimSpace(c)
		if c == "" {
			c = fmt.Sprintf("col%d", i+1)
		}
		if seen[c] > 0 {
			out[i] = fmt.Sprintf("%s_%d", c, seen[c])
		} else {
			out[i] = c
		}
		seen[c]++
	}
	return out
}

func toStr(v any) string {
	if v == nil {
		return ""
	}
	switch x := v.(type) {
	case string:
		return x
	case []byte:
		return string(x)
	case float64:
		if x == float64(int64(x)) {
			return fmt.Sprintf("%d", int64(x))
		}
		return fmt.Sprintf("%v", x)
	case bool:
		if x {
			return "true"
		}
		return "false"
	default:
		return fmt.Sprintf("%v", v)
	}
}
