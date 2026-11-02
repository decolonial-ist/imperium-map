#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Подмена единиц Natural Earth admin-1 полигонами OpenStreetMap.

ЗАЧЕМ (02.11.2026, куратор: «проверяй вздроч. видел ее на всей карте» - «го,
пиздуй на все деньги»). Natural Earth 1:10m генерализована: у границ областей
прямые рёбра по 40-260 км (Коми-Ненецкий, Красноярск-Якутия, Киевская,
Харьковская). Там, где такая единица образует внешний край красного сотни
срезов подряд, карта показывает прямую линию. В OSM те же границы живые
(Коми: длиннейшее ребро 20 км против 264 у NE).

ЧТО ДЕЛАЕТ. Таблица data/ne_override.csv: admin,name (как в NE),query
(запрос Nominatim). `--fetch` тянет полигон (featuretype=state, polygon_geojson)
в cache/ne_override/<admin>__<name>.geojson. `apply(feats)` подменяет геометрию
фичи NE с тем же admin/name, свойства NE остаются. Подключено в
geoclean.admin1_features (единственный загрузчик NE), а preclip.ne_sha
учитывает файлы подмены - подписи регионов меняются, куски пересчитываются.

Запуск:
    .venv/bin/python tools/ne_override.py --fetch        # все строки таблицы без файла
    .venv/bin/python tools/ne_override.py --check        # длиннейшие рёбра NE против OSM
