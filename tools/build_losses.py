#!/usr/bin/env python3
"""Слой потерь имперского контроля НА СОБСТВЕННОЙ территории.

Зачем. Карта показывала расползание империи, но не показывала обратного
движения у неё дома. Курская операция, рейды 2023-2024 годов в Белгородской
области - всё это дни и месяцы, когда на куске территории,
который карта красит имперским красным, империи не было. Задача куратора
19.08.2026: над имперской территорией семантика переворачивается - там
«освобождено» значит ПОТЕРЯ имперского контроля, и рисовать это надо ВЫРЕЗОМ
из красного, а не зелёной заливкой поверх.

Что на входе.
1. data/deepstate/days/*.geojson - дневные снимки фронта. Общая сетка показа
   2022+ помесячная (решение куратора 19.08.2026), но здесь берём именно дни:
   потеря контроля у империи дома - редкое событие, и дата у него должна быть
   точной. Файлы все на диске, сеть не нужна.
   ВАЖНО: до 19.08.2026 украинский контроль внутри РФ выпадал из дневных
   файлов - DeepState красит его отдельным синим #01579b, а в FILL_STATUS
   этого цвета не было (см. tools/fetch_deepstate.py). Курский выступ в наших
   данных просто отсутствовал. Починено, дни пересобраны из кэша.
2. cache/cshapes20.geojson - контур РФ (gwcode 365). Берём интервал
   21.12.1991-17.03.2014, то есть РФ БЕЗ Крыма: Крым по нашей карте идёт
   отдельным слоем оккупированных территорий, и «освобождение» внутри Крыма -
   это украинская семантика, а не потеря империей своего.
3. cache/ne_admin1.geojson - области, чтобы назвать эпизод.
4. RAIDS ниже - курируемые записи о рейдах, которые DeepState зонами не
   рисовал вовсе.

Что на выходе.
- data/losses/<слаг>.geojson - по файлу на эпизод. Фичи с полями from/to
  (даты по дням, включительно), kind, name, source, note.
- data/losses/manifest.json - список эпизодов с окнами и источниками.

Правило отбора. Полигон дня считается потерей, если его статус не имперский
(lost / unknown / liberated) и не меньше половины его площади лежит
внутри контура РФ. Половина - чтобы отсечь украинские полигоны, которые у
DeepState на несколько сот метров заезжают за линию границы (у большого
«освобождённого» тыла Сумщины таких заездов на 0.0004 кв. градуса, это
артефакт рисования, а не потеря контроля). Дальше полигон обрезается по
контуру РФ: в слой идёт только имперская часть.

Запуск: .venv/bin/python tools/build_losses.py
"""
import csv
import glob
import json
import math
import os
import re
import sys
from datetime import date, timedelta

from shapely import affinity
from shapely.geometry import LineString, box, mapping, shape
from shapely.ops import unary_union

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import geoclean as gc
from shapely.prepared import prep

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'cache')
DAYS = os.path.join(ROOT, 'data', 'deepstate', 'days')
OUT = os.path.join(ROOT, 'data', 'losses')

