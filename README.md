# 202609 — Blender 5 conversions & CAD-suitability review

Generated 2026-09-27 with Blender 5.2.2 LTS (headless). **Gallery: https://budotsmediaph.github.io/blender5-scan-review/**

This repo holds the review only: this report, the gallery (`docs/`), per-asset metrics (`analysis/*.json`) and the
conversion scripts (`scripts/`). The scans, the 14 converted `.blend` files (812 MB), full-resolution previews and
per-photo GPS data stay on the local disk. The public gallery leaves out the Plang G photo set (identifiable
person), the Unreal cabin screenshots (third-party) and one underwater clip of unverified origin.
Locally, `python3 scripts/make_gallery.py` builds the full `index.html`, and `--site docs --repo <url>` rebuilds the public copy.

## Verdict: what can become a clean, CAD-like Blender model?

**None of the existing meshes/point clouds is CAD-ready as-is.** Every mesh on this disk is 100 % triangles
(0 quads), and a 5° planar-dissolve keeps 71–83 % of faces. Clean CAD topology would collapse to under 30 %.
They are organic scan surfaces. The CAD-like wins come from **man-made subjects**, rebuilt as low-poly
blockouts over the scan/photo reference:

| Rank | Asset | Why | Route in Blender 5 |
|---|---|---|---|
| 1 | **Daanbantayan telecom tower** (DISK8 `philippines/cebu/daanbantayan-antenna/raw/`; DISK4 copy in `_DUPLICATES_DISK8/`) | Lattice tower, panel antennas, MW dishes, box shelter: pure primitives. 60 JPG + 60 DNG orbit + 3 × 4K video with GPS/altitude SRT | Photogrammetry (Metashape/RealityScan) **only for cameras + sparse points/scale**. Lattice meshes badly. Then model with cylinders/boxes + Array modifiers per tower section |
| 2 | **Mandaue waterpark** point cloud → `blend/PH-Cebu-Metro__mandaue-waterpark_pointcloud.blend` | Rectangular pools, roofs, slides, perimeter walls; grid score 73 | Planar blockout: trace roofs/pools as planes, extrude. Needs a real-world scale reference (cloud is unscaled, ~13 m wide) |
| 3 | **SRP / Sinulog grounds** point cloud → `blend/PH-Cebu-Metro__srp-sinulog-grounds_pointcloud.blend` | Road grid + mid-rise blocks; highest grid score (84) | Massing model: buildings as boxes, roads as planes. Low detail, good for layout/context |
| 4 | **Shizuoka bridge** drone video (DISK8 `projects-data-3d/shizuoka-bridge.mp4`; DISK4 copy in `_DUPLICATES_DISK8/`) | Girder bridge on repeated piers: array-friendly | Model from reference (pier + span module × Array). 720p is too low for good photogrammetry |
| 5 | **Bangkok King Power / Bang Rak** Gaussian splat → `blend/TH-Bangkok__kingpower-bangrak_SPLAT.blend` | Towers + street grid (score 52) but splat centres are noisy | Use as reference for building massing (pair with OSM footprints). No direct mesh |
| 6 | **Liloan Jesus statue** photos (DISK8 `philippines/cebu/liloan-jesus-statue/raw/`; DISK4 copy in `_DUPLICATES_DISK8/`) | Hybrid: CAD-like pedestal (cylinder, struts, ring planter), organic statue; 97 daylight GoPro photos | Photogrammetry → statue retopo (Quad remesh); pedestal rebuilt as primitives |
| 7 | **Daanbantayan city hall** photos (DISK8 `philippines/cebu/daanbantayan-cityhall/raw/`; DISK4 copy in `_DUPLICATES_DISK8/`) | CAD-like 2-storey facade, but night + fisheye + Christmas lights | Weak photogrammetry input: model by hand from reference, or reshoot in daylight |

**Keep as organic scan assets** (decimate / quad-remesh for use as terrain, not CAD): El Nido Polycam
GLBs (7 Commando, Nacpan, El Nido town, Caalan/Lihim), the Caalan diorama `.blend`, Metashape El Nido meshes,
Plang G beach, coral reef, rock-island photos.

