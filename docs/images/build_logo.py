#!/usr/bin/env python3
"""Build the nf-core/msproteomics logo: FragPipe-style 'Faster One' wordmark with the
nf-core apple core replacing FragPipe's lightning bolt. Emits path-only SVGs (glyphs
outlined with fontTools), so the files render everywhere without the font installed.

Sources (auto-downloaded into src/ on first run):
- 'Faster One' typeface, SIL OFL 1.1 — the face the original FragPipe logo uses:
  https://github.com/google/fonts/tree/main/ofl/fasterone
- Apple core paths from nf-core/logos nf-core-logos/nf-core-logo-square.svg
Layout reference (not downloaded): Nesvilab/FragPipe images/fragpipe-icon-prep.svg —
bolt slot proportions and the -0.0763 em letter-spacing come from it. Used with the
FragPipe team's blessing (collaborators on this pipeline).

Outputs out/<variant>_{light,dark}.svg; the msproteomics-apple pair is committed here
as nf-core-msproteomics_logo_{light,dark}.svg. PNGs were rendered with headless Chrome:
  chrome --headless --screenshot=out.png --default-background-color=00000000 \
         --window-size=1400,156 --force-device-scale-factor=2 file://.../logo.svg
Requires: python3 with fontTools (pip install fonttools)."""
import json
import os
import re
from urllib.request import urlretrieve
from xml.etree import ElementTree as ET

from fontTools.misc.transform import Transform
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.svgLib.path import parse_path
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
os.makedirs(SRC, exist_ok=True)

SOURCES = {
    "FasterOne-Regular.ttf":
        "https://github.com/google/fonts/raw/main/ofl/fasterone/FasterOne-Regular.ttf",
    "nf-core-logo-square.svg":
        "https://raw.githubusercontent.com/nf-core/logos/master/nf-core-logos/nf-core-logo-square.svg",
}
for fn, url in SOURCES.items():
    if not os.path.exists(os.path.join(SRC, fn)):
        print(f"downloading {fn}")
        urlretrieve(url, os.path.join(SRC, fn))

# ---- tunables (em fractions; bolt in the original: top=0.660 em above baseline,
# tip 0.129 em below, height 0.790 em) ----
LETTER_SPACING_EM = -0.48418751 / 6.35  # from the original fragpipe SVG
APPLE_H_EM = 0.80        # apple total height incl. stem
APPLE_BELOW_EM = 0.02    # round-shape optical overshoot below baseline
MARGIN_EM = 0.04         # viewBox margin
GAP_EM = 0.035           # visual air between the apple and neighboring ink, both sides
PADS_EM = {"fragpipe-apple": (0.030, 0.030), "msproteomics-apple": (0.045, 0.045),
           "msproteomics-apple-i": (0.045, 0.045), "msproteomics-apple-o1": (0.045, 0.055),
           "msproteomics-apple-t": (0.045, 0.045)}  # gap padding (left, right) around apple

TEXT_LIGHT = "#3c3c3c"
TEXT_DARK = "#fafafa"

font = TTFont(os.path.join(SRC, "FasterOne-Regular.ttf"))
upem = font["head"].unitsPerEm
cmap = font.getBestCmap()
glyphset = font.getGlyphSet()
ntos = lambda v: f"{v:.1f}"

VARIANTS = {
    "fragpipe-apple": ["Fr", None, "gPipe"],
    "msproteomics-apple": ["msprote", None, "mics"],
    "msproteomics-apple-i": ["msproteom", None, "cs"],
    "msproteomics-apple-o1": ["mspr", None, "teomics"],
    "msproteomics-apple-t": ["mspro", None, "eomics"],
}
for segs in VARIANTS.values():
    for seg in segs:
        if seg:
            for ch in seg:
                assert ord(ch) in cmap, f"glyph missing for {ch!r}"


def gname(ch):
    return cmap[ord(ch)]


# ---- kerning: legacy kern table + GPOS PairPos (formats 1/2, incl. extension) ----
def needed_pairs():
    pairs = set()
    for segs in VARIANTS.values():
        for seg in segs:
            if seg:
                for a, b in zip(seg, seg[1:]):
                    pairs.add((gname(a), gname(b)))
    return pairs


