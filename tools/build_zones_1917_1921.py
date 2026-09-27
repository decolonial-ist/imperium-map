#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Реконструкция ЗОНЫ ИМПЕРИИ 12.1917-03.1921 датированными срезами.

ТРЕТЬЯ ИТЕРАЦИЯ (26.08.2026) - СМЕНА РАМКИ. Редакции 1 и 2 строили ЗОНУ
СОВЕТСКОГО КОНТРОЛЯ: всё, что не под красными, уходило в чёрное. Куратор
поймал на этом два бага подряд (Якутия 1918-1919 и Крым при Врангеле:
«белые не считаются чёрным, алло, это имперцы»; «крым красным зарисовывай»).

Принцип проекта (решение куратора 18.08.2026, память empire-not-factions):
белые и красные - две фракции ОДНОЙ империи, спорящие за право ею владеть;
Колчак и Деникин восстанавливали «единую и неделимую». Междоусобицы имперцев
мы не различаем. Показ бинарный: КРАСНОЕ - империя тут была, ЧЁРНОЕ - не была.

Поэтому окна фронтов разделены на два рода (поле `kind`):

- `out` - территория РЕАЛЬНО ВЫШЛА ИЗ ИМПЕРИИ: УНР во всех формах, Финляндия,
  Балтия, Польша, Грузия, Армения, Азербайджан, Горская республика и эмират
  Узун-Хаджи, Алаш-Орда, Хива и Бухара, Танну-Тува, Крымская народная
  республика, Башкирское правительство, Бессарабия у Румынии, Кубанская
  народная республика (01.1918-07.11.1919) и Сибирь в окно самостоятельности
  (04.07-18.11.1918), а также германская оккупация (это не империя, а другая
  держава). Такие окна ВЫЧИТАЮТСЯ из контура - чёрное на карте;
- `in` - территорию держала другая ФРАКЦИЯ ИМПЕРИИ: Комуч, Колчак, Деникин и
  ВСЮР, Врангель, Краснов, Северная область, Семёнов, ДВР, Дутов, интервенция
  с русской белой администрацией. Геометрию такие окна НЕ режут (красное
  остаётся красным), они нужны попапу истории точки, чтобы написать не
  «вне империи», а «в империи · белые (Колчак)».

Поле `cut` (по умолчанию = (kind == 'out')) позволяет завести окно `out`
БЕЗ резки геометрии - для украинского театра, где зону режут посрезовые
вычитания `minus`, а окно нужно только ради имени держателя в попапе.

Как строится геометрия (всё - приближение мирового масштаба, у каждой фичи
`reconstruction: true`):

- ОСНОВА - контур CShapes 2.0 от 11.11.1918 (Советская Россия без Польши,
  Финляндии, Эстонии, Латвии и Литвы; Хива и Бухара в него не входят -
  протектораты);
- ВЫЧИТАНИЕ современных областей (Natural Earth admin-1) как приближения
  границ: «немцы заняли Украину» = минус украинские области, «Кубанская рада»
  = минус Краснодарский край с Адыгеей;
- ДОБАВЛЕНИЕ (`ADDS`) - Хорезм и Бухара после 1920 г. (в основе их нет, в
  CShapes с 18.03.1921 - есть);
- ЯКОРЯ - города и даты из `data/events/ukraina_1917_1921/events.geojson`
  (взятия городов), по ним выставлены даты срезов.

РЕЗКА АТЛАСНЫМИ ЛИНИЯМИ УБРАНА вместе со сменой рамки: линии розд. 44 атласа
УІФ - это граница СОВЕТСКОГО контроля, то есть ровно та межфракционная линия,
которую мы больше не рисуем. Функции резки оставлены ниже как история вопроса
и в сборке не вызываются; файлы линий остаются на диске.

Проверка - `tools/check_cities.py` (регрессионный тест периода по таблице
`data/crosscheck/cities_civilwar.csv`, ожидание «в империи / вне империи») и
общий `tools/crosscheck.py`.

Запуск (нужен shapely из .venv в корне репо):

    cd ~/tmp/imperium-map && .venv/bin/python tools/build_zones_1917_1921.py
