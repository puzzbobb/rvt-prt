//! Element meshes for rvt-prt's plan linework, straight from rvt-rs's IFC model: what
//! ifcopenshell made of the `rvt-ifc` export (each element's body in world feet, its openings
//! cut), without the STEP text.
//!
//! Openings: every opening rvt-rs writes is a vertical prism (a door's or window's box, a hosted
//! opening's box, a shaft's outline), and every host it voids a vertical extrusion. The host is
//! cut in bands: its height split at each opening's bottom and top, each band its plan section
//! less the openings active in it (2D, `i_overlay`), the caps between bands what one band has and
//! the next has not. A host whose body is not an extrusion, and an opening cut through a wall's
//! elevation (`WallProfileOpening`), stay uncut and are counted.
use std::collections::HashMap;

use i_overlay::core::fill_rule::FillRule;
use i_overlay::core::overlay_rule::OverlayRule;
use i_overlay::float::single::SingleFloatOverlay;
use rvt::ifc::IfcModel;
use rvt::ifc::body_geometry::{
    Body, Mesh, Placement, Ring, body_mesh, element_body, extrusion_rings,
};
use rvt::ifc::entities::{IfcEntity, PropertyValue};
use rvt::ifc::export_content::{FAMILY_NAME_PROPERTY, TYPE_NAME_PROPERTY};

use crate::ifc_names::IFC_PRODUCTS;

/// One element's mesh and the identity rvt_prt keeps of it (linkgeom's `Item`).
pub struct Element {
    pub class: String,
    pub tag: i64,
    pub family: String,
    pub materials: String,
    /// Row-major 4×4 placement, feet.
    pub matrix: [f64; 16],
    pub verts: Vec<[f64; 3]>,
    pub faces: Vec<[u32; 3]>,
}

#[derive(Default)]
pub struct Stats {
    pub elements: usize,
    pub openings: usize,
    pub hosts_cut: usize,
    /// Hosts with openings whose body is not an extrusion: drawn uncut.
    pub hosts_uncut: usize,
    /// Openings not cut: through a wall's elevation, or with no prism body.
    pub openings_uncut: usize,
}

/// A vertical prism voiding a host: plan outline and z-range, in world feet.
struct Opening {
    outline: Ring,
    z: [f64; 2],
}

/// `name` (`IFCWALL`) as ifcopenshell spells it (`IfcWall`).
fn class_name(upper: &str) -> String {
    IFC_PRODUCTS
        .binary_search_by(|n| n.to_ascii_uppercase().as_str().cmp(upper))
        .map_or_else(|_| upper.to_string(), |i| IFC_PRODUCTS[i].to_string())
}

fn rect(centre: [f64; 2], x: f64, y: f64) -> Ring {
    let ([cx, cy], w, d) = (centre, x / 2.0, y / 2.0);
    vec![
        (cx - w, cy - d),
        (cx + w, cy - d),
        (cx + w, cy + d),
        (cx - w, cy + d),
    ]
}

fn placement_of(ent: &IfcEntity) -> Placement {
    match ent {
        IfcEntity::BuildingElement {
            location_feet,
            rotation_radians,
            ..
        } => Placement::new(*location_feet, *rotation_radians),
        _ => Placement::new(None, None),
    }
}

/// A world point in `p`'s frame.
fn to_local(p: &Placement, q: [f64; 3]) -> [f64; 3] {
    let (dx, dy) = (q[0] - p.origin[0], q[1] - p.origin[1]);
    [
        p.cos * dx + p.sin * dy,
        -p.sin * dx + p.cos * dy,
        q[2] - p.origin[2],
    ]
}

