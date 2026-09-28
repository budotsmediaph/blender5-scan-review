"""Blender 5 batch converter + CAD-likeness analyzer for scan assets.

Run:  blender -b --factory-startup -P convert_analyze.py -- --src FILE --kind KIND --name NAME --out OUTDIR [--up auto|y|z|keep]
KIND: pcd (Open3D/xyz+rgb PLY), splat (3D Gaussian Splat PLY), glb, msmesh (Metashape model.zip), las, blend
Writes: OUTDIR/blend/NAME.blend, OUTDIR/previews/NAME_*.png, OUTDIR/analysis/NAME.json
"""
import bpy, bmesh, sys, os, json, time, math, zipfile, argparse
import numpy as np
from mathutils import Vector, Matrix

argv = sys.argv[sys.argv.index("--") + 1:]
ap = argparse.ArgumentParser()
ap.add_argument("--src"); ap.add_argument("--kind"); ap.add_argument("--name"); ap.add_argument("--out")
ap.add_argument("--up", default="auto"); ap.add_argument("--tmp", default="/tmp")
ap.add_argument("--max_display", type=int, default=3_000_000)
A = ap.parse_args(argv)
T0 = time.time()
info = {"name": A.name, "src": A.src, "kind": A.kind}
for d in ("blend", "previews", "analysis"):
    os.makedirs(os.path.join(A.out, d), exist_ok=True)


def log(*a):
    print(f"[{time.time()-T0:6.1f}s]", *a, flush=True)


# ---------------------------------------------------------------- PLY / LAS readers
PLY_T = {"char": "i1", "uchar": "u1", "short": "i2", "ushort": "u2", "int": "i4", "uint": "u4",
         "float": "f4", "double": "f8", "int8": "i1", "uint8": "u1", "int16": "i2", "uint16": "u2",
         "int32": "i4", "uint32": "u4", "float32": "f4", "float64": "f8"}


def read_ply_vertices(path):
    with open(path, "rb") as f:
        hdr = b""
        while not hdr.endswith(b"end_header\n"):
            hdr += f.readline()
        off = f.tell()
    lines = hdr.decode("ascii", "ignore").splitlines()
    assert "binary_little_endian" in lines[1], lines[1]
    props, n, cur = [], 0, None
    comments = [l for l in lines if l.startswith("comment")]
    for l in lines:
        p = l.split()
        if p[0] == "element":
            cur = p[1]
            if cur == "vertex":
                n = int(p[2])
        elif p[0] == "property" and cur == "vertex":
            props.append((p[2], "<" + PLY_T[p[1]]))
    v = np.fromfile(path, dtype=np.dtype(props), count=n, offset=off)
    return v, comments


def read_las(path):
    b = open(path, "rb").read(375)
    off = int.from_bytes(b[96:100], "little"); fmt = b[104] & 0x3F
    rlen = int.from_bytes(b[105:107], "little"); n = int.from_bytes(b[107:111], "little")
    sc = np.frombuffer(b[131:155], "<f8"); of = np.frombuffer(b[155:179], "<f8")
    raw = np.fromfile(path, dtype=np.uint8, count=n * rlen, offset=off).reshape(n, rlen)
    xyz = raw[:, :12].copy().view("<i4").astype(np.float64) * sc + of
    rgb_off = {2: 20, 3: 28, 5: 28, 7: 30, 8: 30}.get(fmt)
    col = None
    if rgb_off:
        c = raw[:, rgb_off:rgb_off + 6].copy().view("<u2").astype(np.float64)
        col = np.clip(c / (65535.0 if c.max() > 255 else 255.0), 0, 1)
    info["las_format"] = int(fmt)
    return xyz, col


