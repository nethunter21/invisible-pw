VAULTSEARCH  —  Client Intelligence Console  (v1.0.0)
=====================================================
Local, offline desktop tool to store your own client databases, auto-detect
what each field is, index & search across all of them, and link each client
to their own records across separate datasets. No server. No network calls.
All data stays in vaultsearch.db next to the .exe.

RUN
  1. Double-click VaultSearch.exe (Windows 10/11, 64-bit).
  2. Requires the Microsoft Edge WebView2 Runtime — preinstalled on current
     Windows 10/11. If it ever complains, install the free "Evergreen"
     runtime from Microsoft once, then relaunch.

USE
  • IMPORT DB (top-right) or drag files onto the Databases tab.
    Supported: .csv .tsv .json .ndjson .xlsx .xls .db .sqlite
  • Column types (email / phone / name / account_id / …) are auto-detected;
    identity fields are used to link records. Rename a dataset on import.
  • DATABASES  — every source, schema, per-field fill/distinct stats.
  • SEARCH     — full-text across all datasets or one; click a row for detail.
  • CONNECTOR  — pick a record (Search → Link) to map every record, in any
    dataset, that resolves to the same client (matched & normalized on
    email / phone / username / account id).
  • INTEGRITY  — shared-key clusters for de-duplication / legitimacy checks.

All processing is on your machine. Delete vaultsearch.db to wipe everything.