# статусы дневных файлов, которые НА ТЕРРИТОРИИ РФ означают потерю контроля
LOSS_KIND = {
    'lost': 'lost',           # #01579b - контроль Украины внутри РФ
    # 'mutiny' (#ce93d8, мятеж ПВК «Вагнер» 24.06.2023) СОЗНАТЕЛЬНО НЕ ВКЛЮЧЁН:
    # решение куратора 19.08.2026 - «Вагнер те же имперцы, они ничем не
    # отличались». Междоусобицы имперцев мы не различаем (см. правило
    # empire-not-factions), поэтому мятеж не потеря контроля империей, а спор
    # внутри неё. Данные дневных файлов со статусом mutiny остаются на диске.
    'unknown': 'grey',        # серая зона: не контролирует никто
    'liberated': 'lost',      # зелёный внутри РФ (у DeepState почти не бывает)
}
KIND_RU = {
    'lost': 'вне имперского контроля (украинские силы)',
    'grey': 'серая зона: империя не контролирует',
    'raid': 'рейд: контроль часами-сутками',
    'contested': 'участок оспаривался, но империя его удержала',
    'occupation': 'занято: империя участком не распоряжалась',
    'self_rule': 'своя власть: империя землёй не распоряжалась',
}
# kind, который НЕ вырезается из красного (то же множество в index.html):
#   contested - империя тут удержалась, но участок был под ударом. Приписывать
#               взятие Грайворона, Шебекино, Тёткино или Петропавловска
#               незачем: они взяты не были;
#   raid      - контроль часами-сутками и геометрия условная (круг вокруг
#               города). Требование куратора 26.08.2026: набег не вырезает
#               красное, он живёт строкой в попапе. Дырка в карте означает
#               «участок держал кто-то другой», а набег - это не держание.
# Вырезает только occupation (и статусы фронта lost/grey над территорией РФ).
# ПРАВИЛО КУРАТОРА 28.08.2026: «убрать цветное не значит покрасить красным. там
# где было цветное должно быть черное. какая разница на час или на два - москву
# сожгли». Рейд теперь ВЫРЕЗАЕТ красное: если чужое войско вошло в город и
# сожгло его, империя этим местом в тот день не распоряжалась, сколько бы часов
# это ни длилось. Не вырезается только `contested` - там империя участок
# удержала (Молоди 1572, Петропавловский порт 1854, серые зоны 2023-2024).
NO_CUT = {'contested'}
MIN_FRAC = 0.5            # доля площади полигона внутри РФ
LINK_DEG = 0.5            # склейка полигонов в эпизод по расстоянию
LINK_GAP = 25             # склейка по времени, дней
SIMPLIFY = 0.002          # ~200 м: слой обзорный, точность линии не нужна
MIN_AREA = 2e-5           # ~0.25 кв. км: мельче - шум рисования

DS = 'DeepStateMAP, дневные снимки (deepstatemap.live)'

# Имена и пояснения для эпизодов, которые узнаются по первой дате. Всё
# остальное подписывается автоматически по области и дате.
# ---- курируемые таблицы: data/losses/losses_*.csv (27.09.2026) -------------
# EPISODE_META (эпизоды серой зоны DeepState), RAIDS (рейды 2023-2024), PRE20 с
# частями (досоветские потери контроля), NOT_CONFIRMED и PRE20_NOT_ENTERED
# (проверено и не заведено) живут в CSV - tools/losses_tables.py читает и
# проверяет их; там же описание колонок и форм geom. Имена файлов строками:
# по ним tools/rebuild.py (losses_sig) видит вход слоя.
CSV_FILES = ('losses_episodes.csv', 'losses_raids.csv', 'losses_pre20.csv',
             'losses_pre20_parts.csv', 'losses_rejected.csv')
import losses_tables as lt   # noqa: E402
EPISODE_META = lt.load('EPISODE_META')
RAIDS = lt.load('RAIDS')
NOT_CONFIRMED = lt.load('NOT_CONFIRMED')
PRE20 = lt.load('PRE20')
PRE20_NOT_ENTERED = lt.load('PRE20_NOT_ENTERED')

# --- Курируемые рейды -------------------------------------------------------
# Эпизоды, которые DeepState зонами не рисовал (или рисовал так, что сам
# населённый пункт в зону не попал). Геометрия УСЛОВНАЯ: круг вокруг посёлка,
# обозначение места, а не линия контроля. Даты - по источникам, перечисленным
# в source. Радиус - по здравому смыслу: 2.5-4 км на село, 5 км на посёлок.
#
# kind='raid' ставим только там, где заход В САМ населённый пункт подтверждён;
# где подтверждены обстрелы и бои на подступах, а город остался за империей -
# kind='contested', и из красного такой круг не вырезается. Соблазн покрасить
# Грайворон и Шебекино как взятые велик, но они взяты не были, и врать тут
# незачем: потеря контроля над Козинкой, Глотово и Новой Таволжанкой -
# подтверждённый факт и без этого.

# Эпизоды, которые проверялись и НЕ заводятся - чтобы не заводить их снова.