def srgb_to_lin(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


# ---------------------------------------------------------------- geometry analysis
def orient(P, mode):
    """Return rotation matrix R (3x3) so that P @ R.T is Z-up."""
    if mode == "keep" or mode == "z":
        return np.eye(3), "kept Z-up"
    if mode == "y":  # Y-up -> Z-up  (x, y, z) -> (x, -z, y)
        return np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float), "Y-up converted to Z-up"
    if mode == "-y":  # Y-down (COLMAP style) -> Z-up
        return np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float), "Y-down converted to Z-up"
    # auto: smallest PCA axis = up, sign by skewness (structures stick up from ground)
    S = P[np.random.default_rng(0).choice(len(P), min(len(P), 300_000), replace=False)]
    C = S - S.mean(0)
    w, V = np.linalg.eigh(np.cov(C.T))
    up = V[:, 0]
    h = C @ up
    if ((h - h.mean()) ** 3).mean() < 0:
        up = -up
    x = V[:, 2]
    y = np.cross(up, x)
    R = np.stack([x, y, up])
    if np.linalg.det(R) < 0:
        R[1] = -R[1]
    return R, f"auto PCA (eigen ratios {w[0]/w[2]:.3f}, {w[1]/w[2]:.3f})"


def trim(P, lo=0.5, hi=99.5, pad=0.1):
    a = np.percentile(P, lo, axis=0); b = np.percentile(P, hi, axis=0); d = (b - a) * pad
    return np.all((P >= a - d) & (P <= b + d), axis=1)


def voxel_features(P, v_fixed=None):
    ext = P.max(0) - P.min(0); diag = float(np.linalg.norm(ext))
    v = diag / 256
    Pc = P - P.min(0)
    for _ in range(0 if v_fixed else 4):  # adapt voxel size so occupied voxels hold ~25 pts
        k = np.floor(Pc / v).astype(np.int64)
        dims = k.max(0) + 1
        lin = (k[:, 0] * dims[1] + k[:, 1]) * dims[2] + k[:, 2]
        _, inv0, cnt = np.unique(lin, return_inverse=True, return_counts=True)
        med = np.median(cnt[inv0])  # point-weighted: occupancy seen by a typical point
        if 18 <= med <= 40: break
        v *= math.sqrt(25.0 / max(med, 1))
    if v_fixed: v = v_fixed
    k = np.floor(Pc / v).astype(np.int64); dims = k.max(0) + 1
    lin = (k[:, 0] * dims[1] + k[:, 1]) * dims[2] + k[:, 2]
    uniq, inv, cnt = np.unique(lin, return_inverse=True, return_counts=True)
    m = len(uniq)
    S1 = np.stack([np.bincount(inv, Pc[:, i], m) for i in range(3)], 1)
    mean = S1 / cnt[:, None]
    cov = np.empty((m, 3, 3))
    for i in range(3):
        for j in range(i, 3):
            s = np.bincount(inv, Pc[:, i] * Pc[:, j], m) / cnt - mean[:, i] * mean[:, j]
            cov[:, i, j] = cov[:, j, i] = s
    ok = cnt >= 10
    w, V = np.linalg.eigh(cov[ok])          # ascending
    w = np.clip(w, 1e-12, None)
    l3, l2, l1 = w[:, 0], w[:, 1], w[:, 2]
    planarity = (l2 - l3) / l1; linearity = (l1 - l2) / l1; scatter = l3 / l1
    nrm = V[:, :, 0]; wt = cnt[ok].astype(float)
    flat = (scatter < 0.03) & (planarity > 0.5)
    nz = np.abs(nrm[:, 2])
    wall = flat & (nz < 0.26); horiz = flat & (nz > 0.97)
    res = {
        "voxel_size": float(v), "voxels": int(ok.sum()),
        "flat_frac": float(wt[flat].sum() / wt.sum()),
        "linear_frac": float(wt[(linearity > 0.7)].sum() / wt.sum()),
        "median_scatter": float(np.median(scatter)),
        "wall_frac_of_flat": float(wt[wall].sum() / max(wt[flat].sum(), 1)),
        "horiz_frac_of_flat": float(wt[horiz].sum() / max(wt[flat].sum(), 1)),
    }
    nonh = nz < 0.9
    res["flat_frac_nonhoriz"] = float(wt[flat & nonh].sum() / max(wt[nonh].sum(), 1))
    if wall.sum() > 20:  # orthogonality of wall azimuths (Manhattan-world score, 0=random, 1=perfect grid)
        az = np.arctan2(nrm[wall, 1], nrm[wall, 0])
        z = (wt[wall] * np.exp(4j * az)).sum() / wt[wall].sum()
        res["wall_orthogonality"] = float(abs(z))
    else:
        res["wall_orthogonality"] = 0.0
    return res


