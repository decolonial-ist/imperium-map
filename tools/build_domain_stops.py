#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Остановки ползунка для встраиваемой карты домена (задача 31.08.2026).

Полная карта останавливается на КАЖДОМ событии империи: срезы ядра, снимки
фронта, начала и концы эпизодов сферы, потерь контроля, острогов. Для карты
одного народа это шум: читателю матрицы Нохчи незачем щёлкать через Аляску,
Курилы и Африку. Куратор 31.08.2026: «клики сократить до тех, которые
что-то меняют вокруг и внутри территории народа».

Что считается изменением. На каждый срез кладётся не прямоугольник камеры, а
САМ КОНТУР домена с поясом в полградуса вокруг (data/domains/<id>.json, поля
geometry и stops_buffer_deg); берётся площадь имперского контура внутри него.
Прямоугольник для этого не годится: его угол цепляет соседей, до которых от
территории сотни километров - на карте Нохчи так вылезали четыре щелчка по
Южной Осетии 2008 года. Если между соседними срезами она изменилась больше
порога - дата становится остановкой; если нет, срез остаётся в показе (карта
всё равно рисует его при перемотке), но щелчка на нём не будет.

Кроме срезов остановку дают события слоёв, чья геометрия ПОПАДАЕТ в рамку:
сфера влияния, постсоветские эпизоды, потери имперского контроля (по эпизоду
целиком, а не по каждой фиче - иначе один Курск даст 89 щелчков) и остроги.
Логика повторяет buildStops() в index.html, но с отбором по рамке.

Фронт 2022+ берётся ПОМЕСЯЧНО (months манифеста DeepState), как и в полной
карте: подневные файлы лежат на диске задел ом, в показ не идут.

Порог по умолчанию - 60 км² или 0,05% площади рамки, что больше: он снимает
дрожание контуров источника, но оставляет реальные приобретения.

Запуск:

    cd ~/tmp/imperium-map && .venv/bin/python3 tools/build_domain_stops.py

