"""What one print shares across the sheets it draws: set by pool.write (the level elevations by
model.py) before any sheet is drawn, read by the drawing modules as state.NAME. Forked workers
inherit it."""
import datetime

STOREYS_FT = {}  # level elevations by name (levels.read), set by model.py
PRINT_TIME = datetime.datetime.now()  # the Date/Time Stamp label's value
SHOW_CROP = False  # draw viewport crop frames (Revit does not print them), for checking
NO_SECTION_LINES = False  # sections and elevations drawn without their model linework: a sheet too heavy with it (pool._parallel)

PEN_PATH = None  # the model whose Object Styles and pen table give line weights
HIDDEN = {}  # {view id: BuiltInCategory ids the view hides}
HIDDEN_FILTERS = {}  # {view id: [filters.Filter] the view hides}

LINK_ITEMS = []  # [(linkgeom.meshes(source), {material: cut pattern grids}, symbols, stair edges, pen colour)] per source (host, links)
GRIDS = []  # grids.read()
GRID_TYPES = {}  # grids.grid_types()
PLAN_VIEWS = set()  # DBViewPlan ids: the views that draw grids
REGIONS = []  # fills.read()
INVISIBLE = set()  # CurveElem ids drawn in <Invisible lines>
SHEET_ANNOTATIONS = []  # families.sheet_annotations()
TAG_SYMBOLS = {}  # {tag family symbol id: TitleBlock-like symbol}
ROOM_TAGS = []  # roomtags.read()
ROOM_TAG_STYLE = None  # roomtags.TagStyle

RECORD = None  # [drawing.Prim] while a sheet is drawn for export: link linework is recorded, not stroked
RECORD_META = {}  # {group: {"element", "family", "category"}} of the recorded linework
