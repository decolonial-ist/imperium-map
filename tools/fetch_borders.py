#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Границы для показа: Украина и Ичкерия (задание куратора 06.09.2026).

УКРАИНА. В данных подложки (OpenMapTiles) на месте Крыма лежит ТОЛЬКО
российская версия линии - украинской там нет ни на одном масштабе, проверено
разбором тайлов до z11. Обе спорные версии карта из показа убирает, и
полуостров оставался единственным местом без обводки. Линия берётся из
OpenStreetMap, где граница Украины проведена по признанному положению - с
Крымом, а в Керченском проливе обходит косу Тузла с востока.

ИЧКЕРИЯ. Своей оцифровки границ Чеченской Республики Ичкерия у проекта нет,
и вырез из красного в окне 1996-1999 стоит на контуре современной Чеченской
Республики. Розыск 06.09.2026:
  - закон РФ от 04.06.1992 N 2927-I разделил Чечено-Ингушскую АССР на две
    республики, НЕ определив границу между ними;
  - в 1993 году Аушев и Дудаев подписали договор, по которому Сунженский район
    почти целиком отошёл Ингушетии, а за Чечнёй остались Серноводск и
    Ассиновская - это и есть нынешняя линия. Текст договора и его точная дата
    в открытом доступе не найдены;
  - 26.09.2018 Кадыров и Евкуров обменялись НЕЗАСЕЛЁННЫМИ участками на границе
    Надтеречного района Чечни и Малгобекского района Ингушетии; геометрия этих
    участков не опубликована, откатить обмен нечем.
Поэтому линия Ичкерии = современная граница Чеченской Республики, и оговорка
записана в свойстве why самого файла.

Запуск:
    cd ~/tmp/imperium-map && .venv/bin/python3 tools/fetch_borders.py

На выходе data/borders/ukraine_osm.geojson и data/borders/ichkeria_osm.geojson.
Файл НЕ пишется, если не сошлись проверки по точкам (см. TARGETS).
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

from shapely.geometry import LineString, MultiLineString, Point, box, mapping
from shapely.ops import linemerge, polygonize, unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
OUTDIR = os.path.join(ROOT, 'data', 'borders')
UA = 'imperium-map-research/1.0 (+https://decolonial.ist; contact@decolonial.ist)'
MIRRORS = ['https://overpass-api.de/api/interpreter',
           'https://overpass.kumi.systems/api/interpreter',
           'https://overpass.private.coffee/api/interpreter']
TOL = 0.0015           # упрощение, около 120 м - на наших масштабах невидимо

Q_UA = ('[out:json][timeout:300];\n'
        'rel["type"="boundary"]["boundary"="administrative"]'
        '["admin_level"="2"]["name:en"="Ukraine"];\n'
        'way(r);\nout geom;\n')
# Отношение Чечни в OpenStreetMap - 109877 (найдено через Nominatim по имени
# «Чеченская Республика»; тег name:en у него не «Chechen Republic»).
Q_CE = ('[out:json][timeout:300];\n'
        'rel(109877);\n'
        'way(r);\nout geom;\n')

