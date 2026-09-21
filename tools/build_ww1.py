#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Помесячные срезы Первой мировой войны, 19.07.1914 - 25.12.1917 (ст. ст.).

ЗАЧЕМ (BACKLOG_KARTY.md, Б6 п. 7, 19.09.2026). Между довоенным срезом
1914-04-04 и срезом 1917-12-25, с которого начинается реконструкция 1917-1921,
у карты было только два среза - Галиция по курируемому приобретению
UA_GALICIA_1914 (занята 1914-09-03, оставлена 1915-06-22). Германской
оккупации не было вовсе: Варшава, Вильна, Ковно, Гродно, Митава оставались
красными до конца 1917 года, хотя германские войска взяли их летом 1915-го.
Нашлось при сверке окон восстаний с каноном.

ДВА ПРАВИЛА КУРАТОРА, оба уже действуют:
- «контроль, а не акт»: земля, которую держит противник, - не империя, даже
  если по бумаге она российская;
- «военная оккупация = имперский контроль = красное», во всех эпохах
  (18.09.2026, карточка 01_iran.md: «конечно да!» - и до 1917 года).
  Поэтому Восточная Пруссия 1914 года, Галиция и Буковина 1914-1915 и
  1916-1917 годов, Турецкая Армения и Лазистан 1916-1917 годов краснеют.

МОДЕЛЬ - как у слоя Второй мировой (tools/build_ww2.py): машиночитаемой линии
фронта по датам нет, поэтому она строится из таблицы городов-якорей
data/crosscheck/ww1_cities.csv (у каждого якоря на любую дату есть сторона) -
голосованием ближайших якорей с весом 1/d^3 на сетке 0.05°. Два театра:
Восточный фронт (от Моонзунда до Буковины) и Кавказский.

ОДНО ОТЛИЧИЕ ОТ ВМВ - якорь голосует только за свою землю, пока его не взяли.
В 1914 году граница шла через плотно населённую Польшу и Галицию, и у
обычного голосования нулевая линия легла бы посередине между Калишем и
Познанью, а не по границе: уже на первом срезе карта отрезала бы полосы
Царства Польского, где никакого противника не было. Поэтому:

- землю империи (контур-основу) делят якоря империи - каждый своей стороной
  на дату - и те чужие якоря, которые сейчас ВЗЯТЫ империей (голос «империя»);
- чужую землю (маска стран, куда входили российские войска) делят чужие
  якоря своей стороной и те якоря империи, которые сейчас ВЗЯТЫ противником
  (голос «не империя»).

Невзятый якорь за границей про землю по эту сторону ничего не знает и молчит.
Пока ни один якорь не сменил сторону, срез равен контуру-основе в точности.

И ЕЩЁ ОДНО (21.09.2026) - якорь голосует только за свою сушу: остров - за
свой остров, материк - за материк (связные куски суши Natural Earth admin-1).
Без этого Аренсбург на Эзеле через Ирбенский пролив держал красным мыс
Домеснес (Колка): 59 км² в 26 срезах 1915-09 - 1917-09, хотя северная
Курляндия с июля 1915 года за германцами (Стратегический очерк, ч. 7: до
12/25.08.1917 фронт стоял западнее линии Шлок - оз. Бабит - Олай). Остров
без якорей остаётся как в основе.

ДАТЫ - старый стиль, как на всей карте до 1918 года (README: «датировка
срезов - по датам актов и по старому стилю»). Новый стиль - в note таблицы.
Ключи срезов - первое число каждого месяца по старому стилю, плюс день
Варшавы (23.07.1915) и Риги (21.08.1917), плюс ключи других сборщиков,
попавшие в окно (1914-09-03 и 1915-06-22 от UA_GALICIA_1914): внутри окна
все срезы пишет этот сборщик.

КОНТУР-ОСНОВА - довоенный срез 1914-04-04 из tools/build_expansion.py (с
Урянхайским краем). Галицию из приобретения UA_GALICIA_1914 основа не берёт:
её оккупацию рисует поле.

