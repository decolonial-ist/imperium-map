#!/usr/bin/env python3
"""Слой постсоветских эпизодов, 1990-2022: контроль по датам, а не по годам.

Зачем. Между 1992 и 2022 у карты не было ничего, кроме одного статичного файла
`data/deepstate/territories.geojson` с ГОДОВОЙ пометкой: Приднестровье 1992,
Абхазия и Цхинвальский район 2008, Крым, ОРДЛО и Тузла 2014. Из-за этого
листание ползунком прыгало из 1992 сразу в 2015, и всё появлялось разом. Жалоба
куратора 26.08.2026: «прыжок из 1992 в 2015, и сразу появляются и осетия, и
абхазия, и донбас и крым? там все по очереди было вообще-то».

Чечни на карте не было вообще: обе войны и де-факто независимая Ичкерия
1996-1999 просто не существовали - контур РФ красил Грозный имперским красным
непрерывно с 1992 года.

Что делаем. Разбираем тридцать лет на ДАТИРОВАННЫЕ ЭПИЗОДЫ по тому же правилу,
по которому идёт вся остальная карта: показываем КОНТРОЛЬ, а не декларации.
Красное - империя распоряжается, чёрное - нет.

Вход: `data/postsoviet/registry.csv` - курируемая таблица эпизодов.
Колонки: territory,territory_ru,from,to,kind,event_from,event_to,source,
confidence,note. Строка = ЭПИЗОД, а не территория: у Приднестровья их два
(война и оккупация после соглашения), у Чечни шесть.

`kind` - закрытый список:
  war                  - идёт война за контроль;
  occupation           - оккупация де-факто;
  annexation           - аннексия (оформлена актом о включении в состав);
  de_facto_independent - независимое государство: империя контроля не имеет;
  peacekeepers         - войска империи стоят под видом миротворцев.

РАМКА (поправка куратора 26.08.2026). Приднестровье, Абхазия и Южная Осетия -
это ввод войск на территорию соседних государств, Молдовы и Грузии, и
закрепление там. Ичкерия - другое: колонизованный народ, отстоявший
независимость в войне 1994-1996 годов и уничтоженный второй войной с 1999-го.
Империя теряет и возвращает КОНТРОЛЬ, а не собственность: слова «своё»,
«потеряла своё», «вернула своё» о колонизованных территориях в этом проекте
не употребляются, и в подписях слоя их нет. Различие живёт в поле `kind`, хотя
на карте обе рамки красятся по одному правилу «контроль империи да/нет».

Отсюда `paint` - как эпизод ложится на карту (считается здесь, в таблицу
руками не пишется):
  red  - территория соседнего государства, которой распоряжается империя:
         рисуем красным поверх. kind = occupation / annexation / peacekeepers;
  cut  - точка попадает внутрь контура империи, но контроля империя там не
         имеет: ВЫРЕЗАЕМ из красного (тем же приёмом, что слой потерь
         контроля, см. cutCore в index.html). kind = de_facto_independent,
         а также war внутри контура;
  none - война за территорию соседнего государства, контроль ещё не
         установлен: красить нечем. Эпизод живёт в попапе истории точки и
         даёт остановку ползунка.
Внутри контура эпизод или снаружи - решается геометрией: если больше половины
площади лежит внутри контура ядра империи, эпизод считается внутренним. Это
техническое свойство ПОКАЗА (`in_contour`), а не утверждение о том, чья это
земля.

Геометрия. Руками не рисуем ничего, кроме двух приближений (см. HAND):
  - оккупированные территории берём из `data/deepstate/territories.geojson`
    (DeepStateMAP) - тот самый статичный файл, который слой заменяет в показе.
    Файл остаётся на диске и остаётся источником геометрии;
  - Чечня - Natural Earth admin-1, обрезана контуром ядра;
  - подокна «до 2008» получаются вычитанием рамки: Ахалгорский (Ленингорский)
    район из Цхинвальского и верхнее Кодорское ущелье из Абхазии - до августа
    2008 их держала Грузия, и красить их российским красным с 1992 года
    нельзя. Рамки приближённые, помечены approximate.

Выход: `data/postsoviet.geojson` (фичи с датами, событиями и пруфами) и
`data/postsoviet/report.md` (таблица эпизодов для куратора).

Запуск: .venv/bin/python tools/build_postsoviet.py
Проверка: .venv/bin/python tools/check_postsoviet.py
"""
import csv
import json
import os
import sys
from datetime import date