def ransac_planes(P, v, n_planes=12, iters=400, sample=120_000):
    rng = np.random.default_rng(1)
    S = P[rng.choice(len(P), min(sample, len(P)), replace=False)]
    remaining = np.ones(len(S), bool); thr = 0.6 * v; covers = []; normals = []
    for _ in range(n_planes):
        idx = np.flatnonzero(remaining)
        if len(idx) < 500: break
        Q = S[idx]
        tri = Q[rng.integers(0, len(Q), (iters, 3))]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        nn = np.linalg.norm(n, axis=1); good = nn > 1e-12
        n = n[good] / nn[good, None]; d = -(n * tri[good, 0]).sum(1)
        sub = Q[rng.choice(len(Q), min(20000, len(Q)), replace=False)]
        score = (np.abs(sub @ n.T + d) < thr).sum(0)
        b = int(np.argmax(score))
        inl = np.abs(Q @ n[b] + d[b]) < thr
        covers.append(inl.sum() / len(S)); normals.append(n[b].tolist())
        remaining[idx[inl]] = False
    covers = np.array(covers)
    return {"plane_cover_top12": float(covers.sum()),
            "plane_cover_excl_largest": float(covers.sum() - (covers.max() if len(covers) else 0)),
            "largest_plane": float(covers.max() if len(covers) else 0),
            "plane_normals_z": [round(abs(n[2]), 2) for n in normals]}


def cad_score(g):
    """0-100 heuristic 'man-made grid' score.
    70%: are vertical surfaces aligned to an orthogonal grid at 4x voxel scale (buildings, pools, roads)?
    30%: fraction of the scan that stays planar at 4x scale. Validated against visual review:
    urban/built scenes 50-85, beaches/reefs/karst 5-45."""
    c = g["coarse"]
    return round(100 * (0.7 * c["wall_orthogonality"] + 0.3 * c["flat_frac"]), 1)


# ---------------------------------------------------------------- scene helpers
def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.eevee.taa_render_samples = 16
    sc.view_settings.view_transform = "Standard"
    w = bpy.data.worlds.new("World"); sc.world = w
    w.color = (0.03, 0.03, 0.035)
    sc.render.film_transparent = True
    return sc


def add_scan_lighting(sc):
    """Soft even light for textured scan meshes (textures already carry baked shading)."""
    sc.world.color = (1.0, 1.0, 1.0)
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 1.5; sun.rotation_euler = (math.radians(40), 0, math.radians(35))
    sc.collection.objects.link(sun)


def emission_attr_material(name, attr):
    m = bpy.data.materials.new(name)
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); em = nt.nodes.new("ShaderNodeEmission")
    at = nt.nodes.new("ShaderNodeAttribute"); at.attribute_name = attr
    nt.links.new(at.outputs["Color"], em.inputs["Color"]); nt.links.new(em.outputs[0], out.inputs[0])
    return m


def make_pointcloud(name, P, C, radius, extra=None):
    pc = bpy.data.pointclouds.new(name)
    pc.resize(len(P))
    pc.attributes["position"].data.foreach_set("vector", P.astype(np.float32).ravel())
    if "radius" not in pc.attributes:
        pc.attributes.new("radius", "FLOAT", "POINT")
    r = radius if np.ndim(radius) else np.full(len(P), radius)
    pc.attributes["radius"].data.foreach_set("value", np.asarray(r, np.float32))
    ca = pc.attributes.new("Col", "FLOAT_COLOR", "POINT")
    c4 = np.ones((len(P), 4), np.float32); c4[:, :3] = srgb_to_lin(C)
    ca.data.foreach_set("color", c4.ravel())
    for k, (typ, arr) in (extra or {}).items():
        a = pc.attributes.new(k, typ, "POINT")
        a.data.foreach_set({"FLOAT": "value", "FLOAT_VECTOR": "vector", "QUATERNION": "value"}[typ], arr.astype(np.float32).ravel())
    ob = bpy.data.objects.new(name, pc)
    bpy.context.scene.collection.objects.link(ob)
    pc.materials.append(emission_attr_material(name + "_mat", "Col"))
    return ob