/// The openings voiding each host (by entity index), in world feet, as the STEP writer places them.
fn openings(model: &IfcModel, stats: &mut Stats) -> HashMap<usize, Vec<Opening>> {
    let mut out: HashMap<usize, Vec<Opening>> = HashMap::new();
    let world = |p: &Placement, ring: &Ring, z: [f64; 2]| Opening {
        outline: ring
            .iter()
            .map(|&(x, y)| {
                let q = p.apply([x, y, 0.0]);
                (q[0], q[1])
            })
            .collect(),
        z: [p.origin[2] + z[0], p.origin[2] + z[1]],
    };
    for (idx, ent) in model.entities.iter().enumerate() {
        match ent {
            IfcEntity::BuildingElement {
                ifc_type,
                host_element_index: Some(host),
                extrusion,
                solid_shape,
                representation_map_index,
                ..
            } => {
                let Some(ex) = extrusion else { continue };
                let cut = model.opening_cuts.get(&idx);
                let z = cut
                    .and_then(|c| c.z_range_feet)
                    .map_or([0.0, ex.height_feet], |[z, h]| [z, z + h]);
                let ring = if ifc_type == "IFCOPENINGELEMENT" {
                    if solid_shape.is_some() || representation_map_index.is_some() {
                        stats.openings_uncut += 1;
                        continue;
                    }
                    match cut {
                        Some(c) => Some(rect(c.centre_feet, c.x_dim_feet, c.y_dim_feet)),
                        None => extrusion_rings(ex).map(|(outer, _)| outer),
                    }
                } else {
                    let (x, y) = cut.map_or((ex.width_feet, ex.depth_feet), |c| {
                        (c.x_dim_feet, c.y_dim_feet)
                    });
                    Some(rect(cut.map_or([0.0, 0.0], |c| c.centre_feet), x, y))
                };
                let Some(ring) = ring else { continue };
                out.entry(*host)
                    .or_default()
                    .push(world(&placement_of(ent), &ring, z));
            }
            IfcEntity::VoidOpening {
                host,
                outline_feet,
                depth_feet,
                ..
            } => {
                let Some(h) = model.entities.get(*host) else {
                    continue;
                };
                out.entry(*host).or_default().push(world(
                    &placement_of(h),
                    outline_feet,
                    [0.0, *depth_feet],
                ));
            }
            IfcEntity::WallProfileOpening { .. } => stats.openings_uncut += 1,
            _ => {}
        }
    }
    out
}

type Contour = Vec<[f64; 2]>;
type Shape = Vec<Contour>;

fn signed(c: &Contour) -> f64 {
    (0..c.len())
        .map(|i| {
            let (a, b) = (c[i], c[(i + 1) % c.len()]);
            a[0] * b[1] - b[0] * a[1]
        })
        .sum::<f64>()
        / 2.0
}

/// `c` wound counter-clockwise (`ccw`) or clockwise, for the non-zero fill rule.
fn wound(mut c: Contour, ccw: bool) -> Contour {
    if (signed(&c) > 0.0) != ccw {
        c.reverse();
    }
    c
}

fn ring_contour(r: &Ring) -> Contour {
    r.iter().map(|&(x, y)| [x, y]).collect()
}

fn difference(a: &[Shape], b: &[Shape]) -> Vec<Shape> {
    if a.is_empty() || b.is_empty() {
        return a.to_vec();
    }
    let subject: Vec<Contour> = a.iter().flatten().cloned().collect();
    let clip: Vec<Contour> = b.iter().flatten().cloned().collect();
    subject.overlay(&clip, OverlayRule::Difference, FillRule::NonZero)
}

/// A shape's contours, the outer counter-clockwise and the holes clockwise, closing points dropped.
fn oriented(shape: &Shape) -> Vec<Contour> {
    shape
        .iter()
        .enumerate()
        .filter_map(|(i, c)| {
            let mut c = c.clone();
            while c.len() > 1 && c.first() == c.last() {
                c.pop();
            }
            (c.len() >= 3).then(|| wound(c, i == 0))
        })
        .collect()
}