def kern_values(pairs):
    out = dict.fromkeys(pairs, 0)
    if "kern" in font:
        for st in font["kern"].kernTables:
            table = getattr(st, "kernTable", None)
            if table:
                for p in pairs:
                    out[p] += table.get(p, 0)
    if "GPOS" in font:
        t = font["GPOS"].table
        lookups = t.LookupList.Lookup if t.LookupList else []
        for lk in lookups:
            subs = []
            if lk.LookupType == 2:
                subs = lk.SubTable
            elif lk.LookupType == 9:
                subs = [s.ExtSubTable for s in lk.SubTable if s.ExtensionLookupType == 2]
            for st in subs:
                cov = st.Coverage.glyphs
                if st.Format == 1:
                    covmap = {g: i for i, g in enumerate(cov)}
                    for g1, g2 in pairs:
                        if g1 in covmap:
                            for pvr in st.PairSet[covmap[g1]].PairValueRecord:
                                if pvr.SecondGlyph == g2 and pvr.Value1:
                                    out[(g1, g2)] += getattr(pvr.Value1, "XAdvance", 0)
                elif st.Format == 2:
                    covset = set(cov)
                    cd1 = st.ClassDef1.classDefs
                    cd2 = st.ClassDef2.classDefs
                    for g1, g2 in pairs:
                        if g1 in covset:
                            rec = st.Class1Record[cd1.get(g1, 0)].Class2Record[cd2.get(g2, 0)]
                            if rec.Value1:
                                out[(g1, g2)] += getattr(rec.Value1, "XAdvance", 0)
    return {p: v for p, v in out.items() if v}


KERN = kern_values(needed_pairs())

# ---- apple: parse paths from the nf-core square logo, drop invisible slivers ----
apple_src = []  # (d, fill)
tree = ET.parse(os.path.join(SRC, "nf-core-logo-square.svg"))
for el in tree.iter():
    if el.tag.endswith("}path") and "kernTable" not in el.attrib:
        style = el.get("style", "")
        m = re.search(r"fill:\s*(#[0-9a-fA-F]{6})", style)
        if not m:
            continue
        d = el.get("d")
        bp = BoundsPen({})
        parse_path(d, bp)
        (x0, y0, x1, y1) = bp.bounds
        if (x1 - x0) < 1.0 or (y1 - y0) < 1.0:
            continue  # invisible sliver
        apple_src.append((d, m.group(1).lower(), bp.bounds))

ax0 = min(b[0] for _, _, b in apple_src)
ay0 = min(b[1] for _, _, b in apple_src)
ax1 = max(b[2] for _, _, b in apple_src)
ay1 = max(b[3] for _, _, b in apple_src)
APPLE_W_SRC, APPLE_H_SRC = ax1 - ax0, ay1 - ay0

k = (APPLE_H_EM * upem) / APPLE_H_SRC
apple_w = APPLE_W_SRC * k


def apple_paths_at(x):
    """Apple paths scaled to APPLE_H_EM, left edge at x, bottom at baseline+overshoot."""
    tx = x - ax0 * k
    ty = APPLE_BELOW_EM * upem - ay1 * k
    t = Transform(k, 0, 0, k, tx, ty)
    parts = []
    for d, fill, _ in apple_src:
        sp = SVGPathPen({}, ntos=ntos)
        parse_path(d, TransformPen(sp, t))
        parts.append((sp.getCommands(), fill))
    return parts


# ---- wordmark layout ----
def glyph_path(ch, penx):
    t = Transform(1, 0, 0, -1, penx, 0)  # y-up font units -> y-down SVG, baseline y=0
    sp = SVGPathPen(glyphset, ntos=ntos)
    glyphset[gname(ch)].draw(TransformPen(sp, t))
    return sp.getCommands()


def glyph_bounds(ch, penx):
    t = Transform(1, 0, 0, -1, penx, 0)
    bp = BoundsPen(glyphset)
    glyphset[gname(ch)].draw(TransformPen(bp, t))
    return bp.bounds


