package main

import (
	"encoding/base64"
	"net"
	"path/filepath"
	"strings"
)

func mustListen() net.Listener {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		panic(err)
	}
	return ln
}

func decodeB64(s string) ([]byte, error) {
	if i := strings.Index(s, ","); i >= 0 && strings.Contains(s[:i], "base64") {
		s = s[i+1:]
	}
	return base64.StdEncoding.DecodeString(s)
}

func baseName(p string) string {
	return filepath.Base(p)
}

func cleanName(n string) string {
	n = baseName(n)
	ext := filepath.Ext(n)
	n = strings.TrimSuffix(n, ext)
	n = strings.NewReplacer("_", " ", "-", " ", ".", " ").Replace(n)
	n = strings.TrimSpace(n)
	if n == "" {
		n = "dataset"
	}
	return strings.ToUpper(n[:1]) + n[1:]
}