TARGETS = [
    {'file': 'ukraine_osm.geojson',
     'title': 'Украина',
     'name': 'Государственная граница Украины',
     'query': Q_UA,
     'source': 'OpenStreetMap, отношение границы Украины (admin_level=2), выгрузка Overpass',
     'why': ('подложка на месте Крыма держит только российскую версию линии, '
             'украинской в её данных нет ни на одном масштабе'),
     'inside': {'Симферополь': (34.1, 44.95), 'Севастополь': (33.53, 44.6),
                'Керчь': (36.47, 45.35), 'коса Тузла': (36.54, 45.27),
                'Киев': (30.52, 50.45), 'Мариуполь': (37.55, 47.1)},
     'outside': {'Краснодар': (38.98, 45.04), 'Ростов': (39.7, 47.23),
                 'Минск': (27.56, 53.9)},
     'no_line': ('перешеек Крыма', box(33.4, 45.9, 34.8, 46.3))},
    {'file': 'ichkeria_osm.geojson',
     'title': 'Ичкерия',
     'name': 'Граница Чеченской Республики Ичкерия',
     'query': Q_CE,
     'source': 'OpenStreetMap, отношение границы Чеченской Республики, выгрузка Overpass',
     'why': ('своей оцифровки границ Ичкерии 1991-1999 нет; закон РФ от 04.06.1992 '
             'разделил Чечено-Ингушскую АССР, НЕ определив границу, а линию по '
             'Сунженскому району (Серноводск и Ассиновская за Чечнёй) закрепил '
             'договор Аушева и Дудаева 1993 года, текст которого в открытом доступе '
             'не найден; отличие от нынешнего контура - незаселённые участки, '
             'обменянные 26.09.2018, их геометрия не опубликована'),
     'inside': {'Грозный': (45.7, 43.32), 'Шатой': (45.68, 42.85),
                'Ведено': (46.08, 42.96), 'Серноводск': (45.16, 43.32),
                'Ассиновская': (45.13, 43.24), 'Гудермес': (46.1, 43.35)},
     'outside': {'Назрань': (44.77, 43.22), 'Малгобек': (44.6, 43.51),
                 'Владикавказ': (44.68, 43.02), 'Хасавюрт': (46.59, 43.25)},
     'no_line': None},
]


def ask(query):
    """Overpass отвечает 504, когда занят: пробуем зеркала и повторяем."""
    last = None
    for base in MIRRORS:
        for _ in range(3):
            try:
                req = urllib.request.Request(
                    base, data=urllib.parse.urlencode({'data': query}).encode(),
                    headers={'User-Agent': UA})
                with urllib.request.urlopen(req, timeout=420) as resp:
                    print('  взято с', base)
                    return json.load(resp)
            except Exception as e:                      # noqa: BLE001
                last = '%s: %s' % (base, e)
                print('  не вышло (%s), жду и пробую снова' % e)
                time.sleep(8)
    sys.exit('Overpass не ответил: %s' % last)


def build(t):
    print(t['title'] + ':')
    els = [e for e in ask(t['query']).get('elements', []) if len(e.get('geometry') or []) > 1]
    print('  участков границы: %d, точек %d'
          % (len(els), sum(len(e['geometry']) for e in els)))
    lines = [LineString([(p['lon'], p['lat']) for p in e['geometry']]) for e in els]
    merged = linemerge(unary_union(lines))
    if merged.geom_type == 'LineString':
        merged = MultiLineString([merged])
    simp = MultiLineString([g.simplify(TOL, preserve_topology=True) for g in merged.geoms])
    print('  после склейки и упрощения: кусков %d, точек %d'
          % (len(simp.geoms), sum(len(g.coords) for g in simp.geoms)))

    polys = list(polygonize(simp))
    if not polys:
        sys.exit('  линия не замкнулась в контур - показывать нечего')
    area = unary_union(polys)
    bad = []
    for name, (x, y) in t['inside'].items():
        if not area.contains(Point(x, y)):
            bad.append('%s должен быть ВНУТРИ' % name)
    for name, (x, y) in t['outside'].items():
        if area.contains(Point(x, y)):
            bad.append('%s должен быть СНАРУЖИ' % name)
    if t['no_line']:
        where, rect = t['no_line']
        cut = simp.intersection(rect).length
        if cut > 0.01:
            bad.append('линия режет %s: длина %.3f°' % (where, cut))
    if bad:
        sys.exit('  ПРОВЕРКИ НЕ СОШЛИСЬ, файл не записан:\n    ' + '\n    '.join(bad))
    print('  проверки сошлись: %s внутри, %s снаружи'
          % (', '.join(t['inside']), ', '.join(t['outside'])))

    fc = {'type': 'FeatureCollection', 'features': [{
        'type': 'Feature',
        'properties': {'name': t['name'], 'source': t['source'], 'why': t['why']},
        'geometry': mapping(simp)}]}
    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, t['file'])
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(fc, f, ensure_ascii=False, separators=(',', ':'))
    print('  записано %s (%.1f КБ)' % (path, os.path.getsize(path) / 1024))


def main():
    for t in TARGETS:
        build(t)


if __name__ == '__main__':
    main()
