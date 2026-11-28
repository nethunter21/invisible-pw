QUIET SEARCH  —  Databases Connector Searcher  (v1.1.0)
========================================================
Local, offline desktop tool to store your own client databases, auto-detect
what each field is, index & search across all of them, and link each client
to their own records across separate datasets. No server. No network calls.
All data stays in quietsearch.db next to the .exe.

RUN
  1. Double-click QuietSearch.exe (Windows 10/11, 64-bit).
  2. Requires the Microsoft Edge WebView2 Runtime — preinstalled on current
     Windows 10/11. If it ever complains, install the free "Evergreen"
     runtime from Microsoft once, then relaunch.

IMPORT — ALWAYS ASYNC, NEVER FREEZES
  • IMPORT DB (top-right) opens the native multi-file picker — select any
    number of files at once for bulk loading. Or drag files onto the
    Databases tab (dropped files stream to disk in small chunks, so even a
    very large single file can't freeze or crash the window).
  • All parsing + indexing runs in the background. A progress bar at the top
    shows which file is being indexed and how many rows are done; the UI
    stays fully responsive throughout, no matter how heavy the file is.
  • Large imports commit in batches (a few thousand rows at a time) instead
    of one giant transaction, so even million-row files index reliably.
  • A malformed or corrupt file reports an error for that file only — it
    never takes down the rest of the import or the app.

INDEXING ACCURACY
  Supported: .csv .tsv .txt .log .json .ndjson .xlsx .xls .db .sqlite
  • Delimiter is auto-detected per file by sampling and scoring consistency:
    comma, tab, semicolon, pipe, or colon (combo lists like
    user@mail.com:password ). The modal field count is used as the true
    column count, so one outlier line with extra delimiter characters can't
    blow the whole file out into hundreds of mostly-blank columns.
  • URLs are protected before delimiter detection — the colons in
    https://host:8080/path are never mistaken for a field separator.
  • Fully-blank rows and 100%-empty columns are dropped automatically (no
    more "999 useless blank columns" from padded/ragged source files).
  • Columns with no header row are auto-named from their detected type
    (email, phone, url, hash, account_id, …).
  • Column types (email / phone / name / account_id / …) are auto-detected;
    identity fields are used to link records across datasets.

INTERFACE
  • DATABASES  — every source, schema, per-field fill/distinct stats. Rename
    or delete a dataset at any time (delete also runs in the background).
  • SEARCH     — full-text across all datasets or one; click a row for detail.
  • CONNECTOR  — pick a record (Search → Link) to map every record, in any
    dataset, that resolves to the same client (matched & normalized on
    email / phone / username / account id).
  • INTEGRITY  — shared-key clusters for de-duplication / legitimacy checks.

All processing is on your machine. Delete quietsearch.db to wipe everything.