from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import geoclean as gc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'cache')
DATA = os.path.join(ROOT, 'data')
REG = os.path.join(DATA, 'postsoviet', 'registry.csv')
OUT = os.path.join(DATA, 'postsoviet.geojson')
REPORT = os.path.join(DATA, 'postsoviet', 'report.md')

# срез ядра, действующий на весь постсоветский период (см. data/manifest.json:
# после «1946» у нас есть только «1992», и он держит всё до 2022 года)
CORE_KEY = '1992'

KINDS = {
    'war': 'война за контроль',
    'occupation': 'оккупация',
    'annexation': 'аннексия',
    'de_facto_independent': 'независимость, отстоянная в войне: империя '
                            'контроля не имела',
    'peacekeepers': 'войска империи под видом «миротворцев»',
}
PAINT_BY_KIND = {
    'occupation': 'red',
    'annexation': 'red',
    'peacekeepers': 'red',
    'de_facto_independent': 'cut',
    # war считается отдельно: внутри контура - вырез, снаружи - ничего
}
# серии датированных срезов: в попапе такая серия сворачивается в одну строку
SERIES = {
    'donbas': 'помесячная реконструкция линии контроля на Донбассе '
              '(апрель 2014 - февраль 2015) и первых недель вторжения '
              '2022 года, tools/build_donbas.py',
}
SIMPLIFY = 0.002        # ~200 м, слой обзорный
MIN_INSIDE = 0.5        # доля площади внутри контура ядра, чтобы счесть эпизод внутренним

# ---- рамки приближений ------------------------------------------------------
# Ахалгорский (Ленингорский) район: восточная доля Цхинвальского полигона.
# До августа 2008 его держала Грузия. Рамка по долготе 44.25° отрезает долю
# площадью ~1280 кв. км (у района ~1064 кв. км) - приближение, но оно ставит
# Ахалгори по нужную сторону, а Цхинвали и Джаву оставляет по свою.
AKHALGORI_BOX = (44.25, 41.0, 46.0, 43.5)
# Верхнее Кодорское ущелье (Ажара, Чхалта; в грузинской администрации - «Верхняя
# Абхазия»): северо-восточная доля абхазского полигона, ~1500 кв. км. До
# 12.08.2008 её держала Грузия. Рамка не задевает ни Сухуми, ни Гали.
KODORI_BOX = (41.55, 42.85, 42.2, 43.4)
# Горная Чечня: рамка южнее 43.05° - Веденский, Шатойский, Итум-Калинский,
# Шаройский и Ножай-Юртовский районы. Грозный (43.32), Шали (43.15) и
# Урус-Мартан (43.13) остаются севернее.
CHECHNYA_MTN_BOX = (44.0, 41.0, 47.0, 43.05)

# ---- рисованные приближения -------------------------------------------------
# Ровно два места, где машиночитаемого контура нет ни в одном нашем источнике,
# и эпизод без него на карте не читается. Оба помечены approximate=true и
# названы в попапе.
HAND = {
    # Славянско-краматорский выступ: Славянск, Краматорск, Дружковка,
    # Константиновка, Красный Лиман, Северск - занят 12.04.2014, оставлен
    # 05.07.2014. Лежит СЕВЕРНЕЕ и ЗАПАДНЕЕ линии ОРДЛО, в полигоне
    # DeepStateMAP его нет.
    'sloviansk': [
        [(36.95, 48.45), (38.15, 48.45), (38.15, 49.05), (36.95, 49.05)],
    ],
    # Мариуполь: горсовет захвачен 13.04.2014, город очищен 13.06.2014.
    # Западнее линии ОРДЛО.
    'mariupol': [
        [(37.25, 46.95), (37.85, 46.95), (37.85, 47.25), (37.25, 47.25)],
    ],
}


# ---- источники геометрии ----------------------------------------------------
_cache = {}


def terr(name):
    """Полигон из статичного файла DeepStateMAP."""
    if '__terr' not in _cache:
        with open(os.path.join(DATA, 'deepstate', 'territories.geojson'),
                  encoding='utf-8') as f:
            _cache['__terr'] = {ft['properties']['name']:
                                shape(ft['geometry']).buffer(0)
                                for ft in json.load(f)['features']}
    d = _cache['__terr']
    if name not in d:
        raise SystemExit(f'territories.geojson: нет полигона «{name}», есть '
                         f'{sorted(d)}')
    return d[name]


