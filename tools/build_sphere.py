#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Слой советской сферы влияния из КУРИРУЕМОЙ ТАБЛИЦЫ с источниками.

Задача куратора 26.08.2026: «давай ищи источники. и заполняй все в таблицу
чтобы оно адекватно отображалось, когда кто что почему». До этой правки сфера
жила списком «страна, год_с, год_по» прямо в `tools/build_data.py` (SPHERE) —
собранным навскидку, без единой ссылки, с упрощёнными датировками, без Южного
Йемена и с единым Вьетнамом на 1954–1976 (государств было два).

Теперь источник данных один: `data/sphere/registry.csv` — СТРОКА НА ЭПИЗОД
ОТНОШЕНИЙ, а не на страну. У страны эпизодов может быть несколько: Египет
1955–1972 (помощь и советники) и 1972–1976 (договор ещё действует, советников
уже нет); Сомали 1969–1974 (присутствие), 1974–1977 (договор) — и разрыв.

Колонки таблицы:

    country,country_ru,iso3,from,to,kind,event_from,event_to,source,
    confidence,note

  from / to      — ISO-дата ГГГГ-ММ-ДД (пустой `to` = эпизод не закрыт);
  kind           — тип зависимости из закрытого списка KINDS (см. ниже);
  event_from/to  — ЧТО произошло: подписан договор, введены войска, разорваны
                   отношения, выведена база. Словами, кратко;
  source         — конкретная ссылка или библиография, не «общее знание»;
  confidence     — high (договор/документ), medium (справочная литература),
                   low (оценка).

ГЕОМЕТРИЯ — ТОЛЬКО МАШИНОЧИТАЕМАЯ, ничего не рисуется от руки. Контур страны
ищется по iso3 в словаре GEOM:

  `cs:<gwcode>`      — CShapes 2.0 (`cache/cshapes20.geojson`), исторические
                       границы по датам. Отсюда берутся государства, которых
                       сегодня нет: НДРЙ (gwcode 680, 30.11.1967–21.05.1990),
                       ДРВ/Северный Вьетнам (816, 01.05.1954–30.04.1975), ГДР
                       (265), Чехословакия (315), Югославия (345);
  `hb:<год>:<NAME>`  — historical-basemaps, срез года (Маньчжурия 1945:
                       отдельной страной её не знает ни CShapes, ни ISO);
  `ne1:<admin>:<a|b>` — Natural Earth admin-1, объединение единиц. Так взята
                       СОВЕТСКАЯ ЗОНА Австрии: страна целиком тут неверна,
                       зона была восточной третью.

Окно эпизода РЕЖЕТСЯ интервалами источника контуров: если у CShapes внутри
эпизода граница менялась, на выходе будет несколько фич с одной и той же
подписью эпизода, но разной геометрией и своими под-окнами `gfrom`/`gto`.
Так Египет 1955–1972 показан с Синаем до 09.06.1967 и без него после, а не
одним контуром на семнадцать лет.

Запуск (из корня репозитория):

    .venv/bin/python tools/build_sphere.py
    .venv/bin/python tools/build_sphere.py --report   # + разбор по kind

