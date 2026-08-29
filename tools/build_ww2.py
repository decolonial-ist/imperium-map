#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Помесячные срезы Второй мировой войны, 22.06.1941 - 03.09.1945.

ЗАЧЕМ (задача куратора 26.08.2026). Между срезом 28.06.1940 и срезом 29.06.1945
у карты не было НИ ОДНОГО среза: Вторая мировая отсутствовала на ней как факт.
СССР показывался в границах 1940 года всю войну, хотя с 22.06.1941 по 1944 год
эта территория была под немцами; Белосток гас не 22.06.1941, а скачком в 1945
(README, ограничение 16, последний пункт). Дословно: «расписывай всю вторую
мировую войну по месяцам. как совок терял территории и отступал, а потом как
возвращался. а то снова прыжки дурные какие-то из 40го в 45».

ЧТО ДЕЛАЕТ. Пишет 51 датированный срез (22.06.1941, затем первое число каждого
месяца по 01.05.1945, плюс 09.05.1945, 09.08.1945 и 03.09.1945). Каждый срез -
зона ИМПЕРСКОГО КОНТРОЛЯ на эту дату:

    срез = (контур-основа - оккупированное) + занятое за границей 1941 года

Показ бинарный (правило куратора 19.08.2026): красное - империя тут была,
чёрное - не была. Военная оккупация чужой страны - это имперский контроль,
поэтому Польша, Румыния, Болгария, Венгрия, Югославия, Чехословакия, Австрия,
восточная Германия, Финнмарк, Борнхольм, Маньчжурия, Северная Корея, Южный
Сахалин и Курилы с даты входа войск краснеют.

ОТКУДА ГЕОМЕТРИЯ. Машиночитаемого датасета линии Восточного фронта по датам в
открытом доступе НЕТ (проверено 26.08.2026: GitHub, Zenodo, Harvard Dataverse,
Stanford Spatial History Lab, Chronas, GeaCron, HGIS Germany, Wikimedia Commons,
Bundesarchiv «Lage Ost», pamyat-naroda.ru - везде либо растровые сканы без
геопривязки, либо границы государств, а не фронт). Поэтому линия строится
СКРИПТОМ из таблицы городов-якорей - способ, который куратор и предложил:

  1. `data/crosscheck/ww2_cities.csv` - города-якоря с датами потери и
     освобождения. У каждого якоря на любую дату есть сторона: имперская (+1)
     или нет (-1).
  2. Над театром (рамка BOX) кладётся сетка 0.05° (~5 км). В каждом узле
     считается ВЗВЕШЕННЫЙ ГОЛОС K ближайших якорей:

         score(p) = Σ  s_i / d_i^POW      (i - KNN ближайших якорей)

     Это обратно-взвешенная (IDW) версия диаграммы Вороного: при POW→∞ она в
     неё вырождается, при POW=3 линия идёт примерно посередине между соседними
     якорями разных сторон и не ломается ступеньками на каждой ячейке Вороного.
     Расстояние считается в плоскости (lon·cos φ₀, lat), φ₀ = 52° - середина
     театра.
  3. Множество `score > 0` растеризуется прямоугольниками по строкам сетки,
     склеивается и упрощается (0.05° ≈ 5 км - меньше, чем точность контуров
     источника, ~30 км).
  4. Полученная «красная» маска пересекается с театром и складывается с тем,
     что лежит ВНЕ рамки театра (Урал, Сибирь, Средняя Азия - там империя была
     всю войну и якорей не нужно).

ЧТО ЭТО ДАЁТ ДАРОМ. Котлы и плацдармы модель рисует сама, без ручной геометрии:
осаждённая Одесса до 16.10.1941 и Севастополь до 04.07.1942 - красные острова в
чёрном; Демянский и Холмский котлы - чёрные выступы; Курляндский котёл живёт до
09.05.1945, когда Рига взята 13.10.1944; Бреслау и Познань - чёрные острова за
линией фронта 1945 года; Кубанский плацдарм вермахта держится до сентября 1943.
Ленинград остаётся красным всю блокаду (коридор через Ладогу), Сталинград не
берётся вовсе, Воронеж делится по Дону.

