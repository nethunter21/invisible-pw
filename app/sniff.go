package main

import (
	"regexp"
	"strings"
)

// URL matcher used to shield scheme://host:port/path from delimiter detection.
// RE2-safe (no lookahead): host stops at first ':', then an optional :port,
// then an optional /path that also stops at ':'. So the colons that belong to a
// URL are never counted or split, but the colon that separates the NEXT field is.
var urlMask = regexp.MustCompile(`(?i)[a-z][a-z0-9+.\-]*://[^\s:]+(?::[0-9]+)?(?:/[^\s:]*)?`)

const sentinelOpen = "\x01U"
const sentinelClose = "\x02"

// maskURLs replaces every URL in a line with a delimiter-free sentinel and
// returns the masked line plus the originals (indexed).
func maskURLs(line string) (string, []string) {
	if !strings.Contains(line, "://") {
		return line, nil
	}
	var urls []string
	masked := urlMask.ReplaceAllStringFunc(line, func(m string) string {
		urls = append(urls, m)
		return sentinelOpen + itoa(len(urls)-1) + sentinelClose
	})
	return masked, urls
}

func unmask(cell string, urls []string) string {
	if len(urls) == 0 || !strings.Contains(cell, sentinelOpen) {
		return cell
	}
	for i, u := range urls {
		cell = strings.ReplaceAll(cell, sentinelOpen+itoa(i)+sentinelClose, u)
	}
	return cell
}

var candidates = []rune{',', '\t', ';', '|', ':'}

type delimScore struct {
	delim   rune
	fields  int
	score   float64
	present float64
}

// sniffDelimited auto-detects the delimiter and splits the file. It is used for
// every text/tabular file (csv, tsv, txt, log, combo lists, …).
func sniffDelimited(raw []byte) ([]string, [][]string, error) {
	lines := splitLines(raw)
	if len(lines) == 0 {
		return nil, nil, errEmpty
	}
	// sample up to 500 non-empty lines for detection
	sample := lines
	if len(sample) > 500 {
		sample = sample[:500]
	}
	masked := make([]string, len(sample))
	for i, l := range sample {
		masked[i], _ = maskURLs(l)
	}

	best := delimScore{delim: 0, fields: 1, score: -1}
	for _, d := range candidates {
		s := scoreDelim(masked, d)
		if s.score > best.score {
			best = s
		}
	}

	// No delimiter convincingly splits the data → single column.
	if best.delim == 0 || best.fields < 2 || best.score < 0 {
		return singleColumn(lines), rowsToCells(lines, 0, nil), nil
	}

	// Split every line on the detected delimiter, URL-safe. SplitN is capped at
	// the modal field count: a stray outlier line with extra delimiter
	// characters (e.g. a note or description containing a colon) folds its
	// overflow back into the final column instead of inflating every other
	// row with blank padding columns.
	maxCols := best.fields
	var rows [][]string
	for _, l := range lines {
		m, urls := maskURLs(l)
		parts := strings.SplitN(m, string(best.delim), maxCols)
		cells := make([]string, len(parts))
		for i, p := range parts {
			cells[i] = strings.TrimSpace(unmask(unquote(p), urls))
		}
		rows = append(rows, cells)
	}
	// pad only the rare short row (e.g. a truncated final line) up to maxCols
	for i := range rows {
		for len(rows[i]) < maxCols {
			rows[i] = append(rows[i], "")
		}
	}

	header, body := resolveHeader(rows, maxCols)
	return header, body, nil
}

// scoreDelim rates how well a delimiter partitions the sample lines.
func scoreDelim(lines []string, d rune) delimScore {
	freq := map[int]int{}
	withDelim := 0
	total := 0
	for _, l := range lines {
		if l == "" {
			continue
		}
		total++
		c := strings.Count(l, string(d))
		if c > 0 {
			withDelim++
			freq[c]++
		}
	}
	if total == 0 || withDelim == 0 {
		return delimScore{delim: 0, score: -1}
	}
	// modal field count
	modeCount, modeFreq := 0, 0
	for c, f := range freq {
		if f > modeFreq || (f == modeFreq && c < modeCount) {
			modeCount, modeFreq = c, f
		}
	}
	present := float64(withDelim) / float64(total)
	consistency := float64(modeFreq) / float64(withDelim)
	fields := modeCount + 1
	// require the delimiter to appear on most lines and be consistent
	if present < 0.6 || consistency < 0.5 || fields < 2 {
		return delimScore{delim: 0, score: -1}
	}
	// favor consistency, then more fields; mild penalty on ':' so a stray
	// timestamp colon never beats a real comma/tab layout.
	score := consistency*100 + float64(min(fields, 12))
	if d == ':' {
		score -= 1.5
	}
	return delimScore{delim: d, fields: fields, score: score, present: present}
}