/// Each shape's face at height `z`, facing up or down (earcut, holes kept).
fn add_cap(mesh: &mut Mesh, shapes: &[Shape], z: f64, up: bool) {
    let mut earcut = earcut::Earcut::new();
    let mut tris: Vec<u32> = Vec::new();
    for shape in shapes {
        let contours = oriented(shape);
        if contours.is_empty() {
            continue;
        }
        let mut holes: Vec<u32> = Vec::new();
        let mut n = 0u32;
        for c in &contours[..contours.len() - 1] {
            n += c.len() as u32;
            holes.push(n);
        }
        let points: Vec<[f64; 2]> = contours.iter().flatten().copied().collect();
        earcut.earcut(points.iter().copied(), &holes, &mut tris);
        let base = mesh.vertices.len() as u32;
        mesh.vertices.extend(points.iter().map(|p| [p[0], p[1], z]));
        for t in tris.chunks_exact(3) {
            let [a, b, c] = [t[0], t[1], t[2]].map(|i| points[i as usize]);
            let ccw = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) > 0.0;
            let (i, j, k) = (base + t[0], base + t[1], base + t[2]);
            mesh.triangles
                .push(if ccw == up { [i, j, k] } else { [i, k, j] });
        }
    }
}

/// Each shape's contours walled from `z0` up to `z1`, facing out of the solid. A wall face is split
/// where a point of `below` (at `z0`) or `above` (at `z1`) lies on its edge: the neighbouring
/// bands' and caps' vertices, so faces meet edge to edge (linkgeom draws an edge with one face).
fn add_sides(
    mesh: &mut Mesh,
    shapes: &[Shape],
    z0: f64,
    z1: f64,
    below: &[[f64; 2]],
    above: &[[f64; 2]],
) {
    for ring in shapes.iter().flat_map(oriented) {
        for i in 0..ring.len() {
            let (a, b) = (ring[i], ring[(i + 1) % ring.len()]);
            let (bot, top) = (on_edge(a, b, below), on_edge(a, b, above));
            let at = |t: f64, z: f64| [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), z];
            let base = mesh.vertices.len() as u32;
            mesh.vertices.extend(bot.iter().map(|&t| at(t, z0)));
            mesh.vertices.extend(top.iter().map(|&t| at(t, z1)));
            let (nb, nt) = (bot.len(), top.len());
            let (bv, tv) = (|i: usize| base + i as u32, |j: usize| base + (nb + j) as u32);
            // zip the two rows into a strip, advancing whichever side's next point comes first
            let (mut i, mut j) = (0, 0);
            while i + 1 < nb || j + 1 < nt {
                if j + 1 == nt || (i + 1 < nb && bot[i + 1] <= top[j + 1]) {
                    mesh.triangles.push([bv(i), bv(i + 1), tv(j)]);
                    i += 1;
                } else {
                    mesh.triangles.push([bv(i), tv(j + 1), tv(j)]);
                    j += 1;
                }
            }
        }
    }
}

/// The parameters along `a`→`b` of the points lying on it, with 0 and 1, sorted.
fn on_edge(a: [f64; 2], b: [f64; 2], points: &[[f64; 2]]) -> Vec<f64> {
    let (dx, dy) = (b[0] - a[0], b[1] - a[1]);
    let len2 = dx * dx + dy * dy;
    let mut ts = vec![0.0, 1.0];
    if len2 > 0.0 {
        let len = len2.sqrt();
        for p in points {
            let (px, py) = (p[0] - a[0], p[1] - a[1]);
            let t = (px * dx + py * dy) / len2;
            if (px * dy - py * dx).abs() / len < 1e-6 && t * len > 1e-6 && (1.0 - t) * len > 1e-6 {
                ts.push(t);
            }
        }
    }
    ts.sort_by(f64::total_cmp);
    ts.dedup_by(|x, y| (*x - *y).abs() < 1e-9);
    ts
}

fn vertices(shapes: &[Shape]) -> Vec<[f64; 2]> {
    shapes.iter().flatten().flatten().copied().collect()
}