ЧТО НА ВЫХОДЕ. В каждом срезе одна фича, как у слоя ВМВ: основа минус
занятое противником плюс занятое империей за границей. До 21.09.2026 их было
две (ядро и `occupation: true`), и обводка ядра на карте (index.html,
outlineOf - кольца всех фич) рисовала внутри красного довоенную границу:
Галиция, Восточная Пруссия, Турецкая Армения. Чистка (geoclean.finish)
считается по всему срезу, но правки берутся только в полосе HALO у фронта:
вдали от него срез остаётся основой. Полная чистка всего ядра отщепляла
крошки, которых в основе нет, - остров 10 км² на Каспии, щели на Котельном.

ГРАНИЦЫ ЧЕСТНОСТИ - как у слоя ВМВ: это РЕКОНСТРУКЦИЯ по датам взятия
городов, между якорями линия идёт там, где её проводит формула. У каждого
среза `reconstruction: true`, `approximate: true`.

Шаг канона 'ww1' (tools/check_build_order.py, с 21.09.2026): после
tools/clip_foreign.py, перед build_losses.py. Основа - срез 1914-04-04: его
пишет первый шаг, поздние правки (окна с 18.03.1921) его не касаются, а
обрезка чужой земли уже сняла с него ленты за границами. Поэтому ядро слоя
чистое, а сам слой обрезка пропускает, как срезы ВМВ: занятое за границей -
Эрзерум, Трапезунд, Галиция - она срезала бы как «чужую землю без акта».
Добавить или пересобрать слой к готовому канону - шаги 7-12, около 20 минут.
До 21.09.2026 слой стоял перед обрезкой (19-21.09 - шаг 6 из 12).

Запуск:
    cd ~/tmp/imperium-map && .venv/bin/python tools/build_ww1.py --dry-run
    cd ~/tmp/imperium-map && .venv/bin/python tools/build_ww1.py
    cd ~/tmp/imperium-map && .venv/bin/python tools/check_ww1.py --anchors