// resolveHeader decides whether row 0 is a header or data, and builds column
// names (synthesizing them from detected kinds when there is no header).
func resolveHeader(rows [][]string, cols int) ([]string, [][]string) {
	if len(rows) == 0 {
		return nil, nil
	}
	if looksLikeHeader(rows[0], rows[1:]) {
		return dedupeHeader(rows[0]), rows[1:]
	}
	// headerless: name columns by detected kind
	sampleN := min(200, len(rows))
	cm := detectColumns(genericNames(cols), rows[:sampleN])
	names := make([]string, cols)
	used := map[string]int{}
	for i := 0; i < cols; i++ {
		base := "field_" + itoa(i+1)
		if i < len(cm) {
			if n := nameForKind(cm[i].Kind, i); n != "" {
				base = n
			}
		}
		if used[base] > 0 {
			names[i] = base + "_" + itoa(used[base]+1)
		} else {
			names[i] = base
		}
		used[base]++
	}
	return names, rows
}

func looksLikeHeader(first []string, rest [][]string) bool {
	if len(first) == 0 {
		return false
	}
	// strong signal it's DATA (not a header): a cell carries a data pattern
	for _, c := range first {
		c = strings.TrimSpace(c)
		if c == "" {
			return false // headers are fully populated
		}
		if reEmail.MatchString(c) || reURL.MatchString(c) || reIP.MatchString(c) ||
			reUUID.MatchString(c) || (reNum.MatchString(c) && len(c) > 4) || strings.Contains(c, "://") {
			return false
		}
	}
	// header cells should be short, label-like (mostly letters, no spaces-heavy)
	labelish := 0
	for _, c := range first {
		c = strings.TrimSpace(c)
		if len(c) <= 40 && isLabel(c) {
			labelish++
		}
	}
	if labelish < len(first) {
		return false
	}
	// if the next row's cells have a clearly different shape, first is a header
	if len(rest) > 0 {
		dataHasPattern := false
		for _, c := range rest[0] {
			c = strings.TrimSpace(c)
			if reEmail.MatchString(c) || reNum.MatchString(c) || strings.Contains(c, "://") {
				dataHasPattern = true
				break
			}
		}
		return dataHasPattern || true
	}
	return true
}

func nameForKind(kind string, i int) string {
	switch kind {
	case "email", "phone", "ip", "url", "hash", "uuid", "date", "username", "account_id", "national_id":
		return kind
	case "name":
		return "name"
	case "number":
		return "number_" + itoa(i+1)
	}
	return ""
}

func singleColumn(lines []string) []string {
	// name the single column by what the data looks like
	sampleN := min(200, len(lines))
	rows := make([][]string, sampleN)
	for i := 0; i < sampleN; i++ {
		rows[i] = []string{lines[i]}
	}
	cm := detectColumns([]string{"value"}, rows)
	name := "value"
	if len(cm) > 0 {
		if n := nameForKind(cm[0].Kind, 0); n != "" {
			name = n
		}
	}
	return []string{name}
}

func rowsToCells(lines []string, _ int, _ []string) [][]string {
	out := make([][]string, 0, len(lines))
	for _, l := range lines {
		out = append(out, []string{strings.TrimSpace(l)})
	}
	return out
}

func genericNames(n int) []string {
	out := make([]string, n)
	for i := range out {
		out[i] = "field_" + itoa(i+1)
	}
	return out
}

func splitLines(raw []byte) []string {
	// strip a UTF-8 byte-order mark if present
	if len(raw) >= 3 && raw[0] == 0xEF && raw[1] == 0xBB && raw[2] == 0xBF {
		raw = raw[3:]
	}
	s := string(raw)
	s = strings.ReplaceAll(s, "\r\n", "\n")
	s = strings.ReplaceAll(s, "\r", "\n")
	raw0 := strings.Split(s, "\n")
	out := make([]string, 0, len(raw0))
	for _, l := range raw0 {
		if strings.TrimSpace(l) == "" {
			continue
		}
		out = append(out, l)
	}
	return out
}

func unquote(s string) string {
	s = strings.TrimSpace(s)
	if len(s) >= 2 && (s[0] == '"' && s[len(s)-1] == '"' || s[0] == '\'' && s[len(s)-1] == '\'') {
		return s[1 : len(s)-1]
	}
	return s
}

func isLabel(s string) bool {
	if s == "" {
		return false
	}
	letters, spaces := 0, 0
	for _, c := range s {
		if (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_' || c == '-' || c == ' ' {
			letters++
		}
		if c == ' ' {
			spaces++
		}
	}
	return letters == len(s) && spaces <= 2
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var b [20]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		b[i] = '-'
	}
	return string(b[i:])
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
