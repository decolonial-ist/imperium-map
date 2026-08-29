#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Помесячная линия контроля на Донбассе: апрель 2014 - февраль 2015, плюс 2022.

ЗАЧЕМ (задача куратора 26.08.2026). Донбасс появлялся на карте СПЛОШНЫМ КУСКОМ
с 06.04.2014, причём геометрия бралась одна на все восемь лет - линия ОРДЛО из
статичного файла DeepStateMAP, то есть линия, на которой фронт встал ПОСЛЕ
Дебальцева, в феврале 2015 года. Дословно: «донецкая область появляется сразу
вместе с крымом, сплошным куском. там бои шли и они пытались захватывать города
и их отбивали».

Ошибка ровно та же, которую до этого лечили во Второй мировой: статичная
финальная линия вместо движения фронта. Метод лечения тот же и код тот же -
`tools/build_ww2.py` (города-якоря, взвешенный голос ближайших, нулевая
изолиния). Этот билдер ИМПОРТИРУЕТ его класс поля, а не повторяет:

    import build_ww2 as bw ... bw.Field(anchors)

параметры поля (рамка, шаг сетки, степень, число соседей) подменяются на
донбасские перед созданием поля - театр здесь на порядок меньше, шаг сетки
можно взять мельче.

ЧТО ДЕЛАЕТ. Для каждого среза (даты берутся из `data/postsoviet/registry.csv` -
строки, у которых `territory` начинается на `donbas_`) считает зону, которой
на эту дату распоряжается империя, и пишет её в `data/postsoviet/donbas.geojson`
одним полигоном на срез. Дальше файл подхватывает `tools/build_postsoviet.py`:
геометрия - отсюда, даты, события и пруфы - из курируемой таблицы реестра.

    зона(дата) = { p : Σ s_i(дата) / d_i^3 > 0 } ∩ рамка театра

  * `data/crosscheck/donbas_cities.csv` - таблица якорей: населённый пункт,
    координаты, дата перехода под контроль российской стороны (`lost`), дата
    возврата под контроль Украины (`liberated`). У якоря на любую дату есть
    сторона: +1 (империя распоряжается) или -1 (не распоряжается).
  * якоря со стороной +1 навсегда - это города по ту сторону границы (Ростов,
    Таганрог, Гуково, Белгород) и Беларусь: без них линия у самой границы
    провисала бы внутрь Украины, потому что голосовать за неё было бы некому.
    Крым идёт якорями с 27.02.2014 - плацдарм южного наступления 2022 года.
  * якоря со стороной -1 навсегда - украинское кольцо (Харьков, Днепр,
    Запорожье, Павлоград, Полтава, Киев, Львов, Одесса): они держат поле от
    расползания на всю страну.

РАМКА ТЕАТРА - две разные:
  * срезы 2014-2015 обрезаются Донецкой и Луганской областями (Natural Earth
    admin-1). Вся война этих месяцев шла внутри двух областей, и обрезка не даёт
    полю пролезть ни в Харьковскую область, ни через перешеек из Крыма;
  * срезы 2022 года обрезаются всей Украиной. Крыма в этой выборке Natural Earth
    нет (у этой версии он отнесён к России), и это как раз то, что нужно:
    полуостров красит свой собственный эпизод, а мы его не дублируем.

ЧТО ЭТО ДАЁТ. Апрель 2014 года выглядит так, как он и выглядел: отдельные
занятые города, а не сплошная область. Славянский выступ вырастает 12.04 и
исчезает 05.07. Мариуполь краснеет 13.04 и гаснет 13.06. Июльское наступление
съедает север Луганской области. После Иловайска и Новоазовска на юге вырастает
приморская полоса. Дебальцевский выступ живёт до 18.02.2015 - до этой даты он
украинский, и линия ОРДЛО появляется только 19.02.2015.

