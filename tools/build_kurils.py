#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Курильская гряда: обрезать округа по суше, чтобы гряда не красила воду.

ЗАЧЕМ. Геометрия гряды взята из OpenStreetMap по муниципальным округам
(admin_level=6), а округ включает акваторию: вокруг каждого острова к суше
приписано море. 28.08.2026 файлы обрезали по суше Natural Earth, но с припуском
5 км (`margin=0.05`) - тем самым, который спасает точки на берегу вроде Ситки и
Батуми. Для гряды из мелких островов такой припуск оставляет пятикилометровую
ленту моря вокруг каждого: из 21 877 км² в файлах сушей были 10 473 км², ровно
половина. На карте это красные пятна в океане, а в `check_sea_crumbs.py` - три
самых крупных морских места базлайна: Малая Курильская гряда (614 км²),
район Экармы (210 км²) и Чёрные Братья (152 км²), все на 15 срезах.

ЧТО ДЕЛАЕТ. Режет те же округа по суше с припуском MARGIN (1,1 км): берег
Natural Earth грубее реального, без припуска срезается кромка. Обрезка
идемпотентна - маска с меньшим припуском вложена в маску с большим, поэтому
резать можно прямо по файлам, обрезанным раньше. Исходные округа, как их отдал
Overpass, лежат в `data/kurils/source_admin_2026-08-28/`.

ПРО КОНТРОЛЬНЫЕ ТОЧКИ. Точка Кунашира в `data/crosscheck/expansion.csv` стояла
на 44.000, 145.900 - это Кунаширский пролив, 3,1 км от берега по Natural Earth.
Держалась она только на пятикилометровом припуске. Точка сдвинута вглубь
острова, как раньше сдвигали Абакан и Анадырь.

Запуск:
    .venv/bin/python tools/build_kurils.py
    .venv/bin/python tools/build_kurils.py --dry   # посчитать, не записывая
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))

import geoclean as gc                                    # noqa: E402
from shapely.geometry import Point, mapping, shape       # noqa: E402
from shapely.ops import unary_union                      # noqa: E402

DATA = os.path.join(ROOT, 'data', 'kurils')
CACHE = os.path.join(ROOT, 'cache')
SOURCE = os.path.join(DATA, 'source_admin_2026-08-28')
MARGIN = 0.01            # припуск обрезки, около 1,1 км
FILES = ('north', 'south', 'all')

# Острова, которые обязаны остаться: если какой-то пропал, обрезка зашла далеко.
# Координаты - по точкам внутри суши Natural Earth, не по серединам названий.
ISLANDS = {
    'Шумшу': (50.740, 156.280),
    'Парамушир': (50.350, 155.750),
    'Онекотан': (49.450, 154.750),
    'Экарма': (48.958, 153.940),
    'Матуа': (48.080, 153.230),
    'Симушир': (46.950, 152.000),
    'Чирпой (Чёрные Братья)': (46.460, 150.813),
    'Уруп': (46.050, 150.000),
    'Итуруп': (45.000, 147.900),
    'Кунашир': (44.097, 145.834),
    'Шикотан': (43.800, 146.750),
}


def km2(geom):
    """Площадь в км², грубо - через широту центра."""
    return geom.area * 111.32 * 111.32 * math.cos(math.radians(geom.centroid.y))


def sea_share(geom):
    """Доля площади, лежащей в океане по Natural Earth 10m."""
    with open(os.path.join(CACHE, 'ne_10m_ocean.geojson')) as fh:
        ocean = unary_union([shape(f['geometry'])
                             for f in json.load(fh)['features']])
    inter = geom.intersection(ocean)
    return 0.0 if inter.is_empty else inter.area / geom.area


def main():
    dry = '--dry' in sys.argv[1:]
    total_before = total_after = 0.0
    final = None
    for name in FILES:
        src = os.path.join(SOURCE, name + '.geojson')
        if not os.path.exists(src):
            src = os.path.join(DATA, name + '.geojson')
        with open(src) as fh:
            data = json.load(fh)
        feat = data['features'][0]
        geom = shape(feat['geometry'])
        before = km2(geom)
        clipped, dropped = gc.clip_to_land(geom, CACHE, margin=MARGIN)
        after = km2(clipped)
        total_before += before
        total_after += after

        missing = [n for n, (lat, lon) in ISLANDS.items()
                   if geom.contains(Point(lon, lat))
                   and not clipped.intersects(Point(lon, lat).buffer(0.02))]
        parts = (len(list(clipped.geoms))
                 if clipped.geom_type == 'MultiPolygon' else 1)
        print('%-6s %6.0f -> %6.0f км² (частей %d, снято мелких %d)'
              % (name, before, after, parts, dropped))
        if missing:
            print('   ОСТАНОВЛЕНО: обрезка съела острова: %s'
                  % ', '.join(missing))
            return 1

        note = feat['properties'].get('note', '')
        note = note.split(' Геометрия обрезана')[0].rstrip()
        feat['properties']['note'] = (
            note + ' Геометрия обрезана по суше Natural Earth с припуском '
            '%g° (около 1,1 км), tools/build_kurils.py, 30.08.2026: '
            'муниципальные округа OpenStreetMap включают морскую акваторию, '
            'а прежний припуск 0,05° оставлял вокруг каждого острова ленту '
            'моря в пять километров - гряда красила воду.' % MARGIN)
        feat['geometry'] = mapping(clipped)
        if name == 'all':
            final = clipped
        if not dry:
            out = os.path.join(DATA, name + '.geojson')
            with open(out, 'w') as fh:
                json.dump(gc.sanitize_obj(data), fh, ensure_ascii=False)

    print('всего %.0f -> %.0f км² (суша гряды по справочникам ~10 500 км²)'
          % (total_before, total_after))
    print('доля воды в гряде целиком: %.0f%% (при припуске 0,05° была 52%%)'
          % (100 * sea_share(final)))
    if dry:
        print('--dry: файлы не тронуты')
    return 0


if __name__ == '__main__':
    sys.exit(main())
