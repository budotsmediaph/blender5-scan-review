"""Builds the preview gallery from previews/ and analysis/*.json.

  python3 make_gallery.py                      # local: index.html next to previews/ (full-res, local paths)
  python3 make_gallery.py --site docs --repo URL  # public GitHub Pages copy: docs/index.html + docs/img/*.jpg
"""
import json, glob, os, html, collections, argparse, subprocess

B = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(B)
ap = argparse.ArgumentParser(); ap.add_argument("--site"); ap.add_argument("--repo", default="")
A = ap.parse_args()
# kept out of the public site: third-party screenshots, an identifiable private person, footage of unverified origin
PUBLIC_EXCLUDE = ("Misc__", "plangg-beach_photos", "gauss-underwater")
if A.site:
    os.makedirs(os.path.join(A.site, "img"), exist_ok=True)
REGION = {"PH-Cebu-Metro": "Philippines · Metro Cebu", "PH-Cebu-North": "Philippines · Northern Cebu",
          "PH-Palawan-ElNido": "Philippines · El Nido, Palawan", "TH-Bangkok": "Thailand · Bangkok",
          "JP-Shizuoka": "Japan · Shizuoka", "Underwater": "Underwater reef", "Misc": "Misc (not scans)"}
VERDICT = {  # CAD-suitability call from the review in README.md
    "daanbantayan-telecom-tower": ("cad", "CAD #1 — model with primitives + arrays"),
    "mandaue-waterpark": ("cad", "CAD #2 — planar blockout"),
    "srp-sinulog-grounds": ("cad", "CAD #3 — massing model"),
    "JP-Shizuoka__bridge": ("cad", "CAD #4 — array model from reference"),
    "kingpower-bangrak": ("ref", "Reference for massing (splat)"),
    "liloan-jesus": ("ref", "Hybrid — scan statue, CAD pedestal"),
    "daanbantayan-cityhall": ("ref", "Model by hand; weak photo set"),
    "mactan-airport": ("no", "Weak splat — view only"),
    "mandani-bay": ("no", "Render video only"),
    "pix4d-lihim": ("no", "Tie points only; photos missing"),
    "Misc__": ("no", "Not a scan"),
}
KIND = {"pointcloud": "Point cloud", "SPLAT": "Gaussian splat", "glb": "Polycam GLB mesh", "blend": ".blend scene",
        "mesh": "Metashape mesh", "texmesh": "Metashape textured mesh", "tiepoints": "Pix4D tie points",
        "photos": "Photo set", "thumbs": "Pix4D thumbnails", "video": "Video", "image": "Image", "cabin": "Screenshot"}

assets = collections.OrderedDict()
for f in sorted(os.listdir("previews")):
    if f.startswith("."): continue
    if A.site and any(x in f for x in PUBLIC_EXCLUDE): continue
    stem = f.rsplit(".", 1)[0]
    for suf in ("_oblique", "_top", "_topology", "_contact", "_strip"):
        if stem.endswith(suf):
            stem = stem[: -len(suf)]; break
    assets.setdefault(stem, []).append(f)

def order(fs):
    rank = {"_oblique": 0, "_contact": 0, "_strip": 0, "_top": 1, "_topology": 2}
    return sorted(fs, key=lambda x: next((v for k, v in rank.items() if k in x), 3))

groups = collections.OrderedDict((k, []) for k in REGION)
for stem, fs in assets.items():
    reg = stem.split("__")[0]
    reg = "Underwater" if reg.startswith("Underwater") else reg
    groups.setdefault(reg, []).append((stem, order(fs)))

def src(f):
    """Local: link the original. Site: a 1600 px JPEG copy (PNG renders are 1-7 MB each)."""
    if not A.site:
        return "previews/" + html.escape(f)
    out = f"img/{f.rsplit('.', 1)[0]}.jpg"
    dst = os.path.join(A.site, out)
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(f"previews/{f}"):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f"previews/{f}", "-vf", "scale='min(1600,iw)':-2",
                        "-q:v", "4", "-frames:v", "1", "-update", "1", dst], check=True)
    return html.escape(out)