/// The extruded host (`outer` less `holes`, from 0 up `height`, local feet) with the openings
/// (local plan outline, local z-range) cut out.
fn cut_extrusion(
    outer: &Ring,
    holes: &[Ring],
    height: f64,
    openings: &[(Contour, [f64; 2])],
) -> Mesh {
    let mut host: Shape = vec![wound(ring_contour(outer), true)];
    host.extend(holes.iter().map(|h| wound(ring_contour(h), false)));
    let host = vec![host];
    let mut breaks: Vec<f64> = vec![0.0, height];
    for (_, [z0, z1]) in openings {
        breaks.extend([z0.clamp(0.0, height), z1.clamp(0.0, height)]);
    }
    breaks.sort_by(f64::total_cmp);
    breaks.dedup_by(|a, b| (*a - *b).abs() < 1e-9);
    // bands: (bottom, top, section), consecutive bands with the same openings merged
    let mut bands: Vec<(f64, f64, Vec<usize>)> = Vec::new();
    for w in breaks.windows(2) {
        let mid = (w[0] + w[1]) / 2.0;
        let active: Vec<usize> = (0..openings.len())
            .filter(|&i| openings[i].1[0] < mid && mid < openings[i].1[1])
            .collect();
        match bands.last_mut() {
            Some(last) if last.2 == active => last.1 = w[1],
            _ => bands.push((w[0], w[1], active)),
        }
    }
    let sections: Vec<Vec<Shape>> = bands
        .iter()
        .map(|(_, _, active)| {
            let clip: Vec<Shape> = active
                .iter()
                .map(|&i| vec![wound(openings[i].0.clone(), true)])
                .collect();
            difference(&host, &clip)
        })
        .collect();
    // caps[k]: the faces at the top of band k, up and down; and every vertex at that height
    let caps: Vec<(Vec<Shape>, Vec<Shape>)> = (0..bands.len())
        .map(|k| match sections.get(k + 1) {
            Some(next) => (difference(&sections[k], next), difference(next, &sections[k])),
            None => (sections[k].clone(), Vec::new()),
        })
        .collect();
    let level: Vec<Vec<[f64; 2]>> = (0..bands.len())
        .map(|k| {
            let mut v = vertices(&sections[k]);
            v.extend(sections.get(k + 1).map(|s| vertices(s)).unwrap_or_default());
            v.extend(vertices(&caps[k].0));
            v.extend(vertices(&caps[k].1));
            v
        })
        .collect();
    let base = vertices(&sections[0]);
    let mut mesh = Mesh::default();
    for (k, (z0, z1, _)) in bands.iter().enumerate() {
        let below = if k == 0 { &base } else { &level[k - 1] };
        add_sides(&mut mesh, &sections[k], *z0, *z1, below, &level[k]);
        if k == 0 {
            add_cap(&mut mesh, &sections[0], *z0, false);
        }
        add_cap(&mut mesh, &caps[k].0, *z1, true);
        add_cap(&mut mesh, &caps[k].1, *z1, false);
    }
    mesh
}

/// `mesh` with coincident vertices shared (so linkgeom's sharp edges see faces meet) and
/// triangles that collapse dropped.
fn weld(mesh: Mesh) -> Mesh {
    let mut out = Mesh::default();
    let mut seen: HashMap<[i64; 3], u32> = HashMap::new();
    let remap: Vec<u32> = mesh
        .vertices
        .iter()
        .map(|v| {
            let key = v.map(|c| (c * 1e7).round() as i64);
            *seen.entry(key).or_insert_with(|| {
                out.vertices.push(*v);
                out.vertices.len() as u32 - 1
            })
        })
        .collect();
    out.triangles = mesh
        .triangles
        .iter()
        .map(|t| t.map(|i| remap[i as usize]))
        .filter(|[a, b, c]| a != b && b != c && a != c)
        .collect();
    out
}