# ---- потери контроля ДО XX века -------------------------------------------
# Задача куратора 26.08.2026: «где война с наполеоном? он вроде москву сжег.
# где крымские войны? они вроде тоже сожгли москву». Слой потерь покрывал
# только 2022-2026, а до XX века не было ни одной записи - хотя по нашему же
# правилу (красное = империя тут распоряжалась) эти окна обязаны читаться
# вырезом из красного.
#
# Как устроено. Каждый эпизод - список кусков, у куска своё окно, свой kind и
# своя геометрия:
#   occupation - участком распоряжался кто-то другой недели и годы: ВЫРЕЗ из
#                красного. Геометрия обрезается контуром среза ядра на дату
#                начала - иначе кольцо выреза вылезет за полигон ядра и дырки
#                не получится (механизм cutCore в index.html);
#   raid       - набег, контроль часами-сутками, геометрия условная: НЕ
#                вырезает, живёт строкой в попапе;
#   contested  - до города дошли, но города не взяли: тоже не вырезает.
#
# Виды геометрии:
#   ('ne', admin, [названия]) - современные единицы Natural Earth admin-1
#     (та же условность, что у срезов расползания: современная нарезка - не
#     историческая губерния, а её приближение);
#   ('ne_box', admin, [названия], (minx, miny, maxx, maxy)) - то же с
#     обрезкой рамкой (южная сторона Севастополя);
#   ('box', (minx, miny, maxx, maxy)) - рамка (Сахалин южнее 50-й параллели);
#   ('circle', lon, lat, км) - условный круг: обозначение места, не линия
#   ('file', путь)            - курируемый geojson из OSM (см. part_geom)
#   ('path', [(lon, lat)...], км) - полоса вдоль маршрута войска
#     контроля.
#
# Стиль дат у каждого эпизода помечен в поле style и в тексте: до 1918 года
# источники дают то старый, то новый стиль, и смешивать их молча нельзя.
PRE20_KIND = 'curated-pre20'

MOSCOW = (37.6176, 55.7558)


# Проверено и НЕ заведено в слой потерь - с причиной, чтобы не заводить снова.


def dt(s):
    return date(*map(int, s.split('-')))


def rf_contour():
    """Контур РФ без Крыма: интервал CShapes 21.12.1991-17.03.2014."""
    with open(os.path.join(CACHE, 'cshapes20.geojson'), encoding='utf-8') as f:
        d = json.load(f)
    for feat in d['features']:
        p = feat['properties']
        if p.get('gwcode') != 365:
            continue
        s = (p['gwsyear'], p['gwsmonth'], p['gwsday'])
        e = (p['gweyear'], p['gwemonth'], p['gweday'])
        if s <= (2013, 1, 1) <= e:
            return shape(feat['geometry']).buffer(0)
    raise SystemExit('CShapes: не нашёл контур РФ на 2013 год')


def oblasts():
    """Области РФ: (имя по-русски, латиницей, геометрия) — подпись эпизода."""
    with open(os.path.join(CACHE, 'ne_admin1.geojson'), encoding='utf-8') as f:
        d = json.load(f)
    out = []
    for feat in d['features']:
        p = feat['properties']
        if p.get('admin') != 'Russia':
            continue
        nm = p.get('name_ru') or p.get('name')
        try:
            g = shape(feat['geometry']).buffer(0)
        except Exception:
            continue
        if not g.is_empty:
            out.append((nm, p.get('name') or nm, g))
    return out


def scan_days(rf):
    """day -> список (kind, обрезанная по РФ геометрия)."""
    prf = prep(rf)
    res = {}
    for fp in sorted(glob.glob(os.path.join(DAYS, '*.geojson'))):
        day = os.path.basename(fp)[:-8]
        with open(fp, encoding='utf-8') as f:
            g = json.load(f)
        hits = []
        for feat in g.get('features', []):
            kind = LOSS_KIND.get((feat.get('properties') or {}).get('s'))
            if not kind:
                continue
            try:
                geo = shape(feat['geometry']).buffer(0)
            except Exception:
                continue
            if geo.is_empty or not prf.intersects(geo):
                continue
            inter = geo.intersection(rf)
            if inter.is_empty or geo.area <= 0:
                continue
            if inter.area / geo.area < MIN_FRAC or inter.area < MIN_AREA:
                continue
            hits.append((kind, inter))
        if hits:
            res[day] = hits
    return res


def episodes(byday):
    """Склейка полигонов в эпизоды: рядом в пространстве и во времени."""
    eps = []
    for day in sorted(byday):
        d = dt(day)
        for kind, geo in byday[day]:
            c = geo.representative_point()
            hit = None
            for e in eps:
                if (d - e['last']).days > LINK_GAP:
                    continue
                if (abs(e['cx'] - c.x) < LINK_DEG
                        and abs(e['cy'] - c.y) < LINK_DEG):
                    hit = e
                    break
            if hit is None:
                eps.append({'cx': c.x, 'cy': c.y, 'n': 1,
                            'first': d, 'last': d, 'days': {day: [(kind, geo)]}})
            else:
                hit['days'].setdefault(day, []).append((kind, geo))
                hit['last'] = max(hit['last'], d)
                hit['n'] += 1
                hit['cx'] += (c.x - hit['cx']) / hit['n']
                hit['cy'] += (c.y - hit['cy']) / hit['n']
    eps.sort(key=lambda e: (e['first'], -len(e['days'])))
    return eps