"""
import json
import os
from datetime import date

import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point, box, mapping, shape
from shapely.ops import polygonize, unary_union

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import geoclean as gc
import build_expansion as be   # noqa: E402  (EARLY_PROTECT, reg_geom - Соловки)
import build_ww1 as w1         # noqa: E402  (модель якорей западного театра)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(ROOT, 'cache')

MOSCOW = Point(37.62, 55.75)        # опорная точка советской части при резке
BASE = (1918, 11, 11)               # контур-основа в CShapes
BASE_NOTE = ('основа - контур CShapes 2.0 от 11.11.1918 (без Польши, Финляндии, '
             'Эстонии, Латвии и Литвы)')
PERIOD_END = date(1921, 3, 18)      # с этой даты снова CShapes (линия Риги)

# ---- группы современных областей (Natural Earth admin-1) -------------------

CRIMEA_ISO = ['UA-43', 'UA-40']     # Крым и Севастополь (в NE лежат под Russia)

# REG: имя группы -> (admin в Natural Earth, список name или None = вся страна).
# Третьим элементом можно дать список iso_3166_2 (для безымянных фич NE).
# ---- таблицы реконструкции: data/zones_1917_1921/*.csv (27.09.2026) -------
# Регионы (REG), окна с держателями (WINDOWS), добавления (ADDS) и срезы
# (SLICES, включая срезы западного театра, прежний WEST_KEYS) живут в CSV -
# tools/zones_tables.py читает и проверяет их; там же описание колонок.
# Имена файлов тут строками нарочно: по ним tools/rebuild.py видит вход слоя.
CSV_FILES = ('zones_regions.csv', 'zones_windows.csv', 'zones_adds.csv',
             'zones_slices.csv')
import zones_tables as zt   # noqa: E402
REG = zt.load('REG')
WINDOWS = zt.load('WINDOWS')
ADDS = zt.load('ADDS')
SLICES = zt.load('SLICES')

# ---- окна: регион с даты по дату [с даты; по дату) ------------------------
# Применяются ко ВСЕМ срезам периода. `to=None` - до конца окна реконструкции.
# Даты - по взятиям городов; тот же реестр в data/crosscheck/cities_civilwar.csv.
#
# kind='out' - территория вышла из империи, окно ВЫЧИТАЕТСЯ (чёрное);
# kind='in'  - территорию держала другая фракция империи, геометрию не режем
#              (красное), окно нужно попапу ради имени фракции;
# cut=False  - окно `out` без резки: геометрию режет посрезовый `minus`
#              (украинский театр), окно нужно только ради имени держателя.


# ---- кто держал регион в это окно (короткая подпись для попапа истории точки)
# Ключ - (группа, дата начала окна), значение - имя держателя. Длинная
# формулировка с датами остаётся в поле `why` соответствующего окна.
# Каждому окну WINDOWS обязан соответствовать ключ: иначе сборка падает (см.
# attach_who) - так таблицы не разъезжаются.
# Для окон `out` тут ИМЯ СУБЪЕКТА, вышедшего из империи («Грузинская
# Демократическая Республика»), для окон `in` - ИМЯ ФРАКЦИИ, державшей
# территорию внутри империи («белые (Колчак)», «ВСЮР (Деникин)»). Красное без
# окна `in` - это РСФСР, её попап подписывает сам.


# ---- добавления: Хива и Бухара (в основе-контуре их нет) -------------------
# Хорезмская НСР провозглашена 26.04.1920 (Хива взята 02.02.1920), Бухарская
# НСР - 08.10.1920 (Бухара взята 02.09.1920). В CShapes с 18.03.1921 обе внутри.
KHIVA_REG = ('Uzbekistan', ['Khorezm', 'Karakalpakstan'])
KHIVA_TM = ('Turkmenistan', ['Tashauz'])
CENTRAL_ASIA_ADMINS = ['Uzbekistan', 'Turkmenistan', 'Tajikistan', 'Kyrgyzstan',
                       'Kazakhstan']

# ---- западный театр: модель якорей (22.09.2026) ----------------------------
# В основе слоя (CShapes 11.11.1918) нет Эстонии, Латвии, Литвы, запада Гродненщины и
# Псковщины. Поэтому земля, которую держала империя, была чёрной во все дни
# окна: Эстляндия, Лифляндия и Латгалия до германского наступления февраля
# 1918 года, Эстляндская трудовая коммуна, Латвийская ССР и Литбел 1918-1919
# годов, Вильна 1919 и 1920 годов, Гродно 1920 года (BACKLOG_KARTY Б6 и Б7
# п. 10; правила «империя, а не фракции» и «военная оккупация = контроль»).
# Теперь её красит модель якорей слоя Первой мировой (tools/build_ww1.py):
# сетка 0,05°, вес 1/d^3, KNN ближайших якорей, якорь голосует только за
# свою сушу. Отличие одно: основы здесь нет, и голос симметричный - каждый из
# KNN ближайших городов голосует стороной на дату (империя +1, чужие -1),
# красное - где сумма больше нуля. Модель только ДОБАВЛЯЕТ красное и только
# на земле вне основы внутри WEST_MASK. Якоря - data/crosscheck/
# zones_west_cities.csv (даты н. ст., розыск MAP-MATERIALS/peresmotr_resheniy_
# 2026-09-18/rozysk/b6_baltia_1917_1920_sverka.md), проверка - tools/
# check_cities.py --anchors.
WEST_ANCHORS = os.path.join(DATA, 'crosscheck', 'zones_west_cities.csv')
WEST_TH = dict(id='zones_west', name='страны Балтии и западный фронт 1917-1920',
               box=(19.0, 47.9, 29.5, 60.0), phi0=54.0)
# WEST_MASK - земля вне основы: три республики, Польша, Галиция и края
# нынешних Беларуси и России, которые CShapes 11.11.1918 отдаёт соседям
# (Ивангород, Печоры, Пыталово, Браслав, Поставы, запад Гродненщины).
# Германская Восточная Пруссия (с Мемельским краем и Сольдау) из маски снята
# по контуру OHM 1914 года: РККА в 1920 году в Германию не входила.
# WEST_IN - земля ОСНОВЫ, которую тоже решают якоря: Брестская и Гродненская
# области (окно BY_WEST чернило их сплошь с 09.02.1919, см. WINDOWS)
WEST_MASK = [('Estonia', None), ('Latvia', None), ('Lithuania', None),
             ('Poland', None),
             ('Belarus', ['Grodno', 'Vitebsk', 'Minsk', 'Brest']),
             ('Russia', ['Pskov', 'Leningrad']),
             ('Ukraine', ["L'viv", "Ternopil'", "Ivano-Frankivs'k"])]
WEST_IN = [('Belarus', ['Brest', 'Grodno'])]
# Земля основы, которую якоря решают только в своём окне. Волынь, Ровенщина и
# Хмельнитчина: посрезовые вычитания украинского театра (UA_VOLYN, UA_KHMEL)
# держали их чёрными всё лето 1920 года, а РККА взяла Ровно 04.07.1920 и
# Каменец-Подольский 11.07.1920 (розыск b6_front1920_volyn_2026-09-22). В
# окне [с; по) их решают якоря, до и после - прежние вычитания: якорей
# 1918-1919 годов на Волыни нет, а с 17.11.1920 вычитания уже идут по
# прелиминарной Риге (ноябрьских дат у Староконстантинова в розыске нет - после
# окна Подолье красное по вычитаниям, Проскуров на день раньше взятия 18.11). Тернопольщина - ради Кременца (волынский уезд до 1917
# года, в основе он есть; австрийская часть области решается маской)
WEST_IN_WINDOWS = [(('Ukraine', ['Volyn', 'Rivne', "Khmel'nyts'kyy",
                                "Ternopil'"]),
                    date(1920, 7, 1), date(1920, 11, 17))]
# До германского наступления 18.02.1918 фронт стоял там, где его оставил слой
# Первой мировой (перемирие 02(15).12.1917): запад Беларуси и Волыни с 1915
# года под немцами. В основе CShapes эта земля есть, и срезы 25.12.1917 и
# 08.02.1918 красили её красной, хотя срез ПМВ 01.12.1917 держит её чёрной.
# Занятое противником считается той же моделью по той же таблице якорей
# (data/crosscheck/ww1_cities.csv) на день перемирия и вычитается из основы
WW1_HANDOFF = date(1918, 2, 18)
WW1_FRONT_DAY = date(1917, 12, 2)      # ст. ст.: перемирие, фронт стоит
_west = {}


class WestField:
    """Сетка театра и KNN всех якорей обеих сторон: строится один раз."""

    def __init__(self, anchors, th):
        self.th = th
        x0, y0, x1, y1 = th['box']
        ky = float(np.cos(np.radians(th['phi0'])))
        self.lons = np.arange(x0, x1 + 1e-9, w1.STEP)
        self.lats = np.arange(y0, y1 + 1e-9, w1.STEP)
        lo, la = np.meshgrid(self.lons, self.lats)
        self.shape = lo.shape
        self.A = anchors
        parts = w1.land_parts(th)
        node_land = w1.land_ids(parts, lo.ravel(), la.ravel())
        lon = np.asarray([a['lon'] for a in anchors])
        lat = np.asarray([a['lat'] for a in anchors])
        k = min(w1.KNN, len(anchors))
        dist, idx = cKDTree(np.c_[lon * ky, lat]).query(
            np.c_[lo.ravel() * ky, la.ravel()], k=k)
        if k == 1:
            dist, idx = dist[:, None], idx[:, None]
        wt = 1.0 / np.maximum(dist, 1e-6) ** w1.POW
        # якорь голосует только за свою сушу: через пролив голоса нет
        # (Эзель, Даго и Моон без своих якорей остаются как в основе)
        al = w1.land_ids(parts, lon, lat)[idx]
        nl = node_land[:, None]
        wt[(al >= 0) & (nl >= 0) & (al != nl)] = 0.0
        self.w, self.i = wt, idx

    def mask(self, day):
        s = np.asarray([w1.side_at(a, day) for a in self.A], dtype=float)
        return ((self.w * s[self.i]).sum(axis=1) > 0).reshape(self.shape)

    to_geom = w1.Field.to_geom      # узлы -> полигон тем же растром, что ПМВ


def _west_masks(base):
    if 'field' in _west:
        return
    anchors = w1.load_anchors(WEST_ANCHORS)
    _west['field'] = WestField(anchors, WEST_TH)
    bx = box(*WEST_TH['box'])

    def union_of(spec):
        return unary_union([shape(f['geometry']).buffer(0)
                            for adm, names in spec
                            for f in ne_pick(adm, names)]).intersection(bx)
    with open(os.path.join(DATA, 'ww1', 'ohm_abroad_1914.geojson'),
              encoding='utf-8') as f:
        abroad = [x for x in json.load(f)['features'] if x.get('geometry')]
    prussia = unary_union([shape(x['geometry']).buffer(0) for x in abroad
                           if x['properties'].get('name') == 'Provinz Ostpreußen'])
    _west['abroad1914'] = unary_union([shape(x['geometry']).buffer(0)
                                       for x in abroad])
    # на всём окне: вне основы, без германской Восточной Пруссии
    _west['out'] = union_of(WEST_MASK).difference(base).difference(
        prussia).buffer(0)
    # земля основы, которую решают якоря (с 18.02.1918)
    _west['in'] = union_of(WEST_IN).intersection(base).buffer(0)
    # и та, которую они решают только в своём окне
    _west['in_windows'] = [(union_of([spec]).intersection(base).buffer(0), a, b)
                           for spec, a, b in WEST_IN_WINDOWS]


def west_geom(day, base):
    """Красное западного театра на дату -> (красное, земля основы под якорями).

    До германского наступления 18.02.1918 - фронт слоя ПМВ на день перемирия:
    вся земля маски вне основы, кроме занятого противником и чужого до войны
    (Восточная Пруссия, Галиция, Буковина по контурам OHM 1914 года). Так срез
    25.12.1917 продолжает срез ПМВ 01.12.1917, а не рисует страны Балтии второй
    моделью по шестидесяти городам вместо двухсот. Землю основы в эти дни
    режет ww1_occupied, вторая часть ответа пуста."""
    _west_masks(base)
    if day < WW1_HANDOFF:
        ww1_occupied(base)
        red = _west['out'].difference(_west['ww1_raw']).difference(
            _west['abroad1914']).buffer(0)
        return red, unary_union([])
    fl = _west['field']
    mk = fl.mask(day)
    zone_in = unary_union([_west['in']] + [g for g, a, b in _west['in_windows']
                                           if a <= day < b]).buffer(0)
    zone = unary_union([_west['out'], zone_in])
    if not mk.any():
        return unary_union([]), zone_in
    return fl.to_geom(mk).intersection(zone).buffer(0), zone_in


def ww1_occupied(base):
    """Земля основы, занятая противником на день перемирия, - моделью слоя ПМВ."""
    if 'ww1' not in _west:
        th = next(t for t in w1.THEATRES if t['id'] == 'west')
        fl = w1.Field(w1.load_anchors(), th)
        lost_m, _ = fl.masks(WW1_FRONT_DAY)
        g = fl.to_geom(lost_m).intersection(box(*th['box'])) \
            if lost_m.any() else unary_union([])
        _west['ww1_raw'] = g.buffer(0)
        _west['ww1'] = g.intersection(base).buffer(0)
    return _west['ww1']

# ---- срезы ----------------------------------------------------------------
# key      - дата, с которой срез показывается (она же имя файла)
# minus    - какие группы областей вычесть дополнительно к окнам (украинский
#            театр: там нужна дробность внутри дат). ВНИМАНИЕ: после смены
#            рамки 26.08.2026 сюда попадает ТОЛЬКО то, что вышло из империи -
#            УНР во всех формах, ЗУНР, Польша. Территория, взятая белыми
#            (Одесса при Антанте, Харьков и Киев при Деникине, Донбасс,
#            Екатеринослав, Северная Таврия при Врангеле), остаётся КРАСНОЙ.
# note     - что читается на карте; anchor - чем датировано

# Срезы западного театра (22.09.2026): дни смены власти в городах-якорях
# data/crosscheck/zones_west_cities.csv. Близкие дни сведены в один срез - к
# более позднему, чтобы срез не показывал взятие раньше самого взятия.
# Вычитания `minus` украинского театра срез берёт у предыдущего среза
# (там на эти дни ничего не менялось)


# ---- инструменты ----------------------------------------------------------
def d(s):
    """'1919-06-12' -> date."""
    return date(*[int(x) for x in s.split('-')])


def cshapes(y, m, dd):
    src = json.load(open(os.path.join(CACHE, 'cshapes20.geojson'), encoding='utf-8'))
    for f in src['features']:
        p = f['properties']
        if p.get('gwcode') != 365:
            continue
        if (p['gwsyear'], p['gwsmonth'], p['gwsday']) <= (y, m, dd) <= \
           (p['gweyear'], p['gwemonth'], p['gweday']):
            return shape(f['geometry']).buffer(0)
    raise SystemExit(f'CShapes: нет полигона gwcode 365 на {y}-{m:02d}-{dd:02d}')


_ne_cache = {}


def ne_feats():
    if not _ne_cache.get('__feats'):
        _ne_cache['__feats'] = json.load(
            open(os.path.join(CACHE, 'ne_admin1.geojson'), encoding='utf-8'))['features']
    return _ne_cache['__feats']


def ne_pick(admin, names, isos=None):
    """Фичи Natural Earth admin-1 по стране и списку имён (или iso_3166_2)."""
    feats = ne_feats()
    if names is None and not isos:
        sel = [f for f in feats if f['properties'].get('admin') == admin]
    else:
        sel = [f for f in feats
               if f['properties'].get('admin') == admin
               and (f['properties'].get('name') in (names or [])
                    or f['properties'].get('iso_3166_2') in (isos or []))]
        found = {f['properties'].get('name') for f in sel}
        missing = set(names or []) - found
        if missing:
            raise SystemExit(f'NE admin-1: не найдены области {sorted(missing)} '
                             f'({admin})')
    if not sel:
        raise SystemExit(f'NE admin-1: пустая выборка {admin} {names} {isos}')
    return sel


def ne_union(group):
    """Объединение современных областей группы (Natural Earth admin-1).

    Значение REG - либо кортеж (admin, names[, isos]), либо список таких
    кортежей (группа из нескольких стран, например Туркестан).
    """
    if group in _ne_cache:
        return _ne_cache[group]
    spec = REG[group]
    if isinstance(spec, str) and spec.startswith('file:'):
        # курируемая геометрия из OpenStreetMap: районной нарезки в Natural
        # Earth нет (Таймыр). Тот же файл читает tools/build_expansion.py.
        with open(os.path.join(DATA, spec[5:]), encoding='utf-8') as fh:
            fc = json.load(fh)
        g = unary_union([shape(f['geometry']).buffer(0)
                         for f in fc['features']])
        _ne_cache[group] = g
        return g
    if group == 'CRIMEA':
        sel = [f for f in ne_feats()
               if f['properties'].get('iso_3166_2') in CRIMEA_ISO]
    elif isinstance(spec, list):
        sel = [f for s in spec for f in ne_pick(s[0], s[1],
                                                s[2] if len(s) > 2 else None)]
    else:
        sel = ne_pick(spec[0], spec[1], spec[2] if len(spec) > 2 else None)
    g = unary_union([shape(f['geometry']).buffer(0) for f in sel])
    if group == 'BASHKIR_SMALL':
        # рамка «Малой Башкирии»: юго-восток республики, Уфа (54.74 с.ш.,
        # 55.97 в.д.) остаётся вне вычитания - её держали Комуч и Колчак,
        # то есть имперская фракция. Рамка координатная, как вычитания
        # Кавказа в tools/build_expansion.py, а не историческая граница.
        g = g.intersection(box(55.5, 50.5, 61.0, 54.5))
    _ne_cache[group] = g
    return g


def adds_geom(base):
    """Хива и Бухара: дыры основы-контура внутри современной Средней Азии."""
    if 'KHIVA' in _ne_cache:
        return
    ca = unary_union([shape(f['geometry']).buffer(0) for f in ne_feats()
                      if f['properties'].get('admin') in CENTRAL_ASIA_ADMINS])
    hole = ca.difference(base)
    hole = unary_union([g for g in (hole.geoms if hole.geom_type == 'MultiPolygon'
                                    else [hole]) if g.area > 0.05])
    khiva_box = unary_union(
        [shape(f['geometry']).buffer(0)
         for f in ne_pick(*KHIVA_REG) + ne_pick(*KHIVA_TM)])
    _ne_cache['KHIVA'] = hole.intersection(khiva_box)
    _ne_cache['BUKHARA'] = hole.difference(khiva_box)


def extended(line, poly, step=3.0, tries=6):
    """Продлить концы линии по последнему азимуту, пока не выйдут из полигона.

    Атласные линии местами обрываются внутри контура (обрез разворота, наш
    порог оцифровки) - без продления полигон ими не режется.
    """
    cs = list(line.coords)
    out = list(cs)
    for end in (0, -1):
        p = Point(cs[end])
        if not poly.contains(p):
            continue
        a, b = (cs[1], cs[0]) if end == 0 else (cs[-2], cs[-1])
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = (dx * dx + dy * dy) ** 0.5 or 1
        dx, dy = dx / n, dy / n
        for k in range(1, tries + 1):
            q = (b[0] + dx * step * k, b[1] + dy * step * k)
            if not poly.contains(Point(q)):
                break
        if end == 0:
            out.insert(0, q)
        else:
            out.append(q)
    return LineString(out)


def parts_with(poly, pts):
    """Куски мультиполигона, содержащие любую из точек."""
    geoms = list(poly.geoms) if poly.geom_type == 'MultiPolygon' else [poly]
    return [g for g in geoms if any(g.contains(p) for p in pts)]


def cut_by_atlas(poly, year, idx, add_loops, log):
    """Разрезать полигон атласными линиями, оставить часть с Москвой.

    БОЛЬШЕ НЕ ВЫЗЫВАЕТСЯ (смена рамки 26.08.2026): линии розд. 44 атласа УІФ -
    это граница СОВЕТСКОГО контроля, то есть межфракционная линия внутри
    империи. Оставлена как история вопроса вместе с `extended` и `parts_with`;
    файлы линий остаются в data/atlas и остаются якорями датировки срезов.
    """
    src = json.load(open(os.path.join(
        DATA, 'atlas', f'rozd44_soviet_control_{year}.geojson'), encoding='utf-8'))
    feats = src['features']
    open_lines, loops = [], []
    for i, f in enumerate(feats):
        g = shape(f['geometry'])
        closed = g.coords[0] == g.coords[-1]
        if i in idx and not closed:
            open_lines.append(extended(g, poly))
        elif closed:
            loops.append(g)
    if not open_lines:
        raise SystemExit(f'атлас {year}: среди линий {idx} нет незамкнутых')
    cut = poly.difference(unary_union(open_lines).buffer(0.05))
    keep = parts_with(cut, [MOSCOW])
    if not keep:
        raise SystemExit(f'атлас {year}: после резки нет части с Москвой')
    soviet = unary_union(keep)
    log.append(f'резка линиями {idx} атласа {year}: '
               f'площадь {poly.area:.0f} -> {soviet.area:.0f} град²')
    if add_loops and loops:
        polys = [p for line in loops for p in polygonize([line])]
        enc = unary_union([p.intersection(poly) for p in polys if not p.is_empty])
        if not enc.is_empty:
            soviet = unary_union([soviet, enc])
            log.append(f'добавлены замкнутые контуры-анклавы: {len(polys)} шт, '
                       f'площадь {enc.area:.1f} град²')
    return soviet


def active_windows(day):
    """Окна фронтов, действующие на дату (регион вне советской власти)."""
    out = []
    for w in WINDOWS:
        frm = d(w['frm']) if w['frm'] else date(1917, 1, 1)
        to = d(w['to']) if w['to'] else PERIOD_END
        if frm <= day < to:
            out.append(w)
    return out


def build(sl, base):
    log = []
    day = d(sl['key'])
    geom = base
    for group in sl.get('minus', []):
        before = geom.area
        geom = geom.difference(ne_union(group).buffer(0.02))
        log.append(f'минус {group} (посрезово): {before:.0f} -> {geom.area:.0f} град²')
    fronts, fronts_why = [], []
    for w in active_windows(day):
        # kind='in' - держала другая фракция империи: геометрию НЕ режем
        # (решение куратора 26.08.2026, empire-not-factions), запись идёт
        # только в атрибуцию попапа. То же для окон `out` с cut=False:
        # их геометрию режет посрезовый `minus` (украинский театр).
        if w['cut']:
            before = geom.area
            geom = geom.difference(ne_union(w['group']).buffer(0.02))
            if before - geom.area > 0.5:
                log.append(f'окно {w["group"]} (вне империи): {before:.0f} -> '
                           f'{geom.area:.0f} град²')
            fronts.append(w['group'])
        # атрибуция для попапа истории точки: кто держал регион в этот день
        fronts_why.append({'group': w['group'], 'who': w['who'], 'kind': w['kind'],
                           'frm': w['frm'], 'to': w['to'], 'why': w['why']})
    if day < WW1_HANDOFF:
        occ = ww1_occupied(base)
        if not occ.is_empty:
            before = geom.area
            geom = geom.difference(occ).buffer(0)
            log.append(f'фронт ПМВ на день перемирия (под немцами с 1915 года): '
                       f'{before:.0f} -> {geom.area:.0f} град²')
    added = []
    for a in ADDS:
        if day >= d(a['frm']):
            adds_geom(base)
            geom = unary_union([geom, _ne_cache[a['name']]])
            added.append(a['name'])
    if added:
        log.append(f'добавлены {", ".join(added)}: площадь {geom.area:.0f} град²')
    west, west_in = west_geom(day, base)
    if not west_in.is_empty:
        # землю основы в WEST_IN решают якоря: сперва она снимается целиком
        before = geom.area
        geom = geom.difference(west_in).buffer(0)
        log.append(f'Брестская и Гродненская области - по якорям: '
                   f'{before:.0f} -> {geom.area:.0f} град²')
    if not west.is_empty:
        geom = unary_union([geom, west]).buffer(0)
        log.append(f'западный театр по якорям: +{west.area:.2f} град²')
    # Персия (22.09.2026): русские гарнизоны до эвакуации 01.03.1918 - окна
    # PERSIA_* таблицы ADDS tools/build_expansion.py
    pers = be.occupation_geom(day, 'PERSIA_')
    if not pers.is_empty:
        geom = unary_union([geom, pers]).buffer(0)
        log.append(f'Персия, районы гарнизонов: +{pers.area:.2f} град²')
    geom = geom.simplify(0.02).buffer(0)
    geoms = [g for g in (list(geom.geoms) if geom.geom_type == 'MultiPolygon'
                         else [geom]) if g.area > 0.05]
    fc = {'type': 'FeatureCollection', 'features': [{
        'type': 'Feature',
        'geometry': gc.clean_rings(mapping(gc.finish(g, CACHE))),
        'properties': {
            'name': 'зона империи',
            'year': sl['key'],
            'role': 'core',
            'reconstruction': True,
            'approximate': True,
            'note': sl['note'],
            'anchor': sl['anchor'],
            'fronts': ', '.join(sorted(set(fronts))),
            'fronts_why': fronts_why,
            'added': ', '.join(added),
            'west_deg2': round(west.area, 2),
            'source': ('РЕКОНСТРУКЦИЯ (черновик, ред. 3 от 26.08.2026 - зона '
                       f'ИМПЕРИИ, а не советского контроля): {BASE_NOTE}; '
                       'вычитаются только территории, реально вышедшие из '
                       'империи (окна kind=out); белые фракции - Комуч, '
                       'Колчак, ВСЮР, Врангель, Северная область, Семёнов, '
                       'ДВР - остаются красными. Геометрия приближена '
                       'современными областями Natural Earth admin-1 '
                       '(tools/build_zones_1917_1921.py, WINDOWS); '
                       'Эстония, Латвия, Литва, запад Гродненщины и Псковщины - моделью '
                       'якорей по городам data/crosscheck/zones_west_cities.csv '
                       '(голосование ближайших городов, вес 1/d^3, сетка '
                       '0.05°); проверка - tools/check_cities.py по '
                       'data/crosscheck/cities_civilwar.csv'),
        }} for g in geoms]}
    # Соловки (22.09.2026): куски мельче 0,05 град² выше отброшены, чистка
    # снимает острова - курируемую береговую линию добавляем отдельной фичей
    # (Северная область белых - тоже империя, правило «империя, а не
    # фракции»). Остров от материка отделён, шва обводки не даёт
    for r in sorted(be.EARLY_PROTECT):
        pg = be.reg_geom(r)
        f0 = dict(fc['features'][0])
        f0['properties'] = dict(f0['properties'], protected=r)
        f0['geometry'] = gc.clean_rings(mapping(pg))
        fc['features'].append(f0)
    out = os.path.join(DATA, 'years', sl['key'] + '.geojson')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj(fc), f, ensure_ascii=False)
    return len(geoms), geom.area, log


ATTR_TOL = 0.05      # упрощение слоя атрибуции, как в tools/build_attribution.py
ATTR_DIG = 3


def _round(g):
    def walk(c):
        if isinstance(c[0], (int, float)):
            return [round(c[0], ATTR_DIG), round(c[1], ATTR_DIG)]
        return [walk(x) for x in c]
    return gc.clean_rings({'type': g['type'], 'coordinates': walk(g['coordinates'])})


def build_windows_layer():
    """Слой атрибуции 1917-1921: «кто держал регион и в какие дни».

    Попап истории точки (клик по карте) для окна 12.1917-03.1921 берёт
    атрибуцию отсюда, а не из годовых срезов historical-basemaps: тут даты
    точные (взятия городов), а не «между 1914 и 1920».
    Пишется в data/attribution/windows_1917_1921.geojson.
    """
    out_dir = os.path.join(DATA, 'attribution')
    os.makedirs(out_dir, exist_ok=True)
    feats = []
    for w in WINDOWS:
        g = ne_union(w['group']).simplify(ATTR_TOL).buffer(0)
        if g.is_empty:
            raise SystemExit(f'окно {w["group"]}: пустая геометрия')
        feats.append({'type': 'Feature', 'geometry': _round(mapping(g)),
                      'properties': {'group': w['group'], 'who': w['who'],
                                     'kind': w['kind'], 'cut': w['cut'],
                                     'frm': w['frm'], 'to': w['to'],
                                     'why': w['why']}})
    path = os.path.join(out_dir, 'windows_1917_1921.geojson')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': feats,
                   'note': ('окна реконструкции 1917-1921 [frm; to), frm=null - '
                            'с начала окна (01.12.1917), to=null - до '
                            '18.03.1921. kind=out - территория ВНЕ империи, '
                            '`who` = имя субъекта; kind=in - территорию держала '
                            'другая фракция империи, `who` = имя фракции '
                            '(геометрию такие окна не режут). Геометрия - '
                            'современные области Natural Earth admin-1, '
                            'приближение')},
                  f, ensure_ascii=False)
    print(f'OK data/attribution/windows_1917_1921.geojson: окон {len(feats)}, '
          f'{os.path.getsize(path) // 1024} КБ')


def update_manifest(keys):
    """Ключи срезов - в манифест, не трогая остальных (22.09.2026: срезы
    западного театра; прежние ключи окна регистрировал tools/build_data.py,
    список RECON, вне канона)."""
    path = os.path.join(DATA, 'manifest.json')
    with open(path, encoding='utf-8') as f:
        mf = json.load(f)
    have = set(map(str, mf['years']))
    new = sorted(set(keys) - have)
    if not new:
        return
    mf['years'] = sorted(have | set(keys), key=be.key_date)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj(mf), f, ensure_ascii=False, indent=1)
    print(f'манифест: +{len(new)} ключей окна ({", ".join(new)})')


def slice_sig(sl, day):
    """Подпись среза (tools/slice_sigs.py, 27.09.2026): всё, от чего зависит
    его геометрия и свойства НА ЭТОТ ДЕНЬ. Совпала с прошлой сборкой - срез
    не пересобирается и на берег не идёт."""
    import slice_sigs as ss
    tools = os.path.dirname(os.path.abspath(__file__))
    wins = active_windows(day)
    groups = set(sl.get('minus', [])) | {w['group'] for w in wins if w['cut']}

    def grp(g):
        spec = REG[g]
        if isinstance(spec, str) and spec.startswith('file:'):
            return [spec, ss.sha_file(os.path.join(DATA, spec[5:]))]
        return repr(spec)
    return ss.sha_obj({
        'code': [ss.sha_file(os.path.abspath(__file__)),
                 ss.sha_file(os.path.join(tools, 'build_ww1.py')),
                 ss.sha_file(os.path.join(tools, 'geoclean.py'))],
        'base': [BASE, ss.sha_file(os.path.join(CACHE, 'cshapes20.geojson'))],
        'ne': ss.sha_file(os.path.join(CACHE, 'ne_admin1.geojson')),
        'slice': sl, 'windows': wins,
        'groups': {g: grp(g) for g in sorted(groups)},
        'adds': [a for a in ADDS if day >= d(a['frm'])],
        # до 18.02.1918 запад режет фронт ПМВ на день перемирия (якоря ПМВ),
        # после - модель западного театра по своим якорям; маски театра
        # (OHM 1914, области NE) нужны на всём окне
        'ww1_anchors': ss.sha_file(w1.ANCHORS) if day < WW1_HANDOFF else None,
        'west': [ss.sha_file(WEST_ANCHORS),
                 ss.sha_file(os.path.join(DATA, 'ww1', 'ohm_abroad_1914.geojson'))],
        'persia': [[a['reg'], a['frm'], a['to'], a['kind'], a.get('clip'),
                    ss.reg_sig(be, a['reg'])] for a in be.ADDS
                   if a['reg'].startswith('PERSIA_') and be.d(a['frm']) <= day
                   and not (a['to'] and be.d(a['to']) <= day)],
        'protect': {r: ss.reg_sig(be, r) for r in sorted(be.EARLY_PROTECT)},
    })


def main():
    import argparse
    import slice_sigs as ss
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--all', action='store_true',
                    help='собрать все срезы, не глядя на подписи прошлой сборки')
    ap.add_argument('--only', help='собрать один срез (для отладки; подписи не пишутся)')
    args = ap.parse_args()
    base = cshapes(*BASE)
    print(f'основа: CShapes {BASE[0]}-{BASE[1]:02d}-{BASE[2]:02d}, '
          f'площадь {base.area:.0f} град²')
    sigs = ss.Sigs('zones', use_old=not (args.all or args.only))
    for sl in sorted(SLICES, key=lambda s: d(s['key'])):
        if args.only and sl['key'] != args.only:
            continue
        sig = slice_sig(sl, d(sl['key']))
        path = os.path.join(DATA, 'years', sl['key'] + '.geojson')
        if not args.only and sigs.fresh(sl['key'], sig, path):
            continue
        n, area, log = build(sl, base)
        sigs.put(sl['key'], sig)
        print(f'OK data/years/{sl["key"]}.geojson: фич {n}, площадь {area:.0f} град²')
        for line in log:
            print('   ' + line)
    sigs.report('зоны 1917-1921')
    if args.only:
        return
    build_windows_layer()
    update_manifest([sl['key'] for sl in SLICES])
    sigs.save()
    gc.write_stamp('zones_1917_1921')
    print(f'срезов реконструкции: {len(SLICES)}, окон фронтов: {len(WINDOWS)}')


if __name__ == '__main__':
    main()
