#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка геометрии срезов: артефакты, которые видны на карте глазами.

ЗАЧЕМ (03.09.2026, луп по артефактам). Куратор раз за разом ловил на карте
одно и то же: прямые «по линейке», квадраты рамок, ленты вдоль берега, дырки-
швы, шипы, красные островки-обрезки. Девять прежних чекеров смотрят даты и
точки, а форму контура не смотрит ни один. Этот считает по всем срезам
манифеста:
  straight   - отрезки >= 40 км вне берега (оба конца дальше 0,03° от воды);
  axis       - отрезки >= 20 км строго по параллели или меридиану;
  corner     - прямые углы из двух осевых отрезков >= 10 км;
  sliver     - куски < 5 км² или ленты (компактность < 0,06 при < 300 км²);
  hole       - дырки >= 50 км²;
  spike      - шипы: угол при вершине < 12° при плечах >= 15 км;
  meridian180- отрезки >= 5 км по ±180°;
  island     - отдельные куски 5-20 000 км² (не главный полигон);
  empty      - пустые полигоны в файле;
  multi      - несколько соприкасающихся фич ядра в срезе (внутренние швы).
Находки группируются по МЕСТАМ (кластер 0,5°) и сверяются с базлайном
data/crosscheck/geometry_baseline.json: новое место или место, выросшее по
числу срезов больше чем на 20 %, - красная. Настоящие острова и
содержательные дырки (Рязань до 1521, Бараба, Кабарда) в базлайне и потому
зелёные - базлайн честно перечисляет, что мы терпим.

