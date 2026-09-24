#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Курируемые срезы расползания империи: приобретения по актам, 1450-1991.

ДВЕ СТАДИИ (27.08.2026):
  --only early - срезы 1450-1914 из таблиц ADDS/SUBS (всё, что ниже);
  --only late  - позднее окно 18.03.1921 - 26.12.1991: Танну-Тува,
                 курируемая заплата на Батум и датированный распад СССР.
                 Стадия ПРАВИТ уже лежащие на диске срезы, поэтому её надо
                 прогонять ЕЩЁ РАЗ ПОСЛЕ tools/build_ww2.py.
Без ключа гоняются обе.


ЗАЧЕМ. Источник границ (aourednik/historical-basemaps) даёт всего десять срезов
на четыре века, и между 1815 и 1880 годами у него нет ни одного. Из-за этого
карта врала целыми регионами: Тбилиси попадал в империю только с 1886 (первый
срез CShapes), хотя Картли-Кахети присоединена в 1801; Ташкент, Самарканд,
Хива, Мерв, Карс, Батум, Южный Сахалин, казахские жузы и Черкесия появлялись
тем же скачком 1880/1886; Аляска, наоборот, оставалась российской до 1880,
хотя продана в 1867; Урянхай источник рисует внутри Московского царства в
срезах 1650 и 1700, а протекторат объявлен только в 1914. Замер - таблица
`data/crosscheck/expansion.csv` (39 ошибок из 62 строк до этой правки),
регрессия - `tools/check_expansion.py`.

ЧТО ДЕЛАЕТ. Пересобирает ядро империи для всех срезов 1500-1914:

    срез = контур источника на эту дату
          + приобретения, действующие на дату (ADDS)
          - территории, которых на эту дату у империи ещё/уже нет (SUBS)

