"""Pixel agreement between our sheets and Revit's print, on the MEP linework.

Revit prints the MEP systems in colour and the linked architecture in grey. At `dpi`:
- recall: share of Revit's coloured pixels with one of our drawn pixels within `r` px;
- precision: share of our drawn pixels with a Revit coloured pixel within `r` px.
The whole page is scored, title block included. `mode` picks the pixels: colour
(the MEP systems), grey (the linked architecture's halftone, neutral 100..230) or ink (anything
not white).

python -m rvt_prt.metrics.metrics ours.pdf oracle_dir [dpi] [r] [colour|grey|ink]
"""
import pathlib
import sys

import numpy as np

from rvt_prt import pdf  # absolute: this file is also run as a script


def rgb(page, dpi):
    return pdf.rasterise(page, dpi).astype(int)


def dilate(mask, r):
    out = mask.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= np.roll(np.roll(mask, dy, 0), dx, 1)
    return out


MASKS = {
    "colour": lambda img: img.max(2) - img.min(2) > 80,
    "grey": lambda img: (img.max(2) - img.min(2) < 12) & (img.min(2) >= 100) & (img.max(2) <= 230),
    "ink": lambda img: img.min(2) < 230,
}


def score(revit_page, our_page, dpi=50, r=2, mode="colour"):
    a, b = rgb(revit_page, dpi), rgb(our_page, dpi)
    h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    revit = MASKS[mode](a[:h, :w])
    ours = MASKS[mode](b[:h, :w])
    recall = (revit & dilate(ours, r)).sum() / max(revit.sum(), 1)
    precision = (ours & dilate(revit, r)).sum() / max(ours.sum(), 1)
    return recall, precision, int(revit.sum()), int(ours.sum())


if __name__ == "__main__":
    ours, oracle = pdf.open_document(sys.argv[1]), pathlib.Path(sys.argv[2])
    dpi = int(sys.argv[3]) if len(sys.argv) > 3 else 50
    r = int(sys.argv[4]) if len(sys.argv) > 4 else 2
    mode = sys.argv[5] if len(sys.argv) > 5 else "colour"
    numbers = pdf.toc(ours)  # render.write's bookmarks
    for i, page in enumerate(ours):
        words = {numbers[i]} if i in numbers else set(pdf.page_text(page).split())
        for revit_pdf in sorted(oracle.glob("*.pdf")):
            if revit_pdf.stem in words:
                rc, pr, nr, no = score(pdf.open_document(revit_pdf)[0], page, dpi, r, mode)
                print(f"{revit_pdf.stem}: recall {rc:6.1%}  precision {pr:6.1%}  (Revit {mode} px {nr}, ours {no})")
                break