"""
import csv
import glob
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLE = os.path.join(ROOT, 'data', 'ne_override.csv')
DIR = os.path.join(ROOT, 'cache', 'ne_override')
API = 'https://nominatim.openstreetmap.org/search'
UA = 'imperium-map-research/1.0 (+https://decolonial.ist; contact@decolonial.ist)'
SIMPLIFY = 0.001        # как SIMP срезов в rebuild.py
APPLY_V = 'v2'          # меняется вместе с правилами apply(): входит в подпись


def slug(admin, name):
    s = re.sub(r'[^A-Za-z0-9]+', '_', f'{admin}__{name}').strip('_')
    return s


def rows():
    if not os.path.exists(TABLE):
        return []
    with open(TABLE, encoding='utf-8') as f:
        return [r for r in csv.DictReader(f) if (r.get('admin') or '').strip()]  # колонки: admin,name,query[,minus]


def path_for(admin, name):
    return os.path.join(DIR, slug(admin, name) + '.geojson')


def files_sha():
    """Хеш всех файлов подмены - для подписи регионов (preclip.ne_sha)."""
    h = hashlib.sha1(APPLY_V.encode())
    for p in sorted(glob.glob(os.path.join(DIR, '*.geojson'))):
        h.update(os.path.basename(p).encode())
        with open(p, 'rb') as f:
            h.update(hashlib.sha1(f.read()).hexdigest().encode())
    return h.hexdigest()[:12]


def apply(feats):
    """Подменить геометрию фич NE, у которых есть файл подмены. Возвращает число подмен."""
    if not os.path.isdir(DIR):
        return 0
    idx = {}
    for p in glob.glob(os.path.join(DIR, '*.geojson')):
        idx[os.path.basename(p)[:-8]] = p
    n = 0
    land = _land_buf()
    for f in feats:
        pr = f.get('properties') or {}
        key = slug(pr.get('admin', ''), pr.get('name', ''))
        p = idx.get(key)
        if not p:
            continue
        with open(p, encoding='utf-8') as fh:
            g = json.load(fh)
        geom = g['features'][0]['geometry'] if g.get('type') == 'FeatureCollection' else g
        from shapely.geometry import shape, mapping
        gg = shape(geom).buffer(0)
        if land is not None:
            # морскую зону OSM-полигона снять: оставить сушу NE с припуском 2 км
            # (02.11.2026: Балкан, Астрахань, Приморье тащили морские границы
            # прямыми рёбрами; берег всё равно строит coast_osm по маске OSM)
            cut = gg.intersection(land)
            if not cut.is_empty:
                gg = cut
        # упростить до шага срезов (SIMP 0.001° ≈ 110 м): сырой OSM с вершинами
        # через 30-50 м делал обрезку по чужим границам (clip_foreign) в десятки
        # раз дольше - вторая полная сборка 02.11 стояла на ней полчаса без вывода
        gg = gg.simplify(SIMPLIFY, preserve_topology=True)
        if not gg.is_valid:
            gg = gg.buffer(0)
        geom = mapping(gg)
        f['geometry'] = geom
        pr['ne_override'] = 'OSM'
        n += 1
    return n


_LB = {}


def _land_buf(margin='0.02'):
    """Суша Natural Earth с припуском (cache/ne_admin1_land_buf0.02.wkb), один раз на процесс; None - файла нет."""
    if 'g' not in _LB:
        p = os.path.join(ROOT, 'cache', f'ne_admin1_land_buf{margin}.wkb')
        if os.path.exists(p):
            from shapely import wkb
            from shapely.prepared import prep
            g = wkb.loads(open(p, 'rb').read())
            _LB['g'] = g
        else:
            _LB['g'] = None
    return _LB['g']


def fetch(query):
    url = API + '?' + urllib.parse.urlencode(
        {'q': query, 'format': 'json', 'polygon_geojson': 1, 'limit': 3, 'featuretype': 'state'})
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=120) as f:
        data = json.load(f)
    for it in data:
        if it.get('class') == 'boundary' and it.get('type') == 'administrative' \
                and it.get('geojson', {}).get('type') in ('Polygon', 'MultiPolygon'):
            return it
    return None


def main():
    if '--fetch' in sys.argv:
        os.makedirs(DIR, exist_ok=True)
        bad = []
        for r in rows():
            p = path_for(r['admin'], r['name'])
            if os.path.exists(p) and '--force' not in sys.argv:
                continue
            # «A + B» - объединение нескольких единиц (новые области Казахстана 2022
            # года против старой нарезки NE); колонка minus - вычесть (Архангельская
            # область OSM включает Ненецкий округ, NE - нет)
            from shapely.geometry import shape, mapping
            from shapely.ops import unary_union
            parts, names = [], []
            miss = False
            for q in [x.strip() for x in r['query'].split(' + ') if x.strip()]:
                it = fetch(q); time.sleep(1.1)
                if not it:
                    miss = True; print('!! не найдено:', r['admin'], r['name'], '<-', q); break
                parts.append(shape(it['geojson']).buffer(0)); names.append(it.get('display_name', ''))
            if miss:
                bad.append((r['admin'], r['name'], r['query'])); continue
            geom = unary_union(parts)
            for q in [x.strip() for x in (r.get('minus') or '').split(' + ') if x.strip()]:
                if q.startswith('ne:'):
                    # вычесть единицу Natural Earth как есть (суша без морской зоны):
                    # OSM-полигон Ненецкого округа с морской границей резал
                    # Новую Землю прямыми рёбрами (02.11.2026)
                    adm, _, nm = q[3:].partition('/')
                    raw = json.load(open(os.path.join(ROOT, 'cache', 'ne_admin1.geojson'), encoding='utf-8'))['features']
                    sel = [f for f in raw if f['properties'].get('admin') == adm and f['properties'].get('name') == nm]
                    if not sel:
                        miss = True; print('!! нет в NE (minus):', q); break
                    geom = geom.difference(unary_union([shape(f['geometry']).buffer(0) for f in sel])); names.append('минус NE ' + q[3:])
                    continue
                it = fetch(q); time.sleep(1.1)
                if not it:
                    miss = True; print('!! не найдено (minus):', r['admin'], r['name'], '<-', q); break
                geom = geom.difference(shape(it['geojson']).buffer(0)); names.append('минус ' + it.get('display_name', ''))
            if miss:
                bad.append((r['admin'], r['name'], r['query'])); continue
            it = {'geojson': mapping(geom), 'display_name': ' + '.join(names), 'osm_type': 'union' if len(names) > 1 else parts and None, 'osm_id': None}
            fc = {'type': 'FeatureCollection', 'features': [{
                'type': 'Feature', 'geometry': it['geojson'],
                'properties': {'admin': r['admin'], 'name': r['name'], 'query': r['query'],
                               'osm_type': it.get('osm_type'), 'osm_id': it.get('osm_id'),
                               'display_name': it.get('display_name'),
                               'source': 'OpenStreetMap через Nominatim (featuretype=state, polygon_geojson), tools/ne_override.py',
                               'fetched': time.strftime('%Y-%m-%d')}}]}
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(fc, f, ensure_ascii=False)
            print('  +', r['admin'], r['name'], '<-', (it.get('display_name') or '')[:70],
                  f'{os.path.getsize(p)//1024} КБ')
        print('файлов подмены:', len(glob.glob(os.path.join(DIR, "*.geojson"))), 'не найдено:', len(bad))
        return 1 if bad else 0
    if '--check' in sys.argv:
        import math
        from shapely.geometry import shape
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import geoclean as gc
        raw = json.load(open(os.path.join(ROOT, 'cache', 'ne_admin1.geojson'), encoding='utf-8'))['features']
        def longest(g):
            best = 0
            for poly in (g.geoms if g.geom_type == 'MultiPolygon' else [g]):
                c = list(poly.exterior.coords)
                for a, b in zip(c, c[1:]):
                    best = max(best, math.hypot((a[0]-b[0])*111*math.cos(math.radians((a[1]+b[1])/2)), (a[1]-b[1])*111))
            return best
        for r in rows():
            p = path_for(r['admin'], r['name'])
            ne = [f for f in raw if f['properties'].get('admin') == r['admin'] and f['properties'].get('name') == r['name']]
            if not ne or not os.path.exists(p):
                print('   нет:', r['admin'], r['name'], 'NE' if not ne else '', 'файл' if not os.path.exists(p) else '')
                continue
            o = json.load(open(p, encoding='utf-8'))['features'][0]['geometry']
            print(f"   {r['admin']}/{r['name']}: NE {longest(shape(ne[0]['geometry'])):.0f} км -> OSM {longest(shape(o)):.0f} км")
        return 0
    print(__doc__)
    return 0


if __name__ == '__main__':
    sys.exit(main())