def merge_neighbours(eps):
    """Слить эпизоды, начавшиеся в один день рядом друг с другом.

    Мартовские рейды 2024 идут тремя пятнами вдоль границы на 130 км - это
    один сюжет, а не три; курский выступ и отпочковавшиеся от него серые
    пятна - тоже один. Склеиваем по совпадению стартового дня и пересечению
    окон, лишь бы пятна были на одном участке границы (5 градусов).
    """
    out = []
    for e in eps:
        tgt = None
        for o in out:
            if o['first'] != e['first']:
                continue
            if abs(o['cx'] - e['cx']) < 5 and abs(o['cy'] - e['cy']) < 5:
                tgt = o
                break
        if tgt is None:
            out.append(e)
            continue
        for day, hits in e['days'].items():
            tgt['days'].setdefault(day, []).extend(hits)
        tgt['last'] = max(tgt['last'], e['last'])
    return out


def name_for(e, obl):
    """Область(и), которых касается эпизод: (по-русски, латиницей)."""
    u = unary_union([g for hits in e['days'].values() for _, g in hits])
    hits = [(nm, en, g.intersection(u).area) for nm, en, g in obl
            if g.intersects(u)]
    big = [(nm, en) for nm, en, a in hits if a > 0.05 * u.area]
    return big or [(nm, en) for nm, en, _ in hits]


def daily_features(e, meta):
    """Фичи эпизода: по одной на каждый отрезок, где геометрия не менялась."""
    feats = []
    days = sorted(e['days'])
    prev_wkt = None
    cur = None
    for i, day in enumerate(days):
        hits = e['days'][day]
        kinds = {k for k, _ in hits}
        kind = ('lost' if 'lost' in kinds
                else 'grey')
        geo = unary_union([g for _, g in hits]).simplify(SIMPLIFY)
        if geo.is_empty:
            continue
        wkt = geo.wkt
        # день без снимка внутри эпизода: окно предыдущей фичи тянется до
        # кануна следующего снимка, дырок в показе не остаётся
        if cur is not None and wkt == prev_wkt:
            cur['properties']['to'] = day
            continue
        if cur is not None:
            cur['properties']['to'] = (dt(day) - timedelta(days=1)).isoformat()
        cur = {'type': 'Feature',
               'properties': {'from': day, 'to': day, 'kind': kind,
                              'name': meta['name'], 'kind_ru': KIND_RU[kind],
                              'episode': meta['slug'],
                              'note': meta['note'], 'source': meta['source']},
               'geometry': mapping(geo)}
        feats.append(cur)
        prev_wkt = wkt
    return feats


def circle(lon, lat, km, n=40):
    """Условный круг вокруг точки: обозначение места, не линия контроля."""
    import math
    dlat = km / 111.32
    dlon = km / (111.32 * math.cos(math.radians(lat)))
    pts = [(round(lon + dlon * math.cos(2 * math.pi * i / n), 4),
            round(lat + dlat * math.sin(2 * math.pi * i / n), 4))
           for i in range(n)]
    pts.append(pts[0])
    return {'type': 'Polygon', 'coordinates': [pts]}


RAID_NOTE = ('рейд, контроль часами-сутками; геометрия условная - обозначение '
             'места, не линия контроля')


def build_raids():
    feats = []
    for r in RAIDS:
        kind = r['kind']
        feats.append({
            'type': 'Feature',
            'properties': {
                'from': r['frm'], 'to': r['to'], 'kind': kind,
                'kind_ru': KIND_RU[kind], 'name': r['name'],
                'episode': 'raids-curated', 'key': r['key'],
                'note': r['note'], 'geometry_note': RAID_NOTE,
                'source': r['source'],
            },
            'geometry': circle(r['lon'], r['lat'], r['km']),
        })
    return feats


# ---- геометрия эпизодов до XX века ----------------------------------------
YEARS = os.path.join(ROOT, 'data', 'years')
PRE20_SIMPLIFY = 0.005     # ~500 м: слой обзорный
PRE20_MIN_AREA = 5e-4      # ~6 кв. км: мельче - заусенцы обрезки
_p20 = {}


