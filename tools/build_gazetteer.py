import geoclean as gc
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Справочник городов для ориентира в попапе «история точки».

Подложка (OpenFreeMap) подписи городов на обзорных зумах не отрисовывает
(коллизия символов), поэтому в 2026 её как источник ориентира убрали — попап
на клике по Варшаве после этого мог показывать «Мазовецкое воеводство» ещё и
на Тбилиси (см. README, раздел «История точки»). Решение — свой лёгкий
справочник, который index.html грузит сам и ищет ближайший город по прямой
(гаверсинус), без обращения к тайлам.

Источники:
- Natural Earth 10m populated places (сам справочник; поле NAME_RU — русское
  имя), качается в cache/, зеркало nvkelso/natural-earth-vector на GitHub;
- наши таблицы кампаний/сверки — города оттуда, которых нет в Natural Earth
  (мелкие узлы Гражданской войны и колониальной экспансии), добавляются
  поверх без учёта порога населения.

Отбор по охвату проекта (см. data/sphere.geojson / карту в целом): основная
рамка lon 15..190, lat 35..82 + Аляска lon -170..-130, lat 52..72 — везде,
куда ступала нога империи. Порог по Natural Earth — POP_MAX >= 20000, чтобы
уложиться в компактный файл; свои таблицы идут без порога.

Запуск (из корня репозитория):

    python3 tools/build_gazetteer.py

Выход: data/gazetteer.json — компактный массив
[{"n": "Варшава", "y": 52.23, "x": 21.01, "p": 1700000}, ...],
координаты округлены до 3 знаков, отсортировано по убыванию населения p.
"""
import csv
import json
import math
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'cache')
OUT = os.path.join(ROOT, 'data', 'gazetteer.json')
NE_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
          "master/geojson/ne_10m_populated_places.geojson")
NE_CACHE = os.path.join(CACHE, 'ne_10m_populated_places.geojson')
UA = {"User-Agent": "Mozilla/5.0 (imperium-map; decolonial.ist research)"}

POP_MIN = 20000          # порог для Natural Earth (свои таблицы - без порога)
DEDUPE_KM = 8            # ближе этого к уже взятой точке - считаем тем же городом

# основная рамка + отдельно Аляска (за пределами lon 15..190)
BOXES = [
    (15, 190, 35, 82),
    (-170, -130, 52, 72),
]

# наши таблицы: (файл, колонка с именем места)
EXTRA_TABLES = [
    ('data/events/ukraina_1917_1921/draft_events.csv', 'place'),
    ('data/crosscheck/cities_civilwar.csv', 'city'),
    ('data/crosscheck/checkpoints.csv', 'place'),
    ('data/crosscheck/expansion.csv', 'city'),
]


def in_box(lon, lat):
    for x0, x1, y0, y1 in BOXES:
        if x0 <= lon <= x1 and y0 <= lat <= y1:
            return True
    return False


def haversine_km(y1, x1, y2, x2):
    r = 6371.0
    p1, p2 = math.radians(y1), math.radians(y2)
    dp = math.radians(y2 - y1)
    dl = math.radians(x2 - x1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def fetch_ne():
    if not os.path.exists(NE_CACHE):
        os.makedirs(CACHE, exist_ok=True)
        print('качаю', NE_URL)
        req = urllib.request.Request(NE_URL, headers=UA)
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        with open(NE_CACHE, 'wb') as f:
            f.write(data)
    with open(NE_CACHE, encoding='utf-8') as f:
        return json.load(f)


def ne_entries():
    gj = fetch_ne()
    out = []
    for feat in gj['features']:
        p = feat['properties']
        lon, lat = p.get('LONGITUDE'), p.get('LATITUDE')
        if lon is None or lat is None or not in_box(lon, lat):
            continue
        pop = p.get('POP_MAX') or 0
        if pop < POP_MIN:
            continue
        name = p.get('NAME_RU') or p.get('NAME')
        if not name:
            continue
        out.append({'n': name, 'y': round(lat, 3), 'x': round(lon, 3), 'p': int(pop)})
    return out


def extra_entries(existing_coords):
    """Города из наших таблиц, которых нет рядом ни с одной уже взятой точкой."""
    out = []
    seen = list(existing_coords)   # (y, x), растим по ходу, чтобы не дублировать между таблицами
    for rel_path, name_col in EXTRA_TABLES:
        path = os.path.join(ROOT, rel_path)
        if not os.path.exists(path):
            print('пропуск (нет файла):', rel_path)
            continue
        with open(path, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                name = (row.get(name_col) or '').strip()
                try:
                    lat = float(row.get('lat'))
                    lon = float(row.get('lon'))
                except (TypeError, ValueError):
                    continue
                if not name:
                    continue
                if any(haversine_km(lat, lon, y, x) < DEDUPE_KM for y, x in seen):
                    continue
                seen.append((lat, lon))
                out.append({'n': name, 'y': round(lat, 3), 'x': round(lon, 3), 'p': 20000})
    return out


def main():
    ne = ne_entries()
    print('Natural Earth в рамке проекта:', len(ne))
    extra = extra_entries([(e['y'], e['x']) for e in ne])
    print('добавлено из наших таблиц:', len(extra))
    all_entries = ne + extra
    all_entries.sort(key=lambda e: -e['p'])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj(all_entries), f, ensure_ascii=False, separators=(',', ':'))
    size_kb = os.path.getsize(OUT) / 1024
    print('data/gazetteer.json:', len(all_entries), 'городов,', round(size_kb, 1), 'КБ')


if __name__ == '__main__':
    main()
