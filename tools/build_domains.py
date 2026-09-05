#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Рамки доменов для встраиваемых карт (задача куратора 31.08.2026).

Встраиваемая карта - это та же карта, но с камерой, запертой на территории
одного народа: в базе знаний она стоит рядом с матрицей домена, а следующим
этапом - на странице кампании. Здесь собирается ОПИСАНИЕ РАМКИ, по одному
файлу на домен: data/domains/<domain>.json.

Что такое рамка. Это не утверждение о границе и НЕ рисуется на карте (решение
куратора 31.08.2026: «обычная карта, держит только камера»). Контур нужен,
чтобы посчитать, (1) куда смотреть, (2) докуда пускать камеру, (3) какие
изменения на карте считать «своими» - последнее делает build_domain_stops.py.
Соседи вокруг рисуются как в полной карте.

Откуда контуры (решения куратора 31.08.2026):

ИМЕНА ДОМЕНОВ - имена НАРОДОВ, как в базе знаний (втык куратора 31.08.2026:
«нохчи это народ, украина это государство»). Берём канонические слаги матриц
сайта, modules/matrices/matrices_config.py: nokhchi и ukrainians. Легаси-имена
внутри карты (data/campaigns/ukraina.json и прочее) не трогаем - это наша
кухня, наружу она не выходит.

- nokhchi - территория ЧРИ: как чеченцы определили её в последний раз и как её
  признают оккупированной (заявление Верховной Рады Украины № 2672-IX от
  18.10.2022 - ЧРИ признана временно оккупированной Россией). Ингушетия в ЧРИ
  не входила: республики разошлись в 1991-1992 годах. Геометрию берём из
  Natural Earth admin-1 (cache/ne_admin1.geojson, name='Chechnya'): своей
  оцифровки границ ЧРИ у нас нет, а разница с ней - край в несколько
  километров (справочная площадь ЧРИ 17 300 км², нынешней Чеченской
  Республики - 16 171 км²), и на рамку с запасом она не влияет. ОТКРЫТО и
  записано в TASK_EMBED_MAPS_2026-08-31.md: Сунженский и Малгобекский районы
  (спор с Ингушетией) и Ауховский (Новолакский) район Дагестана.

- ukrainians - границы 1991 года: контур Ukraine из cache/cshapes20.geojson с
  окном 25.12.1991-16.03.2014, то есть С КРЫМОМ (площадь 597 503 км²).

На выходе, кроме контура: bbox, стартовая камера, мягкая и жёсткая зоны для
пружины (index.html, режим встраивания) и окно времени по умолчанию.

Запуск:

    cd ~/tmp/imperium-map && .venv/bin/python3 tools/build_domains.py
