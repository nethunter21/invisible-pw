package main

import (
	"encoding/json"
	"sort"
)

// Connector / entity resolution over YOUR OWN datasets.
// Given a record, it finds every other record (in any dataset) that shares a
// normalized identity key — email, phone, username, account id, etc. This is
// how a client is linked to their own data across your separate tables.

type LinkNode struct {
	RecordID  int64             `json:"recordId"`
	DatasetID int64             `json:"datasetId"`
	Dataset   string            `json:"dataset"`
	Data      map[string]string `json:"data"`
	Via       []string          `json:"via"` // which keys connected it
}

type LinkEdge struct {
	Kind string `json:"kind"`
	Norm string `json:"norm"`
	From int64  `json:"from"`
	To   int64  `json:"to"`
}

type EntityGraph struct {
	Root  int64               `json:"root"`
	Nodes []LinkNode          `json:"nodes"`
	Edges []LinkEdge          `json:"edges"`
	Keys  map[string][]string `json:"keys"` // kind -> normalized values that tie the entity together
}

// resolveEntity builds a linked graph starting from one record, expanding up to
// `depth` hops through shared identity keys.
func (s *Store) resolveEntity(recordID int64, depth int) (EntityGraph, error) {
	if depth <= 0 || depth > 4 {
		depth = 2
	}
	g := EntityGraph{Root: recordID, Keys: map[string][]string{}}
	visited := map[int64]bool{}
	via := map[int64]map[string]bool{}
	edgeSet := map[string]bool{}
	keySet := map[string]map[string]bool{}

	frontier := []int64{recordID}
	visited[recordID] = true

	for hop := 0; hop < depth && len(frontier) > 0; hop++ {
		var next []int64
		for _, rid := range frontier {
			// keys on this record
			krows, err := s.db.Query(`SELECT kind,norm FROM idkeys WHERE record_id=?`, rid)
			if err != nil {
				continue
			}
			type kv struct{ kind, norm string }
			var keys []kv
			for krows.Next() {
				var k, n string
				krows.Scan(&k, &n)
				keys = append(keys, kv{k, n})
				if keySet[k] == nil {
					keySet[k] = map[string]bool{}
				}
				keySet[k][n] = true
			}
			krows.Close()

			for _, k := range keys {
				mrows, err := s.db.Query(`SELECT record_id FROM idkeys WHERE norm=? AND kind=?`, k.norm, k.kind)
				if err != nil {
					continue
				}
				var matches []int64
				for mrows.Next() {
					var m int64
					mrows.Scan(&m)
					matches = append(matches, m)
				}
				mrows.Close()
				for _, m := range matches {
					if m == rid {
						continue
					}
					ek := edgeKey(rid, m, k.kind, k.norm)
					if !edgeSet[ek] {
						edgeSet[ek] = true
						g.Edges = append(g.Edges, LinkEdge{Kind: k.kind, Norm: k.norm, From: rid, To: m})
					}
					if via[m] == nil {
						via[m] = map[string]bool{}
					}
					via[m][k.kind] = true
					if !visited[m] {
						visited[m] = true
						next = append(next, m)
					}
				}
			}
		}
		frontier = next
	}

	for rid := range visited {
		rec, err := s.getRecord(rid)
		if err != nil {
			continue
		}
		node := LinkNode{
			RecordID:  rec.ID,
			DatasetID: rec.DatasetID,
			Dataset:   rec.Dataset,
			Data:      rec.Data,
		}
		for k := range via[rid] {
			node.Via = append(node.Via, k)
		}
		sort.Strings(node.Via)
		g.Nodes = append(g.Nodes, node)
	}
	sort.Slice(g.Nodes, func(i, j int) bool {
		if g.Nodes[i].RecordID == recordID {
			return true
		}
		if g.Nodes[j].RecordID == recordID {
			return false
		}
		return g.Nodes[i].DatasetID < g.Nodes[j].DatasetID
	})
	for k, set := range keySet {
		for n := range set {
			g.Keys[k] = append(g.Keys[k], n)
		}
		sort.Strings(g.Keys[k])
	}
	return g, nil
}

// duplicatesReport scans for identity keys shared by records that the connector
// considers the same client — useful for de-duplication / legitimacy checks.
type DupCluster struct {
	Kind    string   `json:"kind"`
	Norm    string   `json:"norm"`
	Count   int      `json:"count"`
	Records []int64  `json:"records"`
	Where   []string `json:"where"`
}

func (s *Store) duplicates(limit int) ([]DupCluster, error) {
	if limit <= 0 {
		limit = 50
	}
	rows, err := s.db.Query(`
      SELECT kind, norm, COUNT(DISTINCT record_id) c
      FROM idkeys GROUP BY kind, norm HAVING c > 1
      ORDER BY c DESC LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []DupCluster
	for rows.Next() {
		var d DupCluster
		rows.Scan(&d.Kind, &d.Norm, &d.Count)
		rr, _ := s.db.Query(`SELECT DISTINCT record_id, dataset_id FROM idkeys WHERE kind=? AND norm=?`, d.Kind, d.Norm)
		seenDS := map[int64]bool{}
		for rr.Next() {
			var rid, dsid int64
			rr.Scan(&rid, &dsid)
			d.Records = append(d.Records, rid)
			if !seenDS[dsid] {
				seenDS[dsid] = true
				d.Where = append(d.Where, s.datasetName(dsid))
			}
		}
		rr.Close()
		out = append(out, d)
	}
	return out, nil
}

func edgeKey(a, b int64, kind, norm string) string {
	if a > b {
		a, b = b, a
	}
	j, _ := json.Marshal([]any{a, b, kind, norm})
	return string(j)
}
