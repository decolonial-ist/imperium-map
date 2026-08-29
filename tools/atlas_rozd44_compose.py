#!/usr/bin/env python3
"""Сборка слоя «СССР 1922-1923» (атлас УІФ, розд. 44) из двух источников.

Запад (lon < ~100°): оцифровка атласа (data/atlas/rozd44_ussr_1922.geojson) —
там все содержательные границы 1922 г. (западная граница, Бессарабия вне,
Карс турецкий, Тува вне) и калибровка хорошая (q50 ~9 px).

Восток (lon > ~100°): правый лист разворота свёрстан вручную, проекции не
имеет, геометрия атласа там не источник. Но информационно граница СССР 1922
восточнее 100°E = современная граница РФ (CShapes-2019) минус атласные вычеты:
Южный Сахалин (японский, срез по 50°N), Курилы (японские). Тува (вне СССР до
1944) лежит западнее шва и остаётся атласной.

Шов с перекрытием в 1°, чтобы береговые расхождения источников слились.
"""
import json
import os

import numpy as np
from shapely.geometry import Polygon, MultiPolygon, box, mapping, shape
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
SRC = os.path.join(ROOT, 'data', 'atlas', 'rozd44_ussr_1922.geojson')
CSH = os.path.join(ROOT, 'cache', 'cshapes20.geojson')
OUT = os.path.join(ROOT, 'data', 'atlas', 'ussr_1922.geojson')

SEAM = 101.5          # меридиан шва: восточнее Тувы (она вне СССР до 1944,
OVERLAP = 1.0         # и в совр. РФ есть — восточный кусок не должен её нести)

# вычеты 1922 года на востоке (не входили в СССР)
CUT_SOUTH_SAKHALIN = box(140.8, 45.0, 146.0, 50.0)   # японский с 1905, граница по 50°N
CUT_KURILES = box(145.5, 43.0, 157.0, 50.9)          # японские по 1945


def main():
    west_src = unary_union([shape(f['geometry'])
                            for f in json.load(open(SRC))['features']])
    west = west_src.intersection(box(-180, 0, SEAM + OVERLAP, 89))

    ru = None
    neighbors = []
    # соседи, в 1922 точно вне СССР и с границей, совпадающей с современной
    # (Турция — Карсский договор 1921 = совр. граница): вычитание чинит любые
    # заезды калибровки за границу, ничего легитимного не задевая
    NEVER = {712, 710, 640, 630, 700, 731, 290, 375, 360, 385, 366, 367, 368}
    for f in json.load(open(CSH))['features']:
        pr = f['properties']
        if pr.get('gweyear', 0) < 2019:
            continue
        if pr.get('gwcode') == 365:
            ru = shape(f['geometry'])
        elif pr.get('gwcode') in NEVER:
            neighbors.append(shape(f['geometry']).buffer(0))
    assert ru is not None, 'CShapes: не нашёл Россию-2019 (gwcode 365)'
    east = (ru.intersection(box(SEAM - OVERLAP, 0, 180, 89))
              .difference(CUT_SOUTH_SAKHALIN)
              .difference(CUT_KURILES))
    # арктическая полоса левого листа: берег там зажат плашкой заголовка атласа,
    # а политических границ нет — берём современный берег (1922 = 2019)
    arctic = ru.intersection(box(65, 68, SEAM + OVERLAP, 89))

    # Танну-Тува (вне СССР до 1944): лежит на сгибе разворота, её вырезка в
    # оцифровке смещена — вычитаем современный контур (Natural Earth admin-1)
    tuva = unary_union([shape(f['geometry']) for f in json.load(
        open(os.path.join(ROOT, 'cache', 'tuva_ne10m.geojson')))['features']])

    merged = unary_union([west, arctic, east])
    merged = (merged.difference(unary_union(neighbors))
                    .difference(tuva.buffer(0.02))
                    .simplify(0.02).buffer(0))
    geoms = list(merged.geoms) if merged.geom_type == 'MultiPolygon' else [merged]
    geoms = [g for g in geoms if g.area > 0.01]

    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": mapping(g), "properties": {
            "note": "СССР 1922-1923 (розд. 44 атласа УІФ)",
            "west_of_100E": "оцифровка атласа (georef q50 ~9 px = ~30 км)",
            "east_of_100E": ("реконструкция: граница РФ CShapes-2019 минус "
                             "Юж. Сахалин (50°N) и Курилы; правый лист "
                             "разворота свёрстан вручную и как геометрия "
                             "непригоден"),
        }} for g in geoms]}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(fc, f, ensure_ascii=False)
    b = merged.bounds
    print(f"OK {os.path.relpath(OUT, ROOT)}: фич {len(geoms)}, "
          f"bbox lon {b[0]:.1f}..{b[2]:.1f}, lat {b[1]:.1f}..{b[3]:.1f}")


if __name__ == '__main__':
    main()
