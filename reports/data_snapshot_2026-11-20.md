# GPU data snapshot — 2026-11-20

Latest local parse: 2026-11-20 00:18 (UTC+07:00).

| File | Rows | Columns |
|---|---:|---:|
| `data/raw_gpu_data.csv` | 375 | 53 |
| `data/raw_gpu_all_fields.csv` | 375 | 131 |
| `data/project_gpu_data.csv` | 375 | 20 |
| `data/links.csv` | 2249 | 2 |

The GPU tables contain 375 distinct GPU IDs. Of these, 342 have a recognized release year within the selected 2012–2025 scope. The remaining 33 have unrecognized release years and are retained for review; they must not count toward the in-scope target yet. The raw all-fields table preserves source field names and is not the normalized analysis table.

The project table contains 18 selected attributes plus GPU ID and source URL. This is an intermediate crawl snapshot, not a cleaned or exhaustive GPU dataset. There are 158 more confirmed in-scope rows needed to reach 500, or 208 to reach the collection buffer of 550.

The latest crawl stopped on a CAPTCHA after saving 39 pages. No crawler process was running at publication inspection. This update publishes the exported data and parse report; local HTML caches, runtime state, logs, backups and pending code edits are not included in this data update.