def ne_pick(admin, names):
    """Современные единицы Natural Earth admin-1 - как в build_expansion.py."""
    if '__ne' not in _p20:
        with open(os.path.join(CACHE, 'ne_admin1.geojson'), encoding='utf-8') as f:
            _p20['__ne'] = json.load(f)['features']
    feats = [f for f in _p20['__ne'] if f['properties'].get('admin') == admin]
    if names is not None:
        sel = [f for f in feats if f['properties'].get('name') in names]
        missing = set(names) - {f['properties'].get('name') for f in sel}
        if missing:
            raise SystemExit(f'NE admin-1: не найдены единицы {sorted(missing)} '
                             f'({admin})')
        feats = sel
    if not feats:
        raise SystemExit(f'NE admin-1: пустая выборка {admin} {names}')
    return unary_union([shape(f['geometry']).buffer(0) for f in feats])


def key_date(key):
    """Ключ среза -> дата, с которой он показывается (как parseKey в карте)."""
    p = key.split('-')
    return date(int(p[0]), int(p[1]) if len(p) > 1 else 1,
                int(p[2]) if len(p) > 2 else 1)


def slice_key_at(d):
    """Последний срез ядра не позже даты - тем же правилом, что и в показе.

    Ключи берём ИЗ МАНИФЕСТА, а не сканированием каталога (29.08.2026). В
    data/years лежат тринадцать осиротевших файлов прежних сборок (1900, 1918,
    1938, 1994, 2000, 2010 и другие), которых нет в manifest.json: карта их не
    показывает, а glob находил. Для Курской операции сборщик из-за этого
    дотягивал вырез до границы среза 2010, тогда как карта рисует красное по
    срезу 1992, и между двумя линиями границы вдоль всей границы оставалась
    красная полоса - за спиной прорвавшихся. Куратор: «полосочки остаются за
    спинами украинцев, которые прорвались, заняли Суджу».
    """
    if '__keys' not in _p20:
        with open(os.path.join(ROOT, 'data', 'manifest.json'),
                  encoding='utf-8') as f:
            keys = [str(k) for k in json.load(f)['years']]
        _p20['__keys'] = sorted(
            (key_date(k), k) for k in keys
            if os.path.exists(os.path.join(YEARS, k + '.geojson')))
    best = None
    for kd, key in _p20['__keys']:
        if kd <= d:
            best = key
    if best is None:
        raise SystemExit(f'нет среза ядра на {d}: покрытие начинается позже')
    return best


def core_slice(key):
    tag = '__core' + key
    if tag not in _p20:
        with open(os.path.join(YEARS, key + '.geojson'), encoding='utf-8') as f:
            d = json.load(f)
        _p20[tag] = unary_union([shape(x['geometry']).buffer(0)
                                 for x in d['features']]).buffer(0)
    return _p20[tag]


_routes = {}


def route_points(seg):
    """Точки отрезка маршрута из data/losses/routes.csv, по порядку.

    Колонки: segment, seq, place, lat, lon, source, confidence, note.
    Таблица курируется руками; каждая точка обязана иметь источник.
    """
    if not _routes:
        path = os.path.join(ROOT, 'data', 'losses', 'routes.csv')
        with open(path, encoding='utf-8') as fh:
            for r in csv.DictReader(fh):
                if not r['source'].strip():
                    raise SystemExit('routes.csv: точка без источника - '
                                     + r['segment'] + ' / ' + r['place'])
                _routes.setdefault(r['segment'], []).append(
                    (int(r['seq']), float(r['lon']), float(r['lat'])))
        for key in _routes:               # НЕ seg: цикл перетирал бы параметр
            _routes[key].sort()
    if seg not in _routes:
        raise SystemExit(f'routes.csv: нет отрезка «{seg}»')
    return [(lon, lat) for _, lon, lat in _routes[seg]]