def georgia_buffer_2008():
    """Муниципалитеты Грузии, занятые российскими войсками 11.08-10.10.2008.

    Геометрия - OpenStreetMap (отношения admin_level=6), выгружена через
    Overpass и положена в data/postsoviet/georgia_buffer_2008.geojson: файл
    курируемый, в cache/ его держать нельзя - cache в гит не идёт.
    """
    if '__gebuf' not in _cache:
        path = os.path.join(DATA, 'postsoviet', 'georgia_buffer_2008.geojson')
        with open(path, encoding='utf-8') as f:
            fc = json.load(f)
        _cache['__gebuf'] = unary_union(
            [shape(x['geometry']).buffer(0) for x in fc['features']])
    return _cache['__gebuf']


def ne(admin, names):
    """Объединение областей Natural Earth admin-1."""
    if '__ne' not in _cache:
        with open(os.path.join(CACHE, 'ne_admin1.geojson'), encoding='utf-8') as f:
            _cache['__ne'] = json.load(f)['features']
    sel = [f for f in _cache['__ne']
           if f['properties'].get('admin') == admin
           and (names is None or f['properties'].get('name') in names)]
    if names is not None:
        miss = set(names) - {f['properties'].get('name') for f in sel}
        if miss:
            raise SystemExit(f'NE admin-1: не найдены {sorted(miss)} ({admin})')
    if not sel:
        raise SystemExit(f'NE admin-1: пустая выборка {admin} {names}')
    return unary_union([shape(f['geometry']).buffer(0) for f in sel])


def core():
    """Контур ядра империи, действующий на весь постсоветский период."""
    if '__core' not in _cache:
        with open(os.path.join(DATA, 'years', CORE_KEY + '.geojson'),
                  encoding='utf-8') as f:
            _cache['__core'] = unary_union(
                [shape(ft['geometry']).buffer(0) for ft in json.load(f)['features']])
    return _cache['__core']


def hand(key):
    return unary_union([shape({'type': 'Polygon', 'coordinates': [list(r) + [r[0]]]})
                        .buffer(0) for r in HAND[key]])


def donbas():
    """Срезы помесячной реконструкции Донбасса (tools/build_donbas.py).

    Ключ геометрии = `id` фичи = значение `territory` в реестре, поэтому
    добавлять срезы можно строками таблицы, не трогая билдер.
    """
    path = os.path.join(DATA, 'postsoviet', 'donbas.geojson')
    if not os.path.exists(path):
        raise SystemExit(f'нет {path}: сначала .venv/bin/python '
                         f'tools/build_donbas.py')
    with open(path, encoding='utf-8') as f:
        fc = json.load(f)
    out = {}
    for ft in fc['features']:
        p = ft['properties']
        out[p['id']] = (shape(ft['geometry']).buffer(0),
                        f'реконструкция на {p["date"]}: {p["method"]}; '
                        f'якорей {p["anchors"]}, рамка - {p["clip"]} '
                        f'(tools/build_donbas.py, '
                        f'data/crosscheck/donbas_cities.csv)', True)
    return out


