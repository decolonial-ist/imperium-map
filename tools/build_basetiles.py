#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Своя подложка для обзорных зумов (этап 1 плана 15.09.2026, «го» куратора).

Зачем. Стартовый вид карты тянул 125 векторных тайлов OpenFreeMap на 4,9 МБ,
и 90% этих байтов - названия стран, областей и городов на 80 языках, из
которых показ берёт два. Вода и государственные границы, ради которых
подложка нужна, весят 1-3% тайла. На 3G подписи стран появлялись на 47-й
секунде (разбор: MAP-MATERIALS/loop_2026-09-15_load/RAZBOR_ZAGRUZKI.md).

Что делает. Качает тайлы OpenFreeMap той версии, что объявлена в TileJSON
(https://tiles.openfreemap.org/planet): зумы 0-4 на весь мир, зумы 5-6 только
над охватом карты (BBOX). В каждом тайле оставляет ровно те слои и атрибуты,
которые рисует наш урезанный стиль (KEEP_STYLE в ee-shim.js), перекодирует
и пишет gzip в data/basetiles/{z}/{x}/{y}.mvt (нумерация тайлов - как у
OpenStreetMap; шим сам переводит свою сетку в неё). GitHub Pages двоичные
файлы не сжимает, поэтому gzip свой, распаковка в браузере (vendor/fflate).
Тайлы вне охвата и глубже BASE_MAXZOOM карта берёт с OpenFreeMap как раньше.

Опись - data/basetiles/manifest.json: версия планеты, дата, охват по зумам
в номерах тайлов, правила урезания, число тайлов и байт. Шим читает из неё
maxzoom и охват; нет описи - нет своих тайлов, всё едет с OpenFreeMap.

Запуск:
    cd ~/tmp/imperium-map && .venv/bin/python tools/build_basetiles.py
    ... --only 4/9/5          один тайл, с отчётом по слоям
    ... --check               только скачать и посчитать, на диск не писать
    ... --maxzoom 5           меньше зумов (по умолчанию 6)
"""
import argparse
import gzip
import io
import json
import math
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import mapbox_vector_tile as mvt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
OUT = os.path.join(ROOT, 'data', 'basetiles')
TILEJSON = 'https://tiles.openfreemap.org/planet'

# Охват своих тайлов на зумах 5-6: Северная Евразия с запасом на Аляску
# (Русская Америка) и Западную Европу. Долгота 190 = -170: охват переходит
# через 180-й меридиан, поэтому ниже он режется на две полосы.
BBOX = {'west': -30.0, 'east': 190.0, 'south': 25.0, 'north': 85.0}
WORLD_MAXZOOM = 4          # эти зумы - весь мир
BASE_MAXZOOM = 6           # глубже - OpenFreeMap

# Что остаётся в тайле: слой -> (фильтр фичи, атрибуты). Ровно то, что рисует
# урезанный стиль (KEEP_STYLE в ee-shim.js) и что читает шим (RENAMES по
# name, Крым по name:uk, RU_CLAIM_NAMES по name и name:en, текст подписей по
# name:latin / name:nonlatin / name_en / name).
NAME_KEYS = ('name', 'name:en', 'name_en', 'name:latin', 'name:nonlatin', 'name:uk')
RULES = {
    'water':      (lambda p: True, ('class', 'brunnel', 'intermittent')),
    'waterway':   (lambda p: True, ('class', 'brunnel')),
    'water_name': (lambda p: True, NAME_KEYS + ('class',)),
    'landcover':  (lambda p: p.get('subclass') in ('ice_shelf', 'glacier'), ('class', 'subclass')),
    'landuse':    (lambda p: p.get('class') == 'park', ('class',)),
    'boundary':   (lambda p: p.get('admin_level') == 2 and 'claimed_by' not in p,
                   ('admin_level', 'maritime', 'disputed', 'disputed_name')),
    'place':      (lambda p: p.get('class') in ('country', 'state', 'city'),
                   NAME_KEYS + ('class', 'rank', 'capital', 'iso_a2')),
}


def lon2x(lon, z):
    return int(math.floor((lon + 180.0) / 360.0 * (1 << z)))


def lat2y(lat, z):
    r = math.radians(lat)
    return int(math.floor((1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * (1 << z)))


def ranges_for(z):
    """Полосы тайлов [x0, x1, y0, y1] (включительно) на зуме z."""
    n = 1 << z
    if z <= WORLD_MAXZOOM:
        return [[0, n - 1, 0, n - 1]]
    y0 = max(0, lat2y(BBOX['north'], z))
    y1 = min(n - 1, lat2y(BBOX['south'], z))
    out = []
    east = BBOX['east']
    if east > 180:                       # через 180-й меридиан: две полосы
        out.append([lon2x(BBOX['west'], z), n - 1, y0, y1])
        out.append([0, lon2x(east - 360.0, z), y0, y1])
    else:
        out.append([lon2x(BBOX['west'], z), lon2x(east, z), y0, y1])
    return out


def fetch(url, tries=4):
    req = urllib.request.Request(url, headers={'Accept-Encoding': 'gzip',
                                               'User-Agent': 'imperium-map basetiles builder (decolonial.ist)'})
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if data[:2] == b'\x1f\x8b':
                data = gzip.decompress(data)
            return data
        except Exception as e:           # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f'{url}: {last}')


def strip(data):
    """Урезанный тайл (сырой pbf) и отчёт по слоям: было/стало фич, байт."""
    tile = mvt.decode(data, default_options={'y_coord_down': True})
    layers, report = [], {}
    for name, (keep, attrs) in RULES.items():
        src = tile.get(name)
        if not src:
            continue
        feats = []
        for f in src['features']:
            p = f.get('properties') or {}
            if not keep(p):
                continue
            feats.append({'geometry': f['geometry'],
                          'properties': {k: p[k] for k in attrs if k in p}})
        report[name] = [len(src['features']), len(feats)]
        if feats:
            layers.append({'name': name, 'features': feats,
                           'extent': src.get('extent', 4096)})
    if not layers:
        return b'', report
    per_layer = {l['name']: {'extents': l['extent']} for l in layers}
    enc = mvt.encode([{'name': l['name'], 'features': l['features']} for l in layers],
                     default_options={'y_coord_down': True, 'extents': 4096},
                     per_layer_options=per_layer)
    # контроль: ничего не потеряли при перекодировании
    back = mvt.decode(enc, default_options={'y_coord_down': True})
    for l in layers:
        got = len(back.get(l['name'], {}).get('features', []))
        if got != len(l['features']):
            report[l['name']].append(f'ПОТЕРЯ при кодировании: {len(l["features"])} -> {got}')
    return enc, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', help='один тайл z/x/y с отчётом по слоям')
    ap.add_argument('--check', action='store_true', help='скачать и посчитать, не писать')
    ap.add_argument('--maxzoom', type=int, default=BASE_MAXZOOM)
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()

    tj = json.loads(fetch(TILEJSON).decode('utf-8'))
    tpl = tj['tiles'][0]
    planet = tpl.split('/planet/')[1].split('/')[0] if '/planet/' in tpl else '?'
    print(f'тайлы: {tpl}  (планета {planet})')

    if a.only:
        z, x, y = map(int, a.only.split('/'))
        raw = fetch(tpl.replace('{z}', str(z)).replace('{x}', str(x)).replace('{y}', str(y)))
        enc, rep = strip(raw)
        gz = gzip.compress(enc, 9) if enc else b''
        print(f'{z}/{x}/{y}: было {len(raw)} байт сырыми ({len(gzip.compress(raw, 6))} gzip); '
              f'стало {len(enc)} сырыми, {len(gz)} gzip')
        for k, v in rep.items():
            print(f'  {k:12} фич {v[0]:5} -> {v[1]:5}' + (f'  {v[2]}' if len(v) > 2 else ''))
        return

    jobs = []
    for z in range(0, a.maxzoom + 1):
        for x0, x1, y0, y1 in ranges_for(z):
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    jobs.append((z, x, y))
    print(f'тайлов к сборке: {len(jobs)} (зумы 0-{a.maxzoom}, мир до {WORLD_MAXZOOM}, дальше охват {BBOX})')
    if not a.check:
        os.makedirs(OUT, exist_ok=True)

    stats = {'tiles': 0, 'bytes_in': 0, 'bytes_out': 0, 'empty': 0, 'lost': []}
    per_z = {}

    def work(t):
        z, x, y = t
        raw = fetch(tpl.replace('{z}', str(z)).replace('{x}', str(x)).replace('{y}', str(y)))
        enc, rep = strip(raw)
        gz = gzip.compress(enc, 9) if enc else gzip.compress(b'', 9)
        if not a.check:
            d = os.path.join(OUT, str(z), str(x))
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f'{y}.mvt'), 'wb') as f:
                f.write(gz)
        lost = [f'{k}:{v[2]}' for k, v in rep.items() if len(v) > 2]
        return z, len(raw), len(gz), not enc, lost

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(work, t): t for t in jobs}
        for i, fu in enumerate(as_completed(futs), 1):
            t = futs[fu]
            try:
                z, bi, bo, empty, lost = fu.result()
            except Exception as e:       # noqa: BLE001
                print(f'ОШИБКА {t}: {e}', file=sys.stderr)
                sys.exit(2)
            stats['tiles'] += 1; stats['bytes_in'] += bi; stats['bytes_out'] += bo
            stats['empty'] += int(empty)
            if lost:
                stats['lost'].append((t, lost))
            pz = per_z.setdefault(z, {'tiles': 0, 'bytes_in': 0, 'bytes_out': 0})
            pz['tiles'] += 1; pz['bytes_in'] += bi; pz['bytes_out'] += bo
            if i % 200 == 0 or i == len(jobs):
                print(f'  {i}/{len(jobs)}  {time.time() - t0:.0f} с  '
                      f'{stats["bytes_in"] / 1048576:.1f} МБ -> {stats["bytes_out"] / 1048576:.1f} МБ', flush=True)

    print('по зумам:')
    for z in sorted(per_z):
        p = per_z[z]
        print(f'  z{z}: {p["tiles"]:5} тайлов  {p["bytes_in"] / 1048576:7.2f} МБ -> {p["bytes_out"] / 1048576:6.2f} МБ')
    print(f'итого {stats["tiles"]} тайлов, пустых {stats["empty"]}, '
          f'{stats["bytes_in"] / 1048576:.1f} МБ -> {stats["bytes_out"] / 1048576:.1f} МБ')
    if stats['lost']:
        print(f'ПОТЕРИ при перекодировании у {len(stats["lost"])} тайлов:', file=sys.stderr)
        for t, l in stats['lost'][:20]:
            print(f'  {t}: {l}', file=sys.stderr)
    if a.check:
        return
    manifest = {
        'planet': planet, 'tiles_template': tpl, 'built': date.today().isoformat(),
        'world_maxzoom': WORLD_MAXZOOM, 'maxzoom': a.maxzoom, 'bbox': BBOX,
        'ranges': {str(z): ranges_for(z) for z in range(0, a.maxzoom + 1)},
        'layers': {k: list(v[1]) for k, v in RULES.items()},
        'place_classes': ['country', 'state', 'city'],
        'tiles': stats['tiles'], 'bytes': stats['bytes_out'],
        'note': 'нумерация тайлов как у OpenStreetMap (z/x/y), файлы сжаты gzip; '
                'вне охвата и глубже maxzoom карта берёт тайлы OpenFreeMap',
    }
    with open(os.path.join(OUT, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f'опись: {os.path.join(OUT, "manifest.json")}')


if __name__ == '__main__':
    main()
