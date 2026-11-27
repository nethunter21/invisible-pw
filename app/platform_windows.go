//go:build windows

package main

import (
	"strings"
	"syscall"
	"unsafe"
)

var (
	comdlg32         = syscall.NewLazyDLL("comdlg32.dll")
	procGetOpenFileW = comdlg32.NewProc("GetOpenFileNameW")
)

type openfilename struct {
	lStructSize       uint32
	hwndOwner         uintptr
	hInstance         uintptr
	lpstrFilter       *uint16
	lpstrCustomFilter *uint16
	nMaxCustFilter    uint32
	nFilterIndex      uint32
	lpstrFile         *uint16
	nMaxFile          uint32
	lpstrFileTitle    *uint16
	nMaxFileTitle     uint32
	lpstrInitialDir   *uint16
	lpstrTitle        *uint16
	flags             uint32
	nFileOffset       uint16
	nFileExtension    uint16
	lpstrDefExt       *uint16
	lCustData         uintptr
	lpfnHook          uintptr
	lpTemplateName    *uint16
	pvReserved        uintptr
	dwReserved        uint32
	flagsEx           uint32
}

const (
	ofnExplorer      = 0x00080000
	ofnAllowMultiSel = 0x00000200
	ofnFileMustExist = 0x00001000
	ofnPathMustExist = 0x00000800
)

func pickFiles() ([]string, error) {
	buf := make([]uint16, 1<<16)
	filter := utf16z("Data files\x00*.csv;*.tsv;*.json;*.ndjson;*.xlsx;*.xlsm;*.xls;*.db;*.sqlite;*.sqlite3\x00All files\x00*.*\x00\x00")
	title := utf16z("Select client datasets to import")
	ofn := openfilename{
		lpstrFilter: &filter[0],
		lpstrFile:   &buf[0],
		nMaxFile:    uint32(len(buf)),
		lpstrTitle:  &title[0],
		flags:       ofnExplorer | ofnAllowMultiSel | ofnFileMustExist | ofnPathMustExist,
	}
	ofn.lStructSize = uint32(unsafe.Sizeof(ofn))
	r, _, _ := procGetOpenFileW.Call(uintptr(unsafe.Pointer(&ofn)))
	if r == 0 {
		return nil, nil // cancelled
	}
	return parseMultiSelect(buf), nil
}

// The multiselect buffer is a NUL-separated list: dir\0file1\0file2\0\0
// For a single selection it is just the full path\0\0.
func parseMultiSelect(buf []uint16) []string {
	parts := splitNulls(buf)
	if len(parts) == 0 {
		return nil
	}
	if len(parts) == 1 {
		return parts
	}
	dir := parts[0]
	var out []string
	for _, f := range parts[1:] {
		sep := "\\"
		if strings.HasSuffix(dir, "\\") {
			sep = ""
		}
		out = append(out, dir+sep+f)
	}
	return out
}

func splitNulls(buf []uint16) []string {
	var out []string
	start := 0
	for i := 0; i < len(buf); i++ {
		if buf[i] == 0 {
			if i == start {
				break
			}
			out = append(out, syscall.UTF16ToString(buf[start:i]))
			start = i + 1
		}
	}
	return out
}

func utf16z(s string) []uint16 {
	u, _ := syscall.UTF16FromString(strings.ReplaceAll(s, "\x00", "\x00"))
	// UTF16FromString stops at first NUL, so build manually for embedded NULs:
	runes := []uint16{}
	for _, r := range s {
		runes = append(runes, uint16(r))
	}
	runes = append(runes, 0)
	_ = u
	return runes
}
