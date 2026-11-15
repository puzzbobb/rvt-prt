# Version matrix

Every `.rvt` under the corpus's `<folder>/` printed to PDF on the 8 GB
development machine (4 cores, ARM64; `rvt-prt print`, default jobs), each under an external MemAvailable watchdog (floor 768 MB)
and a 1450–1500 s timeout. **Release** is what the file says it is (`BasicFileInfo`), not its
folder: the 2019 folder's Snowdon Towers models and those of three other projects are byte-identical copies
of the 2025 folder's. **Triage** is the first pass (2026-10-16); **Now** the files that failed it,
printed again after the phase's fixes (2026-10-17, timeout 1800 s): seconds with `*` at `eb4a375`,
the rest at `6afa099` (faster sections; a few line ends move, by 3.6 pt at most). *Retried*: a sheet short of memory
in its worker printed again with fewer at once (`render/pool.py`); none was drawn without its
section lines or left blank.

| Folder | File | Release | Sheets | Triage | s | Now | s |
|---|---|---|---|---|---|---|---|
| 2008 | model bc51bc | build 2007-03-24 |  | pre-2014 (clear message) |  |  |  |
| 2008 | model a3a86e | build 2008-03-21 |  | pre-2014 (clear message) |  |  |  |
| 2010 | model 1c383c | 2010 |  | pre-2014 (clear message) |  |  |  |
| 2011 | model d67039 | 2011 |  | pre-2014 (clear message) |  |  |  |
| 2011 | model 87ef91 | 2011 |  | pre-2014 (clear message) |  |  |  |
| 2011 | model a60348 | 2011 |  | pre-2014 (clear message) |  |  |  |
| 2012 | model 2161c2 | 2012 |  | pre-2014 (clear message) |  |  |  |
| 2012 | model 58cad4 | 2012 | 1 | ok | 8 |  |  |
| 2013 | model f39190 | 2013 | 2 | ok | 69 |  |  |
| 2019 | model 862cfb | 2019 | 2 | ok | 119 |  |  |
| 2019 | model b35787 | 2025 | 22 | KILLED (memory) | 506 | as 2025 (same file) |  |
| 2019 | model d62022 | 2025 | 19 | KILLED (memory) | 722 | as 2025 (same file) |  |
| 2019 | model bb225c | build 2008-01-26 |  | pre-2014 (clear message) |  |  |  |
| 2019 | Snowdon Architectural | 2025 | 55 | TIMEOUT | 1450 | as 2025 (same file) |  |
| 2019 | Snowdon Electrical | 2025 | 26 | ok | 120 |  |  |
| 2019 | Snowdon Facades | 2025 | 2 | ok | 66 |  |  |
| 2019 | Snowdon HVAC | 2025 | 18 | ok | 390 |  |  |
| 2019 | Snowdon Plumbing | 2025 | 27 | TIMEOUT | 1500 | as 2025 (same file) |  |
| 2019 | Snowdon Site | 2025 | 3 | ok | 107 |  |  |
| 2019 | Snowdon Structural | 2025 | 12 | ok | 85 |  |  |
| 2019 | model b422d8 | 2019 | 2 | ok | 149 |  |  |
| 2019 | Autodesk architecture sample (advanced) | 2019 | 2 | ok | 157 |  |  |
| 2019 | Autodesk architecture sample (basic) | 2019 | 6 | TIMEOUT | 1500 | ok | 149* |
| 2019 | Autodesk MEP sample (advanced) | 2019 | 8 | ok | 265 |  |  |
| 2019 | Autodesk MEP sample (basic) | 2019 | 8 | ok | 256 |  |  |
| 2019 | Autodesk structure sample (advanced) | 2019 | 9 | ok | 92 |  |  |
| 2019 | Autodesk structure sample (basic) | 2019 | 8 | KILLED (memory) | 104 | ok | 99* |
| 2019 | model fc817f | 2025 | 40 | TIMEOUT | 1500 | as 2025 (same file) |  |
| 2019 | model 7d3700 | 2025 | 54 | UnicodeDecodeError (Shift-JIS RTF) | 17 | as 2025 (same file) |  |
| 2019 | model ed2408 | 2025 | 66 | KILLED (memory) | 301 | as 2025 (same file) |  |
| 2020 | Autodesk architecture sample (basic) | 2020 | 6 | TIMEOUT | 1450 | ok | 77† |
| 2020 | Autodesk structure sample (basic) | 2020 | 8 | ok (sheets redrawn in parent) | 1069 | ok | 55† |
| 2021 | Autodesk architecture sample (advanced) | 2021 | 2 | ok | 184 |  |  |
| 2021 | Autodesk architecture sample (basic) | 2021 | 6 | TIMEOUT | 1450 | ok | 80† |
| 2021 | Autodesk structure sample (basic) | 2021 | 8 | ok (sheets redrawn in parent) | 1120 | ok | 55† |
| 2022 | Autodesk architecture sample (basic) | 2022 | 6 | TIMEOUT | 1450 | ok | 81† |
| 2022 | Autodesk structure sample (basic) | 2022 | 8 | ok (sheets redrawn in parent) | 1117 | ok | 55† |
| 2023 | model 182c9b | 2023 | 0 | no sheets |  |  |  |
| 2023 | Autodesk architecture sample (basic) | 2023 | 6 | TIMEOUT | 1450 | ok | 81† |
| 2023 | Autodesk structure sample (basic) | 2023 | 8 | ok (sheets redrawn in parent) | 1117 | ok | 58† |
| 2024 | model cc0a19 | 2024 | 0 | no sheets |  |  |  |
| 2024 | Autodesk architecture sample (basic) | 2024 | 6 | TIMEOUT | 1450 | ok | 82† |
| 2024 | Autodesk structure sample (basic) | 2024 | 8 | ok (sheets redrawn in parent) | 1073 | ok | 56† |
| 2025 | model 9e0ec3 | 2025 | 0 | no sheets |  |  |  |
| 2025 | model db8535 | 2025 | 0 | no sheets |  |  |  |
| 2025 | model ccf816 | 2025 | 0 | no sheets |  |  |  |
| 2025 | model c47f79 | 2025 | 0 | no sheets |  |  |  |
| 2025 | model b35787 | 2025 | 22 | KILLED (memory) | 382 | ok, 3 sheets retried | 518 |
| 2025 | model d62022 | 2025 | 19 | KILLED (memory) | 726 | ok, 1 sheet retried | 550* |
| 2025 | Snowdon Architectural | 2025 | 55 | TIMEOUT | 1450 | ok | 370 |
| 2025 | Snowdon Electrical | 2025 | 26 | ok | 91 |  |  |
| 2025 | Snowdon Facades | 2025 | 2 | ok | 34 |  |  |
| 2025 | Snowdon HVAC | 2025 | 18 | ok | 58 |  |  |
| 2025 | Snowdon Plumbing | 2025 | 27 | TIMEOUT | 1450 | ok, 2 sheets retried | 415* |
| 2025 | Snowdon Site | 2025 | 3 | ok | 43 |  |  |
| 2025 | Snowdon Structural | 2025 | 12 | ok | 42 |  |  |
| 2025 | Autodesk architecture sample (basic) | 2025 | 6 | TIMEOUT | 1450 | ok | 83† |
| 2025 | model fc817f | 2025 | 40 | TIMEOUT | 1450 | ok, 4 sheets retried | 768 |
| 2025 | model 7d3700 | 2025 | 54 | ok | 283 | ok, 2 sheets retried | 285* |
| 2025 | model ed2408 | 2025 | 66 | ok (sheets redrawn in parent) | 391 | ok, 2 sheets retried | 448* |
| 2026 | Autodesk architecture sample (advanced) | 2026 | 2 | ok | 185 |  |  |
| 2026 | Autodesk architecture sample (basic) | 2026 | 6 | TIMEOUT | 1450 | ok | 82† |
| 2027 | Autodesk architecture sample (advanced) | 2027 | 2 | ok | 182 |  |  |
| 2027 | Autodesk architecture sample (basic) | 2027 | 6 | TIMEOUT | 1450 | ok | 116* |
| 2027 | Autodesk MEP sample (advanced) | 2027 | 8 | ok | 220 |  |  |
| 2027 | Autodesk MEP sample (basic) | 2027 | 8 | ok | 202 |  |  |
| 2027 | Autodesk structure sample (advanced) | 2027 | 9 | ok | 50 |  |  |
| 2027 | Autodesk structure sample (basic) | 2027 | 8 | ok (sheets redrawn in parent) | 1038 | ok | 48 |

- **pre-2014 (clear message):** a file before Revit 2014 stops with its release (or its build
  date, when the release is unknown) and that it is not supported, not a traceback (`640aeab`,
  `201c002`). 2012's model 58cad4 and 2013's model f39190 print. **No 2014–2018 project is in the
  corpus.**
- **†** (2026-10-28, `4eb1cd9` and its fix): the basic architecture and structure samples of 2020–2026, the same
  projects as the 2019 and 2027 files, printed again, 4 jobs: every sheet drawn, none retried, at
  least 4.1 GB free throughout. 2020–2022 first failed (TypeError in `linkgeom._compute_model_curves`:
  a model curve's saved-graphics root is empty in those files); fixed.
- **sheets redrawn in parent** (triage): the pool drew a sheet that failed in its worker in the
  parent process, unguarded; it no longer does (`e735983`).
- **no sheets:** test models without sheets: nothing to print.
