#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Обрезка красного по чужой земле (задание куратора 07.09.2026).

ЗАЧЕМ. Контуры империи взяты из historical-basemaps, а вычитания нарезаны по
современным единицам Natural Earth. Линии двух наборов не совпадают, и там, где
контур источника заходит за нынешнюю границу соседа, оставалась узкая лента
красного. Куратор увидел это на 1842 годе: девять лент вдоль границы с Китаем и
Кореей, то есть карта утверждала, что империя держала полосы Маньчжурии за
шестнадцать лет до Айгунского договора. Проверка показала 204 среза из 246 с
таким дефектом, начиная с 1715 года.

ПРАВИЛО. За нынешней границей соседа красное остаётся ТОЛЬКО там, где на эту
дату действует курируемое приобретение из таблицы ADDS в build_expansion.py -
то есть у участка есть акт, дата и источник. Всё прочее за границей режется.
Так Карсская область (Берлинский трактат 01.07.1878) остаётся, а ленты уходят.

ЧУЖИЕ - список ниже (FOREIGN). В него входят только страны, куда империя не
распространялась НИКОГДА без отдельного акта. Финляндия, Польша, Прибалтика,
Молдова, Кавказ и Средняя Азия сюда НЕ входят: империя ими владела, и их
контуры - часть обычного показа.

Запуск:
    cd ~/tmp/imperium-map && .venv/bin/python3 tools/clip_foreign.py --dry
    cd ~/tmp/imperium-map && .venv/bin/python3 tools/clip_foreign.py

Без --dry файлы переписываются. Скрипт печатает, что срезано на каждом срезе, и
проверяет, что курируемые владения за границей уцелели.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

from shapely.geometry import mapping, shape, Point
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)

import build_expansion as BE                                    # noqa: E402
import geoclean as gc                                           # noqa: E402

CACHE = os.path.join(ROOT, 'cache')
YEARS = os.path.join(ROOT, 'data', 'years')

# Страны, где империи без отдельного акта быть не может.
FOREIGN = ['China', 'Mongolia', 'North Korea', 'South Korea', 'Japan',
           'Afghanistan', 'Iran', 'Turkey', 'Sweden', 'Norway',
           'India', 'Pakistan', 'Nepal', 'Bhutan']

# Что обязано уцелеть после обрезки: точка, дата, чем держалась.
KEEP = [((42.9, 40.6), '1900', 'Карсская область, Берлинский трактат 01.07.1878'),
        ((42.9, 40.6), '1914', 'Карсская область, до Брестского мира')]


def key_date(key):
    """Ключ среза -> дата ГГГГ-ММ-ДД (у годовых ключей - первое января)."""
    k = str(key)
    if len(k) == 4:
        return k + '-01-01'
    if len(k) == 7:
        return k + '-01'
    return k


def foreign_geom():
    ne = gc.load_json(os.path.join(CACHE, 'ne_admin1.geojson')) \
        if hasattr(gc, 'load_json') else json.load(
            open(os.path.join(CACHE, 'ne_admin1.geojson'), encoding='utf-8'))
    parts = [shape(f['geometry']).buffer(0) for f in ne['features']
             if str(f['properties'].get('admin', '')) in FOREIGN]
    if not parts:
        sys.exit('в кэше Natural Earth не нашлось ни одной чужой страны')
    return unary_union(parts)


_RELEVANT = None


def relevant(foreign):
    """Приобретения, которые вообще заходят за нынешнюю границу соседа.

    Их единицы (Карсская область, Аджария), а всего приобретений три сотни:
    считать объединение всех на каждом из 246 срезов - часы работы впустую.
    """
    global _RELEVANT
    if _RELEVANT is None:
        _RELEVANT = []
        for a in BE.ADDS:
            try:
                g = BE.reg_geom(a['reg'])
            except Exception:                                   # noqa: BLE001
                continue
            if g.is_empty or not g.intersects(foreign):
                continue
            inter = g.intersection(foreign)
            if inter.is_empty or inter.area < 1e-4:
                continue
            _RELEVANT.append((a, inter))
            print('за границей по акту: %s (%s, с %s%s)'
                  % (a['name'], a['reg'], a['frm'],
                     ', до ' + a['to'] if a['to'] else ''))
    return _RELEVANT