def add_cameras(bmin, bmax, sc):
    c = (bmin + bmax) / 2; ext = bmax - bmin; diag = float(np.linalg.norm(ext))
    cams = {}
    top = bpy.data.objects.new("CAM_top", bpy.data.cameras.new("CAM_top"))
    top.data.type = "ORTHO"; top.data.ortho_scale = float(max(ext[0], ext[1]) * 1.04)
    top.location = (c[0], c[1], bmax[2] + diag); top.rotation_euler = (0, 0, 0)
    top.data.clip_end = diag * 4
    cams["top"] = top
    obl = bpy.data.objects.new("CAM_oblique", bpy.data.cameras.new("CAM_oblique"))
    obl.data.lens = 35; obl.data.clip_end = diag * 10; obl.data.clip_start = diag / 5000
    d = Vector((1.0, -1.25, 0.9)).normalized()
    dist = 0.5 * diag / math.tan(obl.data.angle / 2) * 0.9
    obl.location = Vector(c.tolist()) + d * dist
    obl.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    cams["oblique"] = obl
    for o in cams.values():
        sc.collection.objects.link(o)
    sc.camera = obl
    return cams


def render(sc, cams, tag, resx=1600, aspect_top=None):
    for k, cam in cams.items():
        sc.camera = cam
        if k == "top" and aspect_top:
            a = min(max(aspect_top, 0.5), 2.0)
            sc.render.resolution_x = resx; sc.render.resolution_y = int(resx / a)
        else:
            sc.render.resolution_x = resx; sc.render.resolution_y = int(resx * 0.625)
        sc.render.filepath = os.path.join(A.out, "previews", f"{A.name}_{k}{tag}.png")
        bpy.ops.render.render(write_still=True)
        log("rendered", sc.render.filepath)


def mesh_topology(ob):
    me = ob.data
    nf = len(me.polygons); nv = len(me.vertices); ne = len(me.edges)
    sizes = np.empty(nf, np.int32); me.polygons.foreach_get("loop_total", sizes)
    le = np.empty(len(me.loops), np.int32); me.loops.foreach_get("edge_index", le)
    efc = np.bincount(le, minlength=ne)
    return {"verts": nv, "faces": nf, "tris": int((sizes == 3).sum()), "quads": int((sizes == 4).sum()),
            "ngons": int((sizes > 4).sum()), "boundary_edges": int((efc == 1).sum()),
            "nonmanifold_edges": int((efc > 2).sum()), "loose_edges": int((efc == 0).sum()),
            "euler_char": nv - ne + nf}


def planar_decimate_ratio(ob, angle_deg=5.0, max_faces=400_000):
    """CAD test: how far do faces collapse when coplanar faces are dissolved?"""
    me = ob.data
    mods = []
    if len(me.polygons) > max_faces:  # pre-collapse huge meshes so the test finishes in seconds
        pre = ob.modifiers.new("pre", "DECIMATE"); pre.ratio = max_faces / len(me.polygons); mods.append(pre)
    dg = bpy.context.evaluated_depsgraph_get()
    n0 = len(ob.evaluated_get(dg).data.polygons)
    mod = ob.modifiers.new("planar", "DECIMATE"); mod.decimate_type = "DISSOLVE"
    mod.angle_limit = math.radians(angle_deg); mod.delimit = set(); mods.append(mod)
    dg = bpy.context.evaluated_depsgraph_get()
    n = len(ob.evaluated_get(dg).data.polygons)
    for m in mods:
        ob.modifiers.remove(m)
    return n / max(n0, 1)


def wire_material():
    m = bpy.data.materials.new("WIRE_preview")
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); em = nt.nodes.new("ShaderNodeEmission")
    wf = nt.nodes.new("ShaderNodeWireframe"); wf.use_pixel_size = True; wf.inputs[0].default_value = 1.0
    mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"
    mix.inputs[6].default_value = (0.82, 0.82, 0.8, 1); mix.inputs[7].default_value = (0.05, 0.05, 0.06, 1)
    nt.links.new(wf.outputs[0], mix.inputs[0]); nt.links.new(mix.outputs[2], em.inputs[0])
    nt.links.new(em.outputs[0], out.inputs[0])
    return m


