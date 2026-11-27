//go:build !windows

package main

// Fallback file picker for non-Windows builds (drag & drop still works in UI).
func pickFiles() ([]string, error) { return nil, nil }
