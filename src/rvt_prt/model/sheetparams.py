"""A sheet's parameters by the names Revit shows them, and the --where filters that select sheets
by them (`rvt-prt list` and `print`, RevitModel.select_sheets).

The built-in ones are the sheet view's own fields (views.py: m_sheetNumber, m_bScheduled,
m_issueDate, m_drawnBy, ...). A project or shared parameter's value is keyed by its parameter
element's id (views.View.params), and the element (ParamElemProject, ParamElemExternal for a shared
parameter) holds its definition: a ParamDef* object whose m_caption is the name Revit shows
(Snowdon's "Sheet Group", ParamDefString) and whose class is its kind (ParamDefYesNo stored as 0 or
1 in ParamValueSetInt).

A filter is NAME=VALUE (the value, * and ? as wildcards), NAME!=VALUE (anything else) or NAME~TEXT
(the value contains TEXT). Names and values are compared without regard to case; a parameter a
sheet has no value for is "". Several filters must all hold.
"""
import fnmatch
import functools

BUILT_IN = ("Sheet Number", "Sheet Name", "Appears In Sheet List", "Sheet Issue Date",
            "Drawn By", "Checked By", "Designed By", "Approved By")
_FIELDS = {"Sheet Issue Date": "issue_date", "Drawn By": "drawn_by", "Checked By": "checked_by",
           "Designed By": "designed_by", "Approved By": "approved_by"}  # views.SHEET_FIELDS
_OPERATORS = ("!=", "~", "=")  # in the order a filter is split at: "!=" before its "="


def _definitions(path):
    """{parameter element id: (name, ParamDef class)} of the model's parameters."""
    from ..core import objgraph
    out = {}
    for eid, g in objgraph.elements(path, ("ParamElem*",)):
        d = next((o for o in g.objects if o.name.startswith("ParamDef")), None)
        caption = d.fields.get("m_caption") if d else None
        if isinstance(caption, str) and caption:
            out[eid] = (caption, d.name)
    return out


@functools.cache
def definitions(path):
    from ..core import diskcache
    return diskcache.cached(path, "param_definitions", ("sheetparams", "objgraph", "registry"),
                            lambda: _definitions(path))


def _shown(value, kind):
    if kind == "ParamDefYesNo" and isinstance(value, int):
        return "Yes" if value else "No"
    return str(value)


def of(sheet, defs):
    """{name: value as Revit shows it} of a layout.Sheet: the built-in parameters, then its project
    and shared ones in name order. A name a built-in parameter has is not taken by another."""
    out = {"Sheet Number": sheet.number, "Sheet Name": sheet.name,
           "Appears In Sheet List": "Yes" if sheet.scheduled else "No"}
    for name, key in _FIELDS.items():
        out[name] = sheet.fields.get(key) or ""
    custom = {}
    for pid, value in sheet.custom.items():
        if pid in defs:
            name, kind = defs[pid]
            custom.setdefault(name, _shown(value, kind))
    for name in sorted(custom, key=str.lower):
        out.setdefault(name, custom[name])
    return out


def parse(text):
    """(name, operator, value) of a filter, or ValueError saying what one looks like."""
    for op in _OPERATORS:
        name, sep, value = text.partition(op)
        if sep and name.strip():
            return name.strip(), op, value.strip()
    raise ValueError(f"not a filter: {text!r} (NAME=VALUE, NAME!=VALUE or NAME~TEXT, "
                     "e.g. \"Appears In Sheet List=Yes\")")


def _yes_no(value):
    return {"true": "yes", "1": "yes", "false": "no", "0": "no"}.get(value, value)


def matches(params, flt):
    """Whether a sheet's parameters ({name: value}) satisfy a parsed filter."""
    name, op, wanted = flt
    lowered = {k.lower(): v for k, v in params.items()}
    value = str(lowered.get(name.lower(), "")).lower()
    wanted = wanted.lower()
    if value in ("yes", "no"):
        wanted = _yes_no(wanted)
    if op == "~":
        return wanted in value
    hit = fnmatch.fnmatchcase(value, wanted)
    return hit if op == "=" else not hit


def select(sheets, params, filters, known=()):
    """The sheets whose parameters (params: {sheet number: {name: value}}) satisfy every filter
    (strings, or parsed). A filter naming no parameter any sheet has, nor one of `known`, is a
    LookupError listing the names there are: a misspelt name would otherwise match nothing, or all."""
    parsed = [parse(f) if isinstance(f, str) else f for f in filters]
    names = {n.lower(): n for p in params.values() for n in p}
    names.update({n.lower(): n for n in known if n.lower() not in names})
    for name, _op, _value in parsed:
        if name.lower() not in names:
            raise LookupError(f"no sheet parameter named {name!r}; the sheets have: "
                              + ", ".join(sorted({n for p in params.values() for n in p}, key=str.lower)))
    return [s for s in sheets if all(matches(params.get(s.number, {}), f) for f in parsed)]
