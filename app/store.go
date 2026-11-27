package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	_ "modernc.org/sqlite"
)

// Store is the local, file-backed database. Everything lives in one SQLite file
// next to the executable. No network, no server.
type Store struct {
	db   *sql.DB
	path string
}

type Dataset struct {
	ID        int64             `json:"id"`
	Name      string            `json:"name"`
	Source    string            `json:"source"`
	Rows      int               `json:"rows"`
	Cols      int               `json:"cols"`
	Created   string            `json:"created"`
	Columns   []ColumnMeta      `json:"columns"`
	TypeCount map[string]int    `json:"typeCount"`
	Tags      map[string]string `json:"tags"`
}

type ColumnMeta struct {
	Name     string `json:"name"`
	Kind     string `json:"kind"`     // detected semantic kind (email, phone, name...)
	Role     string `json:"role"`     // identity | attribute (used by the connector)
	Filled   int    `json:"filled"`   // non-empty values
	Distinct int    `json:"distinct"` // distinct values (indexing stat)
	Sample   string `json:"sample"`
}

func openStore() (*Store, error) {
	dir, err := os.Executable()
	if err == nil {
		dir = filepath.Dir(dir)
	} else {
		dir, _ = os.Getwd()
	}
	path := filepath.Join(dir, "vaultsearch.db")
	db, err := sql.Open("sqlite", path+"?_pragma=journal_mode(WAL)&_pragma=busy_timeout(5000)")
	if err != nil {
		return nil, err
	}
	s := &Store{db: db, path: path}
	return s, s.init()
}

func (s *Store) init() error {
	schema := `
CREATE TABLE IF NOT EXISTS datasets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  source TEXT,
  rows INTEGER DEFAULT 0,
  cols INTEGER DEFAULT 0,
  created TEXT,
  columns TEXT,
  typecount TEXT,
  tags TEXT
);
CREATE TABLE IF NOT EXISTS records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dataset_id INTEGER NOT NULL,
  data TEXT NOT NULL,
  blob TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_ds ON records(dataset_id);
CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(blob, content='records', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS records_ai AFTER INSERT ON records BEGIN
  INSERT INTO records_fts(rowid, blob) VALUES (new.id, new.blob);
END;
CREATE TRIGGER IF NOT EXISTS records_ad AFTER DELETE ON records BEGIN
  INSERT INTO records_fts(records_fts, rowid, blob) VALUES('delete', old.id, old.blob);
END;
-- normalized identity keys for the connector (entity resolution within your own data)
CREATE TABLE IF NOT EXISTS idkeys (
  record_id INTEGER NOT NULL,
  dataset_id INTEGER NOT NULL,
  kind TEXT NOT NULL,
  norm TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_idkeys_norm ON idkeys(norm);
CREATE INDEX IF NOT EXISTS idx_idkeys_rec ON idkeys(record_id);
`
	_, err := s.db.Exec(schema)
	return err
}

// ImportResult is returned to the UI after a dataset is ingested.
type ImportResult struct {
	Dataset Dataset `json:"dataset"`
	Error   string  `json:"error,omitempty"`
}

func (s *Store) saveDataset(name, source string, cols []ColumnMeta, records [][]string, header []string) (Dataset, error) {
	tc := map[string]int{}
	for _, c := range cols {
		tc[c.Kind]++
	}
	colJSON, _ := json.Marshal(cols)
	tcJSON, _ := json.Marshal(tc)
	now := time.Now().Format("2006-01-02 15:04")

	tx, err := s.db.Begin()
	if err != nil {
		return Dataset{}, err
	}
	res, err := tx.Exec(`INSERT INTO datasets(name,source,rows,cols,created,columns,typecount,tags) VALUES(?,?,?,?,?,?,?,?)`,
		name, source, len(records), len(header), now, string(colJSON), string(tcJSON), "{}")
	if err != nil {
		tx.Rollback()
		return Dataset{}, err
	}
	dsID, _ := res.LastInsertId()

	recStmt, _ := tx.Prepare(`INSERT INTO records(dataset_id,data,blob) VALUES(?,?,?)`)
	keyStmt, _ := tx.Prepare(`INSERT INTO idkeys(record_id,dataset_id,kind,norm) VALUES(?,?,?,?)`)
	defer recStmt.Close()
	defer keyStmt.Close()

	for _, row := range records {
		obj := map[string]string{}
		var blob strings.Builder
		for i, h := range header {
			v := ""
			if i < len(row) {
				v = strings.TrimSpace(row[i])
			}
			obj[h] = v
			if v != "" {
				blob.WriteString(v)
				blob.WriteByte(' ')
			}
		}
		dataJSON, _ := json.Marshal(obj)
		r, err := recStmt.Exec(dsID, string(dataJSON), blob.String())
		if err != nil {
			tx.Rollback()
			return Dataset{}, err
		}
		rid, _ := r.LastInsertId()
		// index identity keys for cross-dataset linking
		for i, c := range cols {
			if c.Role != "identity" {
				continue
			}
			var v string
			if i < len(row) {
				v = row[i]
			}
			n := normalizeKey(c.Kind, v)
			if n != "" {
				keyStmt.Exec(rid, dsID, c.Kind, n)
			}
		}
	}
	if err := tx.Commit(); err != nil {
		return Dataset{}, err
	}
	return s.getDataset(dsID)
}

func (s *Store) getDataset(id int64) (Dataset, error) {
	var d Dataset
	var colJSON, tcJSON, tagsJSON string
	err := s.db.QueryRow(`SELECT id,name,source,rows,cols,created,columns,typecount,COALESCE(tags,'{}') FROM datasets WHERE id=?`, id).
		Scan(&d.ID, &d.Name, &d.Source, &d.Rows, &d.Cols, &d.Created, &colJSON, &tcJSON, &tagsJSON)
	if err != nil {
		return d, err
	}
	json.Unmarshal([]byte(colJSON), &d.Columns)
	json.Unmarshal([]byte(tcJSON), &d.TypeCount)
	json.Unmarshal([]byte(tagsJSON), &d.Tags)
	// refresh distinct counts lazily (indexing stats)
	return d, nil
}