Запуск: .venv/bin/python tools/check_geometry.py [--rebaseline] [--places]
Отчёт: data/crosscheck/geometry_report.md. Код 1 - есть новые места.
"""
import argparse
import collections
import json
import math
import os
import sys

from shapely.geometry import Polygon, shape
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geoclean as gc  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(ROOT, 'cache')
BASELINE = os.path.join(DATA, 'crosscheck', 'geometry_baseline.json')
REPORT = os.path.join(DATA, 'crosscheck', 'geometry_report.md')
TYPES = ['straight', 'axis', 'corner', 'sliver', 'hole', 'spike', 'meridian180',
         'island', 'empty', 'multi']


def km(a, b):
    lat = math.radians((a[1] + b[1]) / 2)
    return math.hypot((b[0] - a[0]) * 111.32 * math.cos(lat), (b[1] - a[1]) * 111.32)


def km2(area, lat):
    return area * 111.32 ** 2 * math.cos(math.radians(lat))


_sea = {}


def near_water(pt, tol=0.03):
    """Точка ближе tol от океана/озёр по NE 10m (маска океана нарезана тайлами)."""
    from shapely.geometry import Point
    if 'tree' not in _sea:
        _sea['tree'], _sea['parts'] = gc._sea_tree(CACHE)
        _sea['lakes'] = gc.lakes_mask(CACHE)
    p = Point(pt)
    for i in _sea['tree'].query(p.buffer(tol)):
        if _sea['parts'][i].distance(p) < tol:
            return True
    lk = _sea['lakes']
    return lk is not None and lk.distance(p) < tol


def scan_slice(key):
    fc = json.load(open(os.path.join(DATA, 'years', key + '.geojson'), encoding='utf-8'))
    rows = []
    parts = []
    core = [f for f in fc['features'] if f.get('geometry')
            and (f.get('properties') or {}).get('role', 'core') == 'core']
    if len(core) > 1:
        gs = [shape(f['geometry']).buffer(0) for f in core]
        touch = sum(1 for i in range(len(gs)) for j in range(i + 1, len(gs)) if gs[i].intersects(gs[j]))
        if touch:
            rows.append(('multi', 0.0, 0.0, touch))
    for f in fc['features']:
        g = f['geometry']
        if not g:
            continue
        polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        for poly in polys:
            if not poly or len(poly[0]) < 4:
                rows.append(('empty', 0.0, 0.0, 0))
                continue
            shell = Polygon(poly[0])
            c = shell.centroid
            a_km2 = km2(shell.area, c.y)
            parts.append((a_km2, c.x, c.y))
            compact = 4 * math.pi * shell.area / shell.length ** 2 if shell.length else 1
            if a_km2 < 5 or (compact < 0.06 and a_km2 < 300):
                rows.append(('sliver', c.x, c.y, a_km2))
            for hole in poly[1:]:
                hp = Polygon(hole)
                if hp.area > 0:
                    h_km2 = km2(hp.area, hp.centroid.y)
                    if h_km2 >= 50:
                        rows.append(('hole', hp.centroid.x, hp.centroid.y, h_km2))
            for ring in poly:
                n = len(ring)
                for i in range(n - 1):
                    a, b = ring[i], ring[i + 1]
                    d = km(a, b)
                    if abs(abs(a[0]) - 180) < 1e-6 and abs(abs(b[0]) - 180) < 1e-6 and d >= 5:
                        rows.append(('meridian180', a[0], (a[1] + b[1]) / 2, d))
                        continue
                    axis = abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9
                    if axis and d >= 20:
                        rows.append(('axis', (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, d))
                    if d >= 40 and not axis:
                        if not near_water(a) and not near_water(b):
                            rows.append(('straight', (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, d))
                    # шип: угол при вершине b
                    if i + 2 < n:
                        c2 = ring[i + 2]
                        d2 = km(b, c2)
                        if d >= 15 and d2 >= 15:
                            v1 = (a[0] - b[0], a[1] - b[1]); v2 = (c2[0] - b[0], c2[1] - b[1])
                            dot = v1[0] * v2[0] + v1[1] * v2[1]
                            n1 = math.hypot(*v1); n2 = math.hypot(*v2)
                            if n1 and n2:
                                ang = math.degrees(math.acos(max(-1, min(1, dot / n1 / n2))))
                                if ang < 12:
                                    rows.append(('spike', b[0], b[1], ang))
                        if d >= 10 and d2 >= 10 and axis:
                            ax2 = abs(b[0] - c2[0]) < 1e-9 or abs(b[1] - c2[1]) < 1e-9
                            if ax2 and (abs(a[0] - b[0]) < 1e-9) != (abs(b[0] - c2[0]) < 1e-9):
                                rows.append(('corner', b[0], b[1], d))
    parts.sort(reverse=True)
    for a_km2, x, y in parts[1:]:
        if 5 <= a_km2 <= 20000:
            rows.append(('island', x, y, a_km2))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rebaseline', action='store_true')
    ap.add_argument('--places', action='store_true', help='печатать все места')
    args = ap.parse_args()
    keys = json.load(open(os.path.join(DATA, 'manifest.json')))['years']
    places = collections.defaultdict(set)
    totals = collections.Counter()
    for k in keys:
        for t, x, y, v in scan_slice(k):
            totals[t] += 1
            places[(t, round(x * 2) / 2, round(y * 2) / 2)].add(k)
    cur = {f'{t}|{x}|{y}': len(ks) for (t, x, y), ks in places.items()}
    base = json.load(open(BASELINE)) if os.path.exists(BASELINE) else None
    lines = [f'# Геометрия срезов: {len(keys)} срезов, находок '
             + ', '.join(f'{t} {totals[t]}' for t in TYPES if totals[t]), '']
    bad = []
    if base:
        for k, n in cur.items():
            b = base.get(k)
            if b is None:
                bad.append((k, n, 0))
            elif n > b * 1.2 + 1:
                bad.append((k, n, b))
        gone = [k for k in base if k not in cur]
        lines.append(f'базлайн: мест {len(base)}, сейчас {len(cur)}, новых или выросших '
                     f'{len(bad)}, исчезло {len(gone)}')
        for k, n, b in sorted(bad, key=lambda r: -r[1])[:60]:
            lines.append(f'- НОВОЕ/ВЫРОСЛО {k}: срезов {n} (было {b})')
    if args.places or not base:
        lines.append('')
        for (t, x, y), ks in sorted(places.items(), key=lambda kv: (kv[0][0], -len(kv[1]))):
            ks = sorted(ks)
            lines.append(f'- {t} {x},{y}: срезов {len(ks)} ({ks[0]} .. {ks[-1]})')
    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines[:3 + min(len(bad), 20)]))
    if args.rebaseline or not base:
        with open(BASELINE, 'w', encoding='utf-8') as f:
            json.dump(cur, f, ensure_ascii=False, indent=0, sort_keys=True)
        print(f'базлайн записан: {len(cur)} мест -> {BASELINE}')
        return 0
    if bad:
        print(f'!! новых или выросших мест: {len(bad)} (см. {REPORT})')
        return 1
    print('ok: новых мест нет')
    return 0


if __name__ == '__main__':
    sys.exit(main())
