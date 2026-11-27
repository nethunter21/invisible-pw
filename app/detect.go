package main

import (
	"regexp"
	"strings"
)

var (
	reEmail = regexp.MustCompile(`^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$`)
	rePhone = regexp.MustCompile(`^[\+]?[\d][\d\s().\-]{6,}$`)
	reIP    = regexp.MustCompile(`^(\d{1,3}\.){3}\d{1,3}$`)
	reURL   = regexp.MustCompile(`^(https?://|www\.)`)
	reDate  = regexp.MustCompile(`^\d{4}[-/]\d{1,2}[-/]\d{1,2}|^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}`)
	reNum   = regexp.MustCompile(`^-?\d+(\.\d+)?$`)
	reZip   = regexp.MustCompile(`^\d{4,6}(-\d{4})?$`)
	reUUID  = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)
	reHex   = regexp.MustCompile(`^[0-9a-fA-F]{16,}$`)
)

// kinds that identify a client — used by the connector to link records.
var identityKinds = map[string]bool{
	"email": true, "phone": true, "username": true, "uuid": true,
	"national_id": true, "account_id": true, "ip": true,
}

// detectColumns inspects sampled values + the header name to label each column
// with a semantic kind and whether it is an identity field.
func detectColumns(header []string, rows [][]string) []ColumnMeta {
	cols := make([]ColumnMeta, len(header))
	for i, h := range header {
		seen := map[string]bool{}
		filled := 0
		sample := ""
		votes := map[string]int{}
		for _, r := range rows {
			if i >= len(r) {
				continue
			}
			v := strings.TrimSpace(r[i])
			if v == "" {
				continue
			}
			filled++
			if sample == "" {
				sample = v
			}
			seen[strings.ToLower(v)] = true
			votes[classifyValue(v)]++
		}
		kind := byHeaderName(h)
		if kind == "" {
			kind = topVote(votes)
		}
		// header hints can override a weak value guess for known identity labels
		if hk := byHeaderName(h); hk != "" {
			kind = hk
		}
		role := "attribute"
		if identityKinds[kind] {
			role = "identity"
		}
		cols[i] = ColumnMeta{
			Name:     h,
			Kind:     kind,
			Role:     role,
			Filled:   filled,
			Distinct: len(seen),
			Sample:   trim(sample, 40),
		}
	}
	return cols
}

func classifyValue(v string) string {
	switch {
	case reEmail.MatchString(v):
		return "email"
	case reUUID.MatchString(v):
		return "uuid"
	case reIP.MatchString(v):
		return "ip"
	case reURL.MatchString(v):
		return "url"
	case reHex.MatchString(v):
		return "hash"
	case reDate.MatchString(v):
		return "date"
	case rePhone.MatchString(v) && countDigits(v) >= 7:
		return "phone"
	case reZip.MatchString(v):
		return "number"
	case reNum.MatchString(v):
		return "number"
	default:
		if len(strings.Fields(v)) >= 2 && isWordy(v) {
			return "name"
		}
		return "text"
	}
}

func byHeaderName(h string) string {
	l := strings.ToLower(strings.TrimSpace(h))
	l = strings.NewReplacer("_", "", " ", "", "-", "").Replace(l)
	switch {
	case contains(l, "email", "mail", "eaddr"):
		return "email"
	case contains(l, "phone", "mobile", "cell", "tel", "msisdn"):
		return "phone"
	case contains(l, "username", "login", "handle", "user"):
		return "username"
	case contains(l, "firstname", "lastname", "fullname", "name", "contact"):
		return "name"
	case contains(l, "password", "passwd", "pwd", "secret"):
		return "password"
	case contains(l, "hash", "md5", "sha", "bcrypt"):
		return "hash"
	case contains(l, "uuid", "guid"):
		return "uuid"
	case contains(l, "accountid", "acctid", "customerid", "clientid", "memberid"):
		return "account_id"
	case contains(l, "nationalid", "ssn", "passport", "taxid", "nino"):
		return "national_id"
	case contains(l, "ipaddr", "ipaddress", "ip"):
		return "ip"
	case contains(l, "address", "street", "city", "state", "country", "zip", "postal"):
		return "address"
	case contains(l, "company", "org", "organization", "employer"):
		return "company"
	case contains(l, "dob", "birth", "date", "created", "updated", "timestamp"):
		return "date"
	case contains(l, "status", "active", "verified", "legit", "valid"):
		return "status"
	case contains(l, "amount", "balance", "price", "total", "qty", "count"):
		return "number"
	}
	return ""
}

func topVote(v map[string]int) string {
	best, n := "text", -1
	for k, c := range v {
		if c > n {
			best, n = k, c
		}
	}
	return best
}

// normalizeKey canonicalizes an identity value so the same client matches
// across datasets regardless of formatting.
func normalizeKey(kind, v string) string {
	v = strings.TrimSpace(strings.ToLower(v))
	if v == "" {
		return ""
	}
	switch kind {
	case "email", "username", "uuid", "account_id", "national_id":
		return v
	case "phone":
		var b strings.Builder
		for _, c := range v {
			if c >= '0' && c <= '9' {
				b.WriteRune(c)
			}
		}
		d := b.String()
		if len(d) > 10 {
			d = d[len(d)-10:] // last 10 digits = local number, ignores country prefix noise
		}
		if len(d) < 7 {
			return ""
		}
		return d
	case "ip":
		return v
	}
	return v
}

func contains(s string, subs ...string) bool {
	for _, sub := range subs {
		if strings.Contains(s, sub) {
			return true
		}
	}
	return false
}
func countDigits(s string) int {
	n := 0
	for _, c := range s {
		if c >= '0' && c <= '9' {
			n++
		}
	}
	return n
}
func isWordy(s string) bool {
	letters := 0
	for _, c := range s {
		if (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') {
			letters++
		}
	}
	return letters > len(s)/2
}
func trim(s string, n int) string {
	if len(s) > n {
		return s[:n] + "…"
	}
	return s
}