На выходе: data/domains/<id>_stops.json - список дат с причиной каждой.
"""
import argparse
import glob
import json
import math
import os

from shapely.geometry import box, shape
from shapely.ops import unary_union
from shapely.prepared import prep

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
DATA = os.path.join(ROOT, 'data')
DOM = os.path.join(DATA, 'domains')

KM_DEG = 111.32


def km2(geom, lat):
    """Площадь в км² по местному масштабу: градус долготы уже на cos(широты)."""
    return geom.area * KM_DEG * KM_DEG * math.cos(math.radians(lat))


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def clip(fc, region):
    """Объединение геометрии коллекции, обрезанное рамкой."""
    parts = []
    for f in fc.get('features', []):
        g = f.get('geometry')
        if not g:
            continue
        try:
            s = shape(g).buffer(0)
        except Exception:
            continue
        if s.is_empty or not s.intersects(region):
            continue
        parts.append(s.intersection(region))
    if not parts:
        return None
    return unary_union(parts)


def hits(fc_features, region_prep, region, lat, min_km2):
    """Фичи, чья геометрия ЗАХОДИТ в рамку, а не задевает её углом.

    Без порога площади в остановки лезли соседи, у которых с рамкой общий
    угол: Южная Осетия давала четыре щелчка на карте Нохчи, хотя от неё в
    кадр попадает полоска в несколько километров.
    """
    out = []
    for f in fc_features:
        g = f.get('geometry')
        if not g:
            continue
        try:
            s = shape(g).buffer(0)
        except Exception:
            continue
        if s.is_empty or not region_prep.intersects(s):
            continue
        inter = s.intersection(region)
        if inter.is_empty:
            continue
        # точечные слои (остроги) идут кружком, у них площадь мала по природе
        if km2(inter, lat) < min_km2 and inter.geom_type not in ('Point', 'MultiPoint'):
            continue
        out.append(f)
    return out


def day_after(iso):
    import datetime
    y, m, d = (int(x) for x in iso.split('-')[:3])
    return (datetime.date(y, m, d) + datetime.timedelta(days=1)).isoformat()


def key_to_iso(key):
    p = str(key).split('-')
    y = int(p[0])
    m = int(p[1]) if len(p) > 1 else 1
    d = int(p[2]) if len(p) > 2 else 1
    return '%04d-%02d-%02d' % (y, m, d)


def build(domain_id, thresh_arg, quiet=False):
    dom = load(os.path.join(DOM, domain_id + '.json'))
    region = shape(dom['geometry']).buffer(dom.get('stops_buffer_deg', 0.5))
    rprep = prep(region)
    b = region.bounds
    lat = (b[1] + b[3]) / 2
    frame_km2 = km2(region, lat)
    thresh = thresh_arg if thresh_arg is not None else max(60.0, frame_km2 * 0.0005)

    stops = {}                                     # iso -> (причина, вес)
    # Вес нужен сборщику пакета (build_domain_bundle.py): встраиваемая карта
    # режется жёстко, и резать надо по важности, а не по порядку. У изменений
    # контура вес - сама изменившаяся площадь в км²; у событий - постоянная,
    # подобранная так, чтобы война или уход империи из края не вылетали ради
    # пары сотен квадратных километров дрожания границы.
    W_EVENT = {'ostrog': 400.0, 'loss': 6000.0, 'ps': 9000.0, 'sphere': 5000.0,
               'edge': 1e9}
    # событие считается «своим», если внутрь рамки заходит не меньше этого
    min_ev = max(25.0, frame_km2 * 0.0005)

    def add(d, why, w=None):
        iso = key_to_iso(d)
        if iso not in stops or stops[iso][1] < (w or 0):
            stops[iso] = (why, float(w or 0))

    # ---- срезы ядра --------------------------------------------------------
    mf = load(os.path.join(DATA, 'manifest.json'))
    prev, prev_key, seen_any = None, None, False
    for key in mf['years']:
        path = os.path.join(DATA, 'years', str(key) + '.geojson')
        if not os.path.exists(path):
            continue
        cur = clip(load(path), region)
        iso = key_to_iso(key)
        if prev is None:
            if cur is not None and not cur.is_empty:
                add(iso, ('империя вернулась в кадр' if seen_any
                          else 'первый срез, где империя достаёт до рамки'),
                    W_EVENT['edge'] if not seen_any else W_EVENT['ps'])
                seen_any = True
        else:
            a = prev if prev is not None else box(0, 0, 0, 0)
            b = cur if cur is not None else box(0, 0, 0, 0)
            d = km2(a.symmetric_difference(b), lat)
            if d >= thresh:
                add(iso, 'контур империи изменился на %d км²' % round(d), d)
        if cur is not None and not cur.is_empty:
            prev, prev_key = cur, key
        elif prev is not None and cur is None:
            prev = None

    # ---- фронт 2022+: помесячно, как в полной карте ------------------------
    dsp = os.path.join(DATA, 'deepstate', 'manifest.json')
    if os.path.exists(dsp):
        dsmf = load(dsp)
        prev, last_front = None, None
        for day in (dsmf.get('months') or dsmf.get('days') or []):
            path = os.path.join(DATA, 'deepstate', 'days', day + '.geojson')
            if not os.path.exists(path):
                continue
            fc = load(path)
            occ = {'features': [f for f in fc.get('features', [])
                                if f.get('properties', {}).get('s') == 'occupied']}
            cur = clip(occ, region)
            if cur is None:
                prev = None
                continue
            if prev is None:
                add(day, 'снимок фронта задевает рамку', W_EVENT['edge'])
            else:
                d = km2(prev.symmetric_difference(cur), lat)
                if d >= thresh:
                    add(day, 'линия фронта сдвинулась на %d км²' % round(d), d)
            prev = cur
            last_front = day
        # последний снимок фронта - остановка всегда: иначе у карты идущей
        # войны листание кончается на месяце, где линия сдвинулась заметно, и
        # «сегодня» до читателя не доезжает
        if last_front:
            add(last_front, 'последний снимок фронта', W_EVENT['edge'])

    # ---- события слоёв: только те, что задевают рамку ----------------------
    sp = os.path.join(DATA, 'sphere.geojson')
    if os.path.exists(sp):
        for f in hits(load(sp).get('features', []), rprep, region, lat, min_ev):
            p = f['properties']
            nm = p.get('name_ru') or p.get('name') or 'эпизод'
            if p.get('from'):
                add(p['from'], 'сфера влияния: %s, начало' % nm, W_EVENT['sphere'])
            if p.get('to'):
                add(day_after(p['to']), 'сфера влияния: %s, конец' % nm,
                    W_EVENT['sphere'])

    psp = os.path.join(DATA, 'postsoviet.geojson')
    if os.path.exists(psp):
        for f in hits(load(psp).get('features', []), rprep, region, lat, min_ev):
            p = f['properties']
            nm = p.get('name_ru') or p.get('territory') or 'эпизод'
            if p.get('from'):
                add(p['from'], 'постсоветский эпизод: %s, начало' % nm, W_EVENT['ps'])
            if p.get('to'):
                add(day_after(p['to']), 'постсоветский эпизод: %s, конец' % nm,
                    W_EVENT['ps'])

    # потери контроля: по эпизоду целиком
    lman = os.path.join(DATA, 'losses', 'manifest.json')
    if os.path.exists(lman):
        names = {e['slug']: e.get('name', e['slug'])
                 for e in load(lman).get('episodes', [])}
        for path in sorted(glob.glob(os.path.join(DATA, 'losses', '*.geojson'))):
            slug = os.path.splitext(os.path.basename(path))[0]
            if slug not in names:
                continue
            fs = hits(load(path).get('features', []), rprep, region, lat, min_ev)
            if not fs:
                continue
            frm = min(f['properties']['from'] for f in fs if f['properties'].get('from'))
            tos = [f['properties'].get('to') for f in fs if f['properties'].get('to')]
            add(frm, 'потеря имперского контроля: %s, начало' % names[slug],
                W_EVENT['loss'])
            if tos and len(tos) == len(fs):
                add(day_after(max(tos)), 'потеря имперского контроля: %s, конец'
                    % names[slug], W_EVENT['loss'])

    op = os.path.join(DATA, 'ostrogs', 'ostrogs.geojson')
    if os.path.exists(op):
        for f in hits(load(op).get('features', []), rprep, region, lat, min_ev):
            p = f['properties']
            nm = p.get('name', 'острог')
            if p.get('from'):
                add(p['from'], 'острог %s поставлен' % nm, W_EVENT['ostrog'])
            if p.get('red_from'):
                add(p['red_from'], 'острог %s: земля вокруг закрашена' % nm,
                    W_EVENT['ostrog'])
            if p.get('to'):
                add(day_after(p['to']), 'острог %s снят' % nm, W_EVENT['ostrog'])

    out = {
        'domain': domain_id,
        'threshold_km2': round(thresh, 1),
        'frame_km2': round(frame_km2),
        'note': ('остановки ползунка встраиваемой карты: даты, на которых '
                 'внутри рамки домена что-то меняется; собрано '
                 'tools/build_domain_stops.py'),
        'stops': [{'d': k, 'why': stops[k][0], 'w': round(stops[k][1], 1)}
                  for k in sorted(stops)],
    }
    path = os.path.join(DOM, domain_id + '_stops.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    if not quiet:
        print('%-11s остановок %d (порог %.0f км², пояс %d км²) -> %s'
              % (domain_id, len(out['stops']), thresh, frame_km2,
                 os.path.relpath(path, ROOT)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--domain', help='id домена; по умолчанию все')
    ap.add_argument('--thresh-km2', type=float, default=None)
    a = ap.parse_args()
    ids = ([a.domain] if a.domain else
           sorted(os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(DOM, '*.json'))
                  if not p.endswith(('_stops.json', '_bundle.json',
                                     '_bundles.json', '_base.json'))))
    for i in ids:
        build(i, a.thresh_km2)


if __name__ == '__main__':
    main()
