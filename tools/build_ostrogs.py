#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Остроги точками: то, чем империя в Сибири владела на самом деле.

ЗАЧЕМ (задача куратора 28.08.2026). До этого дня вся Сибирь и весь Дальний
Восток брались тремя актами, и два из трёх стояли на ОСНОВАНИИ ОСТРОГА: 25.09.1632
на закладке Якутского острога разом краснели Якутия, Красноярский край,
Иркутская, Томская, Новосибирская, Кемеровская области, Хакасия, Бурятия,
Забайкалье и Алтай. Куратор: «с каких пор основание острога - это захват
территорий? это супер небольшая крепость, одна, посреди чужих земель, с полтора
калеками людей внутри и поставками раз в месяц. захват - это когда они
установили власть, всех взяли в плен, всех подчинили, фактически всё
контролируют, а не поставили блядскую избу посреди тундры».

Решение куратора: «отмечай только остроги красным (как будто они в котлах) да и
всё» - и не только по Чукотке, а на всю острожную эпоху.

ЧТО ДЕЛАЕТ. Из курируемой таблицы `data/ostrogs/registry.csv` строит по кружку
на острог: точка, радиус, окно существования. Кружок красится тем же красным,
что и империя, и лежит ПОВЕРХ незакрашенной земли - на карте это читается как
то, чем оно и было: гарнизон в избе посреди чужой земли.

ГЕОМЕТРИЯ УСЛОВНАЯ. Радиус - не линия контроля, а обозначение места: тем же
приёмом в проекте уже показаны рейды 2023-2024 годов (`tools/build_losses.py`,
kind='raid'). По умолчанию 15 км - примерно дневной переход от острога и обратно.
Это записано в свойствах каждой фичи и видно в попапе истории точки.

ОСТРОГИ, КОТОРЫЕ ИМПЕРИЯ БРОСИЛА, тоже здесь и гаснут по своей дате: Мангазея
оставлена в 1672 году, Анадырский острог ликвидирован указом 04.05.1764, люди
выведены с 1765-го, укрепления срыты в 1771-м.

Запуск:

    cd ~/tmp/imperium-map && .venv/bin/python tools/build_ostrogs.py
"""
import csv
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geoclean as gc     # noqa: E402  (чистка колец от нулевых отрезков)
from build_expansion import key_date   # noqa: E402  (порядок срезов)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
SRC = os.path.join(DATA, 'ostrogs', 'registry.csv')
OUT = os.path.join(DATA, 'ostrogs', 'ostrogs.geojson')

STEPS = 48          # вершин в кружке
KM_PER_DEG = 111.32


def circle(lon, lat, km, steps=STEPS):
    """Кружок радиуса km вокруг точки, с поправкой на широту."""
    dlat = km / KM_PER_DEG
    dlon = dlat / max(math.cos(math.radians(lat)), 1e-6)
    ring = []
    for i in range(steps):
        a = 2 * math.pi * i / steps
        ring.append([round(lon + dlon * math.cos(a), 4),
                     round(lat + dlat * math.sin(a), 4)])
    ring.append([ring[0][0], ring[0][1]])
    return [ring]


def read_rows(path=SRC):
    with open(path, encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f)
                if (r.get('slug') or '').strip()
                and not r['slug'].startswith('#')]
    bad = []
    for i, r in enumerate(rows, 2):
        for k in ('name_ru', 'lon', 'lat', 'founded', 'source'):
            if not (r.get(k) or '').strip():
                bad.append(f'строка {i}: пустое поле {k}')
        try:
            float(r['lon']), float(r['lat']), float(r['radius_km'] or 15)
        except ValueError:
            bad.append(f'строка {i}: координаты или радиус не число')
    if bad:
        for b in bad:
            print('!! ' + b)
        raise SystemExit('таблица острогов не прошла проверку')
    return rows


def build(rows):
    feats = []
    for r in rows:
        lon, lat = float(r['lon']), float(r['lat'])
        km = float(r['radius_km'] or 15)
        geom = {'type': 'Polygon', 'coordinates': circle(lon, lat, km)}
        feats.append({
            'type': 'Feature',
            'geometry': gc.clean_rings(geom),
            'properties': {
                'slug': r['slug'], 'name': r['name_ru'],
                'from': r['founded'], 'to': (r['gone'] or '').strip() or None,
                'red_from': red_from(lon, lat),
                'lon': lon, 'lat': lat, 'radius_km': km,
                'source': r['source'], 'note': r['note'],
                'kind': 'ostrog',
                'geometry_note': (
                    f'геометрия условная: кружок радиусом {km:g} км вокруг '
                    f'острога, обозначение места, а не линия контроля'),
                'approximate': True,
            },
        })
    return feats


_slices = None


def red_from(lon, lat):
    """Дата, когда земля вокруг острога покраснела ВПЕРВЫЕ.

    ЗАЧЕМ (28.08.2026). Куратор по срезу 15.08.1918: «куча острогов на черной
    земле. они были имперскими тогда?». Точки гасились живым правилом «пока
    земля под ними не красная» - и когда Сибирь снова чернела (окно
    самостоятельности областников 1918 года, вырез набега), остроги XVI-XVII
    веков зажигались заново, как будто это опять фронтир. Считаем дату первого
    покраснения один раз здесь и пишем её в данные; дальше точка гаснет
    навсегда.
    """
    global _slices
    from shapely.geometry import Point, shape
    from shapely.prepared import prep
    if _slices is None:
        with open(os.path.join(DATA, 'manifest.json'), encoding='utf-8') as f:
            keys = json.load(f)['years']
        _slices = []
        for k in keys:
            path = os.path.join(DATA, 'years', str(k) + '.geojson')
            if not os.path.exists(path):
                continue
            with open(path, encoding='utf-8') as f:
                fc = json.load(f)
            # союз фич не нужен: «точка внутри среза» = «точка внутри любой
            # его фичи». unary_union каждого из 192 срезов стоил большую
            # часть времени сборщика (29.08.2026); prep ускоряет contains
            feats = [prep(shape(ft['geometry']).buffer(0))
                     for ft in fc['features']]
            _slices.append((str(k), feats))
        _slices.sort(key=lambda t: key_date(t[0]))
    p = Point(lon, lat)
    for k, feats in _slices:
        if any(g.contains(p) for g in feats):
            return k
    return None


def main():
    rows = read_rows()
    feats = build(rows)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj({'type': 'FeatureCollection', 'features': feats}), f,
                  ensure_ascii=False)
    size = os.path.getsize(OUT)
    gone = [r for r in rows if (r.get('gone') or '').strip()]
    print(f'OK {os.path.relpath(OUT, ROOT)}: острогов {len(feats)}, '
          f'{size // 1024} КБ')
    print(f'   из них империя бросила: {len(gone)} — '
          + ', '.join(f"{r['name_ru']} ({r['gone'][:4]})" for r in gone))
    first = min(rows, key=lambda r: r['founded'])
    last = max(rows, key=lambda r: r['founded'])
    print(f"   окно: {first['founded']} ({first['name_ru']}) .. "
          f"{last['founded']} ({last['name_ru']})")
    gc.write_stamp('ostrogs')


if __name__ == '__main__':
    main()
