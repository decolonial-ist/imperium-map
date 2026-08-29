#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка: нет ли в срезах кусков империи, лежащих в море.

ЗАЧЕМ. Куратор 28.08.2026, глядя на срез 1450 года: «что там за вздроч на
берегу северного ледовитого океана?» - и следом: «такие же артефакты на
побережье есть в магаданской области камчатке и чукотке. проверяй все».

Контуры источников (historical-basemaps, CShapes) нарисованы грубее
современной береговой линии. После вычитаний вдоль побережья остаются узкие
полоски, целиком лежащие в воде: на карте они читаются как владения империи на
берегу океана, хотя это шов между двумя разными береговыми линиями. Полоски
уже, чем припуск margin=0.05 у clip_to_land, поэтому обрезкой по суше они не
снимаются.

ПЕРЕДЕЛКА 29.08.2026. Первая версия считала долю суши по объединению Natural
Earth admin-1 и печатала каждый кусок на каждом срезе: 2958 строк на 99
реальных мест, всегда красная, 8 минут счёта - как сигнал не работала. Была
гипотеза, что среди срабатываний есть ложные - мелкие острова, которых нет в
грубой маске. Проверено по точной воде NE 10m (океан + озёра, острова Св.
Лаврентия, Кинг, Диомиды, Симушир там есть): ВСЕ найденные места и по ней
лежат в воде на 82-100%. Ложных срабатываний нет, это настоящие морские
полоски. Теперь проверка:
  - меряет долю ВОДЫ по NE 10m (океан + озёра) вместо доли суши по admin-1;
  - группирует куски по МЕСТУ (пересечение bbox) и считает места, а не строки;
  - сверяет места с базлайном data/crosscheck/sea_crumbs_baseline.json:
    известные места - зелёная сводка, НОВОЕ место или вдвое выросшее - красная;
  - куски крупнее MAX_PART_KM2 не проверяет вовсе (материк и большие острова;
    морской обрезок такого размера был бы виден на карте без всякой проверки).

Запуск: .venv/bin/python tools/check_sea_crumbs.py
  --rebaseline   перезаписать базлайн текущим состоянием (после пересборки,
                 когда часть мест починена; сначала глазами по карте)
  --places       напечатать все места таблицей, не только новые

