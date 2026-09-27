import geoclean as gc
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Слой атрибуции «кто держал точку» — облегчённые срезы всех государств мира.

Нужен попапу истории точки (клик по карте в index.html): когда точка ВНЕ
красного, надо сказать, кто там был. Ядро империи у нас уже есть
(data/years/*.geojson), а вот остальной мир — только в кэше
historical-basemaps (cache/world_<год>.geojson, все государства с полем NAME).

Здесь эти файлы обрезаются до «геометрия + имя»: NAME, SUBJECTO (если он не
совпадает с именем — это метрополия по данным источника) и name_ru из словаря
RU ниже. Геометрия упрощается до ~0.05° (мировой масштаб, как и весь проект),
дырки полигонов сохраняются.

Год 1930 исключён — файл источника битый (внутри картина ~1920 г.), тот же
разбор в tools/build_data.py.

Для окна 12.1917–03.1921 атрибуция точнее собирается не здесь, а в
tools/build_zones_1917_1921.py (таблица WINDOWS -> data/attribution/
windows_1917_1921.geojson): там у каждой зоны есть дата прихода, дата ухода и
формулировка «кто держал».

Запуск (нужен shapely из .venv в корне репо):

    cd ~/tmp/imperium-map && .venv/bin/python tools/build_attribution.py
"""
import json
import os
import re

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'cache')
OUT = os.path.join(ROOT, 'data', 'attribution')

TOLERANCE = 0.05           # упрощение, градусы (~5 км по меридиану)
MIN_AREA = 0.004           # выбрасываем осколки мельче ~0.004 град² (~40 км²)
NDIGITS = 3                # округление координат: ~100 м, вдвое меньше файлы

# Годы берём из кэша (что скачал build_data.py). 1930 битый.
SKIP_YEARS = {1930}

# Русские имена. Словарь покрывает то, что встречается в имперской периферии;
# чего нет — показывается как в источнике (латиницей), это честнее выдумки.
# Словарь живёт в data/attribution/attribution_names_ru.csv (27.09.2026, по
# слову куратора «переноси всё в CSV»): колонки name, name_ru, comment.
import csv_tables as _ct   # noqa: E402
RU = _ct.load_dict(os.path.join(_ct.ROOT, 'data', 'attribution', 'attribution_names_ru.csv'),
                   ['name', 'name_ru', 'comment'])


def years_in_cache():
    ys = []
    for fn in os.listdir(CACHE):
        m = re.fullmatch(r'world_(\d{4})\.geojson', fn)
        if m and int(m.group(1)) not in SKIP_YEARS:
            ys.append(int(m.group(1)))
    return sorted(ys)


def round_coords(g):
    """Округлить координаты geojson-геометрии до NDIGITS знаков (в 2 раза легче)."""
    def walk(c):
        if isinstance(c[0], (int, float)):
            return [round(c[0], NDIGITS), round(c[1], NDIGITS)]
        return [walk(x) for x in c]
    return {'type': g['type'], 'coordinates': walk(g['coordinates'])}


def prop(f, key):
    p = f.get('properties') or {}
    for k, v in p.items():
        if k.upper() == key:
            return str(v or '').strip()
    return ''


# «Российская империя» c SUBJECTO «Russia» - это не зависимость, а то же
# государство: источник так нормализует суверенные страны. Такие пары гасим,
# чтобы попап не писал «Российская империя (под властью: Россия)».
_STRIP = {'empire', 'kingdom', 'republic', 'of', 'the', 'tsardom', 'grand',
          'duchy', 'federation', 'union', 'states', 'united', 'great'}


def same_state(name, subj):
    """True, если NAME и SUBJECTO — одно государство (зависимости здесь нет)."""
    if not subj or subj == name:
        return True

    def stem(s):
        words = [w for w in re.split(r'[^a-zA-Zа-яА-Я]+', s.lower())
                 if w and w not in _STRIP]
        return ''.join(words)[:5]
    return bool(stem(name)) and stem(name) == stem(subj)


def build_year(year):
    src = os.path.join(CACHE, f'world_{year}.geojson')
    d = json.load(open(src, encoding='utf-8'))
    # одна страна = один полигон: в источнике куски разнесены по фичам
    by_name = {}
    for f in d['features']:
        g = f.get('geometry')
        name = prop(f, 'NAME')
        if not g or not name:
            continue
        try:
            s = shape(g).buffer(0)
        except Exception:
            continue
        if s.is_empty:
            continue
        subj = prop(f, 'SUBJECTO')
        key = (name, subj if same_state(name, subj) is False else '')
        by_name.setdefault(key, []).append(s)

    feats = []
    for (name, subj), geoms in sorted(by_name.items()):
        g = unary_union(geoms).simplify(TOLERANCE).buffer(0)
        parts = list(g.geoms) if g.geom_type == 'MultiPolygon' else [g]
        parts = [p for p in parts if not p.is_empty and p.area >= MIN_AREA]
        if not parts:
            continue
        g = unary_union(parts)
        props = {'name': name, 'year': year}
        if subj:
            props['subjecto'] = subj
        if RU.get(name):
            props['name_ru'] = RU[name]
        if subj and RU.get(subj):
            props['subjecto_ru'] = RU[subj]
        feats.append({'type': 'Feature', 'geometry': round_coords(mapping(g)),
                      'properties': props})

    out = os.path.join(OUT, f'{year}.geojson')
    with open(out, 'w', encoding='utf-8') as fp:
        json.dump({'type': 'FeatureCollection', 'features': feats}, fp,
                  ensure_ascii=False)
    return len(feats), os.path.getsize(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    years, total, no_ru = [], 0, set()
    for y in years_in_cache():
        n, size = build_year(y)
        years.append(y)
        total += size
        print(f'OK data/attribution/{y}.geojson: {n} государств, {size // 1024} КБ')
        d = json.load(open(os.path.join(OUT, f'{y}.geojson'), encoding='utf-8'))
        for f in d['features']:
            if 'name_ru' not in f['properties']:
                no_ru.add(f['properties']['name'])
    manifest = {
        'years': years,
        'tolerance_deg': TOLERANCE,
        'source': ('aourednik/historical-basemaps (GPL-3.0), cache/world_<год>'
                   '.geojson — все государства мира, поле NAME'),
        'note': ('срез = положение дел на этот год; смена между двумя срезами '
                 'датируется только промежутком «между X и Y» — так и '
                 'показывается в попапе истории точки'),
        'note_1930': 'world_1930 исключён: файл источника битый (внутри ~1920 г.)',
        'note_1917_1921': ('для окна 12.1917–03.1921 приоритетна атрибуция из '
                           'data/attribution/windows_1917_1921.geojson '
                           '(tools/build_zones_1917_1921.py, таблица WINDOWS)'),
    }
    with open(os.path.join(OUT, 'manifest.json'), 'w', encoding='utf-8') as fp:
        json.dump(gc.sanitize_obj(manifest), fp, ensure_ascii=False, indent=1)
    print(f'манифест OK: срезов {len(years)}, всего {total // 1024} КБ')
    print(f'без русского имени: {len(no_ru)} названий (показываются как в '
          f'источнике)')


if __name__ == '__main__':
    main()