# ---------------------------------------------------------------- main
sc = fresh()
extra = {}
mesh_objs = []

if A.kind in ("pcd", "splat", "las"):
    if A.kind == "las":
        P, C = read_las(A.src)
        if C is None: C = np.full((len(P), 3), 0.7)
        info["comments"] = []
    else:
        v, comments = read_ply_vertices(A.src); info["comments"] = comments
        P = np.stack([v["x"], v["y"], v["z"]], 1).astype(np.float64)
        if A.kind == "splat":
            C0 = 0.28209479177387814
            C = np.clip(0.5 + C0 * np.stack([v["f_dc_0"], v["f_dc_1"], v["f_dc_2"]], 1), 0, 1)
            op = 1 / (1 + np.exp(-v["opacity"].astype(np.float64)))
            scl = np.exp(np.stack([v["scale_0"], v["scale_1"], v["scale_2"]], 1).astype(np.float64))
            rot = np.stack([v["rot_0"], v["rot_1"], v["rot_2"], v["rot_3"]], 1)
            nrest = sum(1 for n in v.dtype.names if n.startswith("f_rest"))
            info["splat"] = {"count": int(len(P)), "sh_rest_coeffs": nrest, "sh_degree": int(round(math.sqrt(nrest / 3 + 1) - 1)),
                             "opacity_median": float(np.median(op)), "frac_opacity_gt_0.5": float((op > 0.5).mean()),
                             "scale_median": float(np.median(scl.max(1)))}
            # keep visible, non-giant splats for analysis/display
            big = np.percentile(scl.max(1), 99.0)
            keep = (op > 0.35) & (scl.max(1) < big)
            info["splat"]["kept_for_analysis"] = int(keep.sum())
            P, C, op, scl, rot = P[keep], C[keep], op[keep], scl[keep], rot[keep]
            # dense-core crop: 3DGS scenes carry a huge sparse shell of background Gaussians;
            # keep the bbox of the densest 48^3 cells that together hold 75% of opaque splats
            lo, hi = np.percentile(P, 1, 0), np.percentile(P, 99, 0)
            ijk = np.clip(((P - lo) / (hi - lo) * 48).astype(int), 0, 47)
            lin = (ijk[:, 0] * 48 + ijk[:, 1]) * 48 + ijk[:, 2]
            cnt = np.bincount(lin, minlength=48 ** 3)
            order = np.argsort(cnt)[::-1]; cum = np.cumsum(cnt[order])
            cells = order[: np.searchsorted(cum, 0.75 * len(P)) + 1]
            cijk = np.stack(np.unravel_index(cells, (48, 48, 48)), 1)
            cmin = lo + (cijk.min(0) - 0.5) / 48 * (hi - lo); cmax = lo + (cijk.max(0) + 1.5) / 48 * (hi - lo)
            core = np.all((P >= cmin) & (P <= cmax), 1)
            info["splat"]["core_kept"] = int(core.sum())
            P, C, op, scl, rot = P[core], C[core], op[core], scl[core], rot[core]
        else:
            names = v.dtype.names
            C = np.stack([v["red"], v["green"], v["blue"]], 1) / 255.0 if "red" in names else np.full((len(P), 3), 0.7)
    info["raw_points"] = int(len(P))
    offset = np.median(P, 0)
    info["source_offset"] = offset.tolist()
    P = P - offset
    R, how = orient(P, A.up); P = P @ R.T; info["orientation"] = how
    k = trim(P); P, C = P[k], C[k]
    if A.kind == "splat":
        op, scl, rot = op[k], scl[k], rot[k]
    P -= np.array([np.median(P[:, 0]), np.median(P[:, 1]), np.percentile(P[:, 2], 2)])
    info["points_after_trim"] = int(len(P))