Падает с кодом 1, если есть места, которых нет в базлайне, или известное
место выросло больше чем вдвое. Базлайна нет - тоже красная: сначала
--rebaseline по разобранному состоянию.
"""
import argparse
import json
import math
import os
import sys

from shapely.geometry import shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(ROOT, 'cache')
BASELINE = os.path.join(DATA, 'crosscheck', 'sea_crumbs_baseline.json')
WATER_LIMIT = 0.8        # доля воды, выше которой кусок считаем морским
MIN_AREA = 1e-4          # ~1 км²: мельче - шум округления, не смотрим
MAX_PART_KM2 = 5000.0    # крупнее - материк или большой остров, не обрезок
GAP = 0.1                # зазор склейки кусков в одно место, градусы


def km2(g):
    lat = (g.bounds[1] + g.bounds[3]) / 2
    return g.area * (111.32 ** 2) * math.cos(math.radians(lat))


def water_polys():
    """Вода NE 10m: океан + озёра (Каспий и Арал - тоже вода)."""
    polys = []
    for name in ('ne_10m_ocean.geojson', 'ne_10m_lakes.geojson'):
        with open(os.path.join(CACHE, name), encoding='utf-8') as f:
            for ft in json.load(f)['features']:
                g = shape(ft['geometry']).buffer(0)
                polys.extend(g.geoms if g.geom_type == 'MultiPolygon' else [g])
    return polys


def water_share(p, tree, polys):
    """Доля площади куска, лежащая в воде. Пересекаем только соседние
    полигоны воды по STRtree: с полной маской проверка шла 8 минут."""
    idx = tree.query(p)
    if len(idx) == 0:
        return 0.0
    w = sum(p.intersection(polys[i]).area for i in idx)
    return min(w / p.area, 1.0)


def boxes_touch(a, b, gap=GAP):
    return not (a[2] < b[0] - gap or a[0] > b[2] + gap or
                a[3] < b[1] - gap or a[1] > b[3] + gap)


def collect_places():
    """Пройти все срезы, вернуть список мест: bbox, макс площадь, срезы."""
    polys = water_polys()
    tree = STRtree(polys)
    with open(os.path.join(DATA, 'manifest.json'), encoding='utf-8') as f:
        years = json.load(f)['years']

    places, checked, skipped_big = [], 0, 0
    for key in years:
        path = os.path.join(DATA, 'years', str(key) + '.geojson')
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8') as f:
            fc = json.load(f)
        g = unary_union([shape(ft['geometry']).buffer(0)
                         for ft in fc['features']])
        parts = list(g.geoms) if g.geom_type == 'MultiPolygon' else [g]
        checked += 1
        for p in parts:
            if p.area < MIN_AREA:
                continue
            a = km2(p)
            if a > MAX_PART_KM2:
                skipped_big += 1
                continue
            if water_share(p, tree, polys) < WATER_LIMIT:
                continue
            b = p.bounds
            hit = None
            for pl in places:
                if boxes_touch(b, pl['bbox']):
                    hit = pl
                    break
            if hit is None:
                hit = {'bbox': list(b), 'km2': 0.0, 'keys': set()}
                places.append(hit)
            hit['keys'].add(str(key))
            hit['bbox'] = [min(hit['bbox'][0], b[0]), min(hit['bbox'][1], b[1]),
                           max(hit['bbox'][2], b[2]), max(hit['bbox'][3], b[3])]
            hit['km2'] = max(hit['km2'], a)
    return places, checked, skipped_big


def nearest_names(places):
    """Имя ближайшей современной единицы - только для отчёта. admin-1 весит
    40 МБ, поэтому грузим его единожды и только когда есть что называть."""
    if not places:
        return places
    with open(os.path.join(CACHE, 'ne_admin1.geojson'), encoding='utf-8') as f:
        ne = json.load(f)['features']
    cents = [shape(ft['geometry']).buffer(0).centroid for ft in ne]
    names = [ft['properties'].get('name') or ft['properties'].get('admin')
             for ft in ne]
    tree = STRtree(cents)
    for pl in places:
        cx = (pl['bbox'][0] + pl['bbox'][2]) / 2
        cy = (pl['bbox'][1] + pl['bbox'][3]) / 2
        from shapely.geometry import Point
        pl['near'] = names[tree.nearest(Point(cx, cy))]
    return places


def fmt_place(pl):
    bb = [round(v, 2) for v in pl['bbox']]
    n = len(pl['keys']) if isinstance(pl['keys'], set) else pl['keys']
    return (f"  {pl['km2']:6.0f} км²  срезов {n:3d}  {bb}  "
            f"рядом: {pl.get('near', '?')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rebaseline', action='store_true',
                    help='перезаписать базлайн текущим состоянием')
    ap.add_argument('--places', action='store_true',
                    help='напечатать все места, не только новые')
    args = ap.parse_args()

    places, checked, skipped_big = collect_places()
    places.sort(key=lambda pl: -pl['km2'])
    print(f'срезов проверено: {checked}, морских мест: {len(places)} '
          f'(кусков крупнее {MAX_PART_KM2:.0f} км² не смотрим, '
          f'таких {skipped_big})')

    if args.rebaseline:
        nearest_names(places)
        os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
        with open(BASELINE, 'w', encoding='utf-8') as f:
            json.dump({
                'written': '2026-08-29',
                'note': ('зафиксированные морские полоски: швы грубых контуров '
                         'против береговой линии NE 10m, все в воде на '
                         '82-100%. Лечение - пересборка с clip_to_land/'
                         'drop_thin_parts и разбор островов Русской Америки '
                         'у куратора. Место починили - перезапишите базлайн '
                         '(--rebaseline) и сверьте, что мест стало меньше.'),
                'places': [{'bbox': [round(v, 4) for v in pl['bbox']],
                            'km2': round(pl['km2'], 1),
                            'slices': len(pl['keys']),
                            'near': pl['near']} for pl in places],
            }, f, ensure_ascii=False, indent=1)
        print(f'базлайн переписан: {os.path.relpath(BASELINE, ROOT)}, '
              f'мест {len(places)}')
        for pl in places[:10]:
            print(fmt_place(pl))
        if len(places) > 10:
            print(f'  ... и ещё {len(places) - 10} (--places покажет все)')
        return 0

    if not os.path.exists(BASELINE):
        print('!! базлайна нет: разберите места глазами и зафиксируйте их '
              'через --rebaseline')
        nearest_names(places)
        for pl in places:
            print(fmt_place(pl))
        return 1

    with open(BASELINE, encoding='utf-8') as f:
        base = json.load(f)
    known = base['places']

    new, grown = [], []
    for pl in places:
        match = None
        for kn in known:
            if boxes_touch(pl['bbox'], kn['bbox']):
                match = kn
                break
        if match is None:
            new.append(pl)
        elif pl['km2'] > match['km2'] * 2 and pl['km2'] - match['km2'] > 25:
            grown.append((pl, match))

    gone = []
    for kn in known:
        if not any(boxes_touch(pl['bbox'], kn['bbox']) for pl in places):
            gone.append(kn)

    if args.places:
        nearest_names(places)
        for pl in places:
            print(fmt_place(pl))

    print(f"базлайн {base['written']}: известных мест {len(known)}, "
          f'сейчас {len(places)}, новых {len(new)}, выросших {len(grown)}, '
          f'починенных {len(gone)}')
    if gone:
        print('  починенные (можно вычистить из базлайна через --rebaseline):')
        for kn in gone[:10]:
            print(f"    {kn['km2']:6.0f} км²  {kn['bbox']}  рядом: {kn['near']}")
    if new or grown:
        nearest_names([pl for pl in new + [g[0] for g in grown]
                       if 'near' not in pl])
        if new:
            print('!! НОВЫЕ морские места (в базлайне их нет):')
            for pl in new:
                print(fmt_place(pl))
        for pl, kn in grown:
            print(f"!! место у «{kn['near']}» выросло: было {kn['km2']:.0f} км², "
                  f"стало {pl['km2']:.0f} км²  {[round(v, 2) for v in pl['bbox']]}")
        return 1
    print('итог: ok - новых морских мест нет')
    return 0


if __name__ == '__main__':
    sys.exit(main())
