"""Schedules placed on sheets: the Sheet Index (M000), the title block's revision table, and other
schedules, decoded from the object graph.

Decoded:
- DBViewSchedule:
  - m_viewName: schedule name;
  - ScheduleSchema: category id, sort fields (ScheduleSortField), fields (ScheduleField: heading, width, hidden, param),
    filters (ScheduleFilter: field id, filter type, value), grand totals.
  - ScheduleSegmentRec: fixed height (e.g. revision schedule).
  - TableCellStyle: font name, text size, bold flag, horizontal and vertical alignments.
  - Text types (m_bodyTextTypeId, m_headerTextTypeId, m_titleTextTypeId) resolved against FontElem objects.
- ProjectRevision: m_description, m_issuedBy, m_issuedTo, m_date, m_numberStr.
- ScheduleInstance: m_ownerDBViewId, origin_XYZ, m_scheduleId.
"""
import functools
import math
from dataclasses import dataclass, field

from ..core import objgraph


@dataclass
class Field:
    name: str
    param: int  # BuiltInParameter (or a parameter element id)
    width: float  # feet
    hidden: bool = False
    field_id: int | None = None  # ScheduleFieldId, as sort fields and filters name it


@dataclass
class SortField:
    field_id: int
    flags: int  # m_groupingFlags: 0x04 footer, 0x10 blank line, 0x20 footer title, 0x40 footer count
    descending: bool = False


@dataclass
class CellStyle:
    font: str
    size_px: float  # m_textSize, 1/96 in (12 = 1/8")
    bold: bool = False
    halign: int = 0  # m_horizontalAlignment: 0 left, 1 centre, 2 right

    @property
    def size_pt(self):
        """As Revit prints it: px × 25/24, to the half point up (12 → 12.5, 18 → 19, 9 → 9.5)."""
        return math.floor(self.size_px * 25 / 24 * 2 + 0.5) / 2


@dataclass
class Schedule:
    schedule_id: int
    name: str
    columns: list  # [(header, width ft)]
    fixed_height: float | None = None  # feet
    hidden: list = field(default_factory=list)  # hidden field names (sort / group keys)
    fields: list = field(default_factory=list)  # [Field], in record order
    sort: list = field(default_factory=list)  # [SortField]
    filters: list = field(default_factory=list)  # [(field id, filter type, value)]
    grand_total: tuple = (False, False, False, False)  # shown, title, count, totals
    category: int | None = None  # BuiltInCategory
    text_types: tuple = ()  # (body, header, title) TextNoteAttributes ids
    title_style: CellStyle | None = None
    header_styles: list = field(default_factory=list)  # [CellStyle] per visible column
    body_styles: list = field(default_factory=list)  # [CellStyle] per visible column
    title_height: float | None = None  # feet: the title row's stored height, its least (TableRowData m_dHeight)
    grid_style: int | None = None  # the body grid's line style (ScheduleSchema m_bodyGridCategoryId)
    outline_style: int | None = None  # the outline's (m_outlineGridCategoryId: Snowdon's Sheet Index, Wide Lines)


@dataclass
class ScheduleOnSheet:
    instance_id: int
    owner_view: int
    origin: tuple  # top-left, sheet feet
    schedule: Schedule
    rows: list = field(default_factory=list)  # [[cell text]]
    table: list | None = None  # [(kind, cells)] for element schedules (table_rows)


def _cat_id(v):
    if not isinstance(v, dict):
        return None
    return v.get("m_id", {}).get("m_id64") if isinstance(v.get("m_id"), dict) else v.get("m_id64")


@functools.cache
def text_fonts(rf, path):
    """{text type id: (font name, size ft)} from FontElem."""
    out = {}
    for _eid, g in objgraph.elements(path, ("FontElem",)):
        root = g.objects[0]
        owner = objgraph.ref(root.fields.get("m_ownerId"))
        f_obj = next((o for o in g.objects if o.name == "Font"), None)
        if owner and f_obj:
            out[owner] = (f_obj.fields.get("m_name"), f_obj.fields.get("m_size"))
    return out


