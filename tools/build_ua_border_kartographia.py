#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Граница Украины для показа - по официальному контуру ДНВП «Картографія» (07.11.2026).

Куратор 07.11.2026 об островах Херсонщины вне линии: «эти острова выше - они не
украинские? где ты вообще видел чтобы так как ты нарисовал границу кто-то еще ее
рисовал? найди официальные украинские карты по ним сделай».

Источник - Ukraine Subnational Administrative Boundaries (COD-AB), HDX,
https://data.humdata.org/dataset/cod-ab-ukr, данные ДНВП «Картографія»
(State Scientific Production Enterprise "Kartographia"), valid_on 2025-09-01,
лицензия CC BY-IGO. Копия - ~/tmp/MAP-MATERIALS/kartographia_hdx_2026/.
У «Картографії» государственная граница (adm_level 0 в ukr_adminlines) идёт
только по суше, в море линии нет; берег с островами и Керченским проливом -
отдельная береговая линия (adm_level 99). Контур показа = граница ukr_admin0
целиком: сухопутная граница + берег со всеми островами (Джарылгач, Сиваш,
Арабатская стрелка, Тузла, Змеиный). Морской границы и линии в проливе нет -
как на официальной карте.

Запуск: .venv/bin/python3 tools/build_ua_border_kartographia.py
Пишет data/borders/ukraine_kartographia.geojson (упрощение TOL с сохранением топологии).
"""
import json, os
from shapely.geometry import shape, mapping, MultiLineString
from shapely.ops import unary_union

ROOT = os.path.join(os.path.dirname(__file__), '..')
SRC = os.path.expanduser('~/tmp/MAP-MATERIALS/kartographia_hdx_2026/ukr_admin0.geojson')
OUT = os.path.join(ROOT, 'data/borders/ukraine_kartographia.geojson')
TOL = 0.0015


def main():
    fc = json.load(open(SRC, encoding='utf-8'))
    g = shape(fc['features'][0]['geometry']).buffer(0)
    g = g.simplify(TOL, preserve_topology=True)
    lines = []
    for p in (g.geoms if g.geom_type == 'MultiPolygon' else [g]):
        lines.append(p.exterior)
        lines.extend(p.interiors)
    ml = unary_union(MultiLineString([l for l in lines]))
    out = {'type': 'FeatureCollection',
           'properties': {'source': 'HDX cod-ab-ukr, SSPE Kartographia, valid_on 2025-09-01, CC BY-IGO',
                          'note': 'граница по суше + берег с островами; морской границы нет, как у Картографии'},
           'features': [{'type': 'Feature', 'properties': {'name': 'Україна'}, 'geometry': mapping(ml)}]}
    s = json.dumps(out, ensure_ascii=False, separators=(',', ':'))
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(s)
    n = sum(len(x.coords) for x in (ml.geoms if hasattr(ml, 'geoms') else [ml]))
    print(f'{OUT}: {len(s)//1024} КБ, частей {len(ml.geoms) if hasattr(ml, "geoms") else 1}, вершин {n}')


if __name__ == '__main__':
    main()