fn materials(model: &IfcModel, idx: usize, ent: &IfcEntity) -> String {
    let IfcEntity::BuildingElement {
        material_index,
        material_layer_set_index,
        material_profile_set_index,
        ..
    } = ent
    else {
        return String::new();
    };
    let name = |i: usize| model.materials.get(i).map(|m| m.name.clone());
    if material_profile_set_index.is_some_and(|i| i < model.material_profile_sets.len()) {
        return String::new(); // ifcopenshell's IfcMaterialProfileSetUsage has no name
    }
    if let Some(set) = material_layer_set_index.and_then(|i| model.material_layer_sets.get(i)) {
        return set
            .layers
            .iter()
            .filter_map(|l| l.material_index.and_then(name))
            .collect::<Vec<_>>()
            .join("|");
    }
    if let Some(m) = *material_index {
        return name(m).unwrap_or_default();
    }
    model
        .material_constituent_sets
        .iter()
        .find(|s| s.elements.contains(&idx))
        .map(|s| {
            s.material_indices
                .iter()
                .filter_map(|&i| name(i))
                .collect::<Vec<_>>()
                .join("|")
        })
        .unwrap_or_default()
}

fn family(ent: &IfcEntity) -> String {
    let IfcEntity::BuildingElement {
        property_set: Some(set),
        ..
    } = ent
    else {
        return String::new();
    };
    let text = |key: &str| {
        set.properties.iter().find_map(|p| match &p.value {
            PropertyValue::Text(t) if p.name == key => Some(t.clone()),
            _ => None,
        })
    };
    match (text(FAMILY_NAME_PROPERTY), text(TYPE_NAME_PROPERTY)) {
        (Some(f), Some(_)) => f.split(':').next().unwrap_or_default().to_string(),
        _ => String::new(),
    }
}

/// Every building element with a body, its openings cut, in world feet.
pub fn element_meshes(model: &IfcModel) -> (Vec<Element>, Stats) {
    let mut stats = Stats::default();
    let mut voids = openings(model, &mut stats);
    stats.openings = voids.values().map(Vec::len).sum::<usize>() + stats.openings_uncut;
    let mut out = Vec::new();
    for (idx, ent) in model.entities.iter().enumerate() {
        let IfcEntity::BuildingElement {
            ifc_type,
            type_guid,
            ..
        } = ent
        else {
            continue;
        };
        if ifc_type == "IFCOPENINGELEMENT" {
            continue;
        }
        let Some(body) = element_body(ent, &model.representation_maps) else {
            continue;
        };
        let p = placement_of(ent);
        let mesh = match (voids.remove(&idx), body) {
            (Some(ops), Body::Extrusion(ex))
                if ex.height_feet.is_finite() && ex.height_feet > 0.0 =>
            {
                match extrusion_rings(ex) {
                    Some((outer, holes)) => {
                        stats.hosts_cut += 1;
                        let local: Vec<(Contour, [f64; 2])> = ops
                            .iter()
                            .map(|o| {
                                let c = o
                                    .outline
                                    .iter()
                                    .map(|&(x, y)| {
                                        let q = to_local(&p, [x, y, 0.0]);
                                        [q[0], q[1]]
                                    })
                                    .collect();
                                (c, [o.z[0] - p.origin[2], o.z[1] - p.origin[2]])
                            })
                            .collect();
                        Some(cut_extrusion(&outer, &holes, ex.height_feet, &local))
                    }
                    None => None,
                }
            }
            (ops, body) => {
                stats.hosts_uncut += ops.is_some() as usize;
                body_mesh(body)
            }
        };
        let Some(mesh) = mesh.map(weld).filter(|m| !m.triangles.is_empty()) else {
            continue;
        };
        let tag = type_guid
            .as_deref()
            .filter(|t| !t.is_empty() && t.bytes().all(|b| b.is_ascii_digit()));
        out.push(Element {
            class: class_name(ifc_type),
            tag: tag.and_then(|t| t.parse().ok()).unwrap_or(0),
            family: family(ent),
            materials: materials(model, idx, ent),
            matrix: [
                p.cos,
                -p.sin,
                0.0,
                p.origin[0],
                p.sin,
                p.cos,
                0.0,
                p.origin[1],
                0.0,
                0.0,
                1.0,
                p.origin[2],
                0.0,
                0.0,
                0.0,
                1.0,
            ],
            verts: mesh.vertices.iter().map(|&v| p.apply(v)).collect(),
            faces: mesh.triangles,
        });
    }
    stats.elements = out.len();
    (out, stats)
}