def _builtin_id(v):
    """An ElementId field's id, a built-in one (negative) included; None for -1 or absent."""
    x = v.get("m_id", {}).get("m_id64") if isinstance(v, dict) else None
    return x if isinstance(x, int) and x != -1 else None


def definitions(rf, path):
    """All DBViewSchedule definitions decoded from the object graph."""
    fonts = text_fonts(rf, path)
    out = {}
    for eid, g in objgraph.elements(path, ("DBViewSchedule",)):
        root = g.objects[0]
        name = root.fields.get("m_viewName", "")
        schema_idx = next((i for i, o in enumerate(g.objects) if o.name == "ScheduleSchema"), None)
        schema_obj = g.objects[schema_idx] if schema_idx is not None else None
        seg_obj = next((o for o in g.objects if o.name == "ScheduleSegmentRec"), None)
        fixed = seg_obj.fields.get("m_height") if seg_obj else None

        cols = []
        hidden_names = []
        fields = []
        sort = []
        filters = []
        cat = None
        grand_total = (False, False, False, False)
        text_types = ()

        b_id = objgraph.ref(root.fields.get("m_bodyTextTypeId"))
        h_id = objgraph.ref(root.fields.get("m_headerTextTypeId"))
        t_id = objgraph.ref(root.fields.get("m_titleTextTypeId"))
        if b_id in fonts and h_id in fonts and t_id in fonts:
            text_types = (b_id, h_id, t_id)

        if schema_obj and schema_idx is not None:
            cat = _cat_id(schema_obj.fields.get("m_categoryId"))
            grand_total = (
                bool(schema_obj.fields.get("m_showGrandTotal")),
                bool(schema_obj.fields.get("m_showGrandTotalTitle")),
                bool(schema_obj.fields.get("m_showGrandTotalCount")),
                True,
            )
            for s_ptr in schema_obj.fields.get("m_sortFieldArr", []):
                s_idx = g.target(schema_idx, s_ptr)
                if s_idx is not None:
                    sf = g.objects[s_idx].fields
                    fid = sf.get("m_fieldId", {}).get("m_id")
                    flg = sf.get("m_groupingFlags", 0)
                    desc = sf.get("m_sortOrder", 0) == 1
                    sort.append(SortField(fid, flg, desc))

            for f_ptr in schema_obj.fields.get("m_filterArr", []):
                f_idx = g.target(schema_idx, f_ptr)
                if f_idx is not None:
                    ff = g.objects[f_idx].fields
                    fid = ff.get("m_fieldId", {}).get("m_id")
                    ftype = ff.get("m_filterType", 0)
                    val_dict = ff.get("m_value", {})
                    stype = val_dict.get("m_storageType")
                    if stype == 3:
                        v = val_dict.get("m_str", {}).get("m_str", "")
                    elif stype == 1:
                        v = val_dict.get("m_int")
                    elif stype == 2:
                        v = val_dict.get("m_dbl")
                    else:
                        v = ""
                    filters.append((fid, ftype, v))

            field_objs = []
            for f_ptr in schema_obj.fields.get("m_pFields", []):
                f_idx = g.target(schema_idx, f_ptr)
                if f_idx is not None:
                    field_objs.append(g.objects[f_idx])

            field_id_list = [item.get("m_id") for item in schema_obj.fields.get("m_fieldIds", [])]
            for idx, fo in enumerate(field_objs):
                f_id = field_id_list[idx] if idx < len(field_id_list) else idx
                fld_name = fo.fields.get("m_columnHeading", "")
                fld_width = fo.fields.get("m_columnWidth", 0.0)
                hidden = bool(fo.fields.get("m_hidden"))
                param = _cat_id(fo.fields.get("m_paramElemId")) or 0
                f_item = Field(fld_name, param, fld_width, hidden, f_id)
                fields.append(f_item)
                if hidden:
                    hidden_names.append(fld_name)
                else:
                    cols.append((fld_name, fld_width))

        if cat != REVISIONS:
            fixed = None

        sched = Schedule(eid, name, cols, fixed, hidden_names, fields, sort, filters, grand_total, cat, text_types)

        if text_types:
            font = lambda i, tt=text_types: CellStyle(fonts[tt[i]][0], fonts[tt[i]][1] * 12 * 96)
            ncol = len(cols)
            sched.title_style = font(2)
            sched.header_styles = [CellStyle(font(1).font, font(1).size_px, False, 1) for _ in range(ncol)]
            sched.body_styles = [font(0) for _ in range(ncol)]

        style_objs = [
            (
                CellStyle(
                    o.fields.get("m_fontName"),
                    o.fields.get("m_textSize"),
                    bool(o.fields.get("m_flag", 0) & 4),
                    o.fields.get("m_horizontalAlignment", 0),
                ),
                o.fields.get("m_verticalAlignment", 0),
            )
            for o in g.objects
            if o.name == "TableCellStyle"
        ]
        cells = style_objs[2 * len(fields):]
        ncol = len(cols)
        if ncol:
            for h in range(len(cells) - ncol + 1):
                run = cells[h:h + ncol]
                if all(va == 8 for _c, va in run):
                    sched.header_styles = [c for c, _va in run]
                    if h > 0:
                        sched.title_style = cells[h - 1][0]
                    body_cells = cells[h + ncol:h + 2 * ncol]
                    if len(body_cells) == ncol and all(va == 0 for _c, va in body_cells):
                        sched.body_styles = [c for c, _va in body_cells]
                    break
        schema = next((o.fields for o in g.objects if o.name == "ScheduleSchema"), {})
        # built-in line styles: negative ids, which objgraph.ref reads as none
        sched.grid_style = _builtin_id(schema.get("m_bodyGridCategoryId"))
        sched.outline_style = _builtin_id(schema.get("m_outlineGridCategoryId"))
        # the title row's height: the header section's (m_index 0) first row (Snowdon's Sheet
        # Index: 0.4167 in, its title printed in a 30 pt row; its body rows store 1/6 in and
        # print taller, at their text's height)
        for i, o in enumerate(g.objects):
            if o.name == "ScheduleSectionData" and o.fields.get("m_index") == 0 and o.fields.get("m_rows"):
                j = g.target(i, o.fields["m_rows"][0])
                if j is not None and g.objects[j].name == "TableRowData":
                    sched.title_height = g.objects[j].fields.get("m_dHeight")
                break
        out[eid] = sched
    return out