func (s *Store) listDatasets() ([]Dataset, error) {
	rows, err := s.db.Query(`SELECT id FROM datasets ORDER BY id DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Dataset
	for rows.Next() {
		var id int64
		rows.Scan(&id)
		d, err := s.getDataset(id)
		if err == nil {
			out = append(out, d)
		}
	}
	return out, nil
}

func (s *Store) renameDataset(id int64, name string) error {
	_, err := s.db.Exec(`UPDATE datasets SET name=? WHERE id=?`, name, id)
	return err
}

func (s *Store) deleteDataset(id int64) error {
	tx, _ := s.db.Begin()
	tx.Exec(`DELETE FROM records WHERE dataset_id=?`, id)
	tx.Exec(`DELETE FROM idkeys WHERE dataset_id=?`, id)
	tx.Exec(`DELETE FROM datasets WHERE id=?`, id)
	return tx.Commit()
}

type Record struct {
	ID        int64             `json:"id"`
	DatasetID int64             `json:"datasetId"`
	Dataset   string            `json:"dataset"`
	Data      map[string]string `json:"data"`
}

type SearchResult struct {
	Total   int      `json:"total"`
	Records []Record `json:"records"`
}

func (s *Store) datasetName(id int64) string {
	var n string
	s.db.QueryRow(`SELECT name FROM datasets WHERE id=?`, id).Scan(&n)
	return n
}

// search runs full-text search across all data or one dataset.
func (s *Store) search(query string, datasetID int64, limit, offset int) (SearchResult, error) {
	if limit <= 0 || limit > 500 {
		limit = 100
	}
	q := strings.TrimSpace(query)
	var rows *sql.Rows
	var err error
	out := SearchResult{Records: []Record{}}

	names := map[int64]string{}
	drows, _ := s.db.Query(`SELECT id,name FROM datasets`)
	for drows.Next() {
		var id int64
		var n string
		drows.Scan(&id, &n)
		names[id] = n
	}
	drows.Close()

	if q == "" {
		// browse mode
		if datasetID > 0 {
			s.db.QueryRow(`SELECT COUNT(*) FROM records WHERE dataset_id=?`, datasetID).Scan(&out.Total)
			rows, err = s.db.Query(`SELECT id,dataset_id,data FROM records WHERE dataset_id=? ORDER BY id LIMIT ? OFFSET ?`, datasetID, limit, offset)
		} else {
			s.db.QueryRow(`SELECT COUNT(*) FROM records`).Scan(&out.Total)
			rows, err = s.db.Query(`SELECT id,dataset_id,data FROM records ORDER BY id LIMIT ? OFFSET ?`, limit, offset)
		}
	} else {
		match := ftsQuery(q)
		if datasetID > 0 {
			s.db.QueryRow(`SELECT COUNT(*) FROM records_fts f JOIN records r ON r.id=f.rowid WHERE records_fts MATCH ? AND r.dataset_id=?`, match, datasetID).Scan(&out.Total)
			rows, err = s.db.Query(`SELECT r.id,r.dataset_id,r.data FROM records_fts f JOIN records r ON r.id=f.rowid WHERE records_fts MATCH ? AND r.dataset_id=? LIMIT ? OFFSET ?`, match, datasetID, limit, offset)
		} else {
			s.db.QueryRow(`SELECT COUNT(*) FROM records_fts WHERE records_fts MATCH ?`, match).Scan(&out.Total)
			rows, err = s.db.Query(`SELECT r.id,r.dataset_id,r.data FROM records_fts f JOIN records r ON r.id=f.rowid WHERE records_fts MATCH ? LIMIT ? OFFSET ?`, match, limit, offset)
		}
	}
	if err != nil {
		return out, err
	}
	defer rows.Close()
	for rows.Next() {
		var rec Record
		var dataJSON string
		rows.Scan(&rec.ID, &rec.DatasetID, &dataJSON)
		json.Unmarshal([]byte(dataJSON), &rec.Data)
		rec.Dataset = names[rec.DatasetID]
		out.Records = append(out.Records, rec)
	}
	return out, nil
}

func ftsQuery(q string) string {
	parts := strings.Fields(q)
	for i, p := range parts {
		p = strings.ReplaceAll(p, `"`, "")
		parts[i] = `"` + p + `"*`
	}
	return strings.Join(parts, " ")
}

func (s *Store) getRecord(id int64) (Record, error) {
	var rec Record
	var dataJSON string
	err := s.db.QueryRow(`SELECT id,dataset_id,data FROM records WHERE id=?`, id).Scan(&rec.ID, &rec.DatasetID, &dataJSON)
	if err != nil {
		return rec, err
	}
	json.Unmarshal([]byte(dataJSON), &rec.Data)
	rec.Dataset = s.datasetName(rec.DatasetID)
	return rec, nil
}

func (s *Store) stats() map[string]int {
	m := map[string]int{}
	var ds, rec, keys int
	s.db.QueryRow(`SELECT COUNT(*) FROM datasets`).Scan(&ds)
	s.db.QueryRow(`SELECT COUNT(*) FROM records`).Scan(&rec)
	s.db.QueryRow(`SELECT COUNT(*) FROM idkeys`).Scan(&keys)
	m["datasets"] = ds
	m["records"] = rec
	m["indexed"] = keys
	return m
}

func must(_ sql.Result, err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
	}
}
