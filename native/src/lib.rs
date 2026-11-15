//! rvt-prt's native extension, `rvt_prt._native`: rvt-rs's IFC export in-process, in place of
//! the `rvt-ifc` binary. Each call releases the GIL while rvt-rs works.
use pyo3::exceptions::{PyIOError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};
use rvt::RevitFile;
use rvt::ifc::{ExportQualityMode, RvtDocExporter, recount_exported, saved_meshes, write_step};
use rvt::walker::WalkerLimits;

mod ifc_names;
mod mesh;

/// The Revit releases whose element records (and so geometry) rvt-rs reads.
const GEOMETRY_RELEASES: std::ops::RangeInclusive<u32> = 2014..=2027;

fn io_err(e: impl std::fmt::Display) -> PyErr {
    PyIOError::new_err(e.to_string())
}

fn val_err(e: impl std::fmt::Display) -> PyErr {
    PyValueError::new_err(e.to_string())
}

/// Export `path` as IFC4 to `out`, as `rvt-ifc path -o out [--saved-meshes]` does; return the
/// export diagnostics as JSON.
#[pyfunction]
#[pyo3(signature = (path, out, saved_meshes = false))]
fn export_ifc(py: Python<'_>, path: &str, out: &str, saved_meshes: bool) -> PyResult<String> {
    py.detach(|| {
        let mut rf = RevitFile::open(path).map_err(io_err)?;
        let result = RvtDocExporter
            .export_with_diagnostics_mode_and_limits(
                &mut rf,
                ExportQualityMode::Scaffold,
                WalkerLimits::default(),
            )
            .map_err(val_err)?;
        let (mut model, mut diagnostics) = (result.model, result.diagnostics);
        // The saved graphics only improve bodies: when they cannot be read, the bodies stay.
        if saved_meshes && saved_meshes::attach(&mut rf, &mut model).is_ok() {
            recount_exported(&mut diagnostics, &model);
        }
        std::fs::write(out, write_step(&model)).map_err(io_err)?;
        serde_json::to_string(&diagnostics).map_err(val_err)
    })
}

/// Every building element's mesh in `path`, its openings cut, in world feet: the arrays of
/// linkgeom's `.npz` cache as bytes (`verts` f64 ×3, `faces` i32 ×3 indexing the element's own
/// vertices, `index` i64 (v0, v1, f0, f1), `matrices` f64 ×16 row-major), the per-element lists
/// `classes`, `tags`, `families`, `materials`, and `stats`.
///
/// rvt-rs's export shows one phase, the project's last, and leaves out an element that does not
/// exist in it (#1074, RE-184): the Facades link's walls demolished in New Construction, which
/// Snowdon's ceiling plans draw. rvt_prt shows each view's own phase, so it names the earlier
/// `phases` (ElementIds as text, or names) where such elements exist: each is exported too, and
/// the elements it has that the last phase's export has not are added.
#[pyfunction]
#[pyo3(signature = (path, phases = Vec::new()))]
fn element_meshes<'py>(py: Python<'py>, path: &str, phases: Vec<String>) -> PyResult<Bound<'py, PyDict>> {
    let (elements, stats) = py.detach(|| -> PyResult<_> {
        let mut rf = RevitFile::open(path).map_err(io_err)?;
        // the model alone: the export's diagnostics are not used here
        let export = |rf: &mut RevitFile| {
            RvtDocExporter
                .export_with_mode_and_limits(rf, ExportQualityMode::Scaffold, WalkerLimits::default())
                .map_err(val_err)
        };
        let model = export(&mut rf)?;
        let (mut elements, mut stats) = mesh::element_meshes(&model);
        drop(model);
        if !phases.is_empty() {
            let mut seen: std::collections::HashSet<i64> = elements.iter().map(|e| e.tag).collect();
            for phase in &phases {
                // a phase the file does not list, or one its release cannot choose: skipped
                if rf.set_export_phase(phase).is_err() {
                    continue;
                }
                let model = export(&mut rf)?;
                let (more, _) = mesh::element_meshes(&model);
                for e in more {
                    if seen.insert(e.tag) {
                        elements.push(e);
                        stats.elements += 1;
                    }
                }
            }
            rf.clear_export_phase();
        }
        Ok((elements, stats))
    })?;
    let (mut verts, mut faces, mut index, mut matrices) =
        (Vec::new(), Vec::new(), Vec::new(), Vec::new());
    let (mut vo, mut fo) = (0i64, 0i64);
    for e in &elements {
        verts.extend(e.verts.iter().flatten().flat_map(|c| c.to_le_bytes()));
        faces.extend(
            e.faces
                .iter()
                .flatten()
                .flat_map(|&i| (i as i32).to_le_bytes()),
        );
        let (nv, nf) = (e.verts.len() as i64, e.faces.len() as i64);
        index.extend(
            [vo, vo + nv, fo, fo + nf]
                .iter()
                .flat_map(|i| i.to_le_bytes()),
        );
        matrices.extend(e.matrix.iter().flat_map(|c| c.to_le_bytes()));
        (vo, fo) = (vo + nv, fo + nf);
    }
    let d = PyDict::new(py);
    d.set_item("verts", PyBytes::new(py, &verts))?;
    d.set_item("faces", PyBytes::new(py, &faces))?;
    d.set_item("index", PyBytes::new(py, &index))?;
    d.set_item("matrices", PyBytes::new(py, &matrices))?;
    d.set_item(
        "classes",
        elements
            .iter()
            .map(|e| e.class.as_str())
            .collect::<Vec<_>>(),
    )?;
    d.set_item("tags", elements.iter().map(|e| e.tag).collect::<Vec<_>>())?;
    d.set_item(
        "families",
        elements
            .iter()
            .map(|e| e.family.as_str())
            .collect::<Vec<_>>(),
    )?;
    d.set_item(
        "materials",
        elements
            .iter()
            .map(|e| e.materials.as_str())
            .collect::<Vec<_>>(),
    )?;
    let s = PyDict::new(py);
    s.set_item("elements", stats.elements)?;
    s.set_item("openings", stats.openings)?;
    s.set_item("hosts_cut", stats.hosts_cut)?;
    s.set_item("hosts_uncut", stats.hosts_uncut)?;
    s.set_item("openings_uncut", stats.openings_uncut)?;
    d.set_item("stats", s)?;
    Ok(d)
}

/// What rvt_prt can read from `path`: its Revit version and build, and whether rvt-rs reads its
/// geometry. Reads only the identity streams.
#[pyfunction]
fn capabilities<'py>(py: Python<'py>, path: &str) -> PyResult<Bound<'py, PyDict>> {
    let m = py
        .detach(|| rvt::metadata::read_metadata(path))
        .map_err(io_err)?;
    let d = PyDict::new(py);
    d.set_item("revit_version", m.revit_version)?;
    d.set_item("build", m.build)?;
    d.set_item("geometry", GEOMETRY_RELEASES.contains(&m.revit_version))?;
    Ok(d)
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(export_ifc, m)?)?;
    m.add_function(wrap_pyfunction!(capabilities, m)?)?;
    m.add_function(wrap_pyfunction!(element_meshes, m)?)?;
    m.add(
        "GEOMETRY_RELEASES",
        (*GEOMETRY_RELEASES.start(), *GEOMETRY_RELEASES.end()),
    )?;
    Ok(())
}