def part_geom(specs):
    parts = []
    for spec in specs:
        kind = spec[0]
        if kind == 'ne':
            parts.append(ne_pick(spec[1], spec[2]))
        elif kind == 'ne_box':
            parts.append(ne_pick(spec[1], spec[2]).intersection(box(*spec[3])))
        elif kind == 'box':
            parts.append(box(*spec[1]))
        elif kind == 'circle':
            parts.append(shape(circle(spec[1], spec[2], spec[3], n=64)))
        elif kind == 'route':
            # ('route', 'ключ-отрезка', км) - полоса по точкам из
            # data/losses/routes.csv. Заведено 28.08.2026 по требованию
            # куратора «ищи пруфы, ищи карты, ищи документы»: у каждой точки
            # маршрута своя строка с названием места, привязкой, источником и
            # оценкой уверенности, а не безымянная координата в коде.
            pts = route_points(spec[1])
            lat0 = sum(y for _, y in pts) / len(pts)
            k = math.cos(math.radians(lat0))
            line = LineString([(x * k, y) for x, y in pts])
            band = line.buffer(spec[2] / 111.32, resolution=8)
            parts.append(affinity.scale(band, xfact=1 / k, yfact=1,
                                        origin=(0, 0)))
        elif kind == 'path':
            # ('path', [(lon, lat), ...], км) - полоса вдоль маршрута войска.
            # Заведено 28.08.2026 по втыку куратора: набор кружков читался как
            # «войска телепортировались и попали в котлы». Ширина в километрах
            # переводится в градусы через косинус средней широты, чтобы полоса
            # не расползалась по долготе.
            pts = spec[1]
            lat0 = sum(y for _, y in pts) / len(pts)
            k = math.cos(math.radians(lat0))
            line = LineString([(x * k, y) for x, y in pts])
            band = line.buffer(spec[2] / 111.32, resolution=8)
            parts.append(affinity.scale(band, xfact=1 / k, yfact=1,
                                        origin=(0, 0)))
        elif kind == 'file':
            # курируемая геометрия из OpenStreetMap: нарезки такого уровня в
            # Natural Earth нет (Аяно-Майский район, буферные зоны Грузии,
            # Таймыр). Файл лежит в data/, источник записан в его properties.
            with open(os.path.join(ROOT, spec[1]), encoding='utf-8') as fh:
                fc = json.load(fh)
            parts.append(unary_union([shape(f['geometry']).buffer(0)
                                      for f in fc['features']]))
        else:
            raise SystemExit(f'неизвестный вид геометрии: {spec}')
    g = unary_union(parts).buffer(0)
    if g.is_empty:
        raise SystemExit(f'пустая геометрия куска: {specs}')
    return g


def drop_crumbs(g, min_area=PRE20_MIN_AREA):
    polys = list(g.geoms) if g.geom_type == 'MultiPolygon' else [g]
    keep = [p for p in polys if p.area >= min_area]
    return unary_union(keep) if keep else None


def rnd(obj, nd=4):
    if isinstance(obj, (list, tuple)):
        return [rnd(x, nd) for x in obj]
    if isinstance(obj, float):
        return round(obj, nd)
    return obj


_snap_cache = {}


def snap_to_core_border(g, core, d=0.09):
    """Дотягивает вырез до НАШЕЙ линии границы.

    ЗАЧЕМ (28.08.2026). Курский выступ нарисован по линии границы DeepState, а
    ядро у нас идёт контуром CShapes 1992 года. Линии расходятся на 4-8 км, и
    между выступом и краем красного оставалась полоса имперской земли: на карте
    выходило, что украинцы прошли границу насквозь и сразу попали в котёл, а на
    самой границе кто-то остался. Было не так - границу снесли.

    Общая граница выреза с контуром была 8.4 км при фронте прорыва в десятки.
    Здесь мы приращиваем к вырезу полосу ядра, которая лежит и рядом с вырезом
    (не дальше `d`), и рядом с границей (не дальше `d`). Вглубь империи вырез
    от этого не растёт: полоса привязана к линии границы.
    """
    # граница контура и её буфер зависят только от среза ядра, а зовут нас
    # на каждую фичу эпизода (у kursk-2024 их 89): кэш по id(core) - сами
    # контуры живут в кэше _p20, их id стабильны на протяжении прогона
    tag = (id(core), d)
    if tag not in _snap_cache:
        b0 = core.boundary
        _snap_cache[tag] = (b0, b0.buffer(d))
    b, b_buf = _snap_cache[tag]
    if g.distance(b) > d:
        return g
    band = core.intersection(g.buffer(d)).intersection(b_buf)
    if band.is_empty:
        return g
    out = unary_union([g, band]).buffer(0)
    parts = list(out.geoms) if out.geom_type == 'MultiPolygon' else [out]
    keep = [p for p in parts if p.intersects(g)]
    return unary_union(keep).buffer(0) if keep else g