def build(segments, pads_em):
    ls = LETTER_SPACING_EM * upem
    pen = 0.0
    text_parts, bounds, apple_parts, zone = [], [], [], None
    ink_right = None
    prev = None
    for seg in segments:
        if seg is None:
            # place the apple a fixed GAP from the MEASURED ink edge of the previous
            # glyph (ink overhangs the pen position: negative tracking + tiny RSB),
            # and cut the text mask the same GAP after the apple -> equal air on both sides
            gap = GAP_EM * upem
            ax = (ink_right + gap) if ink_right is not None else pen + gap
            apple_parts = apple_paths_at(ax)
            zone = ((ink_right + 2) if ink_right is not None else ax - gap,
                    ax + apple_w + gap)
            bounds.append((ax, -APPLE_H_EM * upem + APPLE_BELOW_EM * upem,
                           ax + apple_w, APPLE_BELOW_EM * upem))
            pen = ax + apple_w + pads_em[1] * upem
            prev = None
            continue
        for ch in seg:
            g = gname(ch)
            if prev is not None:
                pen += KERN.get((prev, g), 0)
            text_parts.append(glyph_path(ch, pen))
            b = glyph_bounds(ch, pen)
            if b:
                bounds.append(b)
                ink_right = b[2]
            pen += glyphset[g].width + ls
            prev = g
    x0 = min(b[0] for b in bounds)
    y0 = min(b[1] for b in bounds)
    x1 = max(b[2] for b in bounds)
    y1 = max(b[3] for b in bounds)
    return text_parts, apple_parts, (x0, y0, x1, y1), zone


def emit(name, text_parts, apple_parts, bbox, fill, zone=None):
    m = MARGIN_EM * upem
    x0, y0, x1, y1 = bbox
    vb = (x0 - m, y0 - m, (x1 - x0) + 2 * m, (y1 - y0) + 2 * m)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb[0]:.1f} {vb[1]:.1f} {vb[2]:.1f} {vb[3]:.1f}">',
    ]
    maskref = ""
    if zone:
        # keep-out slot: glyph speed-dash tails have negative LSB and would thread
        # behind the apple's stem; erase text ink in the slot, cut at the letter lean
        t = 0.2126  # tan(12 deg)
        yt, yb = vb[1], vb[1] + vb[3]
        zx0, zx1 = zone
        pts = (f"{zx0 - t*yt:.1f},{yt:.1f} {zx1 - t*yt:.1f},{yt:.1f} "
               f"{zx1 - t*yb:.1f},{yb:.1f} {zx0 - t*yb:.1f},{yb:.1f}")
        lines += ['  <defs><mask id="slot">',
                  f'    <rect x="{vb[0]:.1f}" y="{vb[1]:.1f}" width="{vb[2]:.1f}" height="{vb[3]:.1f}" fill="#fff"/>',
                  f'    <polygon points="{pts}" fill="#000"/>',
                  '  </mask></defs>']
        maskref = ' mask="url(#slot)"'
    lines.append(f'  <g fill="{fill}"{maskref}>')
    lines += [f'    <path d="{d}"/>' for d in text_parts]
    lines.append("  </g>")
    lines.append("  <g>")
    lines += [f'    <path fill="{f}" d="{d}"/>' for d, f in apple_parts]
    lines += ["  </g>", "</svg>", ""]
    path = os.path.join(OUT, f"{name}.svg")
    with open(path, "w") as fh:
        fh.write("\n".join(lines))
    return vb


specs = {}
for name, segs in VARIANTS.items():
    tp, ap, bbox, zone = build(segs, PADS_EM[name])
    for theme, fill in (("light", TEXT_LIGHT), ("dark", TEXT_DARK)):
        vb = emit(f"{name}_{theme}", tp, ap, bbox, fill, zone)
        specs[f"{name}_{theme}"] = {"w": vb[2], "h": vb[3]}

with open(os.path.join(OUT, "specs.json"), "w") as fh:
    json.dump(specs, fh, indent=1)

capH = getattr(font.get("OS/2"), "sCapHeight", 0)
print(f"upem={upem} capHeight={capH} ({capH/upem:.3f} em)")
print(f"kern pairs in play: { {(a,b):v for (a,b),v in KERN.items()} or 'none'}")
print(f"apple src bbox: {ax0:.1f},{ay0:.1f} -> {ax1:.1f},{ay1:.1f}  "
      f"(w/h aspect {APPLE_W_SRC/APPLE_H_SRC:.3f}), {len(apple_src)} paths kept")
print(f"apple placed: h={APPLE_H_EM}em w={apple_w/upem:.3f}em")
for n, s in specs.items():
    print(f"{n}: viewBox {s['w']:.0f}x{s['h']:.0f} (aspect {s['h']/s['w']:.4f})")