ГРАНИЦЫ ЧЕСТНОСТИ - в README, ограничение 17. Коротко: это РЕКОНСТРУКЦИЯ по
датам взятия городов, а не оцифровка оперативных карт. Между двумя якорями линия
идёт там, где её проводит формула, а не там, где она шла на самом деле; точность
- порядка половины расстояния между соседними якорями (в среднем 100-150 км, на
Крайнем Севере и в калмыцких степях хуже). У каждого среза стоят
`reconstruction: true` и `approximate: true`.

Запуск (нужен shapely и scipy из .venv; ПОСЛЕ tools/build_data.py,
tools/build_expansion.py и tools/build_pact_1939.py - они перезаписывают срезы
источника, на которых этот билдер стоит):

    cd ~/tmp/imperium-map && .venv/bin/python tools/build_ww2.py
    cd ~/tmp/imperium-map && .venv/bin/python tools/check_ww2.py
"""
import argparse
import csv
import json
import os
import sys
from datetime import date

import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_data as bd            # noqa: E402
import build_expansion as be
import geoclean as gc       # noqa: E402  (ne_pick, cs_core, _round, d)

DATA = bd.OUT
CC = os.path.join(DATA, 'crosscheck')
ANCHORS = os.path.join(CC, 'ww2_cities.csv')

# ---- параметры поля -------------------------------------------------------
BOX = (4.0, 38.0, 56.0, 71.5)   # театр: lon_min, lat_min, lon_max, lat_max
STEP = 0.05                     # шаг сетки, градусы (~5.5 км по широте)
POW = 3.0                       # степень обратного расстояния
KNN = 8                         # сколько ближайших якорей голосуют
PHI0 = 52.0                     # широта, по которой сжимаем долготу
FRONT_SIMPLIFY = 0.05           # упрощение линии фронта (~5 км)
SIMPLIFY = 0.01                 # упрощение готового среза
SPECK = 0.004                   # град²: мельче - выбрасываем (шум растра)

WAR = be.d('1941-06-22')
END = be.d('1945-09-03')

# ---- срезы ----------------------------------------------------------------
def _slice_keys():
    keys = ['1941-06-22']
    for y, m0, m1 in ((1941, 7, 12), (1942, 1, 12), (1943, 1, 12),
                      (1944, 1, 12), (1945, 1, 5)):
        keys += [f'{y}-{m:02d}-01' for m in range(m0, m1 + 1)]
    keys += ['1945-05-09',    # капитуляция Германии: максимум в Европе
             '1945-06-29',    # Закарпатье: контур СССР становится послевоенным
             '1945-08-20',    # Маньчжурия взята
             '1945-09-03']    # капитуляция Японии: Корея, Сахалин, Курилы
    return keys


KEYS = _slice_keys()

# КОНТУР-ОСНОВА, поверх которого рисуется фронт.
#   до 29.06.1945 - срез 1940-06-28, который пишет tools/build_pact_1939.py:
#     СССР в границах на 22.06.1941 (Прибалтика, Западная Украина и Беларусь,
#     Бессарабия, Белостокская область по протоколу 04.10.1939). ФАЙЛ ЧИТАЕТСЯ.
#   с 29.06.1945 - послевоенный контур CShapes напрямую, cs(1945-05-08):
#     Закарпатье и Кёнигсберг уже в нём. Берём контур ИСТОЧНИКА, а не файл
#     среза 1945-06-29, потому что этот срез мы САМИ и перезаписываем (в него
#     надо добавить занятую Европу) - иначе повторный прогон читал бы
#     собственный результат.
BASE_PRE = '1940-06-28'
BASE_SWITCH = be.d('1945-06-29')
POSTWAR = (1945, 5, 8)

# ОККУПАЦИЯ ЕВРОПЫ ЖИВЁТ ДО КОНЦА 1945 ГОДА, дальше её подхватывает слой сферы
# влияния (data/sphere.geojson: Польша, Чехословакия, Венгрия, Румыния,
# Маньчжурия, Германия (советская зона), Корея - с 1946 года). Так у стыка нет
# ни ДВОЙНОГО ПОКАЗА (в 1945-м красит только ядро), ни ПРОВАЛА (с 1946-го
# красит только сфера). Следующий за нашими срез - `1946`, он же контур СССР.
ABROAD_UNTIL = be.d('1946-01-01')

# ---- театр: куда Красная армия вошла за границу 1941 года ------------------
# Только страны, где она реально была. Швеция, Швейцария, Италия, Греция,
# Турция, западная Германия и Финляндия (кроме Петсамо, которое и так внутри
# контура) в маску НЕ входят: их не занимали, и красным они стать не могут ни
# при каком раскладе якорей.
ABROAD = [
    ('Poland', None), ('Germany', None), ('Austria', None),
    ('Czech Republic', None), ('Slovakia', None), ('Hungary', None),
    ('Romania', None), ('Bulgaria', None), ('Republic of Serbia', None),
    # два куска, которые в 1941 году были ЧУЖИМИ, а сегодня лежат внутри
    # бывшего СССР - в контур-основу 1940 года они не входят, и без них
    # Кёнигсберг и Ужгород остались бы чёрными после взятия:
    ('Russia', ['Kaliningrad']),          # Восточная Пруссия, взята 09.04.1945
    ('Ukraine', ['Transcarpathia']),      # Закарпатье, венгерское с 15.03.1939
]

# ---- куски, которые считаются не полем, а прямым списком -------------------
# Изолированные театры, где якорей мало, а границы известны точно.
# geom - функция, frm - дата входа войск, until - дата вывода (или None).
EXTRA_SRC = [
    dict(id='FINNMARK', frm='1944-10-25', until='1945-09-25',
         name='Восточный Финнмарк (Киркенес)',
         act='Петсамо-Киркенесская операция; советские войска выведены '
             '25.09.1945',
         geom_note='Natural Earth admin-1: Финнмарк восточнее 28.8° в. д. '
                   '(коммуна Сёр-Варангер и Тана) - приближение'),
    dict(id='BORNHOLM', frm='1945-05-09', until='1946-04-06',
         name='Борнхольм',
         act='десант 9.05.1945, немецкий гарнизон капитулировал 11.05.1945; '
             'советские войска выведены 5.04.1946',
         geom_note='Natural Earth admin-1: Hovedstaden в рамке острова'),
    dict(id='MANCHURIA', frm='1945-08-20', until=None,
         name='Маньчжурия',
         act='Маньчжурская операция 09.08-02.09.1945; советская военная '
             'администрация до мая 1946, Порт-Артур как база - до 1955',
         geom_note='Natural Earth admin-1: Хэйлунцзян, Гирин, Ляонин плюс '
                   'восточная Внутренняя Монголия (восточнее 111.5° в. д.) - '
                   'приближение по современной нарезке'),
    dict(id='KOREA_N', frm='1945-08-24', until=None,
         name='Северная Корея',
         act='вход войск 1-го Дальневосточного фронта, август 1945; '
             'разграничение с США по 38-й параллели, вывод - декабрь 1948',
         geom_note='Natural Earth admin-1: Корея севернее 38-й параллели '
                   '(современная граница КНДР южнее её у Кэсона, поэтому '
                   'режем параллелью, а не границей)'),
    dict(id='SAKHALIN_S', frm='1945-08-25', until=None,
         name='Южный Сахалин (Карафуто)',
         act='Южно-Сахалинская операция 11-25.08.1945; Тойохара взята '
             '25.08.1945',
         geom_note='Natural Earth admin-1: Сахалинская область южнее 50° с. ш. '
                   '(граница 1905-1945 гг. и шла по 50-й параллели)'),
    dict(id='KURILS', frm='1945-09-03', until=None,
         name='Курильские острова',
         act='Курильская десантная операция 18.08-01.09.1945',
         geom_note='Natural Earth admin-1: Сахалинская область восточнее '
                   '145.5° в. д.'),
]

_g = {}


def ne(admin, names=None):
    key = ('ne', admin, tuple(names) if names else None)
    if key not in _g:
        _g[key] = be.ne_pick(admin, names)
    return _g[key]


def clip(g, lon0=-1e3, lat0=-1e3, lon1=1e3, lat1=1e3):
    return g.intersection(box(lon0, lat0, lon1, lat1))


def extra_geom(eid):
    """Геометрия изолированного театра (считается лениво)."""
    if eid in _g:
        return _g[eid]
    if eid == 'FINNMARK':
        g = clip(ne('Norway', ['Finnmark']), lon0=28.8)
    elif eid == 'BORNHOLM':
        g = clip(ne('Denmark', ['Hovedstaden']), 14.5, 54.9, 15.3, 55.4)
    elif eid == 'MANCHURIA':
        g = unary_union([ne('China', ['Heilongjiang', 'Jilin', 'Liaoning']),
                         clip(ne('China', ['Inner Mongol']), lon0=111.5)])
    elif eid == 'KOREA_N':
        g = clip(unary_union([ne('North Korea'), ne('South Korea')]), lat0=38.0)
    elif eid == 'SAKHALIN_S':
        g = clip(ne('Russia', ['Sakhalin']), lat1=50.0, lon1=145.5)
    elif eid == 'KURILS':
        g = clip(ne('Russia', ['Sakhalin']), lon0=145.5)
    else:
        raise SystemExit(f'неизвестный кусок {eid}')
    _g[eid] = g.buffer(0)
    return _g[eid]


def theatre_box():
    if 'box' not in _g:
        _g['box'] = box(*BOX)
    return _g['box']


def abroad_mask():
    """Всё, куда Красная армия могла войти за пределами границ 1941 года."""
    if 'abroad' not in _g:
        _g['abroad'] = unary_union([ne(a, n) for a, n in ABROAD]).buffer(0)
    return _g['abroad']


def base_geom(key):
    """Контур-основа: контур СССР, поверх которого рисуется фронт."""
    if be.key_date(key) >= BASE_SWITCH:
        if 'post' not in _g:
            _g['post'] = be.cs_core(*POSTWAR).buffer(0)
        return _g['post'], ('послевоенный контур CShapes 2.0 на 08.05.1945 '
                            '(Закарпатье и Кёнигсберг уже в нём; акты - '
                            'data/pact1939.geojson)')
    src = BASE_PRE
    if src not in _g:
        path = os.path.join(DATA, 'years', src + '.geojson')
        with open(path, encoding='utf-8') as f:
            fc = json.load(f)
        _g[src] = unary_union([shape(x['geometry']).buffer(0)
                               for x in fc['features']]).buffer(0)
    return _g[src], f'срез {src} (контур СССР, tools/build_pact_1939.py)'


# ---- якоря -----------------------------------------------------------------
def parse_changes(row):
    """Строка таблицы -> хроника [(дата, +1|-1), ...] и старт.

    `changes` (если заполнено) - полная хроника: `1943-02-16:empire;
    1943-03-15:foreign;...`. Если пусто, хроника строится из `lost`/`liberated`.
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
        if row['lost'].strip():
            ch.append((be.d(row['lost'].strip()), -1))
        if row['liberated'].strip():
            ch.append((be.d(row['liberated'].strip()), 1))
    ch.sort()
    return start, ch