def build_pre20():
    """Курируемые эпизоды до XX века: по файлу на эпизод + строки манифеста."""
    out = []
    for ep in PRE20:
        feats = []
        for part in ep['parts']:
            g = part_geom(part['geom'])
            cut = part['kind'] not in NO_CUT
            props = {
                'from': part['frm'], 'to': part['to'], 'kind': part['kind'],
                'kind_ru': KIND_RU[part['kind']], 'name': part['name'],
                'episode': ep['slug'], 'note': part['note'],
                'source': ep['source'], 'confidence': ep['confidence'],
                'style': ep['style'],
            }
            if cut:
                # вырез обязан лежать ВНУТРИ полигона ядра: cutCore в
                # index.html вставляет его кольцом внутрь того полигона, что
                # его содержит. Обрезаем контуром среза, действующего на дату
                # начала - тем же правилом, каким показ выбирает срез.
                key = slice_key_at(dt(part['frm']))
                clipped = drop_crumbs(g.intersection(core_slice(key)))
                if clipped is None or clipped.is_empty:
                    # в обзорный контур участок не попадает вовсе (узкая коса,
                    # острова): вырезать нечего, оставляем отметку места
                    props['outside_core'] = True
                    props['geometry_note'] = (
                        'участок в обзорный контур среза ' + key + ' не '
                        'попадает: вырезать нечего, круг работает отметкой '
                        'места')
                else:
                    g = clipped
                    props['clip'] = key
                    props['geometry_note'] = (
                        'геометрия обрезана контуром среза ' + key)
            else:
                props['geometry_note'] = (
                    'геометрия условная: обозначение места, не линия контроля')
            g = g.simplify(PRE20_SIMPLIFY)
            if props.get('clip'):
                # упрощение на 500 м выносит кромку за подробный берег OSM
                # (26.09.2026: Севастополь 1855 торчал из среза на 1,05 %) -
                # обрезаем тем же срезом ещё раз, уже после упрощения
                g = g.intersection(core_slice(props['clip'])).buffer(0)
            feats.append({'type': 'Feature', 'properties': props,
                          'geometry': gc.clean_rings(rnd(mapping(g)))})
        size = write(os.path.join(OUT, ep['slug'] + '.geojson'), feats)
        out.append({
            'slug': ep['slug'], 'name': ep['name'],
            'from': min(f['properties']['from'] for f in feats),
            'to': max(f['properties']['to'] for f in feats),
            'days': None, 'features': len(feats),
            'regions': [], 'kind': PRE20_KIND,
            'kinds': sorted({f['properties']['kind'] for f in feats}),
            'style': ep['style'], 'confidence': ep['confidence'],
            'note': ' | '.join(f['properties']['name'] + ': '
                               + f['properties']['kind_ru'] for f in feats),
            'source': ep['source'],
        })
        print(f'  {ep["slug"]:28s} {out[-1]["from"]} .. {out[-1]["to"]}  '
              f'кусков {len(feats)}  {size // 1024} КБ  '
              f'{", ".join(out[-1]["kinds"])}')
    return out


def write(path, feats):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj({'type': 'FeatureCollection', 'features': feats}), f,
                  ensure_ascii=False, separators=(',', ':'))
    return os.path.getsize(path)