ПОКАЗ БИНАРНЫЙ (правило куратора 19.08.2026): красное - империя тут была,
чёрное - не была, никаких штриховок и «оспаривается». Поэтому территория, на
которой идёт война за контроль, в контур НЕ ВХОДИТ, сколько бы актов ни было
подписано: горная Чечня и Дагестан краснели по Гюлистанскому трактату 1813
года (а на деле - с контура источника 1783 года), хотя империя воевала там до
1859-го. Список таких территорий - RESIST ниже, даты и пруфы - из НАШЕЙ базы
кампаний (data/campaigns/*.json, tools/build_campaigns.py). Юридическое
присоединение при этом не исчезает: оно остаётся в таблице ADDS и в свойстве
`added` среза. Разбор «акт против контроля» - data/crosscheck/control_vs_act.csv
(tools/build_resistance.py).

и дополнительно заводит ДАТИРОВАННЫЕ срезы на даты самих актов (манифест о
Грузии 12.09.1801, Гюлистан 12.10.1813, Туркманчай 10.02.1828, взятие Ташкента
17.06.1865, продажа Аляски 18.10.1867 и т.д.) - чтобы попап истории точки
называл дату акта, а не «между 1880 и 1886».

ГЕОМЕТРИЯ - только машиночитаемые контуры, ничего не рисуется от руки:
  * основа среза - контур источника (historical-basemaps до 1880, CShapes 2.0
    с 1886), тот же, что собирает tools/build_data.py;
  * приобретения приближены СОВРЕМЕННЫМИ административными единицами
    (Natural Earth admin-1, `cache/ne_admin1.geojson`) - «Гюлистан» это
    современный Азербайджан без Нахичевани плюс Дагестан плюс Сюник и Тавуш,
    «Туркманчай» - остальная Армения, Нахичевань и Ыгдыр;
  * там, где современная нарезка заведомо шире исторической (Сибирь, Поволжье),
    приобретение ОБРЕЗАЕТСЯ контуром источника ближайшего следующего года
    (`clip`) - лишнего не прирастает;
  * Русская Америка берётся прямо из среза источника 1815 г. (западное
    полушарие), а не приближается.

Все выходные фичи помечены `reconstruction: true`, `approximate: true`,
`expansion: true`; в свойствах `added`/`removed` перечислены каждое
приобретение с датой, актом и источником. Слои 1917-1921 (реконструкция зоны
контроля) и 2022+ (фронт) НЕ ТРОГАЮТСЯ.

ГРАНИЦЫ ЧЕСТНОСТИ. Современная административная нарезка - не историческая
граница: Карсская область приближена вилайетами Карс, Ардахан и Артвин,
Бессарабия - всей Молдовой (включая Приднестровье, российское с 1792),
Курляндия и Латгалия отрезаны от Лифляндии рамками по долготе, Черкесия -
Краснодарским краем с Адыгеей и Карачаево-Черкесией. Это записано в поле
`source` каждой добавленной части и в README (раздел «Известные ограничения»).

Запуск (нужен shapely из .venv в корне репо; ПОСЛЕ tools/build_data.py):

    cd ~/tmp/imperium-map && .venv/bin/python tools/build_expansion.py
    cd ~/tmp/imperium-map && python3 tools/check_expansion.py
"""
import argparse
import json
import math
import os
import sys
import urllib.request
from datetime import date

from shapely.geometry import box, mapping, shape, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_data as bd   # noqa: E402  (CORE, CSHAPES_SLICES, fetch - оттуда)
import geoclean as gc     # noqa: E402  (чистка колец от нулевых отрезков)
import core_tables     # noqa: E402  (таблицы ядра - data/core/*.csv)

ROOT = bd.ROOT
DATA = bd.OUT
CACHE = bd.CACHE

SIMPLIFY = 0.005    # ~0.5 км: на 0.02 упрощение утапливало приморские города
DIGITS = 3


def d(s):
    return date(*[int(x) for x in str(s).split('-')])


def key_date(k):
    p = [int(x) for x in str(k).split('-')]
    return date(p[0], p[1] if len(p) > 1 else 1, p[2] if len(p) > 2 else 1)


# ---- регионы: только машиночитаемые контуры --------------------------------
# ('ne', admin, [имена] | None)              - Natural Earth admin-1
# ('ne_box', admin, [имена] | None, рамка)   - то же, обрезано рамкой
# ('alaska',)                                - западное полушарие среза 1815
RU = 'Russia'
# строки - data/core/regions.csv (с 24.09.2026; комментарии строк - колонка comment)
REG = core_tables.load('REG')

NE = 'Natural Earth admin-1 (современная нарезка - приближение)'

# Регионы с курируемой точной береговой линией: общая чистка контура их не
# трогает, после неё они возвращаются как есть (см. build и patch_slice)
EARLY_PROTECT = {'SOLOVKI', 'YAIK_TOWNS'}

# ---- приобретения ----------------------------------------------------------
# A(регион, дата акта, [дата утраты], название, акт, источник акта, [clip])
# clip - ключ среза источника, контуром которого обрезается приобретение
# (современные регионы шире исторических - чтобы не прирастало лишнего).


# Запас на швы при вычитании. Был 0,05° (5,5 км) - пока границы вычитаемых
# областей шли рамками вдали от городов, это никому не мешало. С 01.09.2026
# они идут по настоящим районам и по руслу Кубани, и запас начал съедать
# живую землю: Дербент, Петровск, Екатеринодар и Наурская вывалились из
# контура (check_expansion, 4 ошибки). 0,005° - это 550 м, швы закрывает,
# города не трогает
SUB_BUF = 0.005

# Поздняя стадия (1921-1991) вычитает Туву, Ненецкий округ, север 1930 года и
# Курилы. Их границы идут по морю и по тундре, городов на них нет, а контур
# источника там грубее нарезки NE - без запаса вдоль границы остаются полоски
# в воде (check_sea_crumbs: северные Курилы и Чукотка у 180-го меридиана).
# Поэтому здесь запас прежний, 0,05°: он ничего живого не режет
LATE_SUB_BUF = 0.05


def A(reg, frm, name, act, src, to=None, clip=None, kind='территория'):
    return dict(reg=reg, frm=frm, to=to, name=name, act=act, src=src,
                clip=clip, kind=kind)


ZGRU_SRC = ('розыск MAP-MATERIALS/peresmotr_resheniy_2026-09-18/rozysk/'
            'b5_zapadnaya_gruziya_1803-1867_2026-09-22.md')
ANAT_SRC = ('розыск MAP-MATERIALS/peresmotr_resheniy_2026-09-18/rozysk/'
            'b5_anatoliya_okkupacii_2026-09-22.md, b5_anatoliya_vyvody_2026-09-22.md')
RP92_SRC = ('СИРИО т. 47 («Дела Польши 1792 года»); T. Korzon, «Kościuszko» (1906); '
            '«А. В. Суворов. Документы», т. III (1952); розыск MAP-MATERIALS/'
            'peresmotr_resheniy_2026-09-18/rozysk/b7_rp_1792-1795_dni_2026-09-22.md')
OCC8_SRC = ('ПСЗРИ; «Походный журнал» 1713-1714; Тенгберг; Rambaud; розыск MAP-MATERIALS/'
            'peresmotr_resheniy_2026-09-18/rozysk/b8_finlyandiya_prussiya_2026-09-22.md')
OCC9_SRC = ('ПСЗ-2, ПСЗ-3; сборники договоров России с Китаем; розыск MAP-MATERIALS/'
            'peresmotr_resheniy_2026-09-18/rozysk/b8_manchzhuriya_ili_2026-09-22.md')
OCC10_SRC = ('А. Н. Петров, «Война России с Турцией» (1866-1890); ПСЗ; розыск MAP-MATERIALS/'
             'peresmotr_resheniy_2026-09-18/rozysk/b8_dunay_bolgariya_2026-09-22.md')
OCC10B_SRC = ('Н. Р. Овсяный, «Русское управление в Болгарии в 1877-78-79 гг.», т. I-III (1906-1907); '
              '«Описание русско-турецкой войны 1877-78 гг. на Балканском полуострове» (1901-1913); '
              'А. Н. Петров, «Война России с Турцией 1806-1812 гг.», т. III; розыски MAP-MATERIALS/'
              'peresmotr_resheniy_2026-09-18/rozysk/b10b_bolgariya_1877-1879_dni_2026-09-22.md, '
              'b10b_dunay_1809-1851_dni_2026-09-22.md')
PERSIA_SRC = ('розыск MAP-MATERIALS/peresmotr_resheniy_2026-09-18/rozysk/'
              'b5_persiya_garnizony_1909-1918.csv и b5_persiya_dni_2026-09-22.md')
GILAN_SRC = ('Encyclopaedia Iranica, «Jangali movement» (P. Dailami); '
             'M. Rezun, The Soviet Union and Iran (1981), p. 17; П. Аптекарь, '
             '«Красное солнце. Секретные восточные походы РККА»; розыск '
             'MAP-MATERIALS/peresmotr_resheniy_2026-09-18/rozysk/'
             'b5_gilyan_1920-1921_2026-09-22.md')
# строки - data/core/adds.csv (с 24.09.2026; комментарии строк - колонка comment)
ADDS = core_tables.load('ADDS')

# ---- вычитания: чего у империи на эту дату ещё (или уже) нет ---------------
# S(регион, с даты | None, по дату | None, почему)


def S(reg, frm, to, name, why):
    return dict(reg=reg, frm=frm, to=to, name=name, why=why)


# строки - data/core/subs.csv (с 24.09.2026; комментарии строк - колонка comment)
SUBS = core_tables.load('SUBS')

# ---- война сопротивления: акт есть, контроля нет ---------------------------
# Правило куратора 19.08.2026: показ БИНАРНЫЙ. Красное - империя тут была,
# чёрное - не была. Никаких штриховок и «оспаривается»: пока на территории
# идёт война за контроль, территория не красная, сколько бы актов ни было
# подписано. Юридическое присоединение от этого не исчезает - оно остаётся в
# свойстве `added` среза и в таблице приобретений выше, но контур ядра идёт
# по факту.
#
# ДАТЫ И ПРУФЫ - ИЗ НАШЕЙ СОБСТВЕННОЙ БАЗЫ КАМПАНИЙ, не из головы:
# `data/campaigns/<домен>.json` (выгрузка tools/build_campaigns.py из
# мастер-таблицы DECOLONIAL.IST). Домен nohchi описывает Кавказскую войну
# кампания за кампанией; на него и опираемся. Разбор «акт против контроля» с
# перечислением кампаний-пруфов - `data/crosscheck/control_vs_act.csv`
# (собирается tools/build_resistance.py отсюда же).
#
# R(регион, дата установления контроля, название, чем контроль установлен,
#   источник даты, [кампании], домен, чем территория покрашена сейчас)


def R(reg, until, name, event, src, campaigns, domain, painted, note=''):
    return dict(reg=reg, until=until, name=name, event=event, src=src,
                campaigns=campaigns, domain=domain, painted=painted,
                note=note)


# строки - data/core/resist.csv (с 24.09.2026; комментарии строк - колонка comment)
RESIST = core_tables.load('RESIST')

SUBS += [S(r['reg'], None, r['until'], r['name'],
           'война сопротивления: ' + r['event'] + '. Пруф: ' + r['src']
           + '. Территория покрашена как ' + r['painted'])
         for r in RESIST]


# ---- источники геометрии ---------------------------------------------------
_cache = {}


def ne_feats():
    # один загрузчик admin-1 на процесс: у geoclean.clip_to_land тот же файл
    return gc.admin1_features(CACHE)


def cs_feats():
    """Разобранный cshapes20.geojson (26 МБ) - один раз на процесс.

    До 29.08.2026 cs_core и cs_country парсили файл на каждый промах своего
    кэша: до 15-20 полных парсингов за прогон позднего окна.
    """
    if '__cs_feats' not in _cache:
        with open(os.path.join(CACHE, 'cshapes20.geojson'), encoding='utf-8') as f:
            _cache['__cs_feats'] = json.load(f)['features']
    return _cache['__cs_feats']


def ne_pick_region(admin, regions):
    feats = [f for f in ne_feats() if f['properties'].get('admin') == admin
             and f['properties'].get('region') in regions]
    have = {f['properties'].get('region') for f in feats}
    missing = set(regions) - have
    if missing:
        raise SystemExit(f'NE admin-1: нет region {sorted(missing)} у {admin}')
    return fill_holes(unary_union([shape(f['geometry']).buffer(0) for f in feats]))


def ne_pick(admin, names):
    feats = [f for f in ne_feats() if f['properties'].get('admin') == admin]
    if names is None:
        sel = feats
    else:
        sel = [f for f in feats if f['properties'].get('name') in names]
        missing = set(names) - {f['properties'].get('name') for f in sel}
        if missing:
            raise SystemExit(f'NE admin-1: не найдены области {sorted(missing)} '
                             f'({admin})')
    if not sel:
        raise SystemExit(f'NE admin-1: пустая выборка {admin} {names}')
    return fill_holes(unary_union([shape(f['geometry']).buffer(0) for f in sel]))


# ---- дырки-озёра -----------------------------------------------------------
# Правило простое: дырку внутри контура заливаем ТОЛЬКО если это вода. Дырка,
# которая суша, остаётся дыркой - Великое княжество Рязанское до 1521 года
# сидело анклавом внутри московских земель, и залить его значило бы соврать на
# шесть лет. Маска - Natural Earth 10m lakes (cache/ne_10m_lakes.geojson,
# 1355 озёр). Заливаем, если озёра покрывают больше 60% площади дырки.
_WATER = {}


WATER_SRC = (
    # озёра: Ладога, Онега, Чудское, Ильмень, Байкал и ещё 1350
    ('ne_10m_lakes.geojson',
     'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/'
     'master/geojson/ne_10m_lakes.geojson'),
    # море: Белое с Кандалакшским и Онежским заливами, Мезенский залив,
    # Карское, Енисейский залив, Каспий. Без него срез 17.09.1939 показывал
    # Белое море дыркой в красном - ровно один срез из 168, то есть на
    # ползунке море мигало
    ('ne_10m_ocean.geojson',
     'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/'
     'master/geojson/ne_10m_ocean.geojson'),
)


def water_mask():
    """Вода Natural Earth: озёра плюс море, объединённые в один слой.

    Готовая маска кэшируется на диск (29.08.2026). Профиль сборки одного среза:
    из 145 секунд 108 уходило сюда - 2869 вызовов buffer(0) по озёрам и океану
    на КАЖДЫЙ запуск сборщика. Файл живёт до обновления Natural Earth; удалить -
    пересчитается сам.
    """
    if 'g' not in _WATER:
        from shapely import wkb as _wkb
        wpath = os.path.join(CACHE, 'water_mask_union.wkb')
        if os.path.exists(wpath):
            with open(wpath, 'rb') as f:
                _WATER['g'] = _wkb.loads(f.read())
            return _WATER['g']
        gs = []
        for name, url in WATER_SRC:
            path = os.path.join(CACHE, name)
            # cache/ в гит не идёт, поэтому файлы докачиваем сами - тем же
            # приёмом, каким build_data тянет срезы historical-basemaps
            if not os.path.exists(path) or os.path.getsize(path) < 100000:
                print(f'качаю маску воды: {url}')
                try:
                    os.makedirs(CACHE, exist_ok=True)
                    req = urllib.request.Request(
                        url, headers={'User-Agent':
                                      'decolonial.ist imperium-map'})
                    with urllib.request.urlopen(req, timeout=240) as r, \
                            open(path, 'wb') as fp:
                        fp.write(r.read())
                except Exception as e:                   # noqa: BLE001
                    print(f'!! {name} не скачался ({e}): дырки-водоёмы '
                          f'останутся на карте. Файл: {url}')
            if os.path.exists(path):
                with open(path, encoding='utf-8') as f:
                    src = json.load(f)
                gs += [shape(x['geometry']).buffer(0) for x in src['features']]
        _WATER['g'] = unary_union(gs).buffer(0) if gs else None
        if _WATER['g'] is not None:
            with open(wpath, 'wb') as f:
                f.write(_WATER['g'].wkb)
    return _WATER['g']


_ALL = {}


def src_parts(year):
    """Все связные куски всех государств среза источника: [(полигон, имя)].

    Нужны, чтобы отличить настоящий анклав от обрезка. Приобретения мы берём
    современной нарезкой областей, база - контуром historical-basemaps, и на
    стыке РАЗНЫХ ЛЕТ источника остаётся полоса, которую объединение замыкает в
    дырку. Формально источник эту полосу кому-то отдаёт - но отдаёт КРАЕМ
    большого государства, а не отдельным анклавом.
    """
    if year not in _ALL:
        with open(bd.fetch(year), encoding='utf-8') as f:
            src = json.load(f)
        parts = []
        for feat in src['features']:
            try:
                g = shape(feat['geometry']).buffer(0)
            except Exception:                            # noqa: BLE001
                continue
            if g.is_empty:
                continue
            nm = bd.name_of(feat) or '?'
            for p in (list(g.geoms) if g.geom_type == 'MultiPolygon' else [g]):
                if p.area > 0:
                    parts.append((p, nm))
        _ALL[year] = parts
    return _ALL[year]


# ---- берег, срезанный генерализацией источника -----------------------------
# С 22.09.2026 - по всему миру, а не в коробке Чёрного моря и Азова (ответ
# куратора на строку 28 файла вопросов: «не понял, что ты хочешь залить
# чёрным» - не чёрным, а красным: полосу вдоль моря у областей, которые и так
# красные; это брак рисовки, не решение). Море - маска океана Natural Earth
# (Каспий, Чёрное, Азовское, Белое моря в неё входят, озёра - нет).
COAST_X = 0.30                          # ~30 км: зазор у Кинбурна 11,5 км
COAST_SHARE = 0.90                      # доля ядра единицы внутри контура
# страны, где у империи бывала приморская земля; прочие не считаем - дорого
COAST_COUNTRIES = {
    'Russia', 'Ukraine', 'Belarus', 'Moldova', 'Estonia', 'Latvia', 'Lithuania',
    'Finland', 'Poland', 'Georgia', 'Armenia', 'Azerbaijan', 'Kazakhstan',
    'Uzbekistan', 'Turkmenistan', 'Kyrgyzstan', 'Tajikistan', 'Turkey', 'Iran',
    'China', 'North Korea', 'Mongolia', 'Romania', 'Norway',
    'United States of America'}
_coast_units = None


def coast_units():
    """Единицы Natural Earth: сама единица, ядро без каймы и приморская кайма.

    Кайма - часть единицы в COAST_X от моря. До 22.09.2026 морем служила одна
    вода коробки (якорь «главная вода у середины Чёрного моря»): без якоря
    единице довольно было КРАЕМ задеть коробку, и её кайма добавлялась целиком,
    где бы та ни лежала - 18.09.2026 на срезе 1700 года так пролезла Калмыкия,
    1769 км² в Кумо-Манычской впадине. Теперь кайма считается от самой воды
    океана возле единицы, и внутренняя щель в неё попасть не может.
    """
    global _coast_units
    if _coast_units is None:
        tree, sea = gc._sea_tree(CACHE)
        out = []
        for f in gc.admin1_features(CACHE):
            if f['properties'].get('admin') not in COAST_COUNTRIES:
                continue
            g = shape(f['geometry']).buffer(0)
            if g.is_empty or g.area <= 0:
                continue
            reach = g.buffer(COAST_X)
            idx = tree.query(reach)
            if not len(idx):
                continue
            wet = unary_union([sea[i] for i in idx]).intersection(reach)
            if wet.is_empty:
                continue
            rim = g.intersection(wet.buffer(COAST_X))
            if rim.is_empty:
                continue
            core = g.buffer(-COAST_X)
            if core.is_empty or core.area <= 0:
                core = g
            out.append((g, core, rim))
        _coast_units = out
    return _coast_units


def coast_later(day):
    """Земля, которую таблица ADDS сама датирует ПОЗЖЕ этого дня.

    Заливке туда нельзя. 18.09.2026: без этого запрета заливка покрасила Анапу
    с 1791 по 1829 год - на 38 лет раньше Адрианопольского мира. Контур
    источника доводит красное по Кубани до 1,5 км от крепости, и Анапа была
    чёрной лишь потому, что попадала в щель генерализации; заливка закрывала
    щель при ЛЮБОЙ ширине каймы, от 30 км до 12. Три точки Анапы (1791, 1807,
    1828) при этом уходили с карты: военная точка на красном не показывается.
    Правило бьёт в корень: если у таблицы на эту землю есть акт с более поздней
    датой, значит в этот день она не имперская, и заливка её не трогает.
    Существующее красное правило не снимает - только не даёт добавлять.
    """
    key = ('coast_later', day)
    if key not in _cache:
        later = []
        for a in ADDS:
            if d(a['frm']) <= day:
                continue
            g = reg_geom(a['reg'])
            if g is not None and not g.is_empty:
                later.append(g)
        _cache[key] = unary_union(later) if later else None
    return _cache[key]


def fill_coast(geom, day=None):
    """Достроить берег у единиц, которые империя и так держит."""
    near = geom.buffer(COAST_X)
    nb = near.bounds
    later = coast_later(day) if day is not None else None
    add = []
    for g, core, rim in coast_units():
        b = g.bounds
        if b[2] < nb[0] or b[0] > nb[2] or b[3] < nb[1] or b[1] > nb[3]:
            continue
        if not rim.intersects(near):
            continue
        if core.intersection(geom).area / core.area < COAST_SHARE:
            continue
        piece = rim.intersection(near).difference(geom)
        if later is not None and not piece.is_empty:
            piece = piece.difference(later)
        if piece.is_empty:
            continue
        # ТОЛЬКО ПРИМЫКАЮЩЕЕ. Кусок каймы, отрезанный от материка, всплывает
        # плавучим островом: 18.09.2026 на срезе 1830 года у грузинского берега
        # так появились 517 км² отдельным полигоном ровно на кромке коробки.
        for q in (piece.geoms if hasattr(piece, 'geoms') else [piece]):
            if (q.geom_type == 'Polygon' and not q.is_empty
                    and q.distance(geom) < 1e-9):
                add.append(q)
    if not add:
        return geom
    # СКЛЕИВАЕМ ТОЛЬКО ЗАДЕТОЕ. unary_union по всей империи пересобирает узлы
    # ВЕЗДЕ и сдвигает вершины на доли секунды по всему контуру: 18.09.2026 это
    # дало 9 244 щепки общей площадью 63 км² от Дуная до Амура и подняло чекер
    # геометрии - 86 новых мест, +975 находок «прямая» там, где мы ничего не
    # правили. Поэтому куски, которых прибавка не касается, отдаём как были.
    addg = unary_union(add)
    parts = list(geom.geoms) if geom.geom_type == 'MultiPolygon' else [geom]
    hit = [p for p in parts if p.intersects(addg)]
    rest = [p for p in parts if not p.intersects(addg)]
    merged = unary_union(hit + [addg])
    mp = [g for g in (merged.geoms if hasattr(merged, 'geoms') else [merged])
          if g.geom_type == 'Polygon']
    if rest or len(mp) > 1:
        return MultiPolygon(rest + mp)
    return mp[0]


def fill_source_gaps(geom, year, whole=0.5, report=None):
    """Заливает дырки, которые у источника не государство, а его обрезок.

    ЗАЧЕМ. На срезе 1686-05-06 было две такие: под Ахтыркой (её нашёл куратор,
    рождается на «Левобережной Украине», обрезанной контуром 1700 года) и под
    Лугой (рождается на «Псковской земле», взятой контуром 1500 года). Обе -
    щели между РАЗНЫМИ ГОДАМИ источника внутри земли, которая по обе стороны
    имперская. Источник формально отдаёт их Речи Посполитой, но отдаёт краем
    огромного полигона, а не анклавом.

    ПРАВИЛО. Смотрим кусок источника, накрывающий дырку. Если дырка - это
    практически весь этот кусок (доля >= `whole`), значит перед нами настоящее
    соседнее государство внутри нашего контура: Великое княжество Рязанское до
    1521 года, Новгород-Северский до 1503-го. Такую дырку не трогаем. Если
    дырка - малая доля большого куска, это наш шов, и мы его закрываем.

    Вычитания (имамат, Черкесия, утраты) идут ПОЗЖЕ, их дырки сюда не попадают.
    """
    parts = src_parts(year)
    polys = list(geom.geoms) if geom.geom_type == 'MultiPolygon' else [geom]
    out = []
    for g in polys:
        keep = []
        for r in g.interiors:
            hp = Polygon(r)
            if hp.area <= 0:
                continue
            best, bnm, bshare = 0.0, '-', 0.0
            for p, nm in parts:
                if not p.intersects(hp):
                    continue
                inter = p.intersection(hp).area
                if inter > best:
                    best, bnm, bshare = inter, nm, hp.area / p.area
            enclave = best / hp.area >= 0.5 and bshare >= whole
            c = hp.centroid
            if report is not None:
                report.append((hp.area, round(c.x, 3), round(c.y, 3), bnm,
                               round(100 * bshare, 1), 'оставлена' if enclave
                               else 'закрыта'))
            if enclave:
                keep.append(r)
        out.append(Polygon(g.exterior, keep) if len(keep) != len(g.interiors) else g)
    return unary_union(out).buffer(0)


def fill_water(geom, share=0.6, max_km2=100000.0):
    """Заливает внутренние кольца, которые больше чем на `share` - вода.

    Кольца крупнее max_km2 не трогаются (24.09.2026): с северным Ираном на
    срезах 1941-1945 годов (пачка 4) дырой контура стал весь Каспий, 371 тыс.
    км²; его заливка с обрезкой по суше оставляла у Кулалы, Тюленьих,
    Огурчинского и Апшерона около 2 тыс. км² красного моря (check_sea_crumbs).
    Байкал, Ладога, Балхаш и Арал меньше порога - для них всё по-прежнему."""
    water = water_mask()
    if water is None:
        return geom
    polys = list(geom.geoms) if geom.geom_type == 'MultiPolygon' else [geom]
    out = []
    for g in polys:
        keep = []
        for r in g.interiors:
            hp = Polygon(r)
            if hp.area <= 0 or hp.intersection(water).area / hp.area <= share:
                keep.append(r)
                continue
            km2 = hp.area * 111.32 ** 2 * math.cos(math.radians(hp.centroid.y))
            if km2 > max_km2:
                keep.append(r)
        out.append(Polygon(g.exterior, keep) if len(keep) != len(g.interiors) else g)
    return unary_union(out).buffer(0)


def fill_holes(geom, max_area=3.0):
    """Заделать внутренние дырки современной нарезки.

    26.08.2026, по жалобе куратора («точка круглая несколько десятилетий не
    занята никем»): у Natural Earth территория аренды космодрома Байконур
    вынесена в отдельную единицу с admin='Baykonur Cosmodrome', поэтому в
    объединении областей Казахстана на её месте остаётся дыра 0.75 град².
    В срезах XIX века это выглядело так, будто империя обошла стороной
    круглый кусок степи, — артефакт аренды 1994 года, попавший в 1865 год.
    Дырки крупнее max_area не трогаем: это могут быть настоящие анклавы
    (озёра-моря, чужие территории внутри).
    """
    polys = list(geom.geoms) if geom.geom_type == 'MultiPolygon' else [geom]
    out = []
    for g in polys:
        holes = [r for r in g.interiors if Polygon(r).area >= max_area]
        out.append(Polygon(g.exterior, holes) if len(holes) != len(g.interiors) else g)
    return unary_union(out).buffer(0)


_FILEGEOM = {}


def file_geom(rel):
    """Курируемая геометрия из файла data/<rel>: объединение всех фич.

    Нужна там, где нарезка Natural Earth слишком крупная. Первый случай -
    чуйские двоеданцы: Кош-Агачский и Улаганский районы Республики Алтай,
    выгруженные из OpenStreetMap (admin_level=6).
    """
    if rel not in _FILEGEOM:
        with open(os.path.join(DATA, rel), encoding='utf-8') as f:
            fc = json.load(f)
        _FILEGEOM[rel] = unary_union(
            [shape(x['geometry']).buffer(0) for x in fc['features']]).buffer(0)
    return _FILEGEOM[rel]


def occupation_geom(day, prefix):
    """Действующие на дату приобретения-оккупации, чей регион начинается с
    prefix ('PERSIA_' - Персия 1909-1918). Для слоёв ПМВ и зон: они строятся не
    из таблицы ADDS, а окна гарнизонов держит одна таблица (22.09.2026)."""
    if isinstance(day, str):
        day = key_date(day)
    parts = [reg_geom(a['reg']) for a in ADDS
             if a['reg'].startswith(prefix) and d(a['frm']) <= day
             and not (a['to'] and d(a['to']) <= day)]
    return unary_union(parts).buffer(0) if parts else unary_union([])


def file_units(rel, names):
    """Объединение фич файла data/<rel> с properties.name из списка names."""
    with open(os.path.join(DATA, rel), encoding='utf-8') as f:
        fc = json.load(f)
    sel = [x for x in fc['features'] if x['properties'].get('name') in names]
    miss = set(names) - {x['properties'].get('name') for x in sel}
    if miss:
        raise SystemExit(f'{rel}: нет единиц {sorted(miss)}')
    return unary_union([shape(x['geometry']).buffer(0) for x in sel]).buffer(0)


def hb_core(year):
    """Ядро империи в файле historical-basemaps этого года (как в build_data).

    Результат кэшируется НА ДИСК (29.08.2026): сборка одного года стоит около
    ста секунд - почти всё съедает fill_water, заливка озёр по маске воды в
    600 тысяч вершин. Лет-источников больше десятка, и на каждом прогоне
    сборщик платил заново; отсюда полчаса на шаг. Ключ файла включает отпечаток
    списка имён из build_data.CORE: поменяется таблица - поменяется имя файла,
    и кэш пересчитается сам. Куратор: «может полностью свою карту, чтобы один
    раз сделать а потом только подгружать».
    """
    tag = f'__hb{year}'
    if tag not in _cache:
        import hashlib
        from shapely import wkb as _wkb
        names = bd.CORE[year]
        h = hashlib.md5('|'.join(sorted(names)).encode()).hexdigest()[:8]
        path = os.path.join(CACHE, f'hb_core_{year}_{h}.wkb')
        if os.path.exists(path):
            with open(path, 'rb') as f:
                _cache[tag] = _wkb.loads(f.read())
            return _cache[tag]
        with open(bd.fetch(year), encoding='utf-8') as f:
            src = json.load(f)
        geoms = []
        for feat in src['features']:
            n, s = bd.name_of(feat), bd.subj_of(feat)
            if n in bd.CORE_EXCLUDE:
                continue
            if n in names or s in names:
                geoms.append(shape(feat['geometry']).buffer(0))
        if not geoms:
            raise SystemExit(f'historical-basemaps: пусто для {year} {names}')
        # Крупные внутренние озёра источник режет НЕПОСЛЕДОВАТЕЛЬНО: в
        # world_1800 Ладога и Онега - дырки в контуре империи, в world_1815 они
        # залиты, в world_1880 снова дырки. На карте это читалось как «империя
        # обошла озеро стороной» - у дырки своя красная обводка, ровно как у
        # настоящего выреза. Между 1800 и 1815 годом с Ладогой ничего не
        # случилось: два файла источника нарисованы разными руками.
        _cache[tag] = fill_water(unary_union(geoms))
        with open(path, 'wb') as f:
            f.write(_cache[tag].wkb)
    return _cache[tag]


def cs_core(y, m, dd):
    tag = f'__cs{y}{m}{dd}'
    if tag not in _cache:
        hit = None
        for feat in cs_feats():
            p = feat['properties']
            if p.get('gwcode') != 365:
                continue
            if (p['gwsyear'], p['gwsmonth'], p['gwsday']) <= (y, m, dd) <= \
               (p['gweyear'], p['gwemonth'], p['gweday']):
                hit = feat
        if hit is None:
            raise SystemExit(f'CShapes: нет gwcode 365 на {y}-{m:02d}-{dd:02d}')
        _cache[tag] = shape(hit['geometry']).buffer(0)
    return _cache[tag]


def hb_named(year, name):
    """Отдельная фича файла источника по имени (NAME).

    Нужна ранним срезам: Псков и Рязань в файле 1500 года лежат отдельными
    государствами, и приближать их современными областями незачем - контур
    источника точнее и он из того же семейства данных, что основа среза.
    """
    tag = f'__hbn{year}{name}'
    if tag not in _cache:
        with open(bd.fetch(year), encoding='utf-8') as f:
            src = json.load(f)
        geoms = [shape(feat['geometry']).buffer(0) for feat in src['features']
                 if bd.name_of(feat) == name]
        if not geoms:
            raise SystemExit(f'historical-basemaps {year}: нет фичи NAME={name}')
        _cache[tag] = unary_union(geoms)
    return _cache[tag]


# Западный предел уступленной по конвенции 18.03.1867 территории (ст. I):
# линия через Берингов пролив посередине между островами Ратманова и
# Крузенштерна (168°58'37" з. д.), к северу - по этому меридиану в Ледовитый
# океан, к югу - посередине между островом Св. Лаврентия и мысом Чукотским до
# 172° з. д. и дальше на юго-запад. Всё, что западнее этой линии, - Чукотка,
# не Русская Америка: кусок восточнее 180° (Уэлен, Провидения, остров
# Ратманова) лежит в западных долготах, но продан не был. До 05.09.2026
# сборщик снимал его вместе с Аляской (срезы 1867-1914 без восточной Чукотки).
CHUKOTKA_WEST_OF_1867_LINE = None


def chukotka_side():
    global CHUKOTKA_WEST_OF_1867_LINE
    if CHUKOTKA_WEST_OF_1867_LINE is None:
        from shapely.geometry import Polygon
        CHUKOTKA_WEST_OF_1867_LINE = Polygon([
            (-180.0, 50.0), (-172.0, 55.0), (-172.0, 62.0), (-171.7, 63.9),
            (-168.977, 65.6), (-168.977, 75.0), (-180.0, 75.0)])
    return CHUKOTKA_WEST_OF_1867_LINE


def is_russian_america(p):
    """Кусок западного полушария, лежащий восточнее линии 1867 г."""
    return p.bounds[2] < -30 and not chukotka_side().contains(p.centroid)


def alaska():
    """Русская Америка: западное полушарие среза источника 1815 г.
    восточнее линии конвенции 1867 г. (восточная Чукотка не входит)."""
    if '__ak' not in _cache:
        g = hb_core(1815)
        parts = list(g.geoms) if g.geom_type == 'MultiPolygon' else [g]
        west = [p for p in parts if is_russian_america(p)]
        if not west:
            raise SystemExit('срез 1815: не найдено западное полушарие (Аляска)')
        _cache['__ak'] = unary_union(west)
    return _cache['__ak']


def reg_geom(name):
    if name in _cache:
        return _cache[name]
    parts = []
    for spec in REG[name]:
        kind = spec[0]
        if kind == 'ne':
            parts.append(ne_pick(spec[1], spec[2]))
        elif kind == 'ne_region':
            # единицы страны по полю region Natural Earth (исторические земли
            # Латвии: Vidzeme, Riga, Latgale, Kurzeme, Zemgale)
            parts.append(ne_pick_region(spec[1], spec[2]))
        elif kind == 'ne_box':
            parts.append(ne_pick(spec[1], spec[2]).intersection(box(*spec[3])))
        elif kind == 'ne_minus':
            # регион минус курируемые куски из файлов: замена прямоугольных
            # рамок настоящими границами (01.09.2026)
            g0 = ne_pick(spec[1], spec[2])
            for path in spec[3]:
                g0 = g0.difference(file_geom(path))
            parts.append(g0)
        elif kind == 'ne_az_no_nakh':
            parts.append(ne_pick('Azerbaijan', None)
                         .difference(reg_geom('AZ_NAKHCHIVAN')))
        elif kind == 'hb_name':
            parts.append(hb_named(spec[1], spec[2]))
        elif kind == 'file':
            # курируемая геометрия из файла data/<путь>
            parts.append(file_geom(spec[1]))
        elif kind in ('and_file', 'minus_file'):
            # не кусок, а маска: объединение остальных кусков режется по
            # файлу или без файла (22.09.2026 - земля Речи Посполитой по
            # контурам OHM)
            continue
        elif kind == 'file_where':
            # единицы курируемого файла по именам (22.09.2026: районы
            # Восточной Анатолии OSM для оккупаций 1828-1878)
            parts.append(file_units(spec[1], spec[2]))
        elif kind == 'alaska':
            parts.append(alaska())
        else:
            raise SystemExit(f'неизвестный вид региона: {spec}')
    g = unary_union(parts).buffer(0)
    for spec in REG[name]:
        if spec[0] == 'and_file':
            g = g.intersection(file_geom(spec[1])).buffer(0)
        elif spec[0] == 'minus_file':
            g = g.difference(file_geom(spec[1])).buffer(0)
    if g.is_empty:
        raise SystemExit(f'пустая геометрия региона {name}')
    _cache[name] = g
    return g


# ---- срезы источника -------------------------------------------------------
# ключ -> ('hb', год) | ('cs', (год, месяц, день)); только 1500-1914, дальше
# начинается реконструкция 1917-1921 и её мы не трогаем
SRC = {str(y): ('hb', y) for y in bd.CORE}
SRC.update({k: ('cs', v) for k, v in bd.CSHAPES_SLICES.items()
            if key_date(k) <= date(1914, 12, 31)})
# НАЧАЛО ПОКРЫТИЯ - 1450 год (решение куратора 26.08.2026 при сверке с атласом
# УІФ). Своего среза на 1450 у источника нет и быть не может: на CDN есть
# world_1300, world_1400 и world_1492, но не 1450/1470/1478, а world_1400
# Московского княжества не знает вовсе (его место занимает «Blue Horde») -
# тот же класс дефекта, что у world_1930. Поэтому основой окна 1450-1492 взят
# КОНТУР 1492 ГОДА, из которого вычитается то, чего у Москвы на дату ещё нет:
# новгородская земля до 15.01.1478, Вологда с Заозерьем до 11.08.1471, Тверь
# до 12.09.1485, Вятка до 16.08.1489 (SUBS выше). Приобретения этого окна
# обрезаны контуром 1492 г. (clip='1492'), поэтому срезы 1492 и 1500 годов от
# правки не поменялись ни на градус.
SRC['1450'] = ('hb', 1492)
SRC_ORDER = sorted(SRC, key=key_date)
# дальше 25.12.1917 начинается реконструкция зоны контроля 1917-1921 - её
# срезы собирает другой билдер, сюда мы не лезем
RECON_FROM = date(1917, 12, 25)


def src_geom(key):
    kind, val = SRC[key]
    return hb_core(val) if kind == 'hb' else cs_core(*val)


def base_year(key):
    """Год среза historical-basemaps, если база оттуда; иначе None.

    У баз из CShapes (с 1886 года) полного набора государств мира в том же
    формате нет, и щели там не заливаем - только сообщаем о них.
    """
    kind, val = SRC[key]
    return val if kind == 'hb' else None


def base_key_for(day):
    cur = SRC_ORDER[0]
    for k in SRC_ORDER:
        if key_date(k) <= day:
            cur = k
    return cur


def _round(g):
    def walk(c):
        if isinstance(c[0], (int, float)):
            return [round(c[0], DIGITS), round(c[1], DIGITS)]
        return [walk(x) for x in c]
    return gc.clean_rings({'type': g['type'], 'coordinates': walk(g['coordinates'])})


def active(day):
    adds = [a for a in ADDS if d(a['frm']) <= day
            and (a['to'] is None or day < d(a['to']))]
    subs = [s for s in SUBS if (s['frm'] is None or d(s['frm']) <= day)
            and (s['to'] is None or day < d(s['to']))]
    return adds, subs


def build(key):
    """Собрать срез key. -> (fc, лог) либо (None, причина) если правок нет."""
    day = key_date(key)
    bkey = base_key_for(day)
    geom = src_geom(bkey)
    adds, subs = active(day)
    if not adds and not subs:
        return None, 'правок нет', 0
    log, added, removed = [], [], []
    for a in adds:
        g = reg_geom(a['reg'])
        if a['clip']:
            g = g.intersection(src_geom(a['clip']))
        before = geom.area
        geom = unary_union([geom, g])
        added.append({'name': a['name'], 'from': a['frm'], 'to': a['to'],
                      'act': a['act'], 'source': a['src'], 'kind': a['kind'],
                      'region': a['reg'],
                      'approximate': a['reg'] != 'ALASKA',
                      'geometry_source': ('срез источника 1815 г.'
                                          if a['reg'] == 'ALASKA' else NE)
                      + (f'; обрезано контуром источника {a["clip"]} г.'
                         if a['clip'] else '')})
        if geom.area - before > 0.5:
            log.append(f'+ {a["name"]} ({a["frm"]}): '
                       f'{before:.0f} -> {geom.area:.0f} град²')
    # Швы между контуром источника и добавленными областями оставляют дырки:
    # у среза 1721-08-30 на стыке Ништадтских приобретений с контуром 1715 г.
    # зияла дыра 1.04 град² поперёк Чудского озера. Закрываем ЗДЕСЬ - до
    # вычитаний: RESIST (имамат, Черкесия) и утраты идут ниже, и их дырки
    # трогать нельзя, они содержательные.
    geom = fill_water(geom)
    # Берег, который срезала генерализация источника (18.09.2026). Куратор по
    # кадру Кинбурна: контур historical-basemaps не доходит до береговой линии -
    # от берега Natural Earth до ближайшего красного на срезе 1800 года 11,5 км,
    # и обрезка к суше (припуск 5 км) тут ни при чём. Сетка 0,02° по Северному
    # Причерноморью: 8,1 % имперской суши чёрные и в 1800, и в 1900 - 69 кучек,
    # около 9 500 км²: Одесский берег и низовья Дуная, Сиваш с Арабатской
    # стрелкой, Южный берег Крыма, Керченский полуостров, Тарханкут, Очаков,
    # Кинбурнская коса, Тамань.
    # ПРАВИЛО. Достраиваем берег ТОЛЬКО у тех единиц Natural Earth, чьё ЯДРО
    # (единица, съеденная внутрь на ту же ширину) уже внутри контура на 90 % и
    # больше. Долю берём по ядру, а не по всей площади: у приморской единицы
    # кайма и есть то, чего не хватает, и по полной площади Крым давал 86 %, то
    # есть сам себя не пускал. Чужая земля так попасть не может: единица,
    # которой империя не держит, ядром внутри контура не лежит.
    # ЗАЛИВКА ИДЁТ ДО ВЫЧИТАНИЙ: Буджак, Кабарда и прочее режутся ниже и режутся
    # снова, так что вернуть вырезанное она не может.
    # ВЕСЬ МИР, а не коробка (с 22.09.2026). Мировой замер 18.09.2026 без
    # якоря по воде давал 203 тыс. км² на 1800 и 519 тыс. км² на 1900, почти
    # всё - арктический берег Сибири; сухопутная щель с Китаем в Алматинской
    # области была внутренней и теперь не пройдёт: кайма считается от моря.
    geom = fill_coast(geom, day)
    # Щели на стыке контура источника с современной нарезкой областей: заливаем
    # только там, где источник и так даёт землю империи (см. fill_source_gaps).
    by = base_year(bkey)
    if by is not None:
        gaps = []
        geom = fill_source_gaps(geom, by, report=gaps)
        for a_, x_, y_, nm_, sh_, verdict in gaps:
            if a_ >= 0.02:
                print(f'   ~ дырка {a_:7.4f} град² у {x_},{y_}: {verdict} '
                      f'(источник: {nm_}, дырка = {sh_}% его куска)')
    # Действующее окно оккупации вычитаниями не режется (22.09.2026, пачка 7):
    # вычитание RP_1793 чернит землю Речи Посполитой, а гарнизоны в ней -
    # оккупация, красная до дня ухода войск; окно само кончается этим днём
    occ = [reg_geom(a['reg']) for a in adds if a['kind'] == 'оккупация']
    occ = unary_union(occ).buffer(0) if occ else None
    for s in subs:
        before = geom.area
        if s['reg'] == 'ALASKA':
            # после продажи 1867 г. западное полушарие уходит целиком: контур
            # Аляски у среза 1880 г. чуть иной, чем у 1815-го, вычитанием
            # полигона его до конца не снять
            parts = (list(geom.geoms) if geom.geom_type == 'MultiPolygon'
                     else [geom])
            geom = unary_union([p for p in parts if not is_russian_america(p)])
        else:
            cut = reg_geom(s['reg']).buffer(SUB_BUF)
            if occ is not None:
                cut = cut.difference(occ)
            geom = geom.difference(cut)
        removed.append({'name': s['name'], 'from': s['frm'], 'to': s['to'],
                        'why': s['why'], 'region': s['reg']})
        if before - geom.area > 0.5:
            log.append(f'- {s["name"]}: {before:.0f} -> {geom.area:.0f} град²')
    geom = geom.simplify(SIMPLIFY).buffer(0)
    geoms = [g for g in (list(geom.geoms) if geom.geom_type == 'MultiPolygon'
                         else [geom]) if g.area > 0.002]
    geom = unary_union(geoms)
    geom, sea = gc.clip_to_land(geom, CACHE)
    geom, wet = gc.drop_sea_parts(geom, CACHE)
    geom, thin = gc.drop_thin_parts(geom)
    geom, specks, pinholes = gc.despeckle(geom, CACHE)
    # Курируемые точные береговые линии общая чистка не трогает (22.09.2026):
    # Соловки по береговой линии Natural Earth лежат «в море» (кремль на
    # берегу бухты Благополучия), drop_sea_parts обрезал остров, а
    # drop_thin_parts снимал остаток - строка SOLOVKI с 19.09 стояла в списке
    # приобретений, а на карте островов не было (BACKLOG Б6 п. 2)
    prot = [reg_geom(a['reg']) for a in adds if a['reg'] in EARLY_PROTECT]
    if prot:
        geom = unary_union([geom] + prot).buffer(0)
    if sea or thin or wet or specks or pinholes:
        log.append(f'- обрезка по суше: снято {sea}, ободков снято: {thin}, '
                   f'кусков в открытой воде снято: {wet}, капель снято: {specks}, '
                   f'точечных дырок закрыто: {pinholes}')
    props = {
        'name': 'Российская империя',
        'year': key,
        'role': 'core',
        'reconstruction': True,
        'approximate': True,
        'expansion': True,
        'base': (('контур источника 1492 г. (historical-basemaps) - своего '
                  'среза на 1450 у источника нет, окно 1450-1492 собрано '
                  'вычитаниями из контура 1492 года') if bkey == '1450' else
                 f'контур источника {bkey} ('
                 + ('historical-basemaps' if SRC[bkey][0] == 'hb'
                    else 'CShapes 2.0') + ')'),
        'added': added,
        'removed': removed,
        'source': ('КУРИРУЕМЫЙ СРЕЗ РАСПОЛЗАНИЯ (19.08.2026): контур источника '
                   f'{bkey} плюс приобретения по актам, действующие на '
                   f'{key}, минус территории, которых на эту дату у империи '
                   'ещё или уже нет. Приобретения приближены современными '
                   'административными единицами (Natural Earth admin-1), '
                   'кроме Русской Америки - её контур берём из среза источника '
                   '1815 г. Даты актов по старому стилю, как в ПСЗРИ. '
                   'Собрано tools/build_expansion.py, проверка - '
                   'tools/check_expansion.py по data/crosscheck/expansion.csv'),
    }
    # ОДНА фича на срез: свойства тяжёлые (список приобретений с актами), а
    # островов в контуре под две сотни - раскладывать их по фичам значит
    # продублировать метаданные двести раз и раздуть файл в двадцать раз
    fc = {'type': 'FeatureCollection',
          'features': [{'type': 'Feature', 'geometry': _round(mapping(geom)),
                        'properties': props}]}
    return fc, log, len(geoms)


# ============================================================================
# ПОЗДНЕЕ ОКНО: 18.03.1921 - 26.12.1991
# ============================================================================
# Раньше 18.03.1921 сюда не лезем вовсе: окно 12.1917-03.1921 держит
# tools/build_zones_1917_1921.py, это чужая геометрия.
#
# Эта стадия НЕ пересобирает срезы с нуля - она ПРАВИТ уже лежащие на диске
# файлы (их пишут build_data.py, build_pact_1939.py, build_ww2.py и конвейер
# атласа) и заводит новые ключи копией базового среза. Правки идемпотентны:
# вычитание Тувы дважды даёт тот же контур. Поэтому стадию надо гонять
# ПОСЛЕДНЕЙ, после build_ww2.py:
#
#     .venv/bin/python tools/build_expansion.py --only late
#
# Что чинится:
#  1. ТУВА. Танну-Тува провозгласила независимость 14.08.1921 и вошла в СССР
#     11.10.1944, а на карте краснела с 12.03.1940 - дефект контура CShapes
#     (у него между 18.03.1921 и 11.03.1940 вообще один интервал).
#  2. БАТУМ. Аджария в контурах CShapes 1921-1946 гг. обрезана по берегу так,
#     что Батуми оказывается вне полигона, хотя Аджарская АССР образована
#     16.07.1921 и из СССР не выходила. Тот же класс дефекта, что Тбилиси до
#     правки 1801 года, чинится курируемым добавлением.
#  3. РАСПАД СССР. Между срезами 1946 и 1992 у карты не было ни одного среза -
#     46 лет одной ступенькой, распада империи на карте не существовало.
#     Геометрия машиночитаемая целиком: CShapes даёт контур каждой из
#     четырнадцати республик, и разность «СССР 1946 минус четырнадцать
#     республик» СОВПАДАЕТ с контуром РФ 1992 года ровно, без единого
#     заусенца (проверено: symmetric_difference = 0.0).
LATE_FROM = date(1921, 3, 18)
LATE_DIGITS = 4          # ~11 м: точнее ранних срезов, чтобы не сдвинуть
                         # проверки check_ww2 по якорям

# Даты выхода республик - ПО КОНТРОЛЮ, а не по декларациям (правило куратора
# 19.08.2026: показ бинарный, красное = империя тут была). Республика уходит
# из контура в тот день, когда республика забрала себе союзные структуры на
# своей территории и центр это принял, а не в день декларации о суверенитете.
# Отсюда:
#  * ЛИТВА объявила независимость 11.03.1990, но карта её в этот день не
#    отпускает: с апреля 1990 Москва держала экономическую блокаду, в январе
#    1991 войска и ОМОН брали в Вильнюсе телебашню и Дом печати (13.01.1991,
#    14 убитых). Контроль империя потеряла с провалом путча 21.08.1991;
#  * ГРУЗИЯ - 09.04.1991: референдум 31.03.1991, Акт о восстановлении
#    государственной независимости, всесоюзный референдум 17.03.1991
#    республика не проводила и Союзный договор не подписывала;
#  * КАЗАХСТАН - 16.12.1991, последним.
# (gwcode CShapes, имя, дата выхода, акт, источник)
# строки - data/core/republics.csv (с 24.09.2026; комментарии строк - колонка comment)
REPUBLICS = core_tables.load('REPUBLICS')
USSR_END = '1991-12-26'
USSR_END_ACT = (
    'декларация Совета Республик Верховного Совета СССР № 142-Н от '
    '26.12.1991 о прекращении существования СССР; Беловежское соглашение '
    '08.12.1991, Алма-Атинская декларация 21.12.1991, отставка президента '
    'СССР 25.12.1991')

# правки уже лежащих на диске срезов: ('sub'|'add', провайдер, с, по, что,
# почему). Провайдер: ('reg', имя из REG) | ('cs', gwcode)
# Регионы поздних правок, которые чистка контура не трогает: мелкая
# курируемая геометрия, меньше порогов крапинок (см. patch_slice)
LATE_PROTECT = {'DDR_1953_13', 'DDR_1953_3', 'SOLOVKI'}

# строки - data/core/late_edits.csv (с 24.09.2026; комментарии строк - колонка comment)
LATE_EDITS = core_tables.load('LATE_EDITS')

# новые ключи, которых на диске нет: (ключ, базовый ключ, что случилось)
# строки - data/core/late_new.csv (с 24.09.2026; комментарии строк - колонка comment)
LATE_NEW = core_tables.load('LATE_NEW')


def cs_country(code, on=(1992, 1, 1)):
    """Контур страны CShapes по gwcode на дату (по умолчанию 01.01.1992)."""
    tag = f'__csc{code}{on}'
    if tag not in _cache:
        hit = None
        for feat in cs_feats():
            p = feat['properties']
            if p.get('gwcode') != code:
                continue
            if (p['gwsyear'], p['gwsmonth'], p['gwsday']) <= on <= \
               (p['gweyear'], p['gwemonth'], p['gweday']):
                hit = feat
        if hit is None:
            raise SystemExit(f'CShapes: нет gwcode {code} на {on}')
        _cache[tag] = shape(hit['geometry']).buffer(0)
    return _cache[tag]


def late_geom(spec):
    """Геометрия правки позднего окна.

    ('reg', имя)              - регион из REG (современная нарезка);
    ('cs', gwcode)            - контур страны CShapes;
    ('reg_cs', имя, дата)     - регион, ОБРЕЗАННЫЙ контуром СССР на эту дату.
        Нужен возврату Тувы 11.10.1944: современная нарезка Natural Earth шире
        того, что рисует CShapes, и без обрезки добавление сдвинуло бы границу
        в Монголию на 0,08 град² (~900 км²). Возвращаем ровно то, что вычли.
    """
    if spec[0] == 'reg':
        return reg_geom(spec[1])
    if spec[0] == 'cs':
        return cs_country(spec[1])
    if spec[0] == 'reg_cs':
        return reg_geom(spec[1]).intersection(cs_core(*spec[2]))
    raise SystemExit(f'неизвестный источник геометрии правки: {spec}')


def _round_n(g, digits):
    def walk(c):
        if isinstance(c[0], (int, float)):
            return [round(c[0], digits), round(c[1], digits)]
        return [walk(x) for x in c]
    return gc.clean_rings({'type': g['type'], 'coordinates': walk(g['coordinates'])})


def years_path(key):
    return os.path.join(DATA, 'years', key + '.geojson')


def late_edits_for(day):
    adds, subs = [], []
    for op, spec, frm, to, name, why in LATE_EDITS:
        if d(frm) <= day and (to is None or day < d(to)):
            (adds if op == 'add' else subs).append((spec, name, why, frm, to))
    return adds, subs


def patch_slice(key, adds, subs, extra_note=None):
    """Наложить правки на файл среза. -> список строк лога."""
    path = years_path(key)
    with open(path, encoding='utf-8') as f:
        fc = json.load(f)
    log, touched = [], False
    sub_geom = unary_union([late_geom(s[0]) for s in subs]).buffer(LATE_SUB_BUF) \
        if subs else None
    # 03.09.2026: запас вычитания (5,5 км) не должен есть то, что на этом же
    # срезе добавляется. Иначе между вычтенным севером 1930 г. и добавленным
    # Ненецким округом оставалась чёрная полоса в 5 км - на карте читалась как
    # внутренняя граница (разбор loop_2026-09-03/B2_shvy.md)
    if sub_geom is not None and adds:
        # добавление буферизуется тем же запасом: иначе полоса запаса вдоль
        # границы добавленного куска (уже внутри соседней земли) оставалась
        # чёрной - шов Ненецкого округа 1929 г. шириной 5,5 км
        sub_geom = sub_geom.difference(
            unary_union([late_geom(a[0]) for a in adds]).buffer(LATE_SUB_BUF))
    feats = []
    for feat in fc['features']:
        if sub_geom is None:
            feats.append(feat)
            continue
        g = shape(feat['geometry']).buffer(0)
        g2 = g.difference(sub_geom)
        if g.area - g2.area <= 1e-9:
            feats.append(feat)
            continue
        touched = True
        if g2.is_empty:
            continue
        feat = dict(feat)
        g2 = gc.finish(g2, CACHE)
        feat['geometry'] = _round_n(mapping(g2), LATE_DIGITS)
        feats.append(feat)
    if subs and touched:
        log.append('- ' + ', '.join(s[1] for s in subs))
    if adds:
        have = unary_union([shape(f['geometry']).buffer(0) for f in feats])
        new = unary_union([late_geom(a[0]) for a in adds]).difference(have)
        # 1e-4 град² (~1 км²) - порог шума округления до 4 знаков: без него
        # повторный прогон каждый раз «дописывал» бы заусенец толщиной в метр
        if new.area > 1e-4:
            touched = True
            # 03.09.2026: шов между добавленным куском и ядром закрывается.
            # Кусок идёт по нарезке Natural Earth/OSM, а край ядра - по контуру
            # источника (атлас 1922, CShapes): между ними остаётся полоса
            # ничейной земли до 5-6 км (Ненецкий округ 1929: чёрная лента
            # между тундрой и Коми). Полоса, где кусок и ядро ближе 0,06°
            # друг к другу, заливается; вода снимается обрезкой по суше ниже
            # лента режется по СУШЕ без припуска (иначе она перекрывает устья
            # Оби, Енисея, Хатанги и Печоры, и заливы становятся дырками)
            # have режется окрестностью куска до буфера: лента лежит в
            # new.buffer(0.06), и ближе 0,06 к ней может быть только ядро в
            # 0,12 от куска. Равносильно прежнему, но не буферизует всю
            # империю (4 минуты на срез позднего окна, 22.09.2026)
            near = have.intersection(new.buffer(0.12))
            band = new.buffer(0.06).intersection(near.buffer(0.06))
            if not band.is_empty:
                band = band.intersection(gc.land_mask(CACHE))
            if not band.is_empty:
                new = unary_union([new, band]).buffer(0)
            # швы между кусками самого добавления (север 1930: Таймыр, Эвенкия,
            # Ямал, Гыдан лежат рядом с волосяными зазорами) закрываются
            # морфологически: раздуть на 0,03°, сжать обратно, оставить сушу
            closed = new.buffer(0.03).buffer(-0.03)
            if not closed.is_empty:
                new = unary_union([new, closed.intersection(gc.land_mask(CACHE))]).buffer(0)
            # кусок ВСЕГДА сливается с ядром в одну фичу. Раньше при
            # нескольких фичах он дописывался отдельной фичей, и обводка
            # рисовала его границу как границу империи - красные линии внутри
            # красного (Ненецкий округ 1929, север 1930). Слияние - через
            # merge_core_features: волосяные зазоры закрываются.
            feats.append({'type': 'Feature',
                          'geometry': _round_n(mapping(new), LATE_DIGITS),
                          'properties': {'name': 'Российская империя',
                                         'year': key, 'role': 'core',
                                         'reconstruction': True,
                                         'approximate': True,
                                         'expansion': True,
                                         'late_fix': [a[1] for a in adds],
                                         'source': 'курируемая правка '
                                         'дефекта контура источника, '
                                         'tools/build_expansion.py'}})
            merged = gc.merge_core_features({'type': 'FeatureCollection', 'features': feats})
            feats = merged['features']
            g = shape(feats[0]['geometry']).buffer(0)
            # карманы воды, замкнутые лентой шва (устья, губы до пары сотен км²),
            # заливаются как вода, а не остаются дырками с красной обводкой
            g = fill_water(g)
            g, _ = gc.fill_sea_holes(g, CACHE)
            g, _ = gc.clip_to_land(g, CACHE)
            g, _ = gc.drop_thin_parts(g)
            g, _, _ = gc.despeckle(g, CACHE)
            # Курируемая мелкая геометрия чисткой не снимается (22.09.2026):
            # города ГДР 1953 года меньше порога крапинки (200 км²), и
            # despeckle снял бы Галле, Йену, Мерзебург как обрезки. Возвращаем
            # их по суше после всей чистки
            prot = [late_geom(a[0]) for a in adds
                    if a[0][0] == 'reg' and a[0][1] in LATE_PROTECT]
            if prot:
                land = gc.land_mask(CACHE)
                g = unary_union([g] + [pg.intersection(land) for pg in prot]).buffer(0)
            feats[0] = dict(feats[0])
            feats[0]['geometry'] = _round_n(mapping(g), LATE_DIGITS)
            log.append('+ ' + ', '.join(a[1] for a in adds))
    if not touched and not extra_note:
        return log
    for feat in feats:
        p = feat.setdefault('properties', {})
        p['late_edits'] = [
            {'op': 'add' if (spec, name, why, frm, to) in adds else 'sub',
             'name': name, 'from': frm, 'to': to, 'why': why}
            for spec, name, why, frm, to in adds + subs]
        if extra_note:
            p['late_note'] = extra_note
    fc['features'] = feats
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj(fc), f, ensure_ascii=False)
    return log


def ww2_slice(key, why):
    """Срез внутри окна ВМВ - той же моделью, что строит tools/build_ww2.py.

    Импорт, а не копия соседнего среза: помесячная сетка слоя ВМВ не знает
    промежуточных дат, а якорная проверка check_ww2 --anchors требует, чтобы
    первый срез после взятия города город уже показывал.
    """
    try:
        import build_ww2 as bw
    except ImportError as e:
        print(f'!! {key}: не собран ({e}) - нужен tools/build_ww2.py')
        return False
    fc, nparts, lost, abroad = bw.build(key, bw.Field(bw.load_anchors()))
    p = fc['features'][0]['properties']
    p['late_note'] = why
    with open(years_path(key), 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj(fc), f, ensure_ascii=False)
    print(f'OK data/years/{key}.geojson: модель ВМВ, частей {nparts}, '
          f'оккупировано {lost:.1f} град² - {why}')
    return True


def build_late():
    """Стадия 2: правки срезов 1921-1991 и датированный распад СССР."""
    with open(os.path.join(DATA, 'manifest.json'), encoding='utf-8') as f:
        mf = json.load(f)
    have = [str(y) for y in mf['years']]
    written = []

    # 1. новые ключи копией базового среза
    for key, base, why in LATE_NEW:
        if base == 'ww2':
            # срез внутри окна Второй мировой: копией соседнего его брать
            # нельзя - на 11.10.1944 фронт уже не там, где 1 октября, и
            # проверка check_ww2 --anchors это ловит (Сегед занят 11.10.1944).
            # Поэтому просим построить его ту же модель, что строит весь слой
            if not ww2_slice(key, why):
                continue
            written.append(key)
            continue
        if not os.path.exists(years_path(base)):
            print(f'!! {key}: нет базового среза {base} - пропущен')
            continue
        with open(years_path(base), encoding='utf-8') as f:
            src = json.load(f)
        g = unary_union([shape(x['geometry']).buffer(0)
                         for x in src['features']])
        fc = {'type': 'FeatureCollection', 'features': [{
            'type': 'Feature',
            'geometry': _round_n(mapping(gc.finish(g, CACHE)), LATE_DIGITS),
            'properties': {
                'name': 'Российская империя', 'year': key, 'role': 'core',
                'reconstruction': True, 'approximate': True,
                'expansion': True, 'base': f'контур среза {base}',
                'source': 'КУРИРУЕМЫЙ СРЕЗ ПОЗДНЕГО ОКНА '
                          '(tools/build_expansion.py --only late): ' + why}}]}
        with open(years_path(key), 'w', encoding='utf-8') as f:
            json.dump(gc.sanitize_obj(fc), f, ensure_ascii=False)
        written.append(key)
        print(f'OK data/years/{key}.geojson: копия среза {base} - {why}')

    # 2. срезы распада СССР: контур 1946 года минус республики, вышедшие к дате
    base46 = '1946'
    if os.path.exists(years_path(base46)):
        # у Эстонии, Латвии, Литвы и у пары Узбекистан/Кыргызстан дата
        # одна и та же - срез на дату должен учитывать их всех сразу
        for day in sorted({r[2] for r in REPUBLICS}):
            gone = [r for r in REPUBLICS if r[2] <= day]
            written.append(write_ussr_slice(day, gone, base46))
        written.append(write_ussr_slice(USSR_END, REPUBLICS, base46,
                                        final=True))

    # 3. правки уже лежащих срезов
    keys = sorted(set(have) | set(written), key=key_date)
    for key in keys:
        day = key_date(key)
        if day < LATE_FROM or not os.path.exists(years_path(key)):
            continue
        adds, subs = late_edits_for(day)
        if not adds and not subs:
            continue
        log = patch_slice(key, adds, subs)
        if log:
            print(f'   {key}: ' + '; '.join(log))

    update_manifest(written)
    dump_subs()
    print(f'позднее окно: новых срезов {len(written)}, '
          f'республик в таблице {len(REPUBLICS)}')


def write_ussr_slice(day, gone, base46, final=False):
    """Срез распада: контур 1946 г. минус контуры вышедших республик."""
    # base46 - константа '1946': читать и объединять срез на каждый из ~15
    # вызовов (по одному на дату выхода республики) незачем
    tag = f'__ussr{base46}'
    if tag not in _cache:
        with open(years_path(base46), encoding='utf-8') as f:
            src = json.load(f)
        _cache[tag] = unary_union([shape(x['geometry']).buffer(0)
                                   for x in src['features']])
    g = _cache[tag]
    cut = unary_union([cs_country(code) for code, *_ in gone])
    g = g.difference(cut)
    day_out = [r for r in gone if r[2] == day] or [gone[-1]]
    props = {
        'name': 'СССР' if not final else 'Российская Федерация',
        'year': day, 'role': 'core',
        'reconstruction': True, 'approximate': True, 'expansion': True,
        'base': 'контур СССР 1946 г. (CShapes 2.0, gwcode 365) минус контуры '
                'вышедших республик (CShapes 2.0)',
        'left': [{'name': n, 'from': dd, 'act': a, 'source': s}
                 for _, n, dd, a, s in gone],
        'source': (
            'КУРИРУЕМЫЙ СРЕЗ РАСПАДА СССР (26.08.2026, '
            'tools/build_expansion.py): у карты между срезами 1946 и 1992 не '
            'было ни одного среза - 46 лет одной ступенькой. Геометрия '
            'машиночитаемая целиком: разность контура СССР 1946 г. и контуров '
            'республик CShapes; сумма четырнадцати республик и остатка ровно '
            'равна контуру РФ 1992 г. Даты выхода - ПО КОНТРОЛЮ, а не по '
            'декларациям: показ бинарный. ')
        + (USSR_END_ACT if final
           else 'На эту дату вышли: '
                + '; '.join(f'{r[1]} - {r[3]}' for r in day_out)),
    }
    fc = {'type': 'FeatureCollection', 'features': [{
        'type': 'Feature',
        'geometry': _round_n(mapping(gc.finish(g, CACHE)), LATE_DIGITS),
        'properties': props}]}
    with open(years_path(day), 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj(fc), f, ensure_ascii=False)
    print(f'OK data/years/{day}.geojson: {props["name"]}, '
          f'{g.area:.0f} град², вышли {len(gone)} республик '
          f'(в этот день - {", ".join(r[1] for r in day_out)})')
    return day


def dump_subs():
    """Выгрузить таблицу вычитаний с геометрией: data/subs.geojson.

    ЗАЧЕМ (28.08.2026). Куратор, ткнув в чёрную дырку внутри Коми на срезе
    1585 года: «что за дырка? почему в попапе нет инфы?». Карта показывала
    чёрное, но не говорила, чем оно обосновано, хотя обоснование у каждого
    вычитания в таблице SUBS есть. Теперь оно уезжает в данные и попап истории
    точки может ответить: какая земля, с какой по какую дату вычтена и почему.
    """
    feats = []
    for s in SUBS:
        try:
            g = reg_geom(s['reg'])
        except SystemExit:
            continue
        g = g.simplify(0.01).buffer(0)
        if g.is_empty:
            continue
        feats.append({'type': 'Feature',
                      'properties': {'name': s['name'], 'why': s['why'],
                                     'from': s['frm'], 'to': s['to'],
                                     'reg': s['reg'], 'kind': 'sub'},
                      'geometry': _round_n(mapping(g), 3)})
    path = os.path.join(DATA, 'subs.geojson')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj({'type': 'FeatureCollection',
                                   'features': feats}), f, ensure_ascii=False)
    print(f'OK data/subs.geojson: вычитаний {len(feats)}, '
          f'{os.path.getsize(path) // 1024} КБ')


def build_early():
    keys = sorted(set(SRC_ORDER)
                  | {a['frm'] for a in ADDS}
                  | {a['to'] for a in ADDS if a['to']}
                  | {s['frm'] for s in SUBS if s['frm']}
                  | {s['to'] for s in SUBS if s['to']},
                  key=lambda k: (key_date(k), 0 if k in SRC else 1, len(k), k))
    keys = [k for k in keys if key_date(k) < RECON_FROM]
    # даты границ окон могут совпасть с уже существующим ключом среза
    # ('1500-01-01' и '1500' - один и тот же день): второй ключ дал бы на диске
    # файл-двойник и лишнюю ступеньку в листании ◀▶. Оставляем тот, что уже
    # есть у источника
    seen, uniq = set(), []
    for k in keys:
        if key_date(k) in seen:
            continue
        seen.add(key_date(k))
        uniq.append(k)
    keys = uniq
    written, skipped = [], []
    for key in keys:
        fc, log, nparts = build(key)
        if fc is None:
            skipped.append(key)
            continue
        path = os.path.join(DATA, 'years', key + '.geojson')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(gc.sanitize_obj(fc), f, ensure_ascii=False)
        written.append(key)
        p = fc['features'][0]['properties']
        print(f'OK data/years/{key}.geojson: частей {nparts}, '
              f'{os.path.getsize(path) // 1024} КБ, основа {p["base"]}, '
              f'приобретений {len(p["added"])}, вычитаний {len(p["removed"])}')
        for line in log:
            print('   ' + line)
    if skipped:
        print(f'без правок (файлы источника оставлены как есть): '
              f'{", ".join(skipped)}')
    print(f'срезов расползания: {len(written)}, приобретений в таблице: '
          f'{len(ADDS)}, вычитаний: {len(SUBS)}')
    update_manifest(written)


def preflight():
    """Проверка ДО первой записи на диск: все ли ключи и файлы на месте.

    ЗАЧЕМ (28.08.2026). Билдер писал срезы по одному и падал на середине, если
    в таблице приобретений или вычитаний стоял ключ региона, которого нет в
    REG. Карта после такого падения оставалась с половиной срезов - у куратора
    она просто исчезла. Данные должны меняться или не меняться, а приложение
    падать не должно. Теперь всё, что можно проверить заранее, проверяется
    заранее, и при первой же ошибке билдер не пишет НИЧЕГО.
    """
    bad = []
    seen = set()
    for src, rows in (('ADDS', ADDS), ('SUBS', SUBS)):
        for r in rows:
            reg = r['reg']
            if reg not in REG:
                bad.append(f'{src}: «{r["name"]}» ссылается на регион {reg}, '
                           f'которого нет в REG')
                continue
            if reg in seen:
                continue
            seen.add(reg)
            for spec in REG[reg]:
                if spec[0] in ('file', 'file_where', 'and_file',
                               'minus_file'):
                    path = os.path.join(DATA, spec[1])
                    if not os.path.exists(path):
                        bad.append(f'REG[{reg}]: нет файла data/{spec[1]}')
                    elif spec[0] == 'file_where':
                        try:
                            file_units(spec[1], spec[2])
                        except SystemExit as e:
                            bad.append(f'REG[{reg}]: {e}')
    if bad:
        print('!! таблицы не прошли проверку, НИ ОДИН срез не переписан:')
        for b in bad:
            print('   ' + b)
        raise SystemExit(1)
    print(f'проверка таблиц: регионов {len(seen)}, приобретений {len(ADDS)}, '
          f'вычитаний {len(SUBS)} — ок')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--only', choices=['early', 'late'],
                    help='early - только срезы 1450-1914; late - только '
                         'позднее окно 1921-1991 (Тува, Батум, распад СССР). '
                         'Позднюю стадию НАДО прогонять ещё раз ПОСЛЕ '
                         'build_ww2.py: тот перезаписывает срезы 1941-1945')
    args = ap.parse_args()
    preflight()
    if args.only != 'late':
        build_early()
    if args.only != 'early':
        build_late()
    # штамп порядка сборки: полный прогон и early - это шаг 1 канона,
    # прогон --only late - отдельный шаг ПОСЛЕ build_ww2
    gc.write_stamp('expansion-late' if args.only == 'late' else 'expansion')
    print('дальше: python3 tools/check_expansion.py и '
          'python3 tools/check_cities.py')


def update_manifest(written):
    """Завести новые ключи в манифест, не трогая остальные.

    build_data.py тоже умеет их подхватывать (он сканирует data/years на
    свойство expansion), но пересборка манифеста после этого билдера не
    обязательна - обновляем на месте.
    """
    path = os.path.join(DATA, 'manifest.json')
    with open(path, encoding='utf-8') as f:
        mf = json.load(f)
    mf['years'] = sorted(set(map(str, mf['years'])) | set(written),
                         key=key_date)
    mf['note_expansion'] = (
        'срезы 1500-1914 идут по КУРИРУЕМОЙ таблице приобретений '
        '(tools/build_expansion.py): контур источника плюс приобретения по '
        'актам минус то, чего у империи на дату ещё или уже нет. У источника '
        'между 1815 и 1880 годами нет ни одного среза, поэтому Закавказье, '
        'Средняя Азия, казахская степь, Приамурье и Черкесия появлялись '
        'скачком; регрессия - tools/check_expansion.py по '
        'data/crosscheck/expansion.csv')
    mf['note_resistance'] = (
        'показ бинарный (правило куратора 19.08.2026): территория, где идёт '
        'война за контроль, в контур не входит, сколько бы актов ни было '
        'подписано. Горная Чечня южнее Терека - до 19.08.1859, горный '
        'Дагестан - до 25.08.1859 (сдача Шамиля у Гуниба), левобережье Кубани '
        '- до 21.05.1864. Даты и пруфы из базы кампаний decolonial.ist '
        '(data/campaigns/*.json), список RESIST в tools/build_expansion.py, '
        'разбор - data/crosscheck/control_vs_act.csv')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj(mf), f, ensure_ascii=False, indent=1)
    print(f'OK data/manifest.json: срезов {len(mf["years"])}')


if __name__ == '__main__':
    main()