"""
import argparse
import csv
import json
import os
import sys
from datetime import date

import numpy as np
import shapely
from scipy.spatial import cKDTree
from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_data as bd            # noqa: E402
import build_expansion as be       # noqa: E402  (d, key_date, ne_pick, _round)
import geoclean as gc              # noqa: E402
from build_ww2 import smooth       # noqa: E402  (снятие растровой лестницы)

DATA = bd.OUT
CC = os.path.join(DATA, 'crosscheck')
ANCHORS = os.path.join(CC, 'ww1_cities.csv')

# ---- параметры поля (как у ВМВ) --------------------------------------------
STEP = 0.05                     # шаг сетки, градусы (~5.5 км по широте)
POW = 3.0                       # степень обратного расстояния
KNN = 8                         # сколько ближайших якорей каждой стороны
SIMPLIFY = 0.01                 # упрощение растровых кусков
SPECK = 0.004                   # град²: мельче - шум растра, выбрасываем
LAND_GAP = 0.01                 # град: припуск суши, щели швов admin-1 сливаются
LAND_SNAP = 0.1                 # град: узел в море у берега - к ближайшей суше
HALO = 0.1                      # град: полоса у фронта, где принимается чистка

WAR = '1914-07-19'              # 19.07 (01.08) 1914: Германия объявила войну
END = '1917-12-25'              # с этого среза - tools/build_zones_1917_1921.py
BASE_KEY = '1914-04-04'         # довоенный контур, tools/build_expansion.py
EVENT_KEYS = ['1915-07-23',     # Варшава: в ночь 22/23.07 войска ушли за Вислу
              '1917-08-21']     # Рига оставлена в ночь на 21.08

# ---- театры ----------------------------------------------------------------
# box - рамка поля; abroad - чужая земля, куда российские войска входили.
# Вне маски чужая земля не краснеет ни при каком раскладе якорей.
# Запад - исторические контуры 1914 года из OpenHistoricalMap (CC0, файл
# data/ww1/ohm_abroad_1914.geojson): Герцогство Буковина 1878-1918 (relation
# 2746401), Галиция и Лодомерия 1902-1918 (2800213), провинция Восточная
# Пруссия 1878-1920 (2691482). До 21.09.2026 маска была нынешней нарезкой
# Natural Earth (Калининград, Варминьско-Мазурское, Подкарпатское, Малопольское,
# Львовская, Тернопольская, Ивано-Франковская, Черновицкая области, уезд
# Сучава) и врала в обе стороны: Герца и Фэлтичень - союзная Румыния, а не
# Буковина - краснели в 1915-1917 годах, а галицийская полоса у Белза (ныне
# Люблинское воеводство) оставалась чёрной дырой 254 км² внутри занятого.
# Кавказ - провинции Турции по Natural Earth: в 1914 году они все османские,
# а российская часть (Карс, Ардаган, Артвин, Игдыр) входит в основу.
THEATRES = [
    dict(id='west', name='Восточный фронт', box=(13.5, 44.0, 31.0, 60.5),
         phi0=52.0, abroad_file='ww1/ohm_abroad_1914.geojson'),
    dict(id='caucasus', name='Кавказский фронт', box=(36.0, 36.5, 47.0, 42.5),
         phi0=40.0,
         abroad=[('Turkey', ['Trabzon', 'Rize', 'Giresun', 'Gümüshane',
                             'Bayburt', 'Erzincan', 'Erzurum', 'Agri', 'Van',
                             'Bitlis', 'Mus', 'Bingöl', 'Hakkari', 'Artvin',
                             'Ardahan', 'Kars', 'Iğdir'])]),
]
CAUCASUS = {'кавказ', 'caucasus'}

_g = {}


def theatre_of(row):
    return 'caucasus' if row.get('theatre', '').strip().lower() in CAUCASUS \
        else 'west'


# ---- якоря -----------------------------------------------------------------
def parse_changes(row):
    """Строка таблицы -> (сторона на 19.07.1914, [(дата, +1|-1), ...])."""
    start = 1 if row['start'].strip() == 'empire' else -1
    ch = []
    for part in (row.get('changes') or '').split(';'):
        part = part.strip()
        if not part:
            continue
        day, side = part.split(':')
        side = side.strip()
        if side not in ('empire', 'foreign'):
            raise SystemExit(f'{row["city"]}: сторона «{side}» - ждём '
                             f'empire или foreign')
        ch.append((be.d(day.strip()), 1 if side == 'empire' else -1))
    ch.sort()
    return start, ch


def load_anchors(path=ANCHORS):
    """Проверка ВСЕЙ таблицы до первой записи: кривая строка - отказ целиком."""
    if not os.path.exists(path):
        raise SystemExit(f'{path}: таблицы якорей нет')
    with open(path, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    out, bad = [], []
    for r in rows:
        if (r.get('anchor') or 'yes').strip() != 'yes':
            continue          # строка только для регрессии, поле не задаёт
        try:
            lat, lon = float(r['lat']), float(r['lon'])
            start, ch = parse_changes(r)
        except (ValueError, KeyError) as e:
            bad.append(f'{r.get("city")}: {e}')
            continue
        out.append(dict(city=r['city'], lat=lat, lon=lon, start=start,
                        changes=ch, theatre=theatre_of(r)))
    if bad:
        raise SystemExit('таблица якорей с ошибками:\n  ' + '\n  '.join(bad))
    if not out:
        raise SystemExit(f'{path}: якорей нет')
    return out


def side_at(a, day):
    s = a['start']
    for when, val in a['changes']:
        if when <= day:
            s = val
    return s


# ---- поле ------------------------------------------------------------------
class Field:
    """Сетка одного театра и деревья якорей обеих сторон: строится один раз."""

    def __init__(self, anchors, th):
        self.th = th
        x0, y0, x1, y1 = th['box']
        self.ky = float(np.cos(np.radians(th['phi0'])))
        self.lons = np.arange(x0, x1 + 1e-9, STEP)
        self.lats = np.arange(y0, y1 + 1e-9, STEP)
        lo, la = np.meshgrid(self.lons, self.lats)
        self.shape = lo.shape
        q = np.c_[lo.ravel() * self.ky, la.ravel()]
        mine = [a for a in anchors if a['theatre'] == th['id']]
        self.E = [a for a in mine if a['start'] > 0]     # империя на 19.07.1914
        self.F = [a for a in mine if a['start'] < 0]     # противник
        self.parts = land_parts(th)
        self.node_land = land_ids(self.parts, lo.ravel(), la.ravel())
        self.wE, self.iE = self._knn(self.E, q)
        self.wF, self.iF = self._knn(self.F, q)

    def _knn(self, group, q):
        if not group:
            return None, None
        lon = np.asarray([a['lon'] for a in group])
        lat = np.asarray([a['lat'] for a in group])
        pts = np.c_[lon * self.ky, lat]
        k = min(KNN, len(group))
        d, i = cKDTree(pts).query(q, k=k)
        if k == 1:
            d, i = d[:, None], i[:, None]
        w = 1.0 / np.maximum(d, 1e-6) ** POW
        # якорь голосует только за свою сушу: через пролив голоса нет
        al = land_ids(self.parts, lon, lat)[i]
        nl = self.node_land[:, None]
        w[(al >= 0) & (nl >= 0) & (al != nl)] = 0.0
        return w, i

    def masks(self, day):
        """Узлы сетки: (своя земля ушла к противнику, чужая земля у империи)."""
        n = self.shape[0] * self.shape[1]
        own, foreign = np.zeros(n), np.zeros(n)
        if self.E:
            sE = np.asarray([side_at(a, day) for a in self.E], dtype=float)
            own += (self.wE * sE[self.iE]).sum(axis=1)
            foreign -= (self.wE * (sE[self.iE] < 0)).sum(axis=1)
        if self.F:
            sF = np.asarray([side_at(a, day) for a in self.F], dtype=float)
            foreign += (self.wF * sF[self.iF]).sum(axis=1)
            own += (self.wF * (sF[self.iF] > 0)).sum(axis=1)
        return ((own < 0).reshape(self.shape),
                (foreign > 0).reshape(self.shape))

    def to_geom(self, mask):
        """Маска узлов -> полигон: прямоугольники по строкам, склейка,
        снятие лестницы, упрощение, без крапинок."""
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
        g = smooth(unary_union(boxes), STEP).simplify(SIMPLIFY).buffer(0)
        parts = g.geoms if g.geom_type == 'MultiPolygon' else [g]
        return unary_union([p for p in parts if p.area > SPECK])


# ---- контуры ---------------------------------------------------------------
def base_geom():
    """Довоенный контур империи - файл среза BASE_KEY."""
    if 'base' not in _g:
        path = os.path.join(DATA, 'years', BASE_KEY + '.geojson')
        with open(path, encoding='utf-8') as f:
            fc = json.load(f)
        if any((x.get('properties') or {}).get('ww1') for x in fc['features']):
            raise SystemExit(f'{path}: это срез самого слоя, основой не годится')
        _g['base'] = unary_union([shape(x['geometry']).buffer(0)
                                  for x in fc['features']
                                  if x.get('geometry')]).buffer(0)
    return _g['base']


def abroad_mask(th):
    k = ('abroad', th['id'])
    if k not in _g:
        if th.get('abroad_file'):
            path = os.path.join(DATA, th['abroad_file'])
            if not os.path.exists(path):
                raise SystemExit(f'{path}: нет контуров чужой земли театра')
            with open(path, encoding='utf-8') as f:
                fc = json.load(f)
            _g[k] = unary_union([shape(x['geometry']).buffer(0)
                                 for x in fc['features']
                                 if x.get('geometry')]).buffer(0)
        else:
            _g[k] = unary_union([be.ne_pick(a, n) for a, n in th['abroad']]
                                ).buffer(0)
    return _g[k]


def land_parts(th):
    """Связные куски суши театра по Natural Earth admin-1 (с припуском
    LAND_GAP, чтобы щели швов между единицами не рвали материк): материк,
    Эзель, Моон, Даго, Готланд..."""
    k = ('land', th['id'])
    if k not in _g:
        land = gc.land_mask(be.CACHE).intersection(
            box(*th['box']).buffer(1.0)).buffer(LAND_GAP)
        parts = list(land.geoms) if land.geom_type == 'MultiPolygon' \
            else [land]
        for p in parts:
            shapely.prepare(p)
        _g[k] = parts
    return _g[k]


def land_ids(parts, xs, ys):
    """Номер куска суши для каждой точки; точка в море - к ближайшей суше не
    дальше LAND_SNAP, дальше - -1 (голосует и получает голоса без ограничений)."""
    xs, ys = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    ids = np.full(xs.shape, -1, dtype=int)
    for n, p in enumerate(parts):
        x0, y0, x1, y1 = p.bounds
        cand = np.flatnonzero((ids < 0) & (xs >= x0) & (xs <= x1)
                              & (ys >= y0) & (ys <= y1))
        if cand.size:
            ids[cand[shapely.contains_xy(p, xs[cand], ys[cand])]] = n
    rest = np.flatnonzero(ids < 0)
    if rest.size:
        src, dst = shapely.STRtree(parts).query_nearest(
            shapely.points(xs[rest], ys[rest]), max_distance=LAND_SNAP)
        ids[rest[src]] = dst
    return ids


# ---- ключи срезов ----------------------------------------------------------
def manifest_keys():
    with open(os.path.join(DATA, 'manifest.json'), encoding='utf-8') as f:
        return [str(k) for k in json.load(f)['years']]


def slice_keys():
    """Все ключи окна [WAR, END): свои и чужие, попавшие внутрь."""
    keys = {WAR}
    for y in range(1914, 1918):
        for m in range(1, 13):
            k = f'{y}-{m:02d}-01'
            if be.d(WAR) < be.d(k) < be.d(END):
                keys.add(k)
    keys.update(EVENT_KEYS)
    keys.update(k for k in manifest_keys()
                if be.d(WAR) <= be.key_date(k) < be.d(END))
    return sorted(keys, key=be.key_date)


def phase(key):
    d = be.key_date(key)
    if d < be.d('1915-04-19'):
        return 'манёвренная война 1914 - весна 1915'
    if d < be.d('1915-09-19'):
        return 'Горлицкий прорыв и Великое отступление 1915'
    if d < be.d('1916-05-22'):
        return 'позиционный фронт 1915-1916'
    if d < be.d('1917-06-18'):
        return 'Брусиловский прорыв и позиционный фронт 1916-1917'
    return 'отступление 1917'


SOURCE = (
    'КУРИРУЕМЫЙ СРЕЗ ПЕРВОЙ МИРОВОЙ (19.09.2026, tools/build_ww1.py): зона '
    'имперского контроля на дату по старому стилю. Линия фронта '
    'РЕКОНСТРУИРОВАНА по таблице городов-якорей data/crosscheck/ww1_cities.csv '
    '(дни взятия городов по «Стратегическому очерку войны 1914-1918 гг.», '
    'Зайончковскому и другим источникам таблицы) голосованием ближайших '
    'якорей с весом 1/d^3, сетка 0.05°; якорь голосует за свою землю, чужую '
    'делит, только когда взят. Это не оцифровка оперативных карт: между '
    'якорями линия идёт там, где её проводит формула. Контур-основа - '
    'довоенный срез 1914-04-04. Правила: германская и австрийская оккупация - '
    'не империя («контроль, а не акт»); российская военная оккупация '
    'Восточной Пруссии, Галиции, Буковины и Турецкой Армении - имперский '
    'контроль, красное (куратор 18.09.2026). Проверка - tools/check_ww1.py')

METHOD = (f'голосование {KNN}+{KNN} ближайших якорей двух сторон, вес '
          f'1/d^{POW:g}, сетка {STEP}°; невзятый якорь голосует только за '
          f'свою землю')


def build(key, fields):
    day = be.key_date(key)
    base = base_geom()
    lost_parts, occ_parts = [], []
    for fl in fields:
        bx = box(*fl.th['box'])
        lost_m, occ_m = fl.masks(day)
        if lost_m.any():
            lost_parts.append(fl.to_geom(lost_m).intersection(bx))
        if occ_m.any():
            occ_parts.append(fl.to_geom(occ_m).intersection(bx)
                             .intersection(abroad_mask(fl.th)))
    lost = unary_union(lost_parts).intersection(base) if lost_parts \
        else unary_union([])
    occ = unary_union(occ_parts).difference(base).buffer(0) if occ_parts \
        else unary_union([])
    geom = base.difference(lost).buffer(0) if not lost.is_empty else base
    if not occ.is_empty:
        geom = unary_union([geom, occ]).buffer(0)
    front = unary_union([g for g in (lost, occ) if not g.is_empty])
    if not front.is_empty:
        geom = local_finish(geom, front.buffer(HALO))
    abroad = geom.difference(base).area

    props = {'year': key, 'role': 'core', 'name': 'Российская империя',
             'reconstruction': True, 'approximate': True, 'expansion': True,
             'ww1': True, 'phase': phase(key), 'base': f'срез {BASE_KEY} '
             '(довоенный контур, tools/build_expansion.py)',
             'method': METHOD, 'style': 'даты по старому стилю',
             'anchors': sum(len(f.E) + len(f.F) for f in fields),
             'occupied_deg2': round(lost.area, 2),
             'abroad_deg2': round(abroad, 2),
             'added': [], 'removed': [], 'source': SOURCE}
    feats = [{'type': 'Feature', 'geometry': be._round(mapping(geom)),
              'properties': props}]
    return ({'type': 'FeatureCollection', 'features': feats},
            lost.area, abroad)


def local_finish(raw, zone):
    """geoclean.finish по всему срезу, но правки - только внутри zone (полоса
    у фронта). Вне её срез остаётся основой: полная чистка готового ядра
    отщепляла крошки, которых в основе нет (Каспий, Котельный, 21.09.2026)."""
    cleaned = gc.finish(raw, be.CACHE)
    rem = raw.difference(cleaned).intersection(zone)
    add = cleaned.difference(raw).intersection(zone)
    out = raw
    if not rem.is_empty:
        out = out.difference(rem)
    if not add.is_empty:
        out = out.union(add)
    return out.buffer(0)


def write_front_line(fields, keys):
    """Линия фронта отдельным файлом - пруф геометрии, в показ не идёт."""
    feats = []
    base = base_geom()
    for key in keys:
        day = be.key_date(key)
        for fl in fields:
            bx = box(*fl.th['box'])
            area = unary_union([base, abroad_mask(fl.th)]).intersection(bx)
            lost_m, occ_m = fl.masks(day)
            red = area.intersection(base)
            if lost_m.any():
                red = red.difference(fl.to_geom(lost_m))
            if occ_m.any():
                red = unary_union([red, fl.to_geom(occ_m).intersection(area)])
            line = red.boundary.difference(area.boundary.buffer(0.02))
            if line.is_empty:
                continue
            feats.append({'type': 'Feature',
                          'geometry': be._round(mapping(line.simplify(0.02))),
                          'properties': {'date': key, 'theatre': fl.th['name'],
                                         'phase': phase(key),
                                         'method': METHOD}})
    path = os.path.join(DATA, 'ww1_front.geojson')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': feats}, f,
                  ensure_ascii=False)
    print(f'OK data/ww1_front.geojson: линий {len(feats)}, '
          f'{os.path.getsize(path) // 1024} КБ')


def update_manifest(written):
    path = os.path.join(DATA, 'manifest.json')
    with open(path, encoding='utf-8') as f:
        mf = json.load(f)
    mf['years'] = sorted(set(map(str, mf['years'])) | set(written),
                         key=be.key_date)
    mf['note_ww1'] = (
        'окно 19.07.1914-25.12.1917 (ст. ст.) закрыто 19.09.2026 '
        f'(tools/build_ww1.py): {len(written)} срезов, первое число каждого '
        'месяца плюс Варшава 23.07.1915 и Рига 21.08.1917. Зона имперского '
        'контроля = довоенный контур минус занятое противником плюс занятое '
        'империей за границей (Восточная Пруссия, Галиция, Буковина, Турецкая '
        'Армения). Линия фронта РЕКОНСТРУИРОВАНА по таблице городов-якорей '
        '(data/crosscheck/ww1_cities.csv). Регрессия - tools/check_ww1.py')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj(mf), f, ensure_ascii=False, indent=1)
    print(f'OK data/manifest.json: срезов {len(mf["years"])}')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--only', help='собрать один срез (для отладки)')
    ap.add_argument('--dry-run', action='store_true',
                    help='считать, но не писать файлы')
    ap.add_argument('--anchors', default=ANCHORS,
                    help='другая таблица якорей (только с --dry-run/--preview)')
    ap.add_argument('--preview', metavar='DIR',
                    help='писать срезы в DIR, а не в data/years; манифест и '
                         'штамп не трогать')
    args = ap.parse_args()
    if args.anchors != ANCHORS and not (args.dry_run or args.preview):
        raise SystemExit('чужая таблица якорей - только с --dry-run/--preview')

    # всё проверить ДО первой записи: таблица, основа, маски, ключи
    anchors = load_anchors(args.anchors)
    by_th = {th['id']: sum(a['theatre'] == th['id'] for a in anchors)
             for th in THEATRES}
    print(f'якорей: {len(anchors)} ({", ".join(f"{k} {v}" for k, v in by_th.items())})')
    base_geom()
    for th in THEATRES:
        abroad_mask(th)
    fields = [Field(anchors, th) for th in THEATRES if by_th[th['id']]]
    for fl in fields:
        print(f'театр {fl.th["name"]}: сетка {fl.shape[1]}x{fl.shape[0]}, '
              f'якорей империи {len(fl.E)}, противника {len(fl.F)}')
    keys = [args.only] if args.only else slice_keys()

    written, total = [], 0
    for key in keys:
        fc, lost, occ = build(key, fields)
        if args.dry_run:
            print(f'   {key}  у противника {lost:6.2f} град²  занято за '
                  f'границей {occ:6.2f} град²  [{phase(key)}]')
            continue
        out_dir = args.preview or os.path.join(DATA, 'years')
        path = os.path.join(out_dir, key + '.geojson')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(gc.sanitize_obj(fc), f, ensure_ascii=False)
        kb = os.path.getsize(path) // 1024
        total += kb
        written.append(key)
        print(f'OK {os.path.relpath(path, bd.ROOT)}: {kb:4d} КБ, у противника '
              f'{lost:6.2f} град², за границей {occ:6.2f} град²  [{phase(key)}]')
    if args.dry_run or args.preview:
        return
    write_front_line(fields, keys)
    update_manifest(written)
    gc.write_stamp('ww1')
    print(f'срезов ПМВ: {len(written)}, суммарно {total} КБ')
    print('дальше: .venv/bin/python tools/check_ww1.py --anchors')


if __name__ == '__main__':
    main()
