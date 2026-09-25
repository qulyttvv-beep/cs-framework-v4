#!/usr/bin/env python3
"""Render the Spark X 3D app icon.

A small signed-distance-field raymarcher (numpy only) that renders a rounded,
three-tone cube emblem floating over a graphite squircle plate, lit like a
product shot: warm key light, cool fill, rim light, glossy studio reflections,
crisp shadows, ambient occlusion and a filmic tone curve. Small sizes are
rendered at their own resolution (not shrunk from the master) so they stay sharp.

    python tools/render_icon.py            # writes assets/icon*.png, sparkx.ico, sparkx.icns
    python tools/render_icon.py --size 512 --preview   # fast preview only

Requires: numpy, pillow.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"


# ── math helpers ─────────────────────────────────────────────────────────────
def normalize(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-9)


def rot_x(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rot_y(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


# ── scene ────────────────────────────────────────────────────────────────────
CENTER = np.array([0.0, 0.16, 9.6])          # cube centre (camera looks +z)
HALF = 0.78                                   # half extent
RADIUS = 0.075                                # edge bevel: small = crisp edges
PLATE_Z = CENTER[2] + 1.55                     # back plate, facing the camera
# object -> world: spin 45° about Y, then tip the top toward the camera
R_OW = rot_x(np.radians(-32.0)) @ rot_y(np.radians(45.0))

# face albedos (linear) keyed by object-space axis/sign
FACE = {
    (1, +1): np.array([0.655, 0.615, 0.55]),  # +Y top    warm bone ceramic
    (1, -1): np.array([0.20, 0.20, 0.22]),
    (2, +1): np.array([0.60, 0.215, 0.09]),   # lit side  fired clay
    (2, -1): np.array([0.60, 0.215, 0.09]),
    (0, +1): np.array([0.072, 0.075, 0.086]), # shade side graphite
    (0, -1): np.array([0.072, 0.075, 0.086]),
}
PLATE = np.array([0.030, 0.030, 0.034])

KEY_DIR = normalize(np.array([-0.60, 0.78, -0.50]))
SHADOW_DIR = normalize(np.array([-0.16, 0.60, -0.78]))  # plate shadow light
KEY_COL = np.array([1.00, 0.95, 0.88]) * 2.1
FILL_DIR = normalize(np.array([0.85, 0.10, -0.55]))
FILL_COL = np.array([0.55, 0.65, 0.85]) * 0.35
RIM_DIR = normalize(np.array([0.55, 0.35, 0.95]))
RIM_COL = np.array([1.0, 0.86, 0.74]) * 1.6


def sd_round_box(p, b, r):
    q = np.abs(p) - b
    return (np.linalg.norm(np.maximum(q, 0.0), axis=-1)
            + np.minimum(np.max(q, axis=-1), 0.0) - r)


def to_obj(pw):
    # p_obj = R^T (pw - C)  ->  row-vector form (pw - C) @ R
    return (pw - CENTER) @ R_OW


def scene(pw):
    return sd_round_box(to_obj(pw), HALF - RADIUS, RADIUS)


def calc_normal(p):
    e = 1e-4
    k = np.array([[1, -1, -1], [-1, -1, 1], [-1, 1, -1], [1, 1, 1]], float)
    n = np.zeros_like(p)
    for kk in k:
        n += kk * scene(p + kk * e)[..., None]
    return normalize(n)


def soft_shadow(ro, rd, mint=0.02, maxt=6.0, k=26.0, steps=96):
    res = np.ones(ro.shape[0])
    t = np.full(ro.shape[0], mint)
    for _ in range(steps):
        h = scene(ro + rd * t[:, None])
        res = np.minimum(res, k * h / t)
        t += np.clip(h, 0.01, 0.25)
        if np.all((res < 0.005) | (t > maxt)):
            break
    res = np.clip(res, 0.0, 1.0)
    return res * res * (3 - 2 * res)


def ambient_occlusion(p, n):
    occ = np.zeros(p.shape[0]); sca = 1.0
    for i in range(6):
        h = 0.01 + 0.16 * i / 5.0
        d = scene(p + n * h)
        occ += (h - d) * sca
        sca *= 0.9
    return np.clip(1.0 - 2.2 * occ, 0.0, 1.0)


def environment(r):
    """Dark photo studio: a big softbox overhead, a thin strip on the left."""
    sky = smoothstep(0.25, 0.95, r[:, 1])[:, None] * np.array([1.0, 0.97, 0.92]) * 1.6
    strip = (smoothstep(0.55, 0.9, -r[:, 0]) * smoothstep(-0.2, 0.3, r[:, 1]))[:, None] \
        * np.array([0.9, 0.95, 1.0]) * 0.30
    # a cool strip on the right: the graphite face picks up a faint sheen
    strip_r = (smoothstep(0.45, 0.95, r[:, 0])
               * smoothstep(-0.95, -0.40, r[:, 1]) * (1 - smoothstep(-0.05, 0.35, r[:, 1])))[:, None] \
        * np.array([0.80, 0.88, 1.0]) * 0.42
    # an edge light behind the cube: grazing bevels on the silhouette reflect it,
    # tracing a thin crisp outline that separates the cube from the dark plate
    back = smoothstep(0.55, 0.97, r[:, 2])[:, None] * np.array([0.86, 0.90, 1.0]) * 1.1
    base = np.array([0.018, 0.018, 0.022])
    return base + sky + strip + strip_r + back


def face_albedo(n_world):
    no = n_world @ R_OW                     # world -> object normal
    w = np.abs(no) ** 6
    w /= w.sum(axis=-1, keepdims=True)
    col = np.zeros_like(no)
    for axis in range(3):
        pos = np.where(no[:, axis] >= 0)[0]
        neg = np.where(no[:, axis] < 0)[0]
        col[pos] += w[pos, axis:axis + 1] * FACE[(axis, +1)]
        col[neg] += w[neg, axis:axis + 1] * FACE[(axis, -1)]
    return col


def shade_object(p, n, v):
    alb = face_albedo(n)
    ao = ambient_occlusion(p, n)
    col = np.zeros_like(p)
    for ldir, lcol, shadowed, spec_k in ((KEY_DIR, KEY_COL, True, 1.0),
                                         (FILL_DIR, FILL_COL, False, 0.5),
                                         (RIM_DIR, RIM_COL, False, 0.5)):
        ndl = np.clip(n @ ldir, 0.0, 1.0)
        if shadowed:
            sh = soft_shadow(p + n * 0.004, np.broadcast_to(ldir, p.shape))
        else:
            sh = np.ones(p.shape[0])
        hvec = normalize(ldir - v)
        spec = np.clip((n * hvec).sum(-1), 0.0, 1.0) ** 140 * 1.25 * spec_k
        col += (alb * ndl[:, None] + spec[:, None]) * lcol * sh[:, None]
    # hemispherical ambient
    col += alb * (0.06 + 0.10 * (0.5 + 0.5 * n[:, 1]))[:, None] * ao[:, None]
    # glossy clear-coat reflection with Schlick fresnel
    r = v - 2.0 * (v * n).sum(-1, keepdims=True) * n
    cosv = np.clip(-(v * n).sum(-1), 0.0, 1.0)
    fres = 0.04 + 0.96 * (1.0 - cosv) ** 5
    col += environment(r) * (fres * ao)[:, None] * 1.35
    return col


def shade_plate(p, v):
    n = np.broadcast_to(np.array([0.0, 0.0, -1.0]), p.shape)
    sh = soft_shadow(p + n * 0.01, np.broadcast_to(SHADOW_DIR, p.shape), k=7.5, maxt=5.0)
    ndl = np.clip(n @ SHADOW_DIR, 0.0, 1.0)
    # a soft pool of light on the plate, top-centre, like a product stage
    glow = np.exp(-((p[:, 0] - CENTER[0]) ** 2 * 0.16 + (p[:, 1] - 1.3) ** 2 * 0.22))
    col = PLATE * (0.9 + 5.0 * glow)[:, None]
    col = col * (0.22 + 0.78 * (ndl * sh)[:, None])
    return col


def tonemap(c):
    # ACES fitted (Narkowicz) + gamma
    a, b, cc, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    c = np.clip((c * (a * c + b)) / (c * (cc * c + d) + e), 0.0, 1.0)
    return np.power(c, 1.0 / 2.2)


def render(n_px: int, fov_deg: float = 24.0) -> np.ndarray:
    ys, xs = np.mgrid[0:n_px, 0:n_px]
    u = (xs + 0.5) / n_px * 2 - 1
    v = -((ys + 0.5) / n_px * 2 - 1)
    focal = 1.0 / np.tan(np.radians(fov_deg) / 2)
    dirs = normalize(np.stack([u, v, np.full_like(u, focal)], -1)).reshape(-1, 3)
    N = dirs.shape[0]

    # sphere-trace the object
    t = np.full(N, 3.0)
    hit = np.zeros(N, bool)
    alive = np.arange(N)
    for _ in range(160):
        p = dirs[alive] * t[alive, None]
        d = scene(p)
        t[alive] += d
        done = d < 2e-4
        hit[alive[done]] = True
        far = t[alive] > PLATE_Z + 1
        alive = alive[~(done | far)]
        if alive.size == 0:
            break

    img = np.zeros((N, 3))
    idx = np.where(hit)[0]
    if idx.size:
        p = dirs[idx] * t[idx, None]
        n = calc_normal(p)
        img[idx] = shade_object(p, n, dirs[idx])
    miss = np.where(~hit)[0]
    tp = PLATE_Z / dirs[miss, 2]
    img[miss] = shade_plate(dirs[miss] * tp[:, None], dirs[miss])
    return tonemap(img).reshape(n_px, n_px, 3)


# ── compositing: squircle plate, rim light, drop shadow ──────────────────────
def squircle_mask(size: int, inset: float, n: float = 5.0) -> np.ndarray:
    ys, xs = np.mgrid[0:size, 0:size]
    c = (size - 1) / 2
    half = size * (1 - 2 * inset) / 2
    x = np.abs(xs - c) / half
    y = np.abs(ys - c) / half
    f = x ** n + y ** n
    return np.clip((1.0 - f) * half * 0.9, 0.0, 1.0)   # ~1px AA edge


def compose(scene_rgb: np.ndarray, size: int, inset: float) -> Image.Image:
    body = squircle_mask(size, inset)
    rgb = np.array(Image.fromarray((scene_rgb * 255).astype(np.uint8)).resize(
        (size, size), Image.LANCZOS)).astype(np.float32) / 255.0

    # hairline glass rim: bright on top, fading down
    ys = np.linspace(0, 1, size)[:, None]
    inner = squircle_mask(size, inset + 0.004)
    rim = np.clip(body - inner, 0, 1) * (0.55 * (1 - ys) ** 2 + 0.06)
    rgb = rgb * (1 - rim[..., None]) + rim[..., None] * 1.0

    rgba = np.dstack([rgb, body])
    icon = Image.fromarray((np.clip(rgba, 0, 1) * 255).astype(np.uint8), "RGBA")

    # soft drop shadow under the plate
    shadow = Image.fromarray((body * 110).astype(np.uint8), "L").filter(
        ImageFilter.GaussianBlur(size * 0.022))
    shadow_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_img.putalpha(shadow)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(shadow_img, (0, int(size * 0.012)))
    canvas.alpha_composite(icon)
    return canvas


def sharpen(img: Image.Image, amount: int) -> Image.Image:
    """Unsharp the RGB only, so the anti-aliased squircle edge stays clean."""
    rgb = img.convert("RGB").filter(ImageFilter.UnsharpMask(radius=1.0, percent=amount, threshold=1))
    rgb.putalpha(img.getchannel("A"))
    return rgb


def small_icon(size: int, inset: float) -> Image.Image:
    """Render a small size natively (4x supersampled) instead of shrinking the
    1024 master, which smears the bevels and edges at 16-64 px."""
    return sharpen(compose(render(size * 4), size, inset), 80)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--ss", type=int, default=3, help="supersampling factor")
    ap.add_argument("--inset", type=float, default=0.06)
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()

    raw = render(a.size * a.ss)
    icon = compose(raw, a.size, a.inset)
    ASSETS.mkdir(exist_ok=True)
    if a.preview:
        out = ASSETS / "icon-preview.png"
        icon.save(out)
        print("wrote", out)
        return
    icon.save(ASSETS / "icon.png")
    sizes = {}
    for s in (512, 256, 128):
        sizes[s] = sharpen(icon.resize((s, s), Image.LANCZOS), 45)
    for s in (64, 48, 32, 24, 16):
        # tiny icons get a slimmer margin so the cube stays legible
        sizes[s] = small_icon(s, a.inset * (0.6 if s <= 32 else 0.8))
    for s in (512, 256, 128, 64, 32, 16):
        sizes[s].save(ASSETS / f"icon-{s}.png")
    ico_sizes = (256, 128, 64, 48, 32, 24, 16)
    sizes[256].save(ASSETS / "sparkx.ico", sizes=[(s, s) for s in ico_sizes],
                    append_images=[sizes[s] for s in ico_sizes[1:]])
    try:
        icon.save(ASSETS / "sparkx.icns", append_images=[sizes[s] for s in (512, 256, 128, 64, 32, 16)])
    except Exception as e:  # pillow builds without icns support
        print("icns skipped:", e)
    print("wrote icon.png, icon-*.png, sparkx.ico, sparkx.icns to", ASSETS)


if __name__ == "__main__":
    main()
