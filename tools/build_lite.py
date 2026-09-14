#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Облегчённые срезы для телефона (задача A4, «го» куратора 01.09.2026).

Полная карта тянет мировые срезы по полмегабайта: на телефоне это минуты
белого экрана, а при включённом режиме блокировки iOS она не рисуется вовсе.
Здесь те же срезы пересобираются в лёгкие: упрощение до 0,02° (около двух
километров - на обзорном масштабе телефона невидимо), сортировка полигонов от
крупного к мелкому, сетка точности, выброс осколков. Замер на трёх срезах:
1783 - 215 КБ против 17 КБ по сети, 1900 - 166 против 15, 1992 - 1686 КБ
против 39.

Правила те же, что у пакетов доменов (build_domain_bundle.py), и по той же
причине: MapLibre и Leaflet роняют заливку из-за одной дефектной части
мультиполигона.

На выходе:
    data/years_lite/<ключ>.geojson       - облегчённые срезы ядра
    data/deepstate/months_lite/<день>.geojson - облегчённые снимки фронта
    data/years_lite_bundle.json          - вся облегчённая линия времени одним
                                           файлом (запасной путь карты)
    data/years_lite.topo.json            - та же линия времени одной топологией
                                           с общими дугами (0,6 МБ вместо 5,6;
                                           карта берёт её с 15.09.2026)
    data/lite_manifest.json              - что собрано и с каким упрощением

Запуск:

    cd ~/tmp/imperium-map && .venv/bin/python3 tools/build_lite.py
    ... --tol 0.02 --only 1783   (для проверки одного среза)