def load_anchors(path=ANCHORS):
    with open(path, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        if r.get('anchor', 'yes').strip() != 'yes':
            continue          # строка только для регрессии, поле не задаёт
        start, ch = parse_changes(r)
        out.append(dict(city=r['city'], lat=float(r['lat']),
                        lon=float(r['lon']), start=start, changes=ch))
    if not out:
        raise SystemExit(f'{path}: якорей нет')
    return out


def side_at(a, day):
    s = a['start']
    for when, val in a['changes']:
        if when <= day:
            s = val
    return s


# ---- снятие растровой лестницы ---------------------------------------------
# Зона собирается из ячеек сетки (box на ячейку), поэтому её край - лестница из
# строго горизонтальных и вертикальных отрезков в один шаг. Douglas-Peucker с
# допуском МЕНЬШЕ шага (так было до 27.08.2026) лестницу не трогает вовсе: он
# честно сохраняет каждую ступеньку. На карте это читалось как проведённые под
# линейку прямые внутри красного - куратор их и увидел.
#
# Лечим морфологией, а не более грубым упрощением: размыкание и замыкание
# круглым буфером радиуса чуть меньше шага срезает и выпуклые, и вогнутые углы
# ступенек, оставляя линию там же. Сдвиг края не превышает одной ячейки сетки,
# то есть заведомо меньше заявленной точности реконструкции (половина
# расстояния между соседними якорями).
def smooth(g, step):
    r = 0.72 * step
    g = (g.buffer(r, join_style=1, quad_segs=8)
          .buffer(-2 * r, join_style=1, quad_segs=8)
          .buffer(r, join_style=1, quad_segs=8))
    return g.simplify(step / 3.0).buffer(0)


# ---- поле ------------------------------------------------------------------
class Field:
    """Сетка театра и дерево якорей: строится один раз на весь прогон."""

    def __init__(self, anchors):
        self.anchors = anchors
        self.ky = float(np.cos(np.radians(PHI0)))
        self.lons = np.arange(BOX[0], BOX[2] + 1e-9, STEP)
        self.lats = np.arange(BOX[1], BOX[3] + 1e-9, STEP)
        lo, la = np.meshgrid(self.lons, self.lats)
        self.shape = lo.shape
        pts = np.c_[np.asarray([a['lon'] for a in anchors]) * self.ky,
                    np.asarray([a['lat'] for a in anchors])]
        self.tree = cKDTree(pts)
        k = min(KNN, len(anchors))
        d, i = self.tree.query(np.c_[lo.ravel() * self.ky, la.ravel()], k=k)
        if k == 1:
            d, i = d[:, None], i[:, None]
        self.w = 1.0 / np.maximum(d, 1e-6) ** POW
        self.idx = i

    def red(self, day):
        """Полигон «здесь империя» на дату (внутри рамки театра)."""
        s = np.asarray([side_at(a, day) for a in self.anchors], dtype=float)
        score = (self.w * s[self.idx]).sum(axis=1).reshape(self.shape)
        mask = score > 0
        half = STEP / 2
        boxes = []
        for r in range(mask.shape[0]):
            cut = np.flatnonzero(np.diff(np.r_[0, mask[r].view(np.int8), 0]))
            y0, y1 = self.lats[r] - half, self.lats[r] + half
            for a, b in zip(cut[0::2], cut[1::2]):
                boxes.append(box(self.lons[a] - half, y0,
                                 self.lons[b - 1] + half, y1))
        if not boxes:
            return unary_union([])
        return smooth(unary_union(boxes), STEP)


# ---- сборка среза ----------------------------------------------------------
SOURCE = (
    'КУРИРУЕМЫЙ СРЕЗ ВТОРОЙ МИРОВОЙ (26.08.2026, tools/build_ww2.py): зона '
    'имперского контроля на дату. Линия фронта РЕКОНСТРУИРОВАНА по таблице '
    'городов-якорей data/crosscheck/ww2_cities.csv (даты потери и освобождения '
    'городов) взвешенным голосованием ближайших якорей: score(p) = Σ s_i/d_i^3 '
    'по 8 ближайшим, линия - нулевая изолиния, сетка 0.05° (~5 км). Это '
    'сглаженная диаграмма Вороного, а не оцифровка оперативных карт: между '
    'двумя якорями линия идёт там, где её проводит формула. Машиночитаемого '
    'датасета линии Восточного фронта по датам в открытом доступе нет '
    '(проверено 26.08.2026). Даты освобождения - справочник «Освобождение '
    'городов» (М.: Воениздат, 1985) и хроники операций; даты потери 1941-1942 '
    '- сводки, хроники операций и справочная литература. Контур-основа - срез '
    'СССР, который пишет tools/build_pact_1939.py. Занятое за границей 1941 г. '
    '(Польша, Румыния, Болгария, Венгрия, Югославия, Чехословакия, Австрия, '
    'восточная Германия) - тем же полем внутри маски стран, куда Красная армия '
    'вошла; Финнмарк, Борнхольм, Маньчжурия, Северная Корея, Южный Сахалин и '
    'Курилы - прямым списком (Natural Earth admin-1). Показ бинарный: военная '
    'оккупация = имперский контроль = красное. Проверка - tools/check_ww2.py '
    'по data/crosscheck/ww2_cities.csv')

METHOD = (f'взвешенное голосование {KNN} ближайших якорей, вес 1/d^{POW:g}, '
          f'сетка {STEP}°, линия упрощена до {FRONT_SIMPLIFY}°')


def phase(key):
    d = be.key_date(key)
    if d < be.d('1942-11-19'):
        return 'отступление 1941-1942'
    if d < be.d('1943-07-05'):
        return 'перелом: Сталинград и зима 1942/43'
    if d < be.d('1944-06-22'):
        return 'возврат 1943 - весна 1944'
    if d < be.d('1945-01-12'):
        return 'выход за границу 1941 года'
    return 'Европа и Дальний Восток 1945'


def extras_at(day):
    out = []
    for e in EXTRA_SRC:
        if be.d(e['frm']) <= day and (not e['until']
                                      or day < be.d(e['until'])):
            out.append(e)
    return out


def build(key, field, verbose=True):
    day = be.key_date(key)
    base, base_key = base_geom(key)
    bx = theatre_box()
    red = field.red(day)

    inside = base.intersection(bx)
    outside = base.difference(bx)                # тыл: там империя всю войну
    core = inside.intersection(red)
    # Европейская оккупация - до конца 1945 года, дальше слой сферы влияния
    if day < ABROAD_UNTIL:
        abroad = abroad_mask().intersection(bx).intersection(red)
    else:
        abroad = unary_union([])
    parts = [outside, core, abroad]
    ex = extras_at(day)
    for e in ex:
        parts.append(extra_geom(e['id']))
    geom = unary_union([p for p in parts if not p.is_empty]).buffer(0)
    geom = geom.simplify(SIMPLIFY).buffer(0)
    keep = [g for g in (geom.geoms if geom.geom_type == 'MultiPolygon'
                        else [geom]) if g.area > SPECK]
    geom = unary_union(keep)

    lost = inside.area - core.area               # сколько своей земли под врагом
    props = {
        'name': 'СССР', 'year': key, 'role': 'core',
        'reconstruction': True, 'approximate': True,
        'expansion': True, 'ww2': True,
        'phase': phase(key),
        'base': base_key,
        'method': METHOD,
        'anchors': len(field.anchors),
        'occupied_deg2': round(lost, 2),
        'abroad_deg2': round(abroad.area, 2),
        'extra': [{'id': e['id'], 'name': e['name'], 'from': e['frm'],
                   'until': e['until'], 'act': e['act'],
                   'geometry_source': e['geom_note']} for e in ex],
        'added': [], 'removed': [],
        'source': SOURCE,
    }
    fc = {'type': 'FeatureCollection', 'features': [{
        'type': 'Feature',
        'geometry': be._round(mapping(gc.drop_thin_parts(gc.drop_sea_parts(
            gc.clip_to_land(geom, be.CACHE)[0], be.CACHE)[0])[0])),
        'properties': props}]}
    return fc, len(keep), lost, abroad.area


def write_front_line(field, keys):
    """Линия фронта отдельным файлом - пруф геометрии, в показ не идёт."""
    feats = []
    base, _ = base_geom(KEYS[0])
    inside = base.intersection(theatre_box())
    for key in keys:
        day = be.key_date(key)
        red = field.red(day)
        line = inside.intersection(red).boundary.difference(
            inside.boundary.buffer(0.02))
        if line.is_empty:
            continue
        feats.append({'type': 'Feature',
                      'geometry': be._round(mapping(line.simplify(0.02))),
                      'properties': {'date': key, 'phase': phase(key),
                                     'method': METHOD}})
    path = os.path.join(DATA, 'ww2_front.geojson')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': feats}, f,
                  ensure_ascii=False)
    print(f'OK data/ww2_front.geojson: линий {len(feats)}, '
          f'{os.path.getsize(path) // 1024} КБ')