"""
import json
import math
import os
import sys

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import geoclean as gc  # noqa: E402

CACHE = os.path.join(ROOT, 'cache')
OUT = os.path.join(ROOT, 'data', 'domains')

# Домены базы знаний, у которых есть матрица. Порядок полей - как в описании.
DOMAINS = [
    {
        'id': 'nokhchi',
        'title': 'Нохчи (Чеченцы)',
        'matrix': '/matrices/russia/nokhchi/',
        'campaigns': 'data/campaigns/nohchi.json',
        'frame': ('ne_admin1', {'admin': 'Russia', 'name': 'Chechnya'}),
        'frame_source': (
            'контур современной Чеченской Республики, Natural Earth admin-1 '
            '(cache/ne_admin1.geojson, adm1_code RUS-2416); стоит за ЧРИ - '
            'своей оцифровки границ ЧРИ 1991-1999 у нас нет'),
        'time': ['1550-01-01', None],
    },
    {
        'id': 'ukrainians',
        'title': 'Украинцы',
        'matrix': '/matrices/russia/ukrainians/',
        'campaigns': 'data/campaigns/ukraina.json',
        'frame': ('cshapes', {'cntry_name': 'Ukraine', 'gwsyear': 1991}),
        'frame_source': (
            'границы Украины 1991 года: CShapes 2.0 '
            '(cache/cshapes20.geojson), окно 25.12.1991-16.03.2014, с Крымом'),
        'time': ['1654-01-01', None],
    },
]

# Запас рамки: во сколько раз коробка камеры шире контура. Рамка невидима,
# читателю нужен воздух вокруг территории, иначе на первом же кадре контур
# упирается в края окна. 31.08.2026 ужат с 0,18 до 0,08: у Украинцев прежний
# запас затягивал в кадр пол-Молдовы и Ростов.
PAD = 0.08
# Пояс вокруг контура, внутри которого изменения на карте считаются «своими»
# (build_domain_stops.py). Полградуса - около пятидесяти километров: Кизляр и
# устье Сунжи для Нохчи попадают, Южная Осетия и Ставрополь - уже нет. Рамка
# КАМЕРЫ для этого не годится: это прямоугольник, и её угол цепляет соседей,
# до которых от территории сотни километров.
STOPS_BUF = 0.5
# Мягкая зона пружины: насколько ЗА рамку можно уехать, прежде чем отбросит
# назад (доля размера рамки). Жёсткий предел - вдвое дальше.
SOFT = 0.25


def load_frame(kind, sel):
    if kind == 'ne_admin1':
        feats = [f for f in gc.admin1_features(CACHE)
                 if all(f['properties'].get(k) == v for k, v in sel.items())]
    elif kind == 'cshapes':
        with open(os.path.join(CACHE, 'cshapes20.geojson'), encoding='utf-8') as f:
            feats = [x for x in json.load(f)['features']
                     if all(x['properties'].get(k) == v for k, v in sel.items())]
    else:
        raise ValueError(kind)
    if not feats:
        raise SystemExit('нет контура по отбору %s %s' % (kind, sel))
    return unary_union([shape(f['geometry']).buffer(0) for f in feats])


def camera(bbox):
    """Стартовая камера по коробке: центр и зум, при котором коробка влезает.

    Зум считается по ширине в градусах долготы для окна в 1024 CSS-пикселя -
    точную посадку всё равно делает fitBounds в браузере, здесь нужна опора
    для первого кадра и для нижнего предела зума.
    """
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    dx = max(x1 - x0, 1e-6)
    dy = max(y1 - y0, 1e-6)
    # меркатор: по вертикали градус широты «шире» на cos(lat)
    dyx = dy / max(math.cos(math.radians(cy)), 0.1)
    zx = math.log2(360.0 / dx)
    zy = math.log2(180.0 / dyx)
    return [round(cx, 4), round(cy, 4)], round(min(zx, zy), 2)


def pad_bbox(bbox, k):
    x0, y0, x1, y1 = bbox
    dx, dy = (x1 - x0) * k, (y1 - y0) * k
    return [round(x0 - dx, 4), round(y0 - dy, 4),
            round(x1 + dx, 4), round(y1 + dy, 4)]


def main():
    os.makedirs(OUT, exist_ok=True)
    for d in DOMAINS:
        geom = load_frame(*d['frame'])
        geom = geom.simplify(0.005, preserve_topology=True)
        bbox = list(geom.bounds)
        frame = pad_bbox(bbox, PAD)
        center, zoom = camera(frame)
        out = {
            'id': d['id'],
            'title': d['title'],
            'matrix': d['matrix'],
            'campaigns': d['campaigns'],
            'frame_source': d['frame_source'],
            'bbox_geom': [round(v, 4) for v in bbox],
            'bbox': frame,
            'soft': SOFT,
            'stops_buffer_deg': STOPS_BUF,
            'center': center,
            'zoom': zoom,
            'min_zoom': round(zoom - 0.7, 2),
            'time': d['time'],
            'geometry': gc.sort_polygons(gc.sanitize_geom(mapping(geom))),
        }
        path = os.path.join(OUT, d['id'] + '.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
        print('%-8s рамка %s зум %.2f  %s' % (
            d['id'], ['%.2f' % v for v in frame], zoom,
            os.path.relpath(path, ROOT)))


if __name__ == '__main__':
    main()