else:
    if A.kind == "glb":
        bpy.ops.import_scene.gltf(filepath=A.src)
    elif A.kind == "blend":
        bpy.ops.wm.open_mainfile(filepath=A.src)
        sc = bpy.context.scene
        orig_cam = sc.camera
        info["blend_objects"] = [(o.name, o.type) for o in bpy.data.objects]
        info["blend_source_version"] = ".".join(map(str, bpy.data.version))
    elif A.kind == "msmesh":
        z = zipfile.ZipFile(A.src); tdir = os.path.join(A.tmp, A.name); os.makedirs(tdir, exist_ok=True)
        z.extractall(tdir)
        path = os.path.join(tdir, "mesh.ply")
        with open(path, "rb") as f:
            hdr = b""
            while not hdr.endswith(b"end_header\n"): hdr += f.readline()
            off = f.tell()
        H = hdr.decode().splitlines()
        nv = int([l for l in H if l.startswith("element vertex")][0].split()[2])
        nf = int([l for l in H if l.startswith("element face")][0].split()[2])
        has_uv = any("texcoord" in l for l in H)
        vd = np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")])
        V = np.fromfile(path, vd, nv, offset=off)
        fdt = [("n", "u1"), ("i", "<i4", 3)] + ([("m", "u1"), ("uv", "<f4", 6)] if has_uv else [])
        F = np.fromfile(path, np.dtype(fdt), nf, offset=off + nv * vd.itemsize)
        assert (F["n"] == 3).all()
        me = bpy.data.meshes.new(A.name)
        me.from_pydata(np.stack([V["x"], V["y"], V["z"]], 1).tolist(), [], F["i"].tolist())
        col = me.color_attributes.new("Col", "BYTE_COLOR", "POINT")
        c4 = np.ones((nv, 4), np.float32); c4[:, :3] = srgb_to_lin(np.stack([V["r"], V["g"], V["b"]], 1) / 255.0)
        col.data.foreach_set("color", c4.ravel())
        m = bpy.data.materials.new(A.name + "_mat"); nt = m.node_tree; bsdf = nt.nodes.get("Principled BSDF")
        if has_uv:
            uv = me.uv_layers.new(name="UVMap"); uv.data.foreach_set("uv", F["uv"].reshape(-1, 2).ravel())
            tex = nt.nodes.new("ShaderNodeTexImage")
            tex.image = bpy.data.images.load(os.path.join(tdir, "texture.tif"))
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        else:
            at = nt.nodes.new("ShaderNodeAttribute"); at.attribute_name = "Col"
            nt.links.new(at.outputs["Color"], bsdf.inputs["Base Color"])
        me.materials.append(m)
        ob = bpy.data.objects.new(A.name, me); sc.collection.objects.link(ob)
    mesh_objs = [o for o in sc.objects if o.type == "MESH"]
    if A.kind != "blend":
        add_scan_lighting(sc)
    info["weld"] = {}
    for o in (mesh_objs if A.kind != "blend" else []):  # never alter a hand-made scene
        bm = bmesh.new(); bm.from_mesh(o.data); n0 = len(bm.verts)
        d = max(o.dimensions) * 1e-6 if max(o.dimensions) > 0 else 1e-6
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=d)
        info["weld"][o.name] = [n0, len(bm.verts)]
        bm.to_mesh(o.data); bm.free()
    # gather world-space vertices for analysis
    Ps = []
    for o in mesh_objs:
        me = o.data; a = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", a)
        a = a.reshape(-1, 3).astype(np.float64); M = np.array(o.matrix_world)
        Ps.append(a @ M[:3, :3].T + M[:3, 3])
    P = np.concatenate(Ps)
    info["raw_points"] = int(len(P))
    if A.kind == "msmesh" or A.up != "keep":
        R, how = orient(P - P.mean(0), A.up if A.up != "auto" or A.kind == "msmesh" else "auto")
    else:
        R, how = np.eye(3), "kept (importer Z-up)"
    info["orientation"] = how
    # apply orientation + recentre to the objects themselves
    ctr = np.median(P, 0)
    Mo = Matrix(np.eye(4).tolist())
    Rm = Matrix(R.tolist()).to_4x4()
    P = (P - ctr) @ R.T
    shift = np.array([0, 0, -np.percentile(P[:, 2], 2)])
    P = P + shift
    for o in (mesh_objs if A.kind != "blend" else []):
        o.matrix_world = Matrix.Translation(Vector(shift.tolist())) @ Rm @ Matrix.Translation(Vector((-ctr).tolist())) @ o.matrix_world
    info["topology"] = {o.name: mesh_topology(o) for o in mesh_objs}

