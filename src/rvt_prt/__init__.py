"""rvt-prt: print Autodesk Revit (.rvt) sheets to vector PDF, straight from the file.

The public API is what this module exports: `RevitModel` (open a model, list its sheets, print
them), the errors it raises (`UnsupportedFile`, `NoSheets`) and `__version__`. Everything else
in the package is internal and may change between releases.
"""
from importlib import metadata as _metadata

from .api import NoSheets, RevitModel
from .core.container import UnsupportedFile

try:
    __version__ = _metadata.version("rvt-prt")
except _metadata.PackageNotFoundError:  # run from a source tree that was never installed
    __version__ = "0.1.0"

__all__ = ["NoSheets", "RevitModel", "UnsupportedFile", "__version__"]
