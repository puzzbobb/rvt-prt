"""Draw sheets as PDF pages (through rvt_prt.pdf). 1 sheet foot = 864 pt.

primitives  sheet coordinates, clipping, raw stroked segments, line patterns, leaders
text        embedded fonts, text widths, wrapping, text blocks
linework    model linework: footprints, plan lines of the host and links, sections, pens, hatching
annotate    datums, grids, notes, tags, detail curves, filled regions, room tags, annotation symbols
paper       title blocks and images
tables      schedules
sheet       one sheet as one page, in Revit's drawing order
pool        a set of sheets to a PDF or to drawings, in forked workers
state       what a print shares across its sheets (set by pool.write)
"""
from . import state
from .linework import LINK_CUT_PT, LINK_GREY, LINK_PROJ_PT, LINK_SYSTEM_PT, band, draw_section
from .annotate import tag_axes
from .pool import sheet_drawing, write
from .primitives import PT, _clip_to_rect
from .sheet import draw_sheet, fit_to_content, sheet_numbers
from .text import scale_text

__all__ = ["state", "LINK_CUT_PT", "LINK_GREY", "LINK_PROJ_PT", "LINK_SYSTEM_PT", "band", "draw_section", "tag_axes",
           "sheet_drawing", "write", "PT", "_clip_to_rect", "draw_sheet", "fit_to_content", "sheet_numbers", "scale_text",
           "STOREYS_FT", "TAG_SYMBOLS"]

# shared containers, filled in place by write() (model.py and the probes use them as render.X)
STOREYS_FT = state.STOREYS_FT
TAG_SYMBOLS = state.TAG_SYMBOLS