def revisions(rf, path):
    """{revision id: (number, description, date)}: ProjectRevision m_numberStr, m_description, m_date."""
    return {
        eid: (f.get("m_numberStr", ""), f.get("m_description", ""), f.get("m_date", ""))
        for eid, g in objgraph.elements(path, ("ProjectRevision",))
        for f in [g.objects[0].fields]
    }


def _instances(path):
    """[(instance id, owner view id, (x, y) top-left sheet feet, schedule id)]: ScheduleInstance
    m_ownerDBViewId, origin_XYZ, m_scheduleId."""
    out = []
    for eid, g in objgraph.elements(path, ("ScheduleInstance",)):
        f = g.objects[0].fields
        xyz = (f.get("origin_XYZ") or {}).get("m_xyz")
        if xyz:
            out.append((eid, objgraph.ref(f.get("m_ownerDBViewId")), (xyz[0], xyz[1]), objgraph.ref(f.get("m_scheduleId"))))
    return out


def on_sheets(rf, path, sheets, elevations=None):
    """Every schedule instance with its rows, attached to sheets by owner view."""
    defs = definitions(rf, path)
    revs = revisions(rf, path)
    from ..model import views
    sheet_revs = {v.sheet["number"]: [r for r in v.revisions if r in revs] for v in views.read(rf, path) if v.sheet}
    listed = [s for s in sheets if s.scheduled]  # "Appears In Sheet List"
    out = []
    for eid, owner, origin, sid in _instances(path):
        sched = defs.get(sid) if sid is not None else None
        if sched is None:
            continue
        out.append(ScheduleOnSheet(eid, owner, origin, sched))

    for so in out:
        cat = so.schedule.category
        params = [f.param for f in so.schedule.fields if not f.hidden]  # the shown columns, in order
        if cat in (MEP_SPACES, MECHANICAL_EQUIPMENT):
            so.table = table_rows(so.schedule, items(rf, path, so.schedule, elevations or {}))
            continue
        if cat == REVISIONS:
            sheet = next((s for s in sheets if s.view_id == so.owner_view), None)
            ids = sheet_revs.get(sheet.number, []) if sheet else []
            so.rows = [[revs[r][REVISION_FIELDS[p]] if p in REVISION_FIELDS else "" for p in params] for r in ids]
        elif cat == SHEETS:
            so.rows = [[s.number if p == SHEET_NUMBER else s.name if p == SHEET_NAME else "" for p in params]
                       for s in sorted(listed, key=lambda s: s.number)]
            if any("Group" in h for h in so.schedule.hidden):
                # open: Revit prints a blank first row here (Snowdon's Sheet Index, its hidden
                # "Sheet Group" sort field); no flag found for it (the sort fields' m_groupingFlags are 0)
                so.rows.insert(0, [""] * len(params))
    return out


