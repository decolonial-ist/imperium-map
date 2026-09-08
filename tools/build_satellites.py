#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сателлиты империи: земля, где на месте распоряжается не она сама, а свои
люди на её деньгах и оружии (задание куратора 08.09.2026).

ЗАЧЕМ. Беларусь с 1991 года карта красит отдельным слоем: красная гамма, но
пунктиром - сателлит, а не территория. Тем же приёмом решено показывать Чечню
1993-1994 годов: куратор 08.09.2026 на вопрос «красить ли контроль местной
промосковской оппозиции» - «крась как современную беларусь, зона влияния».

ЧТО ЗДЕСЬ. Заявка домена Нохчи от 08.09.2026 с документами
(NOTICE_OT_NOHCHI_CHECHNYA_1993-1994_KONTROL_2026-09-08.md, таблица точек
chechnya_1991_1994_opposition_control_from_nohchi.csv). Суть: с 16.12.1993 в
Надтеречном районе сидит «Временный совет Чеченской Республики» Умара
Автурханова, который Москва финансирует, вооружает и признаёт законной властью;
летом 1994 к нему прибавляются Урус-Мартан и Гехи (Гантамиров), Толстой-Юрт
(группа Хасбулатова), Ищёрская, Аргун (отряд Лабазанова). Российской армии на
земле ещё нет: экипажи с 02.09.1994, вторжение 11.12.1994 - дальше слой войны.

ЧЕГО ЗДЕСЬ НЕТ. Окно 01.11.1991-15.12.1993, когда Надтеречный район просто не
подчинялся Грозному: это ещё не Москва на земле, а местное неподчинение, и
решения куратора по нему нет.

РАДИУС ТОЧЕК УСЛОВНЫЙ - 8 км, обозначение места, а не линия контроля; тем же
приёмом на карте показаны остроги и рейды.

Запуск: cd ~/tmp/imperium-map && .venv/bin/python3 tools/build_satellites.py
На выходе data/satellite/chechnya_1993_1994.geojson.
"""
import json
import math
import os

from shapely.geometry import mapping, shape, Polygon, Point
from shapely.ops import unary_union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(DATA, 'satellite')
SRC_NOTICE = 'заявка домена Нохчи 08.09.2026 с документами: NOTICE_OT_NOHCHI_CHECHNYA_1993-1994_KONTROL_2026-09-08.md'
END = '1994-12-10'          # 11.12.1994 входит российская армия - дальше слой войны
R_KM = 8.0

# точка: имя, широта, долгота, с какой даты, по какую, чем держалась
POINTS = [
    ('Урус-Мартан', 43.133, 45.538, '1994-07-15', END,
     'отряды Беслана Гантамирова с июля 1994; 02.09.1994 силы Грозного атаковали окраину, город не взяли'),
    ('Гехи', 43.166, 45.472, '1994-07-15', END,
     'база Гантамирова; 16.10.1994 отряды оппозиции отошли в Знаменское и Гехи'),
    ('Ищёрская', 43.714, 45.129, '1994-07-01', END,
     'станица на левом берегу Терека; 06.08.1994 пост оппозиции на Ищерском мосту'),
    ('Толстой-Юрт', 43.442, 45.775, '1994-08-20', '1994-09-16',
     'группа Руслана Хасбулатова с бронетехникой; 17.09.1994 село взято силами Грозного'),
    ('Аргун', 43.295, 45.869, '1994-06-20', '1994-09-04',
     'отряд Руслана Лабазанова, союзника Автурханова; 05.09.1994 разгромлен, город снова под Грозным'),
]


def circle(lon, lat, km, steps=48):
    dlat = km / 111.32
    dlon = dlat / max(math.cos(math.radians(lat)), 1e-6)
    return Polygon([(lon + dlon * math.cos(2 * math.pi * i / steps),
                     lat + dlat * math.sin(2 * math.pi * i / steps))
                    for i in range(steps)])


def main():
    src = os.path.join(DATA, 'chechnya', 'opposition_1993_1994.geojson')
    if not os.path.exists(src):
        raise SystemExit('нет %s - сперва .venv/bin/python3 tools/fetch_osm_units.py '
                         'chechnya_opposition_1994' % src)
    with open(src, encoding='utf-8') as f:
        d = json.load(f)
    district = unary_union([shape(x['geometry']).buffer(0) for x in d['features']])
    if district.is_empty:
        raise SystemExit('контур Надтеречного района пуст')

    feats = [{
        'type': 'Feature',
        'geometry': mapping(district),
        'properties': {
            'name': 'Надтеречный район',
            'holder': 'Временный совет Чеченской Республики (Умар Автурханов)',
            'from': '1993-12-16', 'to': END,
            'why': '16.12.1993 в Знаменском создан Временный совет; Москва его финансирует '
                   '(150 млрд рублей и 1,5 млрд наличными 30.07.1994), вооружает (танки и '
                   'бронетранспортёры из Моздока, август 1994) и признаёт законной властью',
            'source': SRC_NOTICE + '; контур - OpenStreetMap, отношение 1749734',
        }}]
    for name, lat, lon, frm, to, why in POINTS:
        feats.append({
            'type': 'Feature',
            'geometry': mapping(circle(lon, lat, R_KM)),
            'properties': {'name': name, 'holder': 'отряды промосковской оппозиции',
                           'from': frm, 'to': to, 'why': why,
                           'radius_km': R_KM,
                           'note': 'радиус условный - обозначение места, а не линия контроля',
                           'source': SRC_NOTICE}})

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'chechnya_1993_1994.geojson')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': feats}, f,
                  ensure_ascii=False, separators=(',', ':'))
    print('OK %s: фич %d (%.0f КБ)' % (path, len(feats), os.path.getsize(path) / 1024))
    for x in feats:
        p = x['properties']
        print('   %-20s %s .. %s' % (p['name'], p['from'], p['to']))


if __name__ == '__main__':
    main()
