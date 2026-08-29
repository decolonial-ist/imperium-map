#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Оцифровка карт атласа УІФ из векторов PDF по цвету заливки.

Геопривязка берётся из data/atlas/georef.json (строится tools/georef_atlas.py:
LCC + квадратичный варп, ICP белых линий к CShapes-2019; рамка у всех карт
атласа одна, калибровка общая). Обратное отображение px->проекция уточняется
Ньютоном, чтобы снять ошибку квадратичной инверсии в углах листа.

Использование:
  .venv/bin/python tools/digitize_atlas.py --page 145 --color 0.76,0.04,0.15 \
      --out data/atlas/rozd44_ussr_1922.geojson --note "СРСР 1922-1923"
"""
import argparse
import json
import os

import numpy as np
import pymupdf
from shapely.geometry import Polygon, mapping
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
GEOREF = os.path.join(HERE, '..', 'data', 'atlas', 'georef.json')
PDF = os.path.expanduser(
    '~/tmp/MATERIALS/common/Atlas_rosijskogo_imperializmu_i_kolonializmu_UIF_2026/atlas-ua-2.pdf')
DPI = 200
SCALE = DPI / 72.0  # pdf pt -> пиксель рендера


def make_transform():
    """px@200dpi -> lon/lat из georef.json (MLS-сетка локальных подобий)."""
    from georef_atlas import inverse, mls_apply
    g = json.load(open(GEOREF))
    fam, p = g['family'], g['params']
    a = complex(*g['a'])
    b = complex(*g['b'])
    xs0, dxs, nxs = g['mls']['xs']
    ys0, dys, nys = g['mls']['ys']
    xs = xs0 + dxs * np.arange(int(nxs))
    ys = ys0 + dys * np.arange(int(nys))
    Ag = np.array(g['mls']['grid'])

    def px_to_lonlat(coords):
        px = np.asarray(coords, float)
        XY = mls_apply(px, xs, ys, Ag)
        # inverse() ждёт пиксели и сам снимает подобие — подставляем a*XY+b
        z = a * (XY[:, 0] + 1j * XY[:, 1]) + b
        return inverse(np.column_stack([z.real, z.imag]), fam, p, a, b)

    return px_to_lonlat, g


def bezier(p1, c1, c2, p2, n=6):
    out = []
    for i in range(1, n + 1):
        t = i / n
        out.append((
            (1-t)**3*p1.x + 3*(1-t)**2*t*c1.x + 3*(1-t)*t*t*c2.x + t**3*p2.x,
            (1-t)**3*p1.y + 3*(1-t)**2*t*c1.y + 3*(1-t)*t*t*c2.y + t**3*p2.y))
    return out


def extract(page_index, color, min_area_px=400):
    """Полигоны заданной заливки в пикселях рендера; каждый subpath - кольцо."""
    doc = pymupdf.open(PDF)
    page = doc[page_index]
    target = tuple(round(c, 2) for c in color)
    rings = []
    for d in page.get_drawings():
        f = d.get('fill')
        if not f or tuple(round(c, 2) for c in f) != target:
            continue
        ring = []
        last = None
        for item in d['items']:
            kind = item[0]
            if kind == 'l':
                p1, p2 = item[1], item[2]
                if last is None or (p1.x, p1.y) != last:
                    if len(ring) >= 3:
                        rings.append(ring)
                    ring = [(p1.x, p1.y)]
                ring.append((p2.x, p2.y))
                last = (p2.x, p2.y)
            elif kind == 'c':
                p1, c1, c2, p2 = item[1:5]
                if last is None or (p1.x, p1.y) != last:
                    if len(ring) >= 3:
                        rings.append(ring)
                    ring = [(p1.x, p1.y)]
                ring.extend(bezier(p1, c1, c2, p2))
                last = (p2.x, p2.y)
            elif kind == 're':
                r = item[1]
                if len(ring) >= 3:
                    rings.append(ring)
                ring = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
                last = None
        if len(ring) >= 3:
            rings.append(ring)
    polys = []
    for ring in rings:
        try:
            p = Polygon(np.array(ring) * SCALE)
            if p.area >= min_area_px:
                polys.append(p.buffer(0))
        except Exception:
            pass
    print(f"страница {page_index}: колец цвета {target}: {len(rings)}, "
          f"полигонов >= {min_area_px} px²: {len(polys)}")
    return polys


def snap_ring(ll, px, snap_tree, snap_pts, x0, km):
    """Вершины правой половины полотна (px x>x0) магнитятся к современным
    линиям (границы+берега CShapes-2019) в радиусе km — правая страница
    разворота скомпонована вручную, там геометрия атласа не источник."""
    ll = np.asarray(ll, float)
    scale = np.cos(np.radians(np.clip(ll[:, 1], -85, 85))) * 111.0
    q = np.column_stack([ll[:, 0] * scale, ll[:, 1] * 111.0])
    dist, idx = snap_tree.query(q, workers=-1)
    m = (dist < km) & (np.asarray(px)[:, 0] > x0)
    out = ll.copy()
    out[m] = snap_pts[idx[m]]
    return out


def extract_strokes(page_index, color, dashed, min_len_px=30):
    """Полилинии обводки заданного цвета; dashed: True=пунктир, False=сплошная."""
    doc = pymupdf.open(PDF)
    page = doc[page_index]
    target = tuple(round(c, 2) for c in color)
    lines = []
    for d in page.get_drawings():
        c = d.get('color')
        if not c or tuple(round(v, 2) for v in c) != target:
            continue
        is_dashed = bool(d.get('dashes') and d['dashes'].strip() not in ('', '[] 0'))
        if is_dashed != dashed:
            continue
        pl, last = [], None
        for item in d['items']:
            kind = item[0]
            if kind == 'l':
                p1, p2 = item[1], item[2]
                if last is None or (p1.x, p1.y) != last:
                    if len(pl) >= 2:
                        lines.append(pl)
                    pl = [(p1.x, p1.y)]
                pl.append((p2.x, p2.y))
                last = (p2.x, p2.y)
            elif kind == 'c':
                p1, c1, c2, p2 = item[1:5]
                if last is None or (p1.x, p1.y) != last:
                    if len(pl) >= 2:
                        lines.append(pl)
                    pl = [(p1.x, p1.y)]
                pl.extend(bezier(p1, c1, c2, p2))
                last = (p2.x, p2.y)
        if len(pl) >= 2:
            lines.append(pl)
    out = []
    for pl in lines:
        a = np.array(pl) * SCALE
        length = np.hypot(*np.diff(a, axis=0).T).sum()
        if length >= min_len_px:
            out.append(a)
    print(f"страница {page_index}: полилиний цвета {target} "
          f"({'пунктир' if dashed else 'сплошная'}): {len(out)}")
    return out


def to_geo(polys, tr, simplify_deg=0.0, snap=None):
    merged = unary_union(polys)
    geoms = list(merged.geoms) if merged.geom_type == 'MultiPolygon' else [merged]
    out = []
    for g in geoms:
        def ring(coords):
            px = list(coords)
            ll = tr(px)
            if snap:
                ll = snap_ring(ll, px, *snap)
            return ll.tolist()
        p = Polygon(ring(g.exterior.coords),
                    [ring(h.coords) for h in g.interiors]).buffer(0)
        if simplify_deg:
            p = p.simplify(simplify_deg).buffer(0)
        if not p.is_empty:
            out.append(p)
    return out


def build_snap(x0=1600.0, km=80.0):
    """Референс для снапа: все кольца стран CShapes-2019 (границы + берега)."""
    from scipy.spatial import cKDTree
    src = os.path.join(HERE, '..', 'cache', 'cshapes20.geojson')
    d = json.load(open(src))
    pts = []
    for f in d['features']:
        if f['properties'].get('gweyear', 0) < 2019:
            continue
        g = f['geometry']
        polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        for poly in polys:
            for ring in poly:
                r = np.array(ring)
                if r[:, 0].max() < 3 or r[:, 0].min() > 179 or r[:, 1].max() < 4:
                    continue
                for i in range(len(r) - 1):
                    a, b = r[i], r[i + 1]
                    n = max(1, int(np.hypot(*(b - a)) / 0.05))
                    if n > 400:
                        continue
                    for t in np.linspace(0, 1, n, endpoint=False):
                        pts.append(a + (b - a) * t)
    pts = np.array(pts)
    tgt = np.column_stack([pts[:, 0] * np.cos(np.radians(pts[:, 1])) * 111.0,
                           pts[:, 1] * 111.0])
    return cKDTree(tgt), pts, x0, km


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--page', type=int, required=True, help='0-based индекс страницы PDF')
    ap.add_argument('--color', required=True, help='r,g,b заливки (0..1)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--note', default='', help='что за слой (в properties)')
    ap.add_argument('--min-area', type=float, default=400)
    ap.add_argument('--simplify', type=float, default=0.02,
                    help='упрощение в градусах (0 = не упрощать)')
    ap.add_argument('--stroke', choices=['solid', 'dashed'],
                    help='режим линий: оцифровать обводку цвета --color '
                         '(LineString), а не заливку')
    ap.add_argument('--exclude', action='append', default=[],
                    help='x0,y0,x1,y1 px@200dpi — выбросить полигоны с центроидом '
                         'внутри (легенды); можно повторять')
    ap.add_argument('--snap-km', type=float, default=0,
                    help='магнит к линиям CShapes-2019 (0 = выкл)')
    ap.add_argument('--snap-x0', type=float, default=1600,
                    help='снапить только вершины правее этого px (правая страница)')
    args = ap.parse_args()

    import sys
    sys.path.insert(0, HERE)
    tr, g = make_transform()
    color = tuple(float(v) for v in args.color.split(','))
    r = g['residuals_px']
    georef_note = (f"{g['family']}+варп+MLS, резидуалы px q50={r['q50']} "
                   f"q90={r['q90']} (~{g['km_per_px']} км/px)")

    if args.stroke:
        from shapely.geometry import LineString
        strokes = extract_strokes(args.page, color, args.stroke == 'dashed')
        rects = [tuple(float(v) for v in rect.split(',')) for rect in args.exclude]
        feats = []
        for a in strokes:
            cx, cy = a.mean(axis=0)
            if any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in rects):
                continue
            ls = LineString(tr(a))
            if args.simplify:
                ls = ls.simplify(args.simplify)
            feats.append({"type": "Feature", "geometry": mapping(ls),
                          "properties": {"note": args.note,
                                         "source": f"Атлас УІФ (2026), PDF стр. {args.page}, "
                                                   f"обводка {args.color} ({args.stroke})",
                                         "georef": georef_note}})
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump({"type": "FeatureCollection", "features": feats}, f, ensure_ascii=False)
        print(f"OK {args.out}: линий {len(feats)}")
        return

    polys = extract(args.page, color, args.min_area)
    for rect in args.exclude:
        x0, y0, x1, y1 = (float(v) for v in rect.split(','))
        polys = [p for p in polys
                 if not (x0 <= p.centroid.x <= x1 and y0 <= p.centroid.y <= y1)]
    snap = build_snap(args.snap_x0, args.snap_km) if args.snap_km else None
    geo = to_geo(polys, tr, args.simplify, snap)
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": mapping(p),
         "properties": {
             "note": args.note,
             "source": f"Атлас УІФ (2026), PDF стр. {args.page}, заливка {args.color}",
             "georef": (f"{g['family']}+варп, резидуалы px q50={r['q50']} "
                        f"q90={r['q90']} (~{g['km_per_px']} км/px)")}}
        for p in geo]}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(fc, f, ensure_ascii=False)
    b = unary_union(geo).bounds
    print(f"OK {args.out}: фич {len(geo)}, bbox lon {b[0]:.1f}..{b[2]:.1f}, "
          f"lat {b[1]:.1f}..{b[3]:.1f}")


if __name__ == '__main__':
    main()