MEP_SPACES = -2003600
REVISIONS = -2006070  # a revision schedule (on a title block)
SHEETS = -2003100  # a sheet list
REVISION_FIELDS = {-1011951: 0, -1011952: 1, -1011953: 2}  # REVISION_NUM, _DESCRIPTION, _DATE -> revisions()
SHEET_NUMBER, SHEET_NAME = -1007401, -1007400
MECHANICAL_EQUIPMENT = -2001140
ALL_MODEL_MARK = -1001203
ELEM_FAMILY_PARAM = -1002051
ELEM_TYPE_PARAM = -1002050
FAMILY_LEVEL_PARAM = -1002062

FILTERS = {
    2: lambda v, x: v == x,
    3: lambda v, x: v != x,
    8: lambda v, x: x in v,
    9: lambda v, x: x not in v,
    10: lambda v, x: v.startswith(x),
    11: lambda v, x: not v.startswith(x),
    12: lambda v, x: v.endswith(x),
    13: lambda v, x: not v.endswith(x),
}


ITEM_MODULES = ("schedules", "spaces", "annotations", "objgraph", "registry", "container")


def items(rf, path, sched, elevations):
    """The schedule's elements as [{param: (text, sort key, number or None)}], disk-cached per
    category (all they depend on of the schedule) and storey elevations."""
    import hashlib

    from ..core import diskcache
    levels = hashlib.sha1(repr(sorted(elevations.items())).encode()).hexdigest()[:10]
    return diskcache.cached(path, f"schedule_items_{-sched.category}_{levels}", ITEM_MODULES,
                            lambda: _items(rf, path, sched, elevations))


