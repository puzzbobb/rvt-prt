"""Overlay our sheet on Revit's: Revit's print in grey, ours in red, one PNG per sheet.

python -m rvt_prt.metrics.compare ours.pdf oracle_dir out_dir [dpi]
Page i of ours.pdf is matched to <oracle_dir>/<sheet number>.pdf by the number drawn on it.
"""
import pathlib
import sys

import numpy as np

from rvt_prt import pdf


def overlay(revit_page, our_page, dpi):
    """Revit's print lightened to grey, with every dark pixel of ours in red (ours drawn bold)."""
    a = pdf.rasterise(revit_page, dpi, gray=True).astype(int)
    b = pdf.rasterise(our_page, dpi, gray=True)
    g = (255 - (255 - a) // 2).astype(np.uint8)
    out = np.repeat(g[:, :, None], 3, axis=2)
    h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    out[:h, :w][b[:h, :w] < 200] = (0xE0, 0x10, 0x10)
    return out


if __name__ == "__main__":
    ours, oracle, out = pdf.open_document(sys.argv[1]), pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
    dpi = int(sys.argv[4]) if len(sys.argv) > 4 else 30
    out.mkdir(parents=True, exist_ok=True)
    toc = pdf.toc(ours)
    for i, page in enumerate(ours):
        words = {toc[i]} if i in toc else {w[4] for w in pdf.page_words(page)}
        for revit_pdf in sorted(oracle.glob("*.pdf")):
            if revit_pdf.stem in words:
                rp = pdf.open_document(revit_pdf)[0]
                if abs(rp.rect.width - page.rect.width) > 1 or abs(rp.rect.height - page.rect.height) > 1:
                    print(f"{revit_pdf.stem}: page size differs {rp.rect} vs {page.rect}")
                pdf.write_png(overlay(rp, page, dpi), out / f"{revit_pdf.stem}_overlay.png")
                print(f"{revit_pdf.stem}: page {page.rect.width / 72:.1f} x {page.rect.height / 72:.1f} in, same as Revit's: "
                      f"{abs(rp.rect.width - page.rect.width) < 1 and abs(rp.rect.height - page.rect.height) < 1}")
                break