def update_manifest(written):
    path = os.path.join(DATA, 'manifest.json')
    with open(path, encoding='utf-8') as f:
        mf = json.load(f)
    mf['years'] = sorted(set(map(str, mf['years'])) | set(written),
                         key=be.key_date)
    mf['note_ww2'] = (
        'дыра 28.06.1940-29.06.1945 закрыта 26.08.2026 (tools/build_ww2.py): '
        f'{len(written)} помесячных срезов с 22.06.1941 по 03.09.1945. Зона '
        'имперского контроля = контур СССР минус оккупированное плюс занятое '
        'за границей 1941 года. Линия фронта РЕКОНСТРУИРОВАНА по таблице '
        'городов-якорей (data/crosscheck/ww2_cities.csv) взвешенным '
        'голосованием ближайших якорей - машиночитаемого датасета линии '
        'Восточного фронта по датам в открытом доступе нет. Военная оккупация '
        'чужой страны = имперский контроль = красное (показ бинарный). '
        'Регрессия - tools/check_ww2.py')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj(mf), f, ensure_ascii=False, indent=1)
    print(f'OK data/manifest.json: срезов {len(mf["years"])}')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--only', help='собрать один срез (для отладки)')
    ap.add_argument('--dry-run', action='store_true',
                    help='считать, но не писать файлы')
    args = ap.parse_args()

    anchors = load_anchors()
    print(f'якорей: {len(anchors)} (data/crosscheck/ww2_cities.csv)')
    field = Field(anchors)
    print(f'сетка театра: {field.shape[1]}x{field.shape[0]} узлов, шаг {STEP}°')

    keys = [args.only] if args.only else KEYS
    written, total = [], 0
    for key in keys:
        fc, nparts, lost, abroad = build(key, field)
        if args.dry_run:
            print(f'   {key}  частей {nparts:3d}  оккупировано {lost:7.1f} '
                  f'град²  за границей {abroad:6.1f} град²')
            continue
        path = os.path.join(DATA, 'years', key + '.geojson')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(gc.sanitize_obj(fc), f, ensure_ascii=False)
        kb = os.path.getsize(path) // 1024
        total += kb
        written.append(key)
        print(f'OK data/years/{key}.geojson: частей {nparts:3d}, {kb:4d} КБ, '
              f'оккупировано {lost:7.1f} град², за границей {abroad:6.1f} '
              f'град²  [{fc["features"][0]["properties"]["phase"]}]')
    if args.dry_run:
        return
    write_front_line(field, keys)
    update_manifest(written)
    gc.write_stamp('ww2')
    print(f'срезов ВМВ: {len(written)}, суммарно {total} КБ')
    print('дальше: .venv/bin/python tools/check_ww2.py, '
          'python3 tools/check_expansion.py, python3 tools/check_cities.py')


if __name__ == '__main__':
    main()