def card(stem, fs):
    title = stem.split("__", 1)[1] if "__" in stem else stem
    kind = next((v for k, v in KIND.items() if title.endswith(k) or f"_{k}" in title), "")
    j = {}
    jp = f"analysis/{stem}.json"
    if os.path.exists(jp):
        j = json.load(open(jp))
    v = next((val for k, val in VERDICT.items() if k in stem), None)
    facts = []
    if j:
        g = j["geometry"]
        facts.append(f"grid score <b>{g['cad_score']:.0f}</b>")
        if "splat" in j:
            s = j["splat"]; facts.append(f"{s['count']:,} Gaussians · SH{s['sh_degree']} · {s['frac_opacity_gt_0.5']*100:.0f}% opaque")
        elif "topology" in j:
            t = max(j["topology"].values(), key=lambda t: t["faces"])
            facts.append(f"{t['faces']:,} faces · {t['quads']} quads · planar-dissolve keeps {t['planar_dissolve_5deg_face_ratio']*100:.0f}%")
        else:
            facts.append(f"{j['raw_points']:,} points")
        if A.site:
            facts.append(f"Blender 5 file {j['blend_mb']:.0f} MB (not in repo)")
        else:
            facts.append(f"<code>blend/{html.escape(os.path.basename(j['blend']))}</code> ({j['blend_mb']} MB)")
            facts.append(f"src <code>{html.escape(j['src'])}</code>")
    badge = f'<span class="badge {v[0]}">{html.escape(v[1])}</span>' if v else ""
    imgs = "".join(f'<a href="{src(f)}"><img loading="lazy" src="{src(f)}" alt="{html.escape(title)} preview"></a>' for f in fs)
    return (f'<article><header><h3>{html.escape(title)}</h3><span class="kind">{kind}</span>{badge}</header>'
            f'<div class="imgs n{min(len(fs),3)}">{imgs}</div>'
            + (f'<p>{" · ".join(facts)}</p>' if facts else "") + "</article>")

readme = f'<a href="{html.escape(A.repo)}#readme">The README</a>' if A.repo else "README.md"
footer = (f'<footer><a href="{html.escape(A.repo)}">Source and full report on GitHub</a> · generated with Blender 5.2.2 LTS</footer>'
          if A.repo else "")
body = "".join(f'<section><h2>{html.escape(REGION.get(r, r))}</h2><div class="grid">{"".join(card(s, fs) for s, fs in items)}</div></section>'
               for r, items in groups.items() if items)
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scan Asset Previews</title><style>
:root{{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--mute:#6b6b70;--line:#e3e1dc;--img:#1b1c1f;--cad:#1f7a4d;--ref:#9a6a00;--no:#8a8a8f}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#141416;--card:#1d1e21;--ink:#ecebe8;--mute:#9a9aa0;--line:#2c2d31;--img:#0d0d0f;--cad:#4cc38a;--ref:#e0a940;--no:#77777d}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:1500px;margin:0 auto;padding:24px 16px 64px}}h1{{font-size:22px;margin:0 0 4px}}.sub{{color:var(--mute);margin:0 0 24px}}
h2{{font-size:17px;margin:32px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,440px),1fr));gap:16px}}
article{{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}}
header{{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:baseline;padding:10px 12px}}h3{{font-size:15px;margin:0}}
.kind{{color:var(--mute);font-size:13px}}.badge{{margin-left:auto;font-size:12px;font-weight:600;padding:2px 8px;border-radius:99px;border:1px solid currentColor}}
.badge.cad{{color:var(--cad)}}.badge.ref{{color:var(--ref)}}.badge.no{{color:var(--no)}}
.imgs{{display:grid;gap:2px;background:var(--img)}}.imgs.n2,.imgs.n3{{grid-template-columns:1fr 1fr}}.imgs.n3 a:first-child{{grid-column:1/-1}}
.imgs img{{display:block;width:100%;height:100%;object-fit:cover;aspect-ratio:16/10;background:var(--img)}}.imgs.n1 img{{aspect-ratio:auto}}
p{{margin:0;padding:10px 12px;color:var(--mute);font-size:13px}}a{{color:inherit}}footer{{margin-top:40px;color:var(--mute);font-size:13px}}p b{{color:var(--ink)}}code{{font-size:12px;word-break:break-all}}
</style></head><body><main><h1>Scan asset previews</h1>
<p class="sub">Blender 5.2 renders, contact sheets and video strips of drone, GoPro and splat captures, grouped by location. Badges show whether each capture can become a clean, CAD-like Blender model. {readme} has the reasoning. Grid score is a heuristic for man-made geometry (0–100).</p>
{body}{footer}</main></body></html>"""
out_dir = A.site or "."
if A.site:
    open(os.path.join(A.site, ".nojekyll"), "w").close()
path = os.path.join(out_dir, "index.html")
open(path, "w").write(page)
print("wrote", os.path.abspath(path), sum(len(v) for v in groups.values()), "assets")