# ---- каталог геометрий: ключ territory -> контур ----------------------------
# Ключ таблицы `territory` - это И имя эпизодной территории, И ключ геометрии.
def geometries():
    pmr = terr("Придністров'я")
    so = terr('Окупований Цхінвальський район')
    ab = terr('Окупована Абхазія.')
    crimea = unary_union([terr('Окупований Крим'), terr('Острів Тузла')])
    ordlo = terr('ОРДЛО')
    akhalgori = so.intersection(box(*AKHALGORI_BOX))
    kodori = ab.intersection(box(*KODORI_BOX))
    chechnya = ne('Russia', ['Chechnya']).intersection(core())
    g = {
        'transnistria': (pmr, 'DeepStateMAP, статичный контур '
                              'data/deepstate/territories.geojson', False),
        # до августа 2008 Ахалгорский район держала Грузия - вычитаем
        'south_ossetia_pre2008': (so.difference(box(*AKHALGORI_BOX)),
                                  'DeepStateMAP минус Ахалгорский район '
                                  '(рамка по 44.25° в.д.)', True),
        'akhalgori': (akhalgori, 'DeepStateMAP, восточная доля Цхинвальского '
                                 'полигона (рамка по 44.25° в.д.)', True),
        'south_ossetia': (so, 'DeepStateMAP, статичный контур', False),
        # до 12.08.2008 верхнее Кодори держала Грузия - вычитаем
        'abkhazia_pre2008': (ab.difference(box(*KODORI_BOX)),
                             'DeepStateMAP минус верхнее Кодорское ущелье '
                             '(рамка 41.55-42.2° в.д., 42.85-43.4° с.ш.)', True),
        'kodori': (kodori, 'DeepStateMAP, северо-восточная доля абхазского '
                           'полигона (рамка Кодорского ущелья)', True),
        'abkhazia': (ab, 'DeepStateMAP, статичный контур', False),
        'crimea': (crimea, 'DeepStateMAP: Крым и остров Тузла', False),
        'ordlo': (ordlo, 'DeepStateMAP, статичный контур ОРДЛО (линия, на '
                         'которой фронт встал после Дебальцево, 18.02.2015)',
                  True),
        'chechnya': (chechnya, 'Natural Earth admin-1 (Chechnya), обрезана '
                               'контуром ядра', False),
        'chechnya_mountains': (chechnya.intersection(box(*CHECHNYA_MTN_BOX)),
                               'Natural Earth admin-1 (Chechnya) южнее 43.05° '
                               'с.ш. - горные районы', True),
        # Буферные зоны 2008 года - ПО ЗАНЯТЫМ МУНИЦИПАЛИТЕТАМ (28.08.2026).
        # История контура: сперва два нарисованных прямоугольника (92% и 79%
        # периметра строго по осям - на карте две линейки); потом целые регионы
        # Natural Earth, что убрало линейки, но ЗАВЫСИЛО площадь вдвое
        # (11.1 против 6.2 тыс. км²: в Самегрело-Земо-Сванети попадали
        # сванетские горы, где войск не было). Теперь - семь муниципалитетов
        # OpenStreetMap, 4.7 тыс. км²: Гори, Карели, Каспи (коридор к Южной
        # Осетии) и Зугдиди, Хоби, Сенаки, Поти (полоса у Абхазии). Хоби
        # подтверждён порядком снятия постов 08-09.10.2008: сперва Поти, затем
        # Сенаки и Хоби. Хашури и Абаша НЕ включены: выход из Хашури ни одним
        # источником не датирован, Абаша не упомянута вовсе.
        # Южная Осетия и Абхазия вычитаются: буфер - это районы САМОЙ Грузии
        # вокруг них, а не они сами.
        'georgia_buffer': (georgia_buffer_2008().difference(so).difference(ab),
                           'OpenStreetMap, границы муниципалитетов: Гори, '
                           'Карели, Каспи, Зугдиди, Хоби, Сенаки, Поти, минус '
                           'Южная Осетия и Абхазия', True),
        'sloviansk': (hand('sloviansk'),
                      'приближение: славянско-краматорский выступ', True),
        'mariupol': (hand('mariupol'), 'приближение: Мариуполь и окрестности',
                     True),
        'ukraine': (ne('Ukraine', None),
                    'Natural Earth admin-1, вся Украина (эпизод не красит '
                    'карту, нужен попапу и остановке ползунка)', False),
    }
    # помесячная линия контроля на Донбассе и первые недели вторжения 2022 года
    g.update(donbas())
    return g


# ---- сборка -----------------------------------------------------------------
def d(s):
    p = [int(v) for v in str(s).split('-')]
    return date(p[0], p[1], p[2])


