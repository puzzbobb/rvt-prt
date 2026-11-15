"""Linked Revit models: which files a model links, where they sit, and the files themselves.

Read from the records' object graphs (channel 102):
- RvtLinkSymbol, the link type: SymbolInfo.m_name is the linked file's name ("Snowdon Towers
  Sample Architectural.rvt"); m_otherDocModelLocation.m_lastKnownModelPath.m_path its path
  relative to the model; m_phaseMap pairs each of the model's phases (`first`) with the link's
  (`second`).
- RvtLinkInstance: m_name ("Architecture") and InstanceInfo (`m_symbolId`, its type; `m_Trf`,
  the placement: `m_3x3` applied as a matrix, its columns the link's X, Y and Z axes, and
  `m_or` the link's origin, in the model's feet).

Link files are looked up by name beside the model, then in a `links/` folder beside it, then in
the folder `RVT_PRT_LINKS` names, then in `links/` beside this package (a development layout).
"""
import functools
import os
import pathlib
from dataclasses import dataclass
from ..core import paths

LINK_DIR = paths.LINKS  # a checkout's links/, searched last (None installed)


def file_name_alone(name):
    """Whether `name` is a file name and no path, on any system."""
    return bool(name) and name == pathlib.PurePosixPath(name).name == pathlib.PureWindowsPath(name).name


@dataclass
class Link:
    instance_id: int
    type_id: int
    name: str  # instance name ("Architecture")
    file_name: str  # "Snowdon Towers Sample Architectural.rvt"
    origin: tuple = (0.0, 0.0, 0.0)
    axes: tuple = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    folder: pathlib.Path | None = None  # the linking model's folder
    phase_map: dict | None = None  # {link phase id: model phase id} (RvtLinkSymbol.m_phaseMap)

    halftone = True  # Revit's default display for a link in a host view (By Host View: halftone not decoded)

    @property
    def folders(self):
        """Where the linked file is looked for, in order: beside the model, in `links/` beside it,
        in `RVT_PRT_LINKS`, in `links/` beside this package."""
        folders = []
        if self.folder is not None:
            folders += [self.folder, self.folder / "links"]
        if os.environ.get("RVT_PRT_LINKS"):
            folders.append(pathlib.Path(os.environ["RVT_PRT_LINKS"]))
        if LINK_DIR is not None:
            folders.append(LINK_DIR)
        return folders

    @property
    def path(self):
        """The linked file, from the first of `folders` holding it; None when not found."""
        return next((f / self.file_name for f in self.folders if (f / self.file_name).exists()), None)


@dataclass
class Host:
    """The open model itself, as a source of model geometry beside its links: in its own
    coordinates and printed in full pen (a link is placed and halftone)."""
    path: pathlib.Path
    origin: tuple = (0.0, 0.0, 0.0)
    axes: tuple = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    halftone = False

    @property
    def file_name(self):
        return self.path.name


@functools.cache
def read(rf, path):
    """The model's links, in element id order (Link)."""
    from ..core import objgraph
    files, instances = {}, []
    for eid, g in objgraph.elements(path, ("RvtLinkSymbol", "RvtLinkInstance")):
        objs = {o.name: o.fields for o in g.objects}
        if g.objects[0].name == "RvtLinkSymbol":
            name = (objs.get("SymbolInfo") or {}).get("m_name", "")
            # a file name alone: one naming a folder ("../x.rvt", "/srv/x.rvt", "C:\\x.rvt") would
            # have the print open a file outside the folders linked models are looked for in
            if name.lower().endswith(".rvt") and file_name_alone(name):
                pm = g.objects[0].fields.get("m_phaseMap", [])
                files[eid] = (name, {e["second"]["m_id64"]: e["first"]["m_id"]["m_id64"] for e in pm})
        elif "InstanceInfo" in objs:
            info = objs["InstanceInfo"]
            instances.append((eid, g.objects[0].fields.get("m_name", ""), info["m_symbolId"]["m_id"]["m_id64"],
                              info["m_Trf"]))
    out = []
    for eid, name, type_id, trf in instances:
        if type_id not in files:
            continue
        m = trf["m_3x3"]
        axes = tuple(tuple(float(m[r][c]) for r in range(3)) for c in range(3))
        file_name, phase_map = files[type_id]
        out.append(Link(eid, type_id, name, file_name, tuple(float(x) for x in trf["m_or"]), axes,
                        folder=pathlib.Path(path).resolve().parent, phase_map=phase_map))
    return out