**Not usable for modelling:** Mactan airport splat (only 28 % of Gaussians opaque, mostly floaters),
Mandani Bay (Luma render video only, no 3D data), Pix4D Lihim (tie points only, source photos on `F:\` missing),
Unreal cabin screenshots (not scans).

## Gaussian splats (handled separately)

| File | Gaussians | SH degree | Opaque (>0.5) | Notes |
|---|---|---|---|---|
| `TH-Bangkok/kingpower-bangrak_SPLAT/bkk bangrak kingpower 240326.ply` | 2,168,210 | 3 | 76 % | Polycam export, Y-up → converted to Z-up |
| `PH-Cebu-Metro/mactan-airport_SPLAT/ph-macia-airport_jawsetpostshot.ply` | 2,165,927 | 3 | 28 % | Jawset Postshot export, Y-down → Z-up; subject is a small dense core inside a large sparse shell |

The splat `.blend` files store each Gaussian as a point with `Col` (SH DC colour), `opacity`, `scale`, and
`rot_wxyz` (rotated into the Z-up frame) attributes. They are opaque, dense-core, 99th-percentile-size filtered.
Blender renders them as coloured dots. True splat rendering needs a 3DGS add-on or SuperSplat/Postshot. A
proper splat→mesh (2DGS/SuGaR/Postshot mesh) needs the original capture photos, which are **not on this disk**.

## Folder layout (reorganised by location, original filenames kept)

```
PH-Cebu-Metro/      srp-sinulog-grounds_pointcloud · mandaue-waterpark_pointcloud · mactan-airport_SPLAT
                    mandani-bay_luma-video
PH-Cebu-North/      plangg-beach_pointcloud+photos (point cloud only; photos → _DUPLICATES_DISK8)
PH-Palawan-ElNido/  lihim-resort_pix4d-project · elnido_metashape-projects · polycam-exports_glb-blend-video
TH-Bangkok/         kingpower-bangrak_SPLAT
_misc/              unreal-airplane-cabin_screenshots
_DUPLICATES_DISK8/  720 files (5.7 GB) byte-identical to copies on DISK8. Same sub-paths as before,
                    _manifest.tsv maps each to its DISK8 twin + MD5 (see "Duplicates of DISK8" below)
202609_blender5_files/
  blend/      14 Blender 5 files (point clouds as native PointCloud objects, meshes welded + textures packed)
  previews/   top + oblique renders, wireframe close-ups for meshes, photo contact sheets, video strips
  analysis/   per-asset JSON metrics · moves.tsv (old → new paths) · photo_exif.csv (GPS/date per photo)
  scripts/    convert_analyze.py · run_batch.sh · batch_jobs.tsv · make_gallery.py
              undo_duplicates_disk8.sh · undo_organize.sh
```

Moved whole folders, so Pix4D (`.p4d` + folder) and Metashape (`.psx` + `.files`) projects stay intact.
To revert: first `scripts/undo_duplicates_disk8.sh` (puts the DISK8 duplicates back), then `scripts/undo_organize.sh` (restores the original 2026-09-27 layout).

## Duplicates of DISK8 (moved 2026-09-28)

These 720 files are MD5-identical to files on `DISK8 wd3_6/projects-data-3d`. Every DISK8 twin is in a permanent
location, not in DISK8's `_duplicates/` or `_broken/`. They were moved (not deleted) to `_DUPLICATES_DISK8/`, keeping
their paths:

| Moved from | Files | DISK8 twin |
|---|---|---|
| `PH-Cebu-North/daanbantayan-telecom-tower_photos` | 126 (3.8 GB) | `philippines/cebu/daanbantayan-antenna/raw/` |
| `PH-Palawan-ElNido/rock-islands_photos` | 328 (1.1 GB) | `philippines/palawan/elnido-rock-islands/raw/` |
| `PH-Cebu-North/daanbantayan-cityhall_photos` | 123 (0.4 GB) | `philippines/cebu/daanbantayan-cityhall/raw/` |
| `PH-Cebu-Metro/liloan-jesus-statue_photos` | 97 (0.2 GB) | `philippines/cebu/liloan-jesus-statue/raw/` |
| `PH-Cebu-North/plangg-beach_pointcloud+photos/pg-plankgbeach` | 41 (0.16 GB) | `philippines/people/bogo-beach-plank-pose/raw/` |
| `Underwater-Reef/coral_pointcloud+video` | 4 (0.05 GB) | `projects-data-3d/underwater/underwater/` |
| `JP-Shizuoka/bridge_drone-video` | 1 (0.05 GB) | `projects-data-3d/shizuoka-bridge.mp4` |

Folders left empty were removed, including the `JP-Shizuoka/` and `Underwater-Reef/` groups. The coral Blender
conversion's source path now points into `_DUPLICATES_DISK8/`. The Plang G point cloud had no DISK8 twin and stayed put.

## Issues found

- **Duplicate removed (2026-09-28, on request):** `polycam-exports_glb-blend-video/7commando-beach.glb` was byte-identical (MD5) to `palawan-elnido-7commando.glb`. It went to the DISK4 Trash; the kept copy is the one the Blender conversion uses.
- **Missing source photos:** Metashape projects point to `../../../../20230730/elnido1/*.JPG`. Pix4D points to `F:/2023-08-10_ph_palawan_elnido_lihim_caalan_sunny/`. Neither is on this disk. Pix4D densification never finished.
- **Unwelded mesh:** `palawan-elnido-caalan-lihimresrto.glb` (Blender 3.6 glTF export) is triangle soup: 2.17 M vertices, 362 k after welding. The Blender 5 conversion is welded.
- **No real-world scale:** every point cloud/GLB is in arbitrary units (e.g. waterpark about 13 m, El Nido town about 5 m). Scale against a known dimension before CAD work.
- `pg-jesus.zip` and `elnuido-calaan-lihim.blend1` were deleted (outside this process) at 21:22 on 2026-09-27, before the reorganisation.

## Metrics (in `analysis/*.json`)

Voxel covariance (voxel sized so a typical point shares it with ~25 others), repeated at 4× scale:
`flat_frac` (locally planar), `wall_orthogonality` (do vertical-surface normals sit on a 90° grid: 0 = random,
1 = perfect), sequential-RANSAC plane coverage. For meshes, also tri/quad/ngon counts, boundary and non-manifold
edges, and the 5° planar-dissolve face ratio. `cad_score` = 100 × (0.7 × coarse orthogonality + 0.3 × coarse flat
fraction). It is a heuristic, checked against the renders: built scenes scored 45–85, beaches/reef/karst 0–40.
It measures *the scene*, not the data quality, so the ranking above also weighs capture quality.

| Asset | cad_score | Notes |
|---|---|---|
| SRP / Sinulog grounds (points) | 84 | road grid, blocks |
| Mandaue waterpark (points) | 73 | pools, roofs |
| Bangkok King Power (splat) | 52 | towers, streets; noisy centres |
| El Nido town (GLB `elnido2beahc`) | 45 | town grid at small scale inside karst terrain |
| Plang G beach (points) | 40 | huts on flat sand |
| Coral reef (points) | 22 | organic |
| Nacpan / 7 Commando / Caalan (GLB), Metashape, Pix4D, airport splat | 0–14 | terrain or too sparse |