def main():
    if not os.path.exists(REG):
        raise SystemExit(f'нет таблицы {REG}')
    with open(REG, encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f)
                if r.get('territory') and not r['territory'].startswith('#')]
    geo = geometries()
    ck = core()
    feats, report, bad = [], [], []
    for i, r in enumerate(rows, 2):
        key = r['territory'].strip()
        if key not in geo:
            bad.append(f'строка {i}: неизвестная территория «{key}»')
            continue
        kind = r['kind'].strip()
        if kind not in KINDS:
            bad.append(f'строка {i}: kind «{kind}» не из списка {sorted(KINDS)}')
            continue
        if not r.get('source', '').strip():
            bad.append(f'строка {i}: пустой источник')
        g, gsrc, approx = geo[key]
        try:
            t0 = d(r['from'])
        except Exception:
            bad.append(f'строка {i}: не разбирается дата from «{r["from"]}»')
            continue
        t1 = None
        if r.get('to', '').strip():
            try:
                t1 = d(r['to'])
            except Exception:
                bad.append(f'строка {i}: не разбирается дата to «{r["to"]}»')
                continue
            if t1 < t0:
                bad.append(f'строка {i}: to раньше from')
        # внутри контура империи эпизод или снаружи - по геометрии, а не по
        # названию. Это про показ, а не про принадлежность земли.
        inside = g.intersection(ck).area / g.area if g.area else 0
        in_contour = inside >= MIN_INSIDE
        if kind in PAINT_BY_KIND:
            paint = PAINT_BY_KIND[kind]
        else:                                   # war
            paint = 'cut' if in_contour else 'none'
        if kind == 'de_facto_independent' and not in_contour:
            bad.append(f'строка {i}: de_facto_independent вне контура империи '
                       f'({key}, внутри {inside:.0%}) - вырезать нечего')
        if paint == 'red' and in_contour:
            bad.append(f'строка {i}: {kind} внутри контура империи ({key}, '
                       f'внутри {inside:.0%}) - красное поверх красного')
        feats.append({
            'type': 'Feature',
            'properties': {
                'territory': key,
                'name_ru': r['territory_ru'].strip(),
                'from': r['from'].strip(),
                'to': (r.get('to') or '').strip(),
                'kind': kind,
                'kind_ru': KINDS[kind],
                'paint': paint,
                'in_contour': in_contour,
                'event_from': r.get('event_from', '').strip(),
                'event_to': r.get('event_to', '').strip(),
                'source': r.get('source', '').strip(),
                'confidence': r.get('confidence', '').strip(),
                'note': r.get('note', '').strip(),
                'geometry_source': gsrc,
                'approximate': approx,
                # серия датированных срезов: попап сворачивает её в одну
                # строку, иначе клик в Донецк выдавал бы два десятка строк
                'series': r.get('series', '').strip(),
                'series_ru': SERIES.get(r.get('series', '').strip(), ''),
            },
            'geometry': gc.clean_rings(
                mapping(g.simplify(SIMPLIFY, preserve_topology=True))),
        })
        report.append((r['from'].strip(), (r.get('to') or '').strip() or '—',
                       r['territory_ru'].strip(), KINDS[kind], paint,
                       r.get('event_from', '').strip(),
                       r.get('source', '').strip()))
    if bad:
        print('ОШИБКИ ТАБЛИЦЫ:')
        for b in bad:
            print(' ', b)
        sys.exit(1)
    feats.sort(key=lambda f: (f['properties']['from'], f['properties']['territory']))
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj({'type': 'FeatureCollection',
                   'note': 'постсоветские эпизоды 1990-2022, tools/build_postsoviet.py',
                   'features': feats}), f, ensure_ascii=False, separators=(',', ':'))
    report.sort()
    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write('# Постсоветские эпизоды: что показывает карта\n\n')
        f.write('Собрано `tools/build_postsoviet.py` из '
                '`data/postsoviet/registry.csv`.\n'
                'Колонка «показ»: `red` - красим красным поверх (территория '
                'соседнего государства под империей), `cut` - вырезаем из '
                'красного (точка внутри контура империи, но контроля там нет), '
                '`none` - на карте не красим, эпизод живёт в попапе и даёт '
                'остановку ползунка.\n\n')
        f.write('| с | по | территория | тип | показ | событие | источник |\n')
        f.write('|---|---|---|---|---|---|---|\n')
        for row in report:
            f.write('| ' + ' | '.join(x.replace('|', '/') for x in row) + ' |\n')
    print(f'{OUT}: {len(feats)} эпизодов, '
          f'{sum(1 for x in feats if x["properties"]["paint"] == "red")} красим, '
          f'{sum(1 for x in feats if x["properties"]["paint"] == "cut")} вырезаем, '
          f'{sum(1 for x in feats if x["properties"]["paint"] == "none")} только в попапе')
    print(f'{REPORT}: таблица эпизодов')
    print('\nдальше: .venv/bin/python tools/check_postsoviet.py')


if __name__ == '__main__':
    main()