def allowed_at(date, foreign):
    """Курируемые приобретения, действующие на дату: их за границей не режем."""
    parts = [inter for a, inter in relevant(foreign)
             if a['frm'] <= date and not (a['to'] and a['to'] <= date)]
    return unary_union(parts) if parts else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true', help='только показать, не писать')
    ap.add_argument('--only', help='один ключ среза')
    a = ap.parse_args()

    foreign = foreign_geom()
    relevant(foreign)
    files = sorted(glob.glob(os.path.join(YEARS, '*.geojson')))
    if a.only:
        files = [f for f in files if os.path.basename(f)[:-8] == a.only]
    touched, total_cut = 0, 0.0
    for path in files:
        key = os.path.basename(path)[:-8]
        with open(path, encoding='utf-8') as f:
            fc = json.load(f)
        # Срезы Второй мировой НЕ трогаем: их геометрия построена
        # tools/build_ww2.py по таблице городов-якорей, а не унаследована от
        # источника, и она осознанно включает занятое за нынешней границей -
        # Маньчжурию, Северную Корею, Финнмарк. Первый прогон 07.09.2026 срезал
        # Харбин, Мукден, Порт-Артур, Пхеньян и Киркенес, и check_ww2 это
        # поймал (6 ошибок из 180).
        if any((f.get('properties') or {}).get('ww2') for f in fc['features']):
            continue
        g = unary_union([shape(x['geometry']).buffer(0)
                         for x in fc['features'] if x.get('geometry')])
        bleed = g.intersection(foreign)
        if bleed.is_empty or bleed.area < 1e-6:
            continue
        allowed = allowed_at(key_date(key), foreign)
        cut = bleed.difference(allowed) if allowed is not None else bleed
        if cut.is_empty or cut.area < 1e-6:
            continue
        n = len(list(cut.geoms)) if hasattr(cut, 'geoms') else 1
        print(f'{key}: режу {cut.area:.4f} кв. градуса, кусков {n}'
              + (f' (оставлено по актам {bleed.area - cut.area:.4f})'
                 if allowed is not None and bleed.area - cut.area > 1e-6 else ''))
        total_cut += cut.area
        touched += 1
        if a.dry:
            continue
        feats = []
        for x in fc['features']:
            if not x.get('geometry'):
                feats.append(x)
                continue
            g0 = shape(x['geometry'])
            if not g0.is_valid:
                g0 = g0.buffer(0)
            gg = g0.difference(cut)
            if gg.is_empty:
                continue
            # Рез идёт по чужой нарезке, и на шве остаются осколки: первый
            # прогон 07.09.2026 дал 93 новых места в check_geometry. Убираем
            # тонкие куски и крапинки - но НЕ зовём finish и sanitize_obj: они
            # закрывают дырки-озёра и заливают красным Байкал с Ладогой.
            gg, _ = gc.drop_thin_parts(gg)
            gg, _, _ = gc.despeckle(gg, CACHE)
            if gg.is_empty:
                continue
            y = dict(x)
            y['geometry'] = mapping(gg)
            feats.append(y)
        fc['features'] = feats
        # Ни finish, ни sanitize_obj здесь НЕ зовём. Они закрывают дырки-озёра
        # (fill_lake_holes), и первый прогон 07.09.2026 залил красным Байкал,
        # Ладогу, Онегу и Балхаш - площадь среза 1900 года выросла на 11 кв.
        # градуса вместо того, чтобы уменьшиться. Наше дело здесь одно: убрать
        # лишнее за чужой границей, ничего больше не трогая.
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(fc, f, ensure_ascii=False)
    print(f'--- срезов затронуто {touched}, срезано всего {total_cut:.3f} кв. градуса')

    if not a.dry:
        bad = []
        for (lon, lat), key, why in KEEP:
            p = os.path.join(YEARS, key + '.geojson')
            if not os.path.exists(p):
                continue
            g = unary_union([shape(x['geometry']).buffer(0)
                             for x in json.load(open(p, encoding='utf-8'))['features']
                             if x.get('geometry')])
            # Сверяем с тем, что было ДО обрезки: если участка не было и
            # раньше - это чужая дыра в данных, а не наша потеря.
            was = subprocess.run(['git', 'show', 'HEAD:data/years/%s.geojson' % key],
                                 capture_output=True, text=True, cwd=ROOT)
            had = False
            if was.returncode == 0:
                go = unary_union([shape(x['geometry']).buffer(0)
                                  for x in json.loads(was.stdout)['features']
                                  if x.get('geometry')])
                had = go.contains(Point(lon, lat))
            if had and not g.contains(Point(lon, lat)):
                bad.append('%s: %s пропало с карты' % (key, why))
            elif not had:
                print('  внимание: %s - %s не было на карте и ДО обрезки' % (key, why))
        if bad:
            sys.exit('ПОСЛЕ ОБРЕЗКИ ПОТЕРЯНО:\n  ' + '\n  '.join(bad))
        print('проверка: курируемые владения за границей на месте')


if __name__ == '__main__':
    main()