def _items(rf, path, sched, elevations):
    from ..model import spaces as sp
    names = sp.level_names(rf, path)
    level = lambda lid: (names.get(lid, ""), (elevations.get(names.get(lid), 0.0), names.get(lid, "")), None)
    spaces = sp.read(rf, path, elevations)
    out = []
    if sched.category == MEP_SPACES:
        for s in spaces:
            if s.area is None:
                continue  # unplaced
            out.append({
                sp.ROOM_NUMBER: (s.number, s.number, None),
                sp.ROOM_NAME: (s.name, s.name, None),
                sp.ROOM_AREA: (f"{round(s.area)} SF", s.area, s.area),
                sp.ROOM_LEVEL_ID: level(s.level_id),
            })
    elif sched.category == MECHANICAL_EQUIPMENT:
        from . import annotations
        family_cats = {}
        family_names = {}
        for fid, g in objgraph.elements(path, ("Family",)):
            root = g.objects[0]
            if "m_name" in root.fields:
                family_names[fid] = root.fields["m_name"]
            for o in g.objects:
                if "m_categoryId" in o.fields:
                    cid = o.fields["m_categoryId"].get("m_id", {}).get("m_id64")
                    family_cats[fid] = cid
                    break

        sym_family = {}
        sym_names = {}
        for sid, g in objgraph.elements(path, ("FamilySymbol",)):
            fid = objgraph.ref(g.objects[0].fields.get("m_familyId"))
            if fid:
                sym_family[sid] = fid
            for o in g.objects:
                if o.name == "SymbolInfo" and "m_name" in o.fields:
                    sym_names[sid] = o.fields["m_name"]
                    break

        mech_insts = []
        for eid, g in objgraph.elements(path, ("FamilyInstance",)):
            sid = objgraph.ref(g.objects[0].fields.get("m_masterSymbolId"))
            fid = sym_family.get(sid)
            cat = family_cats.get(fid)
            if cat == MECHANICAL_EQUIPMENT:
                lvl = objgraph.ref(g.objects[0].fields.get("m_assocLevelId"))
                loc = None
                for o in g.objects:
                    if o.name == "InstanceInfo" and "m_Trf" in o.fields:
                        loc = o.fields["m_Trf"].get("m_or")
                        break
                mech_insts.append((eid, lvl, loc, family_names.get(fid, ""), sym_names.get(sid, "")))

        marks = annotations.string_params(rf, path, {eid for eid, *_ in mech_insts}, ALL_MODEL_MARK)
        for eid, lvl, loc, fam, typ in mech_insts:
            s = sp.containing(spaces, loc[0], loc[1], loc[2], lvl) if loc else None
            mark = marks.get(eid, "")
            out.append({
                sp.ROOM_NUMBER: (s.number if s else "", s.number if s else "", None),
                sp.ROOM_NAME: (s.name if s else "", s.name if s else "", None),
                ALL_MODEL_MARK: (mark, mark, None),
                ELEM_FAMILY_PARAM: (fam, fam, None),
                ELEM_TYPE_PARAM: (typ, typ, None),
                FAMILY_LEVEL_PARAM: level(lvl),
            })
    return out


def table_rows(sched, elements):
    """[(kind, cells)] with kind "row", "blank", "footer" or "total", as Revit prints them: the
    filters applied, sorted by the sort fields, grouped by the first when it has a footer."""
    by_id = {f.field_id: f for f in sched.fields}
    visible = [f for f in sched.fields if not f.hidden]
    for fid, ftype, value in sched.filters:
        f, test = by_id.get(fid), FILTERS.get(ftype)
        if f and test:
            elements = [e for e in elements if test(e.get(f.param, ("",))[0], value)]
    keys = [(by_id[s.field_id].param, s.descending) for s in sched.sort if s.field_id in by_id]
    for param, desc in reversed(keys):
        elements = sorted(elements, key=lambda e: e.get(param, ("", ""))[1], reverse=desc)
    cells = lambda e: [e.get(f.param, ("",))[0] for f in visible]

    def totals(group, first):
        row = [""] * len(visible)
        for i, f in enumerate(visible):
            nums = [e[f.param][2] for e in group if f.param in e and e[f.param][2] is not None]
            if nums:
                row[i] = f"{round(sum(nums))} SF"
        row[0] = first
        return row

    out = []
    g = sched.sort[0] if sched.sort else None
    if g is not None and g.flags & 0x04 and g.field_id in by_id:
        param = by_id[g.field_id].param
        groups = []
        for e in elements:
            v = e.get(param, ("",))[0]
            if groups and groups[-1][0] == v:
                groups[-1][1].append(e)
            else:
                groups.append((v, [e]))
        for v, group in groups:
            if g.flags & 0x10:
                out.append(("blank", [""] * len(visible)))
            out += [("row", cells(e)) for e in group]
            title = v if g.flags & 0x20 else ""
            if g.flags & 0x40:
                title = f"{title}: {len(group)}" if title else str(len(group))
            out.append(("footer", totals(group, title)))
    else:
        out = [("row", cells(e)) for e in elements]
    shown, title, count, _tot = sched.grand_total
    if shown:
        text = "Grand total" if title else ""
        if count:
            text = f"{text}: {len(elements)}" if text else str(len(elements))
        out.append(("total", totals(elements, text)))
    return out
