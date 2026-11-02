#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Граница Украины для показа: суша + берег Крыма + Керченский пролив (куратор 01.11.2026).

Исходник - data/borders/ukraine_osm_sea.geojson (выгрузка tools/fetch_borders.py,
контур с морской границей). В нём линия у берегов идёт по морской границе, и в
Азове получалось кольцо. Морские участки снимаются; Крым обводится по берегу
маски суши OSM (cache/osm_land/mask.pkl), перешейки не пересекаются. В проливе
остаётся линия отношения, с обходом косы Тузла с востока; концы её замкнуты на
берег у северного и южного выхода из пролива.

Запуск: .venv/bin/python3 tools/build_ua_coast_border.py
Пишет data/borders/ukraine_osm.geojson.
"""
import json, os, pickle, sys
from shapely import wkb
from shapely.geometry import LineString, MultiLineString, Point, box, mapping, shape
from shapely.ops import linemerge, nearest_points, polygonize, unary_union

ROOT = os.path.join(os.path.dirname(__file__), '..')
SRC = os.path.join(ROOT, 'data/borders/ukraine_osm_sea.geojson')
OUT = os.path.join(ROOT, 'data/borders/ukraine_osm.geojson')
MASK = os.path.join(ROOT, 'cache/osm_land/mask.pkl')
TOL = 0.0015
KINDS_LAND = ('land', 'L', 1)
# где Крым отрезается от материка при выборе берега: Перекоп и Арабатская стрелка
ISTHMUS = [LineString([(33.58, 46.13), (34.08, 46.13)]), LineString([(34.6, 45.97), (35.5, 45.97)])]
STRAIT_Y = (45.095, 45.42)              # широты, между которыми в проливе берег заменён линией


def main():
    src = shape(json.load(open(SRC, encoding='utf-8'))['features'][0]['geometry'])
    ring = max(src.geoms, key=lambda g: g.length)
    area = unary_union(list(polygonize(src)))
    cells = pickle.load(open(MASK, 'rb'))['cells']
    win = box(31.5, 44, 37.5, 46.6)
    parts = []
    for (x, y), (kind, lw, sw) in cells.items():
        c = box(x, y, x + 1, y + 1)
        if not c.intersects(win):
            continue
        if lw:
            parts.append(wkb.loads(lw))
        elif not sw and kind in KINDS_LAND:
            parts.append(c)
    land = unary_union(parts).intersection(win).buffer(0)

    # суша Крыма: разрезаем по перешейкам и берём кусок с Симферополем
    cutter = unary_union([c.buffer(0.0005) for c in ISTHMUS])
    pieces = land.difference(cutter)
    geoms = list(pieces.geoms) if pieces.geom_type == 'MultiPolygon' else [pieces]
    crimea = next(g for g in geoms if g.contains(Point(34.1, 44.95)))
    near = crimea.buffer(0.15)
    isles = [g for g in geoms if g is not crimea and near.contains(g) and g.area > 2e-4
             and g.representative_point().y < 45.9]
    coast = unary_union([crimea.exterior] + [g.exterior for g in isles])
    coast = coast.difference(cutter.buffer(0.001))       # линии разреза в берег не идут

    # пролив: линия отношения между широтами
    sy, ny = STRAIT_Y
    pts = list(ring.coords)
    hole = box(36.3, sy, 37.2, ny)
    idx = [i for i, p in enumerate(pts) if 36.3 < p[0] < 37 and sy - 0.3 <= p[1] <= ny + 0.3]
    strait = LineString(pts[min(idx):max(idx) + 1]).intersection(hole)
    strait = max(strait.geoms, key=lambda g: g.length) if hasattr(strait, 'geoms') else strait
    coast = coast.difference(hole)
    # замыкаем концы линии на берег
    links = []
    for end in (Point(strait.coords[0]), Point(strait.coords[-1])):
        links.append(LineString([end, nearest_points(end, coast)[1]]))

    # суша: участки контура, которые не в море
    # морские участки контура = всё между стыком с Россией у Азова и устьем Дуная
    a = min(range(len(pts)), key=lambda i: Point(pts[i]).distance(Point(38.23, 47.11)))
    b = min(range(len(pts)), key=lambda i: Point(pts[i]).distance(Point(29.67, 45.22)))
    print('стыки', a, pts[a], b, pts[b], 'всего', len(pts))
    lo, hi = sorted((a, b))
    landline = [LineString(pts[hi:] + pts[:lo + 1])]
    all_lines = landline + [strait] + links + [g for g in getattr(coast, 'geoms', [coast])]
    merged = linemerge(unary_union([l for l in all_lines if l.length > 0]))
    if merged.geom_type == 'LineString':
        merged = MultiLineString([merged])
    simp = MultiLineString([g.simplify(TOL, preserve_topology=True) for g in merged.geoms])

    # проверки до записи
    bad = []
    if simp.intersects(LineString([(33.72, 46.11), (33.95, 46.11)])):
        bad.append('линия режет Перекоп')
    if simp.intersects(box(35.5, 45.9, 36.4, 46.2)) or simp.intersects(box(36.7, 45.5, 37.6, 46.3)):
        bad.append('осталась линия в Азове')
    if simp.distance(Point(36.6, 45.25)) > 0.1:
        bad.append('нет линии в проливе')
    if bad:
        sys.exit('ПРОВЕРКИ НЕ СОШЛИСЬ, файл не записан: ' + '; '.join(bad))
    d = json.load(open(SRC, encoding='utf-8'))
    d['features'][0]['geometry'] = mapping(simp)
    d['features'][0]['properties']['note'] = ('морские участки сняты 01.11.2026: Крым по берегу '
                                             'маски суши OSM, в проливе линия отношения')
    json.dump(d, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('кусков', len(simp.geoms), 'точек', sum(len(g.coords) for g in simp.geoms),
          'КБ', os.path.getsize(OUT) // 1024, [round(g.length, 2) for g in simp.geoms][:12], 'островов', len(isles))


if __name__ == '__main__':
    main()