# ---- analysis
log("points for analysis", len(P))
S = P if len(P) <= 2_500_000 else P[np.random.default_rng(2).choice(len(P), 2_500_000, replace=False)]
g = voxel_features(S)
g.update(ransac_planes(S, g["voxel_size"]))
g["coarse"] = voxel_features(S, v_fixed=4 * g["voxel_size"])
ext = P.max(0) - P.min(0)
g["extent_xyz"] = [round(float(x), 3) for x in ext]
g["cad_score"] = cad_score(g)
info["geometry"] = g
log("geometry", json.dumps(g))

# ---- build scene
bmin, bmax = np.percentile(P, 0.5, 0), np.percentile(P, 99.5, 0)
if A.kind in ("pcd", "splat", "las"):
    n = len(P)
    area = max(ext[0] * ext[1], ext[0] * ext[2], ext[1] * ext[2])
    rad = 1.0 * math.sqrt(area / n)
    if A.kind == "splat":
        # rotate splat orientations by the same Z-up rotation: q' = qR * q
        qr = np.array(Matrix(R.tolist()).to_quaternion())
        q = rot / np.linalg.norm(rot, axis=1, keepdims=True)
        w1, x1, y1, z1 = qr; w2, x2, y2, z2 = q.T
        qn = np.stack([w1*w2 - x1*x2 - y1*y2 - z1*z2, w1*x2 + x1*w2 + y1*z2 - z1*y2,
                       w1*y2 - x1*z2 + y1*w2 + z1*x2, w1*z2 + x1*y2 - y1*x2 + z1*w2], 1)
        extra = {"opacity": ("FLOAT", op), "scale": ("FLOAT_VECTOR", scl), "rot_wxyz": ("QUATERNION", qn)}
        rad = np.clip(scl.mean(1), rad * 0.3, rad * 1.5)
    ob = make_pointcloud(A.name, P, C, rad, extra)
    info["display_radius"] = float(np.median(rad))

cams = add_cameras(bmin, bmax, sc)
render(sc, cams, "", aspect_top=float(ext[0] / max(ext[1], 1e-9)))

# topology close-up for meshes
if mesh_objs:
    for o in mesh_objs:
        pd = planar_decimate_ratio(o)
        info["topology"][o.name]["planar_dissolve_5deg_face_ratio"] = pd
    wm = wire_material()
    vl = bpy.context.view_layer; vl.material_override = wm
    c = (bmin + bmax) / 2; diag = float(np.linalg.norm(bmax - bmin))
    cz = bpy.data.objects.new("CAM_topology", bpy.data.cameras.new("CAM_topology"))
    cz.data.type = "ORTHO"; cz.data.ortho_scale = diag / 14; cz.data.clip_end = diag * 4
    # look straight down at the densest spot (median vertex)
    cz.location = (float(np.median(P[:, 0])), float(np.median(P[:, 1])), float(bmax[2] + diag))
    sc.collection.objects.link(cz)
    sc.eevee.taa_render_samples = 4
    render(sc, {"topology": cz}, "", resx=1200)
    vl.material_override = None
    bpy.data.objects.remove(cz); bpy.data.materials.remove(wm)
    sc.eevee.taa_render_samples = 16

sc.camera = cams["oblique"]
sc.render.resolution_x, sc.render.resolution_y = 1920, 1200
if A.kind == "blend":
    sc.camera = orig_cam  # keep the author's camera active
    sc.render.film_transparent = False
info["seconds"] = round(time.time() - T0, 1)
blend_path = os.path.join(A.out, "blend", A.name + ".blend")
if A.kind in ("glb", "msmesh", "blend"):
    try:
        bpy.ops.file.pack_all()
    except Exception as e:
        log("pack failed", e)
bpy.ops.wm.save_as_mainfile(filepath=blend_path, compress=True, copy=False)
info["blend"] = blend_path; info["blend_mb"] = round(os.path.getsize(blend_path) / 1e6, 1)
json.dump(info, open(os.path.join(A.out, "analysis", A.name + ".json"), "w"), indent=1, default=str)
log("DONE", A.name, "cad_score", g["cad_score"])
