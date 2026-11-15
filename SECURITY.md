# Security policy

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Please report privately through the repository's GitHub security advisories ("Report a
vulnerability"), not in a public issue. Include the rvt-prt version, the platform, and, if you
can share one, a file that shows the problem. A crafted file you made yourself is ideal.

## Scope

rvt-prt parses `.rvt` files, which may come from anyone. In scope:

- a crash, a hang, or unbounded memory or disk use caused by a file (for example decompression
  bombs, or counts read from a header that drive allocation);
- writing anywhere other than the output named by `-o` and the cache directory, or reading a
  file other than the model and the linked models beside it;
- anything that runs code from a file's contents.

Not in scope: a file that prints incorrectly. Please report that as an ordinary issue.

## What rvt-prt does about hostile files

| Risk | What bounds it |
|---|---|
| A file that inflates to gigabytes (a decompression bomb) | A file may inflate to 40 times its size (64 MB at least) in all. Revit's own files inflate to 4 or 5 times. Past the limit the file is refused |
| Counts in a record that would be looped over or allocated | An array count greater than the bytes left in its record is refused. Every read is bounds-checked by Python |
| A damaged or misleading file | A misread is reported in one line naming the part that could not be read. A record that does not decode is skipped |
| A sheet that takes for ever to draw | `--sheet-timeout SECONDS` stops it. Off by default, since large real sheets take minutes |
| A sheet that takes all the memory | Each sheet is drawn in its own process under an address-space cap, and the machine's free memory is watched. `--memory-limit GB` caps the whole print, run in a process of its own: past it the print stops with one line (the native extension may print two lines of its own first) |
| A linked model named with a path (`../../x.rvt`) | A linked model is looked for by file name alone, in the folders linked models are looked for in |
| Output file names taken from sheet names | Characters a file name cannot hold are replaced. Files are written only inside the output folder |
| A cache file someone else planted | Cache folders are created for the user alone, and a cache folder that someone else owns or others can write to is not read |

These are tested with damaged and crafted inputs (`tests/unit/test_hostile.py`,
`tests/integration/test_damaged_files.py`), and the readers were fuzzed with thousands of damaged
copies of a small model.

**What is not bounded.** There is no limit on the whole print's time, only on each sheet's.
Reading the model before the sheets are drawn has no time limit. The native extension (rvt-rs)
and the PDF and image libraries (MuPDF) parse data from the file with their own safeguards, not
rvt-prt's. For files you do not trust, give both limits and run the print in a container or
sandbox with its own limits as well:

```bash
rvt-prt print untrusted.rvt -o out --memory-limit 4 --sheet-timeout 300
```

## The disk cache

rvt-prt caches what it decodes from a model under the user's cache directory, or the folder
`RVT_PRT_CACHE` names (`rvt-prt cache` lists it). The cache is stored with Python's pickle, which runs code when loaded, so it is trusted
only because it is the user's own. Do not point rvt-prt at a cache directory others can write
to, and do not share cache files.

## Dependencies

PDF writing uses PyMuPDF (MuPDF). Vulnerabilities in it are fixed by upgrading it. rvt-prt
pins only a minimum version.