Пишет `data/sphere.geojson`. `tools/build_data.py` больше сферу не собирает —
он вызывает этот модуль (иначе прогон конвейера затирал бы таблицу черновиком).
Регрессия — `tools/check_sphere.py`.
"""
import argparse
import csv
import json
import os
import sys

from shapely.geometry import shape, mapping
from shapely.ops import unary_union

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import geoclean as gc

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(ROOT, 'cache')
OUT = os.path.join(ROOT, 'data')
CSV_PATH = os.path.join(OUT, 'sphere', 'registry.csv')

SIMPLIFY = 0.05          # градуса, как в слое атрибуции
DIGITS = 3
# Упрощение съедает малые государства целиком: у Сан-Томе и Принсипи с допуском
# 0.05° точка столицы выпадает из собственного контура, у Гренады наоборот
# появляется там, где суши нет. Контуры площадью меньше NO_SIMPLIFY (кв. градуса)
# идут в слой как есть — на весе файла это не сказывается, островов мало.
NO_SIMPLIFY = 5.0

# Закрытый список типов зависимости. Описан в README, разделе «Сфера влияния».
KINDS = {
    'occupation': 'оккупационная зона',
    'bloc': 'блок: ОВД или СЭВ, войска на территории',
    'client_treaty': 'договор о дружбе и сотрудничестве с военной статьёй',
    'client_military': 'военное присутствие: база, советники',
    'client_aid': 'военная и экономическая помощь, присутствия нет',
    'intervention': 'прямая военная интервенция',
}
CONF = ('high', 'medium', 'low')

# iso3 -> откуда брать контур. Коды ISO 3166-1 alpha-3, для исчезнувших
# государств — ISO 3166-3 в трёхбуквенном виде (DDR — ГДР, YMD — НДРЙ,
# CSK — Чехословакия, YUG — Югославия), для того, чего в ISO нет вообще:
# VDR — ДРВ (Северный Вьетнам), MCH — Маньчжурия, AUT-SU — советская зона
# Австрии (страна целиком тут неверна).
GEOM = {
    # Европа и блок
    'DDR': 'cs:265',
    'POL': 'cs:290',
    'CSK': 'cs:315',
    'HUN': 'cs:310',
    'ROU': 'cs:360',
    'BGR': 'cs:355',
    'ALB': 'cs:339',
    'YUG': 'cs:345',
    'FIN': 'cs:375',
    'AUT-SU': 'ne1:Austria:Niederösterreich|Burgenland|Wien',
    # Азия
    'MNG': 'cs:712',
    'PRK': 'cs:731',
    'CHN': 'cs:710',
    'MCH': 'hb:1945:Manchuria',
    'VDR': 'cs:816',
    'VNM': 'cs:816',
    'LAO': 'cs:812',
    'KHM': 'cs:811',
    'AFG': 'cs:700',
    'IND': 'cs:750',
    'BGD': 'cs:771',
    'MMR': 'cs:775',
    'IDN': 'cs:850',
    # Ближний Восток
    'IRQ': 'cs:645',
    'SYR': 'cs:652',
    'EGY': 'cs:651',
    'YMD': 'cs:680',
    'YEM': 'cs:678',
    'LBY': 'cs:620',
    'DZA': 'cs:615',
    'ISR': 'cs:666',
    # Африка
    'SOM': 'cs:520',
    'ETH': 'cs:530',
    'AGO': 'cs:540',
    'MOZ': 'cs:541',
    'COG': 'cs:484',
    'BEN': 'cs:434',
    'MDG': 'cs:580',
    'GIN': 'cs:438',
    'MLI': 'cs:432',
    'GNB': 'cs:404',
    'CAF': 'cs:482',
    'BFA': 'cs:439',
    'NER': 'cs:436',
    'SDN': 'cs:625',
    'MRT': 'cs:435',
    'GHA': 'cs:452',
    'CPV': 'cs:402',
    'GNQ': 'cs:411',
    'ZMB': 'cs:551',
    'TZA': 'cs:510',
    'UGA': 'cs:500',
    'ZWE': 'cs:552',
    # Кого CShapes 2.0 не знает вовсе — современный контур Natural Earth
    # admin-1 целиком. Границы этих четверых внутри их окон не менялись.
    'STP': 'ne1:Sao Tome and Principe:*',
    'SYC': 'ne1:Seychelles:*',
    'ESH': 'ne1:Western Sahara:*',
    'GRD': 'ne1:Grenada:*',
    # Латинская Америка
    'CUB': 'cs:40',
    'NIC': 'cs:93',
    'VEN': 'cs:101',
    'PER': 'cs:135',
    'CHL': 'cs:155',
    'GUY': 'cs:110',
}

# Горизонт карты: незакрытые эпизоды тянутся до него. Сам `to` в свойствах
# остаётся ПУСТЫМ — попап пишет «по сегодня», а не выдуманную дату.
HORIZON = '2026-12-31'
# У CShapes 2.0 покрытие кончается 31.12.2019. Для окон 2020+ берём последний
# интервал: границы Мали, Нигера и ЦАР с тех пор не менялись.
CS_END = '2019-12-31'

_cache = {}


def d2t(s):
    """'1979-12-25' -> (1979, 12, 25); пустая строка -> None."""
    s = (s or '').strip()
    if not s:
        return None
    p = [int(x) for x in s.split('-')]
    while len(p) < 3:
        p.append(1)
    return tuple(p[:3])


def load_cshapes():
    if 'cs' not in _cache:
        with open(os.path.join(CACHE, 'cshapes20.geojson'), encoding='utf-8') as f:
            _cache['cs'] = json.load(f)['features']
    return _cache['cs']


def load_hb(year):
    key = f'hb{year}'
    if key not in _cache:
        with open(os.path.join(CACHE, f'world_{year}.geojson'), encoding='utf-8') as f:
            _cache[key] = json.load(f)['features']
    return _cache[key]


def load_ne1():
    if 'ne1' not in _cache:
        with open(os.path.join(CACHE, 'ne_admin1.geojson'), encoding='utf-8') as f:
            _cache['ne1'] = json.load(f)['features']
    return _cache['ne1']


def cs_intervals(gwcode):
    """-> [(from, to, geometry)] по возрастанию, даты строками ISO."""
    out = []
    for f in load_cshapes():
        p = f['properties']
        if p.get('gwcode') != gwcode:
            continue
        a = f"{p['gwsyear']:04d}-{p['gwsmonth']:02d}-{p['gwsday']:02d}"
        b = f"{p['gweyear']:04d}-{p['gwemonth']:02d}-{p['gweday']:02d}"
        out.append((a, b, f['geometry']))
    return sorted(out)


def geom_slices(spec, frm, to):
    """Геометрия эпизода, порезанная интервалами источника контуров.

    -> [(gfrom, gto, shapely-геометрия, подпись источника)]
    """
    to = to or HORIZON
    kind, _, rest = spec.partition(':')
    if kind == 'cs':
        gw = int(rest)
        ivs = cs_intervals(gw)
        if not ivs:
            raise SystemExit(f'CShapes: нет gwcode {gw}')
        out = []
        for a, b, g in ivs:
            lo, hi = max(a, frm), min(b, to)
            if lo > hi:
                continue
            out.append((lo, hi, shape(g), f'CShapes 2.0, gwcode {gw} ({a}..{b})'))
        if not out:
            # Окно целиком вне интервалов источника. Два случая, и оба реальны:
            #  * покрытие CShapes кончается 31.12.2019, а эпизод идёт дальше;
            #  * ГОСУДАРСТВА БОЛЬШЕ НЕТ, а присутствие продолжалось — Западная
            #    группа войск стояла на востоке Германии до 31.08.1994, хотя
            #    контур ГДР у CShapes кончается 02.10.1990.
            # До 28.08.2026 второй случай не обрабатывался вовсе: строка молча
            # выпадала из слоя, и это заметила только регрессия по Лейпцигу.
            if frm > ivs[-1][1]:
                a, b, g = ivs[-1]
                why = (f'покрытие источника кончается {CS_END}' if b >= CS_END
                       else f'государства с {b} у источника больше нет, '
                            f'а присутствие продолжалось')
                out.append((frm, to, shape(g),
                            f'CShapes 2.0, gwcode {gw} (последний контур '
                            f'{a}..{b}; {why})'))
            elif to < ivs[0][0]:
                a, b, g = ivs[0]
                out.append((frm, to, shape(g),
                            f'CShapes 2.0, gwcode {gw} (первый контур {a}..{b}; '
                            f'раньше {a} источник государства не знает)'))
        elif out[-1][1] < to:
            # хвост, которого у источника нет: интервал государства кончился
            # раньше эпизода (НДРЙ исчезает 21.05.1990) или кончилось само
            # покрытие CShapes (31.12.2019, а Мали и Нигер идут дальше).
            # Тянем последний известный контур — своего у него всё равно нет.
            lo, hi, g, s = out.pop()
            why = (f'продлён за {CS_END} — покрытие источника кончается там'
                   if hi >= CS_END else f'продлён с {hi} до конца эпизода')
            out.append((lo, to, g, s + '; ' + why))
        return out
    if kind == 'hb':
        year, _, name = rest.partition(':')
        for f in load_hb(int(year)):
            p = {k.upper(): v for k, v in (f.get('properties') or {}).items()}
            if str(p.get('NAME') or '') == name:
                return [(frm, to, shape(f['geometry']),
                         f'historical-basemaps, срез {year}, NAME={name}')]
        raise SystemExit(f'historical-basemaps {year}: нет NAME={name}')
    if kind == 'ne1':
        admin, _, names = rest.partition(':')
        if names == '*':
            # СТРАНА ЦЕЛИКОМ по современным контурам. Так заведены четверо, кого
            # CShapes 2.0 не знает вовсе: Сан-Томе и Принсипи, Сейшелы, Гренада
            # и Западная Сахара (контур САДР). Границы этих четверых внутри их
            # окон не менялись, так что потери от современного контура нет.
            parts = [shape(f['geometry']) for f in load_ne1()
                     if f['properties'].get('admin') == admin]
            if not parts:
                raise SystemExit(f'Natural Earth admin-1: нет admin={admin}')
            return [(frm, to, unary_union(parts),
                     f'Natural Earth admin-1, {admin} целиком '
                     f'({len(parts)} единиц, современный контур)')]
        want = set(names.split('|'))
        parts, got = [], set()
        for f in load_ne1():
            p = f['properties']
            if p.get('admin') == admin and p.get('name') in want:
                parts.append(shape(f['geometry']))
                got.add(p['name'])
        if want - got:
            raise SystemExit(f'Natural Earth admin-1 {admin}: нет {sorted(want - got)}')
        return [(frm, to, unary_union(parts),
                 f'Natural Earth admin-1, {admin}: {", ".join(sorted(got))}')]
    raise SystemExit(f'непонятный источник контура: {spec}')


def round_geom(g, digits=DIGITS):
    def rc(c):
        if isinstance(c[0], (int, float)):
            return [round(float(c[0]), digits), round(float(c[1]), digits)]
        return [rc(x) for x in c]
    m = mapping(g)
    return gc.clean_rings({'type': m['type'],
                           'coordinates': rc(m['coordinates'])})


def read_rows(path=CSV_PATH):
    with open(path, encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f)
                if (r.get('country') or '').strip()
                and not (r.get('country') or '').startswith('#')]
    bad = []
    for i, r in enumerate(rows, 2):
        if r['kind'] not in KINDS:
            bad.append(f'строка {i}: kind «{r["kind"]}» не из списка {sorted(KINDS)}')
        if r['confidence'] not in CONF:
            bad.append(f'строка {i}: confidence «{r["confidence"]}» не из {CONF}')
        if r['iso3'] not in GEOM:
            bad.append(f'строка {i}: для iso3 «{r["iso3"]}» нет контура в GEOM')
        if not d2t(r['from']):
            bad.append(f'строка {i}: пустая дата from')
        if r['to'] and r['to'] < r['from']:
            bad.append(f'строка {i}: to раньше from')
        if not (r.get('source') or '').strip():
            bad.append(f'строка {i}: пустой source — «общее знание» в таблицу не идёт')
        if not (r.get('event_from') or '').strip():
            bad.append(f'строка {i}: пустой event_from')
    if bad:
        for b in bad:
            print('!! ' + b)
        raise SystemExit('таблица сферы не прошла проверку')
    return rows


def build(rows):
    feats = []
    silent = []
    for n, r in enumerate(rows, 1):
        ep = f'{r["iso3"]}-{r["from"]}'
        slices = list(geom_slices(GEOM[r['iso3']], r['from'],
                                  r['to'] or HORIZON))
        # Строка без единой фичи - это МОЛЧАЛИВАЯ ПОТЕРЯ: эпизод есть в таблице
        # с датами и пруфом, а на карте его нет. Так до 28.08.2026 пропадала
        # Западная группа войск в Германии. Молчать об этом нельзя.
        if not slices:
            silent.append(f'{r["country_ru"]} {r["from"]}-{r["to"] or "идёт"} '
                          f'(iso3 {r["iso3"]})')
        for gf, gt, g, gsrc in slices:
            gs = g if g.area < NO_SIMPLIFY else g.simplify(SIMPLIFY,
                                                           preserve_topology=True)
            if gs.is_empty:
                gs = g
            feats.append({
                'type': 'Feature',
                'geometry': round_geom(gs),
                'properties': {
                    'ep': ep,
                    'name': r['country'],
                    'name_ru': r['country_ru'],
                    'iso3': r['iso3'],
                    'from': r['from'],
                    'to': r['to'],
                    'kind': r['kind'],
                    'kind_ru': KINDS[r['kind']],
                    'event_from': r['event_from'],
                    'event_to': r['event_to'],
                    'source': r['source'],
                    'confidence': r['confidence'],
                    'note': r['note'],
                    'gfrom': gf,
                    'gto': gt,
                    'geometry_source': gsrc,
                },
            })
    if silent:
        print(f'!! {len(silent)} эпизодов БЕЗ ГЕОМЕТРИИ - их нет на карте:')
        for x in silent:
            print(f'   {x}')
        raise SystemExit('строка таблицы не должна молча пропадать из слоя')
    return feats


def report(rows, feats):
    print(f'эпизодов в таблице: {len(rows)}, фич на выходе: {len(feats)}'
          f' (окна режутся интервалами контуров)')
    by = {}
    for r in rows:
        by[r['kind']] = by.get(r['kind'], 0) + 1
    print('по типу зависимости:')
    for k in KINDS:
        if by.get(k):
            print(f'  {k:16s} {by[k]:3d}  — {KINDS[k]}')
    cf = {}
    for r in rows:
        cf[r['confidence']] = cf.get(r['confidence'], 0) + 1
    print('по достоверности: ' + ', '.join(f'{k} — {cf.get(k, 0)}' for k in CONF))
    cs = sorted({r['country_ru'] for r in rows})
    print(f'стран и территорий: {len(cs)}')
    print('  ' + ', '.join(cs))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--csv', default=CSV_PATH)
    ap.add_argument('--report', action='store_true')
    args = ap.parse_args()
    rows = read_rows(args.csv)
    feats = build(rows)
    path = os.path.join(OUT, 'sphere.geojson')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj({'type': 'FeatureCollection', 'features': feats}), f,
                  ensure_ascii=False)
    print(f'OK {os.path.relpath(path, ROOT)}: {len(feats)} фич '
          f'из {len(rows)} эпизодов, {os.path.getsize(path) // 1024} КБ')
    if args.report:
        report(rows, feats)
    return 0


if __name__ == '__main__':
    sys.exit(main())
