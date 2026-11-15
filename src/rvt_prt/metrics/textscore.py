"""Text agreement with Revit's print: each word we print, matched to the same word in Revit's PDF
whose origin is within `tol` inches; also Revit's words (left of the title block) that we print.

python -m rvt_prt.metrics.textscore ours.pdf oracle_dir [tol_in]
"""
import collections
import pathlib
import sys

from rvt_prt import pdf  # absolute: this file is also run as a script

TITLE_X_IN = 34.0


def words(page):
    H = page.rect.height
    return [(w[4].replace("\u2010", "-").replace("\xad", "-"), w[0] / 72, (H - w[3]) / 72) for w in pdf.page_words(page) if w[0] / 72 < TITLE_X_IN]


def match(ours, theirs, tol):
    by = collections.defaultdict(list)
    for t, x, y in theirs:
        by[t].append((x, y))
    hit = 0
    for t, x, y in ours:
        if any(abs(x - a) <= tol and abs(y - b) <= tol for a, b in by.get(t, [])):
            hit += 1
    return hit


if __name__ == "__main__":
    ours, oracle = pdf.open_document(sys.argv[1]), pathlib.Path(sys.argv[2])
    tol = float(sys.argv[3]) if len(sys.argv) > 3 else 0.1
    tot = [0, 0, 0]
    toc = pdf.toc(ours)
    for i, page in enumerate(ours):
        names = {toc[i]} if i in toc else set(pdf.page_text(page).split())
        for revit_pdf in sorted(oracle.glob("*.pdf")):
            if revit_pdf.stem in names:
                a, b = words(page), words(pdf.open_document(revit_pdf)[0])
                h = match(a, b, tol)
                tot[0] += h; tot[1] += len(a); tot[2] += len(b)
                print(f"{revit_pdf.stem}: our words {len(a):4}, on Revit's within {tol} in {h:4} ({h / max(len(a), 1):6.1%}); Revit words {len(b):4}")
    print(f"all: {tot[0]} of our {tot[1]} words placed as Revit's ({tot[0] / max(tot[1], 1):.1%}); Revit prints {tot[2]}")
