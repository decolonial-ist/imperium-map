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


# Тип точки. Куратор 01.09.2026: «ну заводи этот тип. но пусть он тоже будет
# красным. не надо ему другого цвета». Поэтому цвет у всех один - имперское
# красное, а отличаются точки размером и словом в попапе:
#   ostrog  - изба с гарнизоном, живёт ясаком;
#   zavod   - завод и посёлок при нём: земля, лес, вода и приписанные люди;
#   faktor  - фактория компании, которой государство отдало право занимать
#             землю (Российско-Американская компания, привилегии 1799 года).
# Острог и крепость - разные вещи, и куратор 01.09.2026 велел их развести.
# ОСТРОГ - XVI-XVII век и деревянный тын: вертикально врытые заострённые
# брёвна (отсюда и слово), внутри изба с гарнизоном, задача - брать ясак.
# КРЕПОСТЬ - XVIII век и регулярная фортификация: земляной вал, ров, бастионы
# по инженерному плану, артиллерия. В документах проекта это видно дословно:
# указ 28.05.1723 велит при заводах на Исети ставить «новую крѣпость» с
# гарнизоном, инструкция Кирилову 1734 года - «хотя малую земляную крѣпостцу
# по искуству инженерныхъ офицеровъ». На Кавказе острогов не было вовсе:
# линия строилась сразу крепостями, укреплениями, фортами и редутами.
KIND_WORD = {'ostrog': 'острог', 'krepost': 'крепость', 'zavod': 'завод',
             'faktor': 'фактория компании', 'katorga': 'каторжный пост',
             'priisk': 'прииск'}


def build(rows, skipped=None):
    feats = []
    for r in rows:
        lon, lat = float(r['lon']), float(r['lat'])
        km = float(r['radius_km'] or 15)
        kind = (r.get('kind') or '').strip() or 'ostrog'
        if kind not in KIND_WORD:
            raise SystemExit('неизвестный тип точки «%s» у %s; допустимы: %s'
                             % (kind, r['slug'], ', '.join(KIND_WORD)))
        # ТОЧКА НА УЖЕ КРАСНОЙ ЗЕМЛЕ В ПОКАЗ НЕ ИДЁТ (02.09.2026).
        # Куратор: «мне не надо появление заводов внутри покрасневшей зоны,
        # можешь скрыть это, включая лишние шаги». Смысл слоя - показать, чем
        # империя занимала ЧУЖОЕ: острог, крепость, завод ставятся там, где
        # красного ещё нет. Предприятие, заведённое внутри давно занятой земли,
        # ничего про захват не говорит и только мельтешит на ползунке -
        # появилось и тут же погасло
        red = red_from(lon, lat)
        if red is not None and str(red) <= str(r['founded']):
            if skipped is not None:
                skipped.append((r['name_ru'], KIND_WORD[kind],
                                r['founded'][:4], str(red)[:4]))
            continue
        geom = {'type': 'Polygon', 'coordinates': circle(lon, lat, km)}
        feats.append({
            'type': 'Feature',
            'geometry': gc.clean_rings(geom),
            'properties': {
                'slug': r['slug'], 'name': r['name_ru'],
                'from': r['founded'], 'to': (r['gone'] or '').strip() or None,
                # Правило «точка гаснет, когда земля вокруг покраснела»
                # придумано 28.08.2026 для ОСТРОЖНОЙ эпохи: острог показывает
                # присутствие там, где красного ещё нет. Для промышленной
                # колонизации оно работает наоборот и вырезает её целиком:
                # Невьянский завод поставлен в 1702 году на земле, покрасневшей
                # в 1587-м, и не показывался НИ НА ОДНОЙ дате. Куратор
                # 01.09.2026, посмотрев карту: «семь или больше крепостей разом
                # возникают... заводы не видны». Поэтому правило снято для
                # заводов и факторий, а у крепостей - только там, где земля
                # покраснела ПОЗЖЕ постройки; крепость, поставленная внутри
                # уже красного, тоже светится всегда, иначе её нет вовсе.
                'red_from': red_visible(kind, r['founded'], lon, lat),
                'lon': lon, 'lat': lat, 'radius_km': km,
                'source': r['source'], 'note': r['note'],
                'kind': kind, 'kind_ru': KIND_WORD[kind],
                # чья это была земля до точки: ясачные волости и народы,
                # собрано розыском 01.09.2026 (MAP-MATERIALS/industrial/11_narody.md)
                'land': (r.get('land') or '').strip(),
                'geometry_note': (
                    f'геометрия условная: кружок радиусом {km:g} км вокруг '
                    f'точки ({KIND_WORD[kind]}), обозначение места, а не '
                    f'линия контроля'),
                'approximate': True,
            },
        })
    return feats


_slices = None


def red_visible(kind, founded, lon, lat):
    """Дата гашения точки - или None, если точку гасить не надо.

    Правило одно для всех типов (02.09.2026): точка светится от постройки до
    того дня, когда земля вокруг покраснела. Точки, поставленные на уже
    красной земле, до сюда не доходят - их отсеивает build().
    """
    red = red_from(lon, lat)
    if red is None:
        return None
    return red if str(red) > str(founded) else None


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
    skipped = []
    feats = build(rows, skipped)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj({'type': 'FeatureCollection', 'features': feats}), f,
                  ensure_ascii=False)
    size = os.path.getsize(OUT)
    if skipped:
        print(f'   СКРЫТО (земля уже была красной): {len(skipped)} — '
              + ', '.join(f'{n} — {k}, {f}, красное с {rd}'
                          for n, k, f, rd in skipped))
    shown = {f['properties']['slug'] for f in feats}
    gone = [r for r in rows
            if (r.get('gone') or '').strip() and r['slug'] in shown]
    print(f'OK {os.path.relpath(OUT, ROOT)}: острогов {len(feats)}, '
          f'{size // 1024} КБ')
    print(f'   из них империя бросила: {len(gone)} — '
          + ', '.join(f"{r['name_ru']} ({r['gone'][:4]})" for r in gone))
    vis = [r for r in rows if r['slug'] in shown]
    first = min(vis, key=lambda r: r['founded'])
    last = max(vis, key=lambda r: r['founded'])
    print(f"   окно: {first['founded']} ({first['name_ru']}) .. "
          f"{last['founded']} ({last['name_ru']})")
    gc.write_stamp('ostrogs')


if __name__ == '__main__':
    main()