"""
import argparse
import json
import os
import subprocess
import sys

import shapely
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import geoclean as gc  # noqa: E402
from build_domain_bundle import drop_slivers  # noqa: E402

DATA = os.path.join(ROOT, 'data')
TOL = 0.02
ND = 3
# Квантование топологии (этап 2 плана 15.09.2026): сетка 1e5 на охват всех
# срезов - шаг около 200 м, мельче упрощения 0,02° в восемь раз, на кадре
# не видно. При 1e4 (около 2 км) файл 0,34 МБ вместо 0,61, но это уже грубее
# самих срезов.
TOPO_Q = '1e5'


def lighten(fc, tol, nd):
    parts = []
    for f in fc.get('features', []):
        g = f.get('geometry')
        if not g:
            continue
        try:
            s = shape(g).buffer(0)
        except Exception:
            continue
        if not s.is_empty:
            parts.append(s)
    if not parts:
        return None
    g = unary_union(parts).simplify(tol, preserve_topology=True).buffer(0)
    if g.is_empty:
        return None
    try:
        g = shapely.set_precision(g, 10.0 ** -nd)
    except Exception:
        g = g.buffer(0)
    if not g.is_valid:
        g = g.buffer(0)
    g = drop_slivers(g, tol * tol * 4)
    if g is None or g.is_empty:
        return None
    return gc.sort_polygons(gc.sanitize_geom(mapping(g)))


def write(path, geom, src):
    fc = {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'lite': True, 'src': src},
         'geometry': geom}]}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(fc, f, ensure_ascii=False, separators=(',', ':'))
    return os.path.getsize(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tol', type=float, default=TOL)
    ap.add_argument('--only')
    a = ap.parse_args()

    out_y = os.path.join(DATA, 'years_lite')
    out_m = os.path.join(DATA, 'deepstate', 'months_lite')
    os.makedirs(out_y, exist_ok=True)
    os.makedirs(out_m, exist_ok=True)

    mf = json.load(open(os.path.join(DATA, 'manifest.json'), encoding='utf-8'))
    keys = [str(k) for k in mf['years']]
    if a.only:
        keys = [k for k in keys if k == a.only]
    done_y, size_y, skipped = [], 0, []
    bounds = {}                     # охват среза [зап, юг, вост, сев] - стартовому виду
    for k in keys:
        src = os.path.join(DATA, 'years', k + '.geojson')
        if not os.path.exists(src):
            continue
        g = lighten(json.load(open(src, encoding='utf-8')), a.tol, ND)
        if g is None:
            skipped.append(k)
            continue
        size_y += write(os.path.join(out_y, k + '.geojson'), g,
                        'data/years/%s.geojson' % k)
        done_y.append(k)
        bounds[k] = [round(v, 3) for v in shape(g).bounds]

    dsp = os.path.join(DATA, 'deepstate', 'manifest.json')
    done_m, size_m = [], 0
    if os.path.exists(dsp) and not a.only:
        ds = json.load(open(dsp, encoding='utf-8'))
        for day in (ds.get('months') or []):
            src = os.path.join(DATA, 'deepstate', 'days', day + '.geojson')
            if not os.path.exists(src):
                continue
            fc = json.load(open(src, encoding='utf-8'))
            occ = {'features': [f for f in fc.get('features', [])
                                if f.get('properties', {}).get('s') == 'occupied']}
            g = lighten(occ, a.tol, ND)
            if g is None:
                continue
            size_m += write(os.path.join(out_m, day + '.geojson'), g,
                            'data/deepstate/days/%s.geojson' % day)
            done_m.append(day)

    # Пакет всей облегчённой линии времени одним файлом. Карта греет историю
    # фоном; двести тридцать отдельных запросов - это двести тридцать обменов
    # с сервером, и на мобильной сети одни только задержки складываются в
    # секунды. Пакет отдаётся одним обращением, а срезы в нём лежат по ключу.
    bundle = {'tol': a.tol, 'keys': done_y, 'slices': {}}
    for k in done_y:
        with open(os.path.join(out_y, k + '.geojson'), encoding='utf-8') as f:
            bundle['slices'][k] = json.load(f)
    bpath = os.path.join(DATA, 'years_lite_bundle.json')
    with open(bpath, 'w', encoding='utf-8') as f:
        json.dump(bundle, f, ensure_ascii=False, separators=(',', ':'))
    bsize = os.path.getsize(bpath)

    # Вся облегчённая линия времени ОДНОЙ ТОПОЛОГИЕЙ (этап 2 плана 15.09.2026,
    # «го» куратора). Пакет из 233 копий срезов весил 5,6 МБ сжатыми, хотя
    # соседние срезы делят одни и те же границы: TopoJSON хранит каждую дугу
    # один раз, а срез - как список ссылок на дуги. Замер 15.09: 30 868 дуг,
    # 98 тысяч точек, 0,61 МБ сжатыми при квантовании 1e5. Карта берёт файл
    # одним запросом и собирает срез из дуг при первом обращении
    # (vendor/topojson-client.min.js). Сборка - geo2topo из topojson-server
    # (package.json, `npm ci`); без него топология не собирается, карта
    # остаётся на пакете, и об этом говорится в конце вывода.
    tpath = os.path.join(DATA, 'years_lite.topo.json')
    tsize = 0
    geo2topo = os.path.join(ROOT, 'node_modules', '.bin', 'geo2topo')
    if a.only:
        pass                                   # один срез - топологию не трогаем
    elif os.path.exists(geo2topo) and done_y:
        cmd = [geo2topo, '-q', TOPO_Q] + [os.path.join(out_y, k + '.geojson') for k in done_y]
        with open(tpath, 'w', encoding='utf-8') as f:
            subprocess.run(cmd, stdout=f, check=True)
        topo = json.load(open(tpath, encoding='utf-8'))
        missing = [k for k in done_y if k not in topo.get('objects', {})]
        if missing:
            sys.exit('топология без срезов: %s' % ', '.join(missing[:8]))
        tsize = os.path.getsize(tpath)
    else:
        print('geo2topo не найден (%s): топология не собрана, поставьте node-инструменты '
              'командой `cd %s && npm ci`' % (geo2topo, ROOT), file=sys.stderr)

    man = {
        'note': ('облегчённые срезы для телефона: упрощение %.3f°, координаты '
                 'до %d знаков; сборка tools/build_lite.py' % (a.tol, ND)),
        'tol': a.tol, 'years': done_y, 'months': done_m,
        'skipped': skipped,
        'bundle': 'data/years_lite_bundle.json',
        'topology': 'data/years_lite.topo.json' if tsize else None,
        'topology_q': TOPO_Q,
        # Охват каждого среза (15.09.2026, этап 3): index.html подгоняет
        # стартовый вид под срез даты ДО первого запроса тайлов подложки, а
        # не после первого рендера - иначе подложка успевала запросить полсотни
        # тайлов обзорного вида, которые тут же выбрасывались.
        'bounds': bounds,
    }
    with open(os.path.join(DATA, 'lite_manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(man, f, ensure_ascii=False, separators=(',', ':'))
    # штамп для check_build_order: облегчённые срезы производны от обычных и
    # обязаны пересобираться ПОСЛЕ всей цепочки, иначе телефон покажет
    # вчерашнюю карту
    gc.write_stamp('lite')
    print('срезов %d (%.1f МБ), снимков фронта %d (%.1f МБ), пропущено %d, '
          'пакет линии времени %.1f МБ, топология %.1f МБ'
          % (len(done_y), size_y / 1048576, len(done_m), size_m / 1048576,
             len(skipped), bsize / 1048576, tsize / 1048576))
    if skipped:
        print('пустые после упрощения:', ', '.join(skipped[:8]))


if __name__ == '__main__':
    main()