def main():
    os.makedirs(OUT, exist_ok=True)
    mpath = os.path.join(OUT, 'manifest.json')
    # --pre20: пересобрать ТОЛЬКО курируемые эпизоды до XX века, не трогая
    # разбор 1514 дневных снимков DeepState (он идёт минуты) и не переписывая
    # уже собранные эпизоды 2022+. Строки манифеста для них берутся из самого
    # манифеста, файлы на диске остаются как есть.
    if '--pre20' in sys.argv[1:]:
        with open(mpath, encoding='utf-8') as f:
            prev = json.load(f)
        manifest = [e for e in prev.get('episodes', [])
                    if e.get('kind') != PRE20_KIND]
        print(f'--pre20: эпизоды 2022+ не трогаем ({len(manifest)} шт.)')
        manifest += build_pre20()
        write_manifest(mpath, manifest)
        return

    rf = rf_contour()
    obl = oblasts()
    byday = scan_days(rf)
    print(f'дней с потерями на территории РФ: {len(byday)}')
    eps = merge_neighbours(episodes(byday))

    manifest = []
    used = set()
    for e in eps:
        first = e['first'].isoformat()
        meta = dict(EPISODE_META.get(first, {}))
        pairs = name_for(e, obl)
        regions = [ru for ru, _ in pairs]
        if not meta:
            reg = regions[0] if regions else 'территория РФ'
            en = pairs[0][1] if pairs else 'rf'
            meta = dict(
                slug=re.sub(r'[^a-z0-9]+', '-', en.lower()).strip('-') or 'rf',
                name=f'{reg}: серая зона с {first}',
                note='Серая зона DeepState на территории РФ: империя участок не '
                     'контролирует. Отдельного разбора эпизода нет.',
                source=DS)
            meta['slug'] += '-' + first[:7]
        slug = meta['slug']
        while slug in used:
            slug += '-2'
        used.add(slug)
        meta['slug'] = slug
        feats = daily_features(e, meta)
        if not feats:
            continue
        # дотягиваем вырезы до нашей линии границы - см. snap_to_core_border
        snapped = 0
        for f in feats:
            pr = f['properties']
            if pr.get('kind') in NO_CUT:
                continue
            try:
                g0 = shape(f['geometry']).buffer(0)
                core = core_slice(slice_key_at(dt(pr['from'])))
                g1 = snap_to_core_border(g0, core)
            except Exception:                            # noqa: BLE001
                continue
            if g1.area > g0.area * 1.0001:
                f['geometry'] = gc.clean_rings(rnd(mapping(g1)))
                snapped += 1
        if snapped:
            print(f'    граница подтянута у {snapped} из {len(feats)} фич')
        # последняя фича эпизода: окно до последнего снимка эпизода
        feats[-1]['properties']['to'] = e['last'].isoformat()
        size = write(os.path.join(OUT, slug + '.geojson'), feats)
        manifest.append({
            'slug': slug, 'name': meta['name'],
            'from': first, 'to': e['last'].isoformat(),
            'days': len(e['days']), 'features': len(feats),
            'regions': regions, 'kind': 'deepstate',
            'note': meta['note'], 'source': meta['source'],
        })
        print(f'  {slug:28s} {first} .. {e["last"]}  '
              f'дней {len(e["days"]):4d}  фич {len(feats):4d}  {size // 1024} КБ'
              f'  {", ".join(regions)}')

    raids = build_raids()
    size = write(os.path.join(OUT, 'raids-curated.geojson'), raids)
    manifest.append({
        'slug': 'raids-curated', 'name': 'Рейды на территорию РФ (курируемо)',
        'from': min(r['properties']['from'] for r in raids),
        'to': max(r['properties']['to'] for r in raids),
        'days': None, 'features': len(raids), 'regions': ['Белгородская область'],
        'kind': 'curated', 'note': RAID_NOTE,
        'source': 'см. поле source у каждой записи',
    })
    print(f'  {"raids-curated":28s} курируемых рейдов {len(raids)}  '
          f'{size // 1024} КБ')

    manifest += build_pre20()
    write_manifest(os.path.join(OUT, 'manifest.json'), manifest)
    gc.write_stamp('losses')


def write_manifest(path, manifest):
    manifest = sorted(manifest, key=lambda e: (e['from'], e['slug']))
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj({
            'note': 'Потери имперского контроля на территории самой империи. '
                    'Над территорией РФ семантика фронта перевёрнута: '
                    '«освобождено» = империя участок не держит, рисуется '
                    'вырезом из красного. Внутри Украины семантика прежняя.',
            'note_dates': 'даты по ДНЯМ (общая сетка периода 2022+ помесячная, '
                          'здесь исключение - решение куратора 19.08.2026); '
                          'окно from..to включительно',
            'note_rf': 'принадлежность к территории РФ - по контуру CShapes 2.0 '
                       'gwcode 365, интервал 21.12.1991-17.03.2014 (РФ без '
                       'Крыма: Крым идёт отдельным слоем оккупированных '
                       'территорий)',
            'note_raids': RAID_NOTE,
            'note_pre20': 'эпизоды до XX века (kind ' + PRE20_KIND + ') '
                          'курируемые: occupation вырезает красное и обрезан '
                          'контуром среза ядра, raid и contested не вырезают и '
                          'живут строкой в попапе. Стиль дат - в поле style у '
                          'каждого эпизода',
            'not_confirmed': NOT_CONFIRMED,
            'pre20_not_entered': PRE20_NOT_ENTERED,
            'episodes': manifest,
        }), f, ensure_ascii=False, indent=1)
    print(f'эпизодов: {len(manifest)}')


if __name__ == '__main__':
    main()
