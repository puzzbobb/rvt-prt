"""View filters (ParameterFilterElement) and the filters a view hides, from the records'
object graphs (channel 102).

- ParameterFilterElement: m_name; m_oCategoryRule -> FilterCategoryRule.m_categories; its rules
  are the FilterStringRule objects of its graph (m_ruleString; m_oValueProvider ->
  ParameterValueProvider.m_parameter, a BuiltInParameter such as -1140325
  RBS_SYSTEM_CLASSIFICATION_PARAM; m_oEvaluator, whose class is the test: FilterStringContains,
  BeginsWith, EndsWith, Equals).
- A view lists its filters in FilterOverrides.m_oaSettings -> FilterGraphicSettings
  (m_filterElemId, m_bVisibilityFlag, m_bEnabledFlag). Snowdon's HVAC views hide Domestic,
  Sanitary and Vent: those piping systems are not printed, linked or not.
An element matches a filter when its category is one of the filter's and its parameter value
satisfies the rule; the value of the system classification is taken from its system type's name.
"""
import functools
from dataclasses import dataclass, field

SYSTEM_CLASSIFICATION = -1140325  # BuiltInParameter RBS_SYSTEM_CLASSIFICATION_PARAM
OPS = {"FilterStringContains": lambda v, s: s.lower() in v.lower(),
       "FilterStringBeginsWith": lambda v, s: v.lower().startswith(s.lower()),
       "FilterStringEndsWith": lambda v, s: v.lower().endswith(s.lower()),
       "FilterStringEquals": lambda v, s: v.lower() == s.lower()}


@dataclass
class Filter:
    element_id: int
    name: str
    categories: frozenset
    rules: list = field(default_factory=list)  # [(parameter id, operator class name, string)], every string rule
    tree: tuple | None = None  # ("and" | "or", inverted, [nodes]); ("not", node); ("rule", param, op, value)

    def matches(self, category, classification):
        """True when an element of `category` whose system classification is `classification`
        passes the filter's rules (a filter without rules matches every element of its
        categories). A rule on a parameter not evaluated here is unknown, and a filter whose
        result is unknown does not match: no match rather than a guess."""
        if category not in self.categories:
            return False
        if self.tree is None:
            return True
        return _evaluate(self.tree, {SYSTEM_CLASSIFICATION: classification}) is True


def _evaluate(node, values):
    """True, False or None (unknown) for a rule tree, given {parameter id: string value}."""
    kind = node[0]
    if kind == "rule":
        _k, param, op, value = node
        if param not in values or values[param] is None or op not in OPS:
            return None
        return OPS[op](values[param], value)
    if kind == "not":
        r = _evaluate(node[1], values)
        return None if r is None else not r
    _k, inverted, children = node
    results = [_evaluate(c, values) for c in children]
    if kind == "and":
        r = False if False in results else (None if None in results else True)
    else:
        r = True if True in results else (None if None in results else False)
    return r if r is None or not inverted else not r


def _node(g, i):
    """The rule tree of object i of a ParameterFilterElement's graph."""
    o = g.objects[i]
    f = o.fields
    targets = lambda key: [t for p in (f.get(key) or []) if (t := g.target(i, p)) is not None]
    if o.name in ("LogicalAndFilterData", "LogicalOrFilterData"):
        return ("and" if "And" in o.name else "or", bool(f.get("m_inverted")), [_node(g, t) for t in targets("m_filters")])
    if o.name == "ElementParameterFilterData":
        return ("and", bool(f.get("m_inverted")), [_node(g, t) for t in targets("m_rules")])
    if o.name == "FilterInverseRule":
        inner = g.target(i, f.get("m_oInnerRule"))
        return ("not", _node(g, inner)) if inner is not None else ("rule", None, "?", None)
    provider, evaluator = g.target(i, f.get("m_oValueProvider")), g.target(i, f.get("m_oEvaluator"))
    param = g.objects[provider].fields.get("m_parameter") if provider is not None else None
    param = param["m_id"]["m_id64"] if isinstance(param, dict) else None
    value = f.get("m_ruleString", f.get("m_ruleValue"))
    return ("rule", param, g.objects[evaluator].name if evaluator is not None else "?", value)


def _filter(eid, g):
    f = g.objects[0].fields
    cats = next((frozenset(c["m_id"]["m_id64"] for c in o.fields.get("m_categories", []))
                 for o in g.objects if o.name == "FilterCategoryRule"), frozenset())
    combination = g.target(0, f.get("m_oRuleCombination"))
    tree = _node(g, combination) if combination is not None else None
    rules = []

    def collect(n):
        if n[0] == "rule":
            rules.append(n[1:])
        elif n[0] == "not":
            collect(n[1])
        else:
            for c in n[2]:
                collect(c)
    if tree is not None:
        collect(tree)
    if tree is not None and not rules:
        tree = None
    return Filter(eid, f.get("m_name", ""), cats, rules, tree)


@functools.cache
def read(rf, path):
    """{filter id: Filter}."""
    from ..core import objgraph
    return {eid: _filter(eid, g) for eid, g in objgraph.elements(path, ("ParameterFilterElement",))}


MODULES = ("filters", "objgraph", "registry")


def _disk(name, fn):
    @functools.cache
    def wrapper(rf, path):
        from ..core import diskcache
        return diskcache.cached(path, name, MODULES, lambda: fn(rf, path))
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _all_hidden_in_view(rf, path):
    from ..core import objgraph
    fs = read(rf, path)
    out = {}
    for eid, g in objgraph.elements(path, ("DBView*",)):
        res = []
        for o in g.objects:
            if o.name == "FilterGraphicSettings":
                fid = objgraph.ref(o.fields.get("m_filterElemId"))
                if fid in fs and not o.fields.get("m_bVisibilityFlag") and o.fields.get("m_bEnabledFlag") and fs[fid] not in res:
                    res.append(fs[fid])
        if res:
            out[eid] = res
    return out


all_hidden_in_view = _disk("hidden_filters", _all_hidden_in_view)


def hidden_in_view(rf, path, view_id):
    """The filters a view (or template) hides: its entries with visible = 0."""
    if view_id is None:
        return []
    return all_hidden_in_view(rf, path).get(view_id, [])


def hidden(filters, category, classification):
    """True when any of the (hidden) filters matches the element."""
    return any(f.matches(category, classification) for f in filters)