ГРАНИЦЫ ЧЕСТНОСТИ. Это РЕКОНСТРУКЦИЯ по датам перехода населённых пунктов, а
не оцифровка карт боевых действий. Между двумя соседними якорями линия идёт
там, где её проводит формула. Точность - порядка половины расстояния между
соседними якорями: на Донбассе якоря стоят густо (10-25 км), в Херсонской и
Черниговской областях 2022 года - редко (50-80 км). У каждого среза стоят
`reconstruction: true` и `approximate: true`.

Запуск (нужны shapely, scipy и numpy из .venv):

    cd ~/tmp/imperium-map && .venv/bin/python tools/build_donbas.py
    cd ~/tmp/imperium-map && .venv/bin/python tools/build_postsoviet.py
    cd ~/tmp/imperium-map && .venv/bin/python tools/check_donbas.py
"""
import argparse
import csv
import json
import os
import sys

import geoclean as gc
from datetime import date

import numpy as np
from shapely.geometry import Point, box, mapping
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_expansion as be       # noqa: E402  (ne_pick, d, _round)
import build_ww2 as bw             # noqa: E402  (Field, load_anchors, side_at)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
ANCHORS = os.path.join(DATA, 'crosscheck', 'donbas_cities.csv')
REG = os.path.join(DATA, 'postsoviet', 'registry.csv')
OUT = os.path.join(DATA, 'postsoviet', 'donbas.geojson')

# ---- параметры поля (подменяют глобали build_ww2) --------------------------
BOX = (21.0, 44.0, 41.5, 53.2)   # вся Украина плюс полоса за границей
STEP = 0.02                      # шаг сетки, ~2.2 км по широте
POW = 3.0                        # степень обратного расстояния
KNN = 8                          # сколько ближайших якорей голосуют
PHI0 = 48.5                      # широта, по которой сжимаем долготу
FRONT_SIMPLIFY = 0.005           # упрощение линии; ДОЛЖНО быть меньше шага сетки
SIMPLIFY = 0.008                 # упрощение готового полигона, ~800 м
SPECK = 0.0002                   # град²: мельче - выбрасываем (шум растра)

# С этой даты срез обрезается всей Украиной, до неё - двумя областями.
FULL_FROM = be.d('2022-02-01')
PREFIX = 'donbas_'

_g = {}


# ---- якоря: колонки те же, что у ВМВ, но смысл `lost`/`liberated` зеркальный
def parse_changes(row):
    """Строка таблицы -> хроника [(дата, +1|-1), ...] и стартовая сторона.

    ВНИМАНИЕ, ЗЕРКАЛО. В `ww2_cities.csv` империя - это точка отсчёта: `lost` =
    империя потеряла город, `liberated` = вернула. Здесь таблица написана с
    украинской стороны, как её и просил куратор: `lost` = населённый пункт
    ПОТЕРЯН УКРАИНОЙ (перешёл под контроль российской стороны, +1), а
    `liberated` = ВОЗВРАЩЁН под контроль Украины (-1). Поэтому знаки
    противоположны тем, что ставит `build_ww2.parse_changes`, и эта функция им
    подменяется - иначе поле считало бы ровно наоборот.

    Колонка `changes` (полная хроника вида `2014-04-16:empire;
    2014-08-18:foreign`) читается как в ВМВ: `empire` = +1.
    """
    start = 1 if row['start'].strip() == 'empire' else -1
    ch = []
    raw = row.get('changes', '').strip()
    if raw:
        for part in raw.split(';'):
            part = part.strip()
            if not part:
                continue
            day, side = part.split(':')
            ch.append((be.d(day.strip()),
                       1 if side.strip() == 'empire' else -1))
    else:
        if row.get('lost', '').strip():
            ch.append((be.d(row['lost'].strip()), 1))
        if row.get('liberated', '').strip():
            ch.append((be.d(row['liberated'].strip()), -1))
    ch.sort()
    return start, ch


def anchors():
    """Якоря слоя. Параметры поля и разбор дат подменяются здесь же."""
    bw.BOX, bw.STEP, bw.POW = BOX, STEP, POW
    bw.KNN, bw.PHI0, bw.FRONT_SIMPLIFY = KNN, PHI0, FRONT_SIMPLIFY
    bw.parse_changes = parse_changes
    return bw.load_anchors(ANCHORS)


class Field(bw.Field):
    """Поле ВМВ с двумя поправками растеризации.

    1. КООРДИНАТЫ УЗЛОВ ОКРУГЛЯЮТСЯ. Сетка строится через numpy.arange, и у
       соседних строк общая граница получается разной в последнем бите
       (37.60999999999999 против 37.61000000000001). Для GEOS это не
       «соприкасаются», а «щель шириной 1e-14», и объединение прямоугольников
       распадается на сотни горизонтальных полос: у среза 2022-03-19 их было
       740 штук одинаковой площади. На глаз заливка сплошная, но файл раздут, а
       проверка «точка внутри полигона» на такой щели даёт «снаружи».
       Округление до девяти знаков делает общую границу побитово одинаковой.
    2. УПРОЩЕНИЕ ЛИНИИ ИДЁТ С preserve_topology. Допуск, равный шагу сетки,
       рвёт лесенку границы: на пробе площадь падала с 68 до 34 град².
       Здесь допуск вчетверо меньше шага и топология сохраняется.
    """

    def red(self, day):
        s = np.asarray([bw.side_at(a, day) for a in self.anchors], dtype=float)
        score = (self.w * s[self.idx]).sum(axis=1).reshape(self.shape)
        mask = score > 0
        half = STEP / 2
        boxes = []
        for r in range(mask.shape[0]):
            cut = np.flatnonzero(np.diff(np.r_[0, mask[r].view(np.int8), 0]))
            y0, y1 = round(self.lats[r] - half, 9), round(self.lats[r] + half, 9)
            for a, b in zip(cut[0::2], cut[1::2]):
                boxes.append(box(round(self.lons[a] - half, 9), y0,
                                 round(self.lons[b - 1] + half, 9), y1))
        if not boxes:
            return unary_union([])
        return bw.smooth(unary_union(boxes), STEP)


def clip_geom(day):
    """Рамка театра на дату: две области или вся Украина."""
    if day >= FULL_FROM:
        if 'ua' not in _g:
            _g['ua'] = be.ne_pick('Ukraine', None).buffer(0)
        return _g['ua'], ('Natural Earth admin-1: Украина без Крыма '
                          '(полуостров красит свой эпизод)')
    if 'dl' not in _g:
        _g['dl'] = be.ne_pick('Ukraine', ["Donets'k", "Luhans'k"]).buffer(0)
    return _g['dl'], 'Natural Earth admin-1: Донецкая и Луганская области'


def slice_dates(path=REG):
    """Даты срезов - из курируемой таблицы эпизодов, а не из этого файла.

    Так дата живёт в ОДНОМ месте: правится строка реестра - двигается и
    геометрия. Иначе таблица и билдер разъезжаются молча.
    """
    with open(path, encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f)
                if r.get('territory', '').strip().startswith(PREFIX)]
    if not rows:
        raise SystemExit(f'{path}: нет строк {PREFIX}*')
    out = []
    for r in rows:
        out.append((r['territory'].strip(), be.d(r['from'].strip()),
                    r['territory_ru'].strip()))
    out.sort(key=lambda x: x[1])
    return out


def km2_area(area):
    """Площадь в градусах² -> тысячи км² (грубо, по средней широте театра)."""
    return area * 111.32 ** 2 * float(np.cos(np.radians(PHI0))) / 1000.0


def km2(geom):
    return km2_area(geom.area)


METHOD = (f'взвешенное голосование {KNN} ближайших якорей, вес 1/d^{POW:g}, '
          f'сетка {STEP}°, линия упрощена до {FRONT_SIMPLIFY}°')

SOURCE_GEOM = (
    'РЕКОНСТРУКЦИЯ (tools/build_donbas.py, 26.08.2026): зона, которой '
    'распоряжается империя, на дату среза. Линия построена из таблицы якорей '
    'data/crosscheck/donbas_cities.csv (даты перехода населённых пунктов) '
    'взвешенным голосованием ближайших якорей: score(p) = Σ s_i/d_i^3 по 8 '
    'ближайшим, линия - нулевая изолиния, сетка 0.02° (~2 км). Тот же код, что '
    'у слоя Второй мировой (класс поля импортируется из tools/build_ww2.py). '
    'Это не оцифровка карт боевых действий: между двумя якорями линия идёт '
    'там, где её проводит формула')


def build(key, day, field, name):
    """Срез: поле, обрезанное рамкой театра, без кусков без единого якоря.

    ПОЧЕМУ ВЫБРАСЫВАЮТСЯ КУСКИ БЕЗ ЯКОРЯ. У самой границы за узлы сетки
    голосуют якоря ПО ТУ СТОРОНУ (Гуково, Донецк Ростовской области), и поле
    даёт вдоль неё красную полосу шириной несколько километров - даже в
    апреле 2014 года, когда границу держали украинские пограничники. Куску,
    в котором нет ни одного якоря имперской стороны, опереться не на что: это
    артефакт метода, а не занятая земля. Так же выбрасываются крошки мельче
    SPECK - шум растеризации.
    """
    clip, clip_note = clip_geom(day)
    red = field.red(day)
    geom = red.intersection(clip).buffer(0)
    geom = geom.simplify(SIMPLIFY, preserve_topology=True).buffer(0)
    parts = list(geom.geoms) if geom.geom_type == 'MultiPolygon' else [geom]
    ours = [Point(a['lon'], a['lat']) for a in field.anchors
            if bw.side_at(a, day) > 0]
    keep, drop = [], 0.0
    for g in parts:
        if g.area > SPECK and any(g.contains(p) for p in ours):
            keep.append(g)
        else:
            drop += g.area
    geom = unary_union(keep)
    props = {
        'id': key, 'date': day.isoformat(), 'name': name,
        'reconstruction': True, 'approximate': True,
        'method': METHOD, 'anchors': len(field.anchors),
        'parts': len(keep), 'area_kkm2': round(km2(geom), 1),
        'dropped_kkm2': round(km2_area(drop), 2),
        'clip': clip_note, 'source': SOURCE_GEOM,
    }
    return {'type': 'Feature', 'properties': props,
            'geometry': be._round(mapping(geom))}, len(keep), km2(geom)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true',
                    help='считать и напечатать, но не писать файл')
    ap.add_argument('--only', help='один срез (id из реестра) - для отладки')
    args = ap.parse_args()

    an = anchors()
    print(f'якорей: {len(an)} ({os.path.relpath(ANCHORS, ROOT)})')
    field = Field(an)
    print(f'сетка театра: {field.shape[1]}x{field.shape[0]} узлов, шаг {STEP}°')

    feats = []
    for key, day, name in slice_dates():
        if args.only and key != args.only:
            continue
        ft, nparts, area = build(key, day, field, name)
        feats.append(ft)
        print(f'  {key:20} {day}  частей {nparts:2d}  '
              f'{area:6.1f} тыс. км²  {name}')
    if args.dry_run:
        print('(dry-run: файл не записан)')
        return
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj({'type': 'FeatureCollection',
                   'note': 'помесячная линия контроля на Донбассе 2014-2015 и '
                           'первые недели вторжения 2022 года, '
                           'tools/build_donbas.py',
                   'features': feats}), f, ensure_ascii=False,
                  separators=(',', ':'))
    print(f'OK {os.path.relpath(OUT, ROOT)}: срезов {len(feats)}, '
          f'{os.path.getsize(OUT) // 1024} КБ')
    print('дальше: .venv/bin/python tools/build_postsoviet.py, '
          'затем tools/check_donbas.py и tools/check_postsoviet.py')


if __name__ == '__main__':
    main()
