#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Западная граница СССР 1939-1941 по Дополнительному протоколу от 04.10.1939.

ЗАЧЕМ. Срезы 1939-1941 у нас были построены разностью контуров CShapes, а
западной рамкой в этой разности служит ПОСЛЕВОЕННЫЙ контур. Белосток в 1945
году вернулся Польше, поэтому разность его не содержала: наша линия шла по
Западному Бугу вместо Нарева и Писсы, то есть восточнее реальной советской
границы 1939-1941 (README, ограничение 16). Тем же образом терялись Ломжа,
Августов, Лубачув, правобережный Перемышль и Бещады.

ЧТО ДЕЛАЕТ. Собирает линию раздела из открытого Дополнительного протокола от
04.10.1939 (Ведомости ВС СССР 1940 № 10 (73); RGBl. 1940 II Nr. 1, S. 4 ff.) -
единственного документа пакета, официально опубликованного обеими сторонами.
Протокол расписывает линию 41 сегментом; выписка с параллельным немецким
текстом и таблицей отождествления рек -
data/sources/treaties/molotov-ribbentrop-1939/border_description.md, разд. 4.

ИЗ ЧЕГО СТРОИТСЯ ГЕОМЕТРИЯ (ничего не рисуется от руки):

  * РЕКИ - OpenStreetMap через Overpass API, waterway=river|stream по именам
    (Czarna Hańcza, Marycha, Wołkuszanka, Blizna, Pisa, Narew, Orz, Brok, Bug /
    Заходні Буг / Західний Буг, Солокія, Łówcza, Gnojnik, Lubaczówka,
    San / Сян). Кэш - cache/osm_border1939/*.json, качает
    tools/fetch_border_1939.py. Отрезок русла между двумя точками берётся
    поиском кратчайшего пути по графу слитых линий (Дейкстра), а не
    «сортировкой точек» - иначе меандры складываются в зигзаг.
  * СЕГМЕНТ 12 («по бывшей русско-германской государственной границе») -
    южная граница Варминско-Мазурского воеводства из Natural Earth admin-1:
    это и есть та самая граница Восточной Пруссии 1914 года, дожившая до
    наших дней административной линией.
  * ПРЯМЫЕ «УСЛОВНЫЕ ЛИНИИ» протокола (сегменты 3, 7-8, 10-11, 16-19, 22-25,
    28-32, 35-38) - отрезки между населёнными пунктами, названными в
    протоколе; координаты пунктов - OSM (place=*), кэш там же. Сам протокол
    (Примечание 2) объявляет эти участки подлежащими уточнению при
    демаркации, то есть точнее прямой между деревнями документ не даёт.

ЧТО ОСТАЛОСЬ ПРИБЛИЖЕНИЕМ (список честности, он же в README):
  * ТОЧКИ, КОТОРЫХ НЕТ В OSM - семь штук: оз. Едрыно (сегмент 3), д. Жабиково
    (22), д. Пецки (24), д. Надбужнэ (25), д. Бжезина (31), фольварок Сиглы
    (33), ручей Пшикопа у д. Добча (39-40). Каждая взята на прямой между
    соседними названными пунктами и прогнана через approx() - список с
    координатами и объяснением печатается при запуске.
  * СЕВЕРНЫЙ КОНЕЦ (сегменты 1-4). Протокол начинает линию на р. Игорка у
    границы с Литвой; мы начинаем её на Чёрной Ганьче у устья Марыхи и
    продлеваем на северо-восток за пределы Польши, потому что дальше на север
    линия 1939 года - это германо-литовская граница, а не советская, и на наш
    контур она не влияет.
  * КАНАВЫ И РУЧЬИ БЕЗ ИМЕНИ (сегменты 6, 15, 21) заменены прямыми: у
    безымянной канавы в OSM нет ни имени, ни способа её опознать.
  * ЛИНИЯ ЕСТЬ, А ДЕМАРКАЦИИ НЕТ. Комиссия 09.10.1939 уточняла линию на
    местности и наносила её на карту 1:25 000 - эта карта не оцифрована.

ЧТО ДАЁТ НА ВЫХОДЕ:
  data/border_1939.geojson  - сама линия с посегментной разметкой: у каждой
                              фичи номер сегмента и его текст из протокола;
  soviet_west_1939()        - полигон территории, добавляемой срезам 1939-1941:
                              всё ВОСТОЧНЕЕ линии внутри современной Польши
                              (Белостокская область БССР, Ломжа, Августов,
                              Лубачувщина, правобережье Сана, Бещады) - 2.88
                              град², две части. Идёт в слой фактов для попапа;
  soviet_west_1939_show()   - он же с нахлёстом 0.12 град на восток: у соседа
                              (кусок 1939 года) западная кромка обрезана
                              контуром CShapes, который генерализован на
                              5-10 км, и без нахлёста между ними остаются
                              щели-волоски. Идёт в геометрию срезов.

ПРИМЕНЯЕТСЯ ТОЛЬКО К ОКНУ 17.09.1939 - 21.06.1941. Срез 29.06.1945 и всё
послевоенное эту геометрию НЕ получают: Белосток вернулся Польше по договору о
советско-польской границе от 16.08.1945, и там наша прежняя линия верна.

Запуск (из корня репозитория, нужен shapely из .venv):

    .venv/bin/python tools/fetch_border_1939.py     # один раз, качает OSM
    .venv/bin/python tools/build_border_1939.py     # линия + отчёт
"""
import heapq
import json
import math
import os
import sys

import geoclean as gc

from shapely.geometry import (LineString, MultiLineString, Point, box,
                              mapping)
from shapely.ops import linemerge, split, substring, unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_data as bd            # noqa: E402
import build_expansion as be       # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OSM = os.path.join(ROOT, 'cache', 'osm_border1939')
DATA = bd.OUT
OUT_SIMPLIFY = 0.0003      # ~30 м: хранимая линия, счёт идёт по полной

PROTOCOL = ('Дополнительный протокол к германо-советскому договору о дружбе и '
            'границе от 04.10.1939, разд. I (открытый, ратифицирован; '
            '«Ведомости Верховного Совета СССР» 1940 № 10 (73), RGBl. 1940 II '
            'Nr. 1, S. 4 ff.). Выписка по 41 сегменту с параллельным немецким '
            'текстом - data/sources/treaties/molotov-ribbentrop-1939/'
            'border_description.md, разд. 4')


# ---------------------------------------------------------------------------
# 1. Загрузка кэша OSM
# ---------------------------------------------------------------------------
def _load(fname):
    p = os.path.join(OSM, fname + '.json')
    if not os.path.exists(p):
        raise SystemExit(f'нет кэша {p}: сначала tools/fetch_border_1939.py')
    with open(p, encoding='utf-8') as f:
        return json.load(f)['elements']


_ways = None
_places = None


def ways():
    global _ways
    if _ways is None:
        _ways = []
        for f in ('rivers', 'rivers_east'):
            for e in _load(f):
                if e.get('type') == 'way' and e.get('geometry'):
                    _ways.append((e['tags'].get('name', ''),
                                  LineString([(p['lon'], p['lat'])
                                              for p in e['geometry']])))
    return _ways


def places():
    """{имя: [(lat, lon), ...]} по всем кэшам населённых пунктов."""
    global _places
    if _places is None:
        _places = {}
        for f in ('places_north', 'places_north2', 'places_mazovia',
                  'places_bug', 'places_south', 'places_south2'):
            for e in _load(f):
                t = e.get('tags', {})
                lat = e.get('lat') or (e.get('center') or {}).get('lat')
                lon = e.get('lon') or (e.get('center') or {}).get('lon')
                if lat is None or not t.get('name'):
                    continue
                _places.setdefault(t['name'], []).append((lat, lon))
    return _places


def P(name, near=None):
    """Точка населённого пункта по имени; near - подсказка (lat, lon)."""
    cand = places().get(name)
    if not cand:
        raise SystemExit(f'OSM: не найден пункт «{name}»')
    if near is None:
        if len({(round(a, 3), round(b, 3)) for a, b in cand}) > 1:
            raise SystemExit(f'OSM: «{name}» неоднозначен, нужен near=')
        lat, lon = cand[0]
    else:
        lat, lon = min(cand, key=lambda c: (c[0] - near[0]) ** 2
                       + (c[1] - near[1]) ** 2)
    return (round(lon, 5), round(lat, 5))


def off(pt, dlat=0.0, dlon=0.0):
    """Сдвиг от центра деревни к названной в протоколе окраине (в градусах)."""
    return (round(pt[0] + dlon, 5), round(pt[1] + dlat, 5))


def mid(a, b, w=0.5):
    return (round(a[0] + (b[0] - a[0]) * w, 5),
            round(a[1] + (b[1] - a[1]) * w, 5))


# ---------------------------------------------------------------------------
# 2. Отрезок русла между двумя точками - кратчайший путь по графу
# ---------------------------------------------------------------------------
def _pieces(name_re, bbox=None):
    import re
    rx = re.compile(name_re)
    sel = []
    bb = box(*bbox) if bbox else None
    for n, ls in ways():
        if not rx.search(n):
            continue
        if bb is not None:
            ls2 = ls.intersection(bb)
            if ls2.is_empty:
                continue
            sel += [g for g in (ls2.geoms if ls2.geom_type == 'MultiLineString'
                                else [ls2]) if g.geom_type == 'LineString'
                    and g.length > 0]
        else:
            sel.append(ls)
    if not sel:
        raise SystemExit(f'OSM: нет русел по «{name_re}» в {bbox}')
    m = linemerge(sel)
    return list(m.geoms) if m.geom_type == 'MultiLineString' else [m]


def _cut(pieces, pt):
    """Разрезать ближайший кусок в проекции точки; вернуть новый список."""
    p = Point(pt)
    i = min(range(len(pieces)), key=lambda k: pieces[k].distance(p))
    ln = pieces[i]
    d = ln.project(p)
    out = pieces[:i] + pieces[i + 1:]
    for a, b in ((0, d), (d, ln.length)):
        if b - a > 1e-12:
            out.append(substring(ln, a, b))
    return out, tuple(round(c, 9) for c in ln.interpolate(d).coords[0])


def river(name_re, a, b, bbox=None, label=''):
    """Русло от точки a до точки b: кратчайший путь по слитым линиям."""
    pieces = _pieces(name_re, bbox)
    pieces, na = _cut(pieces, a)
    pieces, nb = _cut(pieces, b)
    # граф: узлы - концы кусков (округлённые), рёбра - сами куски
    def key(c):
        return (round(c[0], 9), round(c[1], 9))
    graph = {}
    for ln in pieces:
        u, v = key(ln.coords[0]), key(ln.coords[-1])
        if u == v:
            continue
        graph.setdefault(u, []).append((v, ln.length, ln))
        graph.setdefault(v, []).append((u, ln.length, LineString(
            list(ln.coords)[::-1])))
    if na not in graph or nb not in graph:
        raise SystemExit(f'русло {label or name_re}: точка вне графа')
    dist = {na: 0.0}
    prev = {}
    q = [(0.0, na)]
    seen = set()
    while q:
        dd, u = heapq.heappop(q)
        if u in seen:
            continue
        seen.add(u)
        if u == nb:
            break
        for v, w, ln in graph.get(u, ()):
            if dist.get(v, 1e18) > dd + w:
                dist[v] = dd + w
                prev[v] = (u, ln)
                heapq.heappush(q, (dist[v], v))
    if nb not in prev and nb != na:
        raise SystemExit(f'русло {label or name_re}: путь не найден '
                         f'(куски не сшиваются)')
    coords = []
    cur = nb
    chain = []
    while cur != na:
        u, ln = prev[cur]
        chain.append(ln)
        cur = u
    for ln in reversed(chain):
        cs = list(ln.coords)
        coords += cs if not coords else cs[1:]
    return coords


# ---------------------------------------------------------------------------
# 3. Сегмент 12 - бывшая русско-германская граница = южная кромка
#    Варминско-Мазурского воеводства
# ---------------------------------------------------------------------------
def old_reich_border(a, b):
    wm = be.ne_pick('Poland', ['Warmian-Masurian'])
    ring = LineString(list((wm.geoms[0] if wm.geom_type == 'MultiPolygon'
                            else wm).exterior.coords))
    da, db = ring.project(Point(a)), ring.project(Point(b))
    lo, hi = sorted((da, db))
    s1 = substring(ring, lo, hi)
    s2 = MultiLineString([substring(ring, hi, ring.length),
                          substring(ring, 0, lo)])
    take = s1 if s1.length <= s2.length else linemerge(s2)
    cs = list(take.coords) if take.geom_type == 'LineString' else \
        [c for g in take.geoms for c in g.coords]
    if Point(cs[0]).distance(Point(a)) > Point(cs[-1]).distance(Point(a)):
        cs = cs[::-1]
    return cs


# ---------------------------------------------------------------------------
# 4. Линия: 41 сегмент протокола, с севера на юг
# ---------------------------------------------------------------------------
APPROX = []          # точки, которых нет в OSM - для отчёта честности


def approx(name, pt, why):
    APPROX.append((name, pt, why))
    return pt


def build_line():
    # --- север: Сувалкский участок (сегменты 1-12) ----------------------
    czh_box = (22.7, 53.7, 23.7, 54.3)
    # устье Марыхи в Чёрной Ганьче (сегмент 2): берём точку схода двух русел
    mar = _pieces(r'^Marycha$', czh_box)
    czh = _pieces(r'^Czarna Hańcza$', czh_box)
    best = min(((m.distance(c), m, c) for m in mar for c in czh),
               key=lambda x: x[0])
    mm = best[2].interpolate(best[2].project(Point(best[1].coords[-1]
                             if Point(best[1].coords[-1]).distance(best[2])
                             < Point(best[1].coords[0]).distance(best[2])
                             else best[1].coords[0])))
    marycha_mouth = (round(mm.x, 5), round(mm.y, 5))

    wol = _pieces(r'^Wołkuszanka$', (23.2, 53.7, 23.7, 53.9))
    best = min(((w.distance(c), w, c) for w in wol for c in czh),
               key=lambda x: x[0])
    wm_ = best[2].interpolate(best[2].project(Point(best[1].coords[-1])))
    wolk_mouth = (round(wm_.x, 5), round(wm_.y, 5))

    ostrynskie = P('Ostryńskie', near=(53.803, 23.426))
    czarny_brod = P('Czarny Bród', near=(53.878, 23.203))
    szczebra = P('Szczebra')
    topilowka = P('Topiłówka')
    pruska = P('Pruska Mała')

    seg = []                    # [(номер, подпись, [координаты])]

    # 0 - продление на СВ за пределы Польши: севернее линия 1939 г. - это
    #     германо-литовская граница, наш контур она не задаёт
    seg.append((0, 'продление на СВ за границу Польши (не часть протокола)',
                [(23.90, 57.0), (23.90, 54.35), marycha_mouth]))
    # 3-4: прямые через оз. Едрыно - озера в OSM по этому имени нет
    jedryno = approx('оз. Едрыно (сегм. 3)',
                     mid(marycha_mouth, wolk_mouth, 0.45),
                     'озеро под этим именем в OSM не найдено; точка взята на '
                     'прямой между устьем Марыхи и устьем Волкушанки')
    seg.append((3, 'прямая к СВ оконечности оз. Едрыно и далее к Чёрной Ганьче '
                'против устья Волкушанки', [marycha_mouth, jedryno,
                                            wolk_mouth]))
    # 5: вверх по Волкушанке до пункта южнее д. Остриньске
    seg.append((5, 'вверх по р. Волкушанка до пункта южнее д. Остриньске',
                river(r'^Wołkuszanka$', wolk_mouth,
                      off(ostrynskie, dlat=-0.004),
                      (23.2, 53.7, 23.7, 53.9), 'Волкушанка')))
    # 6-8: канава, Чарны Бруд, ж/д мост через Близну у сев. окраины Щебры
    seg.append((6, 'по канаве на ЮЗ и СЗ, далее прямыми к д. Чарны Бруд и к ж/д '
                'мосту через р. Близна у северной окраины д. Щебра '
                '(канава безымянная - заменена прямыми)',
                [off(ostrynskie, dlat=-0.004), czarny_brod,
                 off(szczebra, dlat=0.005)]))
    # 9-10: вниз по Близне до перекрёстка, прямая к пункту севернее Топиловки
    bl = river(r'^Blizna$', off(szczebra, dlat=0.005),
               off(topilowka, dlat=0.008), (22.9, 53.85, 23.1, 54.0), 'Близна')
    seg.append((9, 'вниз по р. Близна до перекрёстка дорог Сувалки - Щебра II '
                'и Рачки - Щебра II', bl))
    seg.append((10, 'прямая к пункту севернее д. Топиловка и далее к бывшей '
                'русско-германской границе ~900 м ЮЗ д. Пруска Мала',
                [off(topilowka, dlat=0.008), off(pruska, dlat=-0.006,
                                                 dlon=-0.010)]))
    # 12: по бывшей русско-германской границе до пересечения с Писсой
    pisa_box = (21.4, 53.2, 22.1, 53.8)
    pisa = _pieces(r'^Pisa$', pisa_box)
    wm = be.ne_pick('Poland', ['Warmian-Masurian'])
    wm_line = (wm.geoms[0] if wm.geom_type == 'MultiPolygon' else wm).exterior
    xs = unary_union(pisa).intersection(wm_line)
    if xs.is_empty:
        raise SystemExit('Писса не пересекает границу Варминско-Мазурского')
    px = xs.geoms[0] if xs.geom_type.startswith('Multi') else xs
    pisa_cross = (round(px.x, 5), round(px.y, 5))
    seg.append((12, 'по бывшей русско-германской государственной границе '
                '(южная кромка Варминско-Мазурского воеводства - она же '
                'граница Восточной Пруссии 1914 г.) до пересечения с р. Писса',
                old_reich_border(off(pruska, dlat=-0.006, dlon=-0.010),
                                 pisa_cross)))
    # 13: вниз по Писсе до впадения в Нарев
    nar_box = (20.9, 52.7, 22.2, 53.4)
    nar = _pieces(r'^Narew$', nar_box)
    xs = unary_union(pisa).intersection(unary_union(nar).buffer(0.002))
    pm = xs.centroid
    pisa_mouth = (round(pm.x, 5), round(pm.y, 5))
    seg.append((13, 'вниз по р. Писса до впадения в р. Нарев',
                river(r'^Pisa$', pisa_cross, pisa_mouth, pisa_box, 'Писса')))
    # 14: вниз по Нареву до устья ручья у вост. окраины Ломж... - у Остроленки
    lawy = P('Ławy')
    nx = unary_union(nar)
    lp = nx.interpolate(nx.project(Point(off(lawy, dlon=-0.02))))
    narew_exit = (round(lp.x, 5), round(lp.y, 5))
    seg.append((14, 'вниз по р. Нарев до устья безымянного ручья между '
                'г. Остроленка и д. Островы',
                river(r'^Narew$', pisa_mouth, narew_exit, nar_box, 'Нарев')))
    # 15-19: ручей, Лавы, Суск, Трошын, Стылэнги, р. Ож у д. Бучин
    susk = P('Susk Stary')
    troszyn = P('Troszyn', near=(53.031, 21.733))
    stylagi = P('Stylągi')
    buczyn = P('Buczyn')
    seg.append((15, 'вверх по ручью к вост. окраине д. Лавы, далее прямыми: '
                'д. Суск - дорога Трошын - Рабенды - перекрёсток южнее '
                'д. Стылэнги - р. Ож южнее д. Бучин',
                [narew_exit, off(lawy, dlon=0.004), off(susk, dlat=-0.004),
                 off(troszyn, dlon=-0.005), off(stylagi, dlat=-0.004),
                 off(buczyn, dlat=-0.004)]))
    # 20-21: вверх по Ож до левого притока, по притоку до 1200 м вост.
    #        д. Малиново-Старэ
    sokolowo = P('Sokołowo')
    rogowek = P('Rogówek')
    orz_box = (21.4, 52.7, 22.1, 53.0)
    orz_to = mid(sokolowo, rogowek)
    seg.append((20, 'вверх по р. Ож до левого притока между д. Соколово и '
                'д. Роговэк',
                river(r'^Orz$', off(buczyn, dlat=-0.004), orz_to, orz_box,
                      'Ож')))
    malinowo = P('Malinowo Stare')
    seg.append((21, 'по притоку до пункта в 1200 м восточнее д. Малиново-Старэ '
                '(приток безымянный - заменён прямой)',
                [orz_to, off(malinowo, dlon=0.017)]))
    # 22-25: Острув-Мазовецка - Жабиково, р. Брочиско у Новой Золоторыи,
    #        Пецки, Западный Буг у д. Надбужнэ
    zlotoria = P('Nowa Złotoria')
    brok_box = (21.8, 52.65, 22.4, 53.0)
    brok = _pieces(r'^Brok$', brok_box)
    bx = unary_union(brok)
    zp = bx.interpolate(bx.project(Point(off(zlotoria, dlon=-0.006,
                                             dlat=0.004))))
    brok_pt = (round(zp.x, 5), round(zp.y, 5))
    zabikowo = approx('д. Жабиково (сегм. 22)',
                      mid(off(malinowo, dlon=0.017), brok_pt, 0.45),
                      'в OSM не найдена; точка взята на прямой между притоком '
                      'Ожа и р. Брочиско у Новой Золоторыи, юго-восточнее '
                      'г. Острув-Мазовецка (протокол оставляет Острув Германии)')
    nur = P('Nur', near=(52.668, 22.318))
    bug_box = (21.8, 49.8, 25.2, 52.8)
    bug = _pieces(r'^(Bug|Заходні Буг|Західний Буг)', bug_box)
    bgx = unary_union(bug)
    npt = bgx.interpolate(bgx.project(Point(off(nur, dlat=0.004))))
    bug_north = (round(npt.x, 5), round(npt.y, 5))
    pecki = approx('д. Пецки (сегм. 24)', mid(brok_pt, bug_north, 0.5),
                   'в OSM не найдена; точка взята на прямой между р. Брочиско '
                   'и Западным Бугом')
    nadbuzne = approx('д. Надбужнэ (сегм. 25)', bug_north,
                      'в OSM не найдена; точка выхода на Западный Буг взята у '
                      'с. Нур - протокол ставит её в 1500 м восточнее '
                      'д. Надбужнэ, то есть на этом же участке русла')
    seg.append((22, 'прямыми на ЮВ: шоссе Острув-Мазовецка - Жабиково - '
                'р. Брочиско у д. Нова Золоторыя - дорога южнее д. Пецки - '
                'р. Западный Буг в 1500 м восточнее д. Надбужнэ',
                [off(malinowo, dlon=0.017), zabikowo, brok_pt, pecki,
                 nadbuzne]))
    # 26: вверх по Западному Бугу до устья Солокии
    sol_box = (23.6, 50.2, 24.4, 50.6)
    sol = _pieces(r'^(Sołokija|Солокія)$', sol_box)
    slx = unary_union(sol)
    best = min(((s.distance(bgx), s) for s in sol), key=lambda x: x[0])
    sm = bgx.interpolate(bgx.project(Point(best[1].coords[-1]
                         if Point(best[1].coords[-1]).distance(bgx)
                         < Point(best[1].coords[0]).distance(bgx)
                         else best[1].coords[0])))
    sol_mouth = (round(sm.x, 5), round(sm.y, 5))
    seg.append((26, 'вверх по р. Западный Буг до устья р. Солокия',
                river(r'^(Bug|Заходні Буг|Західний Буг)', bug_north, sol_mouth,
                      bug_box, 'Западный Буг')))
    # 27: по Солокии до пункта против СЗ окраины с. Угнув
    uhniv = P('Угнів', near=(50.366, 23.750))
    up = slx.interpolate(slx.project(Point(off(uhniv, dlat=0.006,
                                               dlon=-0.006))))
    sol_end = (round(up.x, 5), round(up.y, 5))
    seg.append((27, 'по р. Солокия до пункта против СЗ окраины с. Угнув',
                river(r'^(Sołokija|Солокія)$', sol_mouth, sol_end, sol_box,
                      'Солокия')))
    # 28-32: Ходыванце, Журавце, Криница у Жилки, Бжезина, Пизуны
    chody = P('Chodywańce')
    zurawce = P('Żurawce')
    zylka = P('Żyłka')
    pizuny = P('Pizuny')
    brzezina = approx('д. Бжезина (сегм. 31)',
                      mid(off(zylka, dlat=-0.003, dlon=0.004),
                          off(pizuny, dlat=0.005, dlon=-0.011), 0.5),
                      'одноимённой деревни между Жилкой и Пизунами в OSM нет '
                      '(ближайшая Brzezina - в 30 км юго-западнее); точка '
                      'взята на прямой между ними')
    seg.append((28, 'прямыми на СЗ и ЮЗ: южная окраина д. Ходыванце - пункт '
                '~1300 м севернее д. Журавце - ручей Криница против '
                'д. Жилка - д. Бжезина - пункт ~800 м СЗ д. Пизуны',
                [sol_end, off(chody, dlat=-0.004), off(zurawce, dlat=0.012),
                 off(zylka, dlat=-0.003, dlon=0.004), brzezina,
                 off(pizuny, dlat=0.005, dlon=-0.011)]))
    # 33: ручей Лувча против д. Гарбы, вверх до фольварка Сиглы
    garby = P('Garby')
    lowcza = P('Łówcza', near=(50.293, 23.289))
    sigly = approx('фольварок Сиглы (сегм. 33)', off(lowcza, dlon=0.004),
                   'фольварка под этим именем в OSM нет; взята восточная '
                   'окраина д. Лувча, к которой протокол ведёт вверх по ручью')
    seg.append((33, 'прямая к ручью Лувча против ЮВ окраины д. Гарбы, вверх по '
                'ручью до фольварка Сиглы',
                [off(pizuny, dlat=0.005, dlon=-0.011),
                 off(garby, dlat=-0.003), sigly]))
    # 34: ручей Гнойник против с. Гораец, вниз до дороги Гораец - Цешанув
    gorajec = P('Gorajec', near=(50.269, 23.205))
    gn = _pieces(r'^Gnojnik$', (23.1, 50.2, 23.4, 50.35))
    gnx = unary_union(gn)
    g1 = gnx.interpolate(gnx.project(Point(off(gorajec, dlat=-0.003,
                                               dlon=0.004))))
    seg.append((34, 'прямая к ручью Гнойник против ЮВ окраины с. Гораец, вниз '
                'по ручью до пересечения дорогой Гораец - Цешанув',
                [sigly, (round(g1.x, 5), round(g1.y, 5))]))
    # 35-40: Цешанув, Дахнув, Футоры, Забяла, ручей Пшикопа у д. Добча
    cieszanow = P('Cieszanów')
    dachnow = P('Dachnów')
    futory = P('Futory')
    zabiala = P('Zabiała')
    dobcza = P('Dobcza')
    d1 = approx('ручей Пшикопа у д. Добча (сегм. 39-40)',
                off(dobcza, dlat=0.004, dlon=-0.004),
                'ручья Przykopa под этим именем у Добчи в OSM нет (ближайший '
                'одноимённый - канава в 22 км южнее, у устья Любачувки); взята '
                'СЗ окраина д. Добча, откуда линия идёт прямой к Любачувке')
    seg.append((35, 'прямыми на ЮЗ: вост. окраина с. Цешанув - зап. окраина '
                'д. Дахнув - ЮВ окраина д. Футоры - СЗ окраина д. Забяла - '
                'ручей Пшикопа против СЗ окраины д. Добча',
                [(round(g1.x, 5), round(g1.y, 5)), off(cieszanow, dlon=0.006),
                 off(dachnow, dlon=-0.006), off(futory, dlat=-0.003),
                 off(zabiala, dlat=0.004, dlon=-0.005), d1]))
    # 40: вниз по Пшикопе до Пшилубеня (низовье Любачувки), по ней до Сана
    san_box = (21.8, 48.9, 23.2, 50.3)
    lub_box = (22.5, 50.0, 23.3, 50.25)
    lub = _pieces(r'^Lubaczówka$', lub_box)
    san = _pieces(r'^(San|Сян|San - Сян|Сян - San)$', san_box)
    sanx = unary_union(san)
    lubx = unary_union(lub)
    # вход на Любачувку: ближайшая к точке у Добчи точка русла
    lin = lubx.interpolate(lubx.project(Point(d1)))
    lub_from = (round(lin.x, 5), round(lin.y, 5))
    # устье Любачувки: ближайшая к Сану точка русла
    lmouth_pt = min((Point(c) for g in lub for c in g.coords),
                    key=lambda p: p.distance(sanx))
    lub_to = (round(lmouth_pt.x, 5), round(lmouth_pt.y, 5))
    ls = sanx.interpolate(sanx.project(lmouth_pt))
    san_from = (round(ls.x, 5), round(ls.y, 5))
    seg.append((40, 'вниз по ручью Пшикопа до впадения в р. Пшилубен '
                '(низовье Любачувки), далее вниз по ней до впадения в р. Сан '
                '(Пшикопа заменена прямой - в OSM её нет)',
                [d1, lub_from]
                + river(r'^Lubaczówka$', lub_from, lub_to, lub_box,
                        'Любачувка') + [san_from]))
    # 41: вверх по Сану до истока
    src = max((Point(c) for g in san for c in g.coords), key=lambda p: -p.y)
    san_src = (round(src.x, 5), round(src.y, 5))
    seg.append((41, 'вверх по р. Сан до его истока (станции Сянки и Ужок - на '
                'стороне СССР)',
                river(r'^(San|Сян|San - Сян|Сян - San)$', san_from, san_src,
                      san_box, 'Сан')))
    seg.append((42, 'продление на юг за границу Польши (не часть протокола)',
                [san_src, (san_src[0], 45.0)]))

    coords = []
    for _, _, cs in seg:
        cs = [(round(c[0], 5), round(c[1], 5)) for c in cs]
        if coords and coords[-1] == cs[0]:
            cs = cs[1:]
        coords += cs
    # выкинуть подряд идущие дубли
    out = [coords[0]]
    for c in coords[1:]:
        if c != out[-1]:
            out.append(c)
    return LineString(out), seg


_line = None


def line():
    global _line
    if _line is None:
        _line = build_line()
    return _line


# ---------------------------------------------------------------------------
# 5. Полигон: всё восточнее линии внутри современной Польши
# ---------------------------------------------------------------------------
_east = None
EAST_PAD = 0.12      # ~10 км: нахлёст на соседей, чтобы закрыть шов с CShapes


def east_of_line():
    """Половина рамки, лежащая восточнее линии раздела."""
    global _east
    if _east is None:
        ls, _ = line()
        frame = box(14.0, 46.0, 30.0, 56.0)
        parts = list(split(frame, ls).geoms)
        if len(parts) < 2:
            raise SystemExit('линия не делит рамку надвое: '
                             'концы не выходят за неё')
        _east = max(parts, key=lambda g: g.centroid.x)
    return _east


def _clip(pl):
    g = east_of_line().intersection(pl).buffer(0)
    parts = [p for p in (g.geoms if g.geom_type == 'MultiPolygon' else [g])
             if p.area >= 0.004]      # заусенцы генерализации NE
    return unary_union(parts)


def soviet_west_1939():
    """Строгая версия: ровно современная Польша восточнее линии.

    Идёт в слой фактов (попап истории точки) - там нельзя залезать к соседям,
    иначе точка в Беларуси получит подпись про Белостокскую область.
    """
    return _clip(be.ne_pick('Poland', None))


def soviet_west_1939_show():
    """Версия для показа: та же территория с нахлёстом EAST_PAD на восток.

    Восточная кромка куска - государственная граница Польши по Natural Earth,
    а соседний кусок 1939 года обрезан контуром CShapes, который в Беловежской
    пуще и под Перемышлем генерализован на 5-10 км. Без нахлёста между ними
    остаются щели-волоски (проверено: 7 дырок, крупнейшая 0.010 град²).
    Нахлёст уходит в Гродненскую, Брестскую и Львовскую области, то есть в
    территорию, которая на этих же срезах и так красная.
    """
    return _clip(be.ne_pick('Poland', None).buffer(EAST_PAD))


# ---------------------------------------------------------------------------
def main():
    ls, seg = line()
    fc = {'type': 'FeatureCollection', 'features': []}
    for num, txt, cs in seg:
        if len(cs) < 2:
            continue
        g = LineString([(c[0], c[1]) for c in cs]).simplify(OUT_SIMPLIFY)
        fc['features'].append({
            'type': 'Feature', 'geometry': be._round(mapping(g)),
            'properties': {'segment': num, 'text': txt, 'source': PROTOCOL}})
    path = os.path.join(DATA, 'border_1939.geojson')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj(fc), f, ensure_ascii=False)
    print(f'OK data/border_1939.geojson: сегментов {len(seg)}, '
          f'точек {len(ls.coords)}, {os.path.getsize(path) // 1024} КБ')
    print(f'   линия: {ls.bounds[1]:.3f}..{ls.bounds[3]:.3f} с.ш., '
          f'{ls.bounds[0]:.3f}..{ls.bounds[2]:.3f} в.д., '
          f'длина {ls.length * 111:.0f} км (грубо)')
    g = soviet_west_1939()
    print(f'   полигон восточнее линии внутри Польши: {g.area:.2f} град² '
          f'(~{g.area * 111 * 111 * math.cos(math.radians(52)) / 1000:.0f} '
          f'тыс. км²), частей '
          f'{len(g.geoms) if g.geom_type == "MultiPolygon" else 1}')
    for city, lat, lon in (('Белосток', 53.132, 23.169),
                           ('Ломжа', 53.178, 22.075),
                           ('Августов', 53.844, 22.980),
                           ('Граево', 53.647, 22.454),
                           ('Кольно', 53.412, 21.934),
                           ('Замбрув', 52.985, 22.243),
                           ('Семятыче', 52.427, 22.868),
                           ('Сувалки', 54.099, 22.928),
                           ('Сейны', 54.106, 23.350),
                           ('Остроленка', 53.084, 21.567),
                           ('Острув-Мазовецка', 52.800, 21.898),
                           ('Бяла-Подляска', 52.032, 23.117),
                           ('Хелм', 51.143, 23.472),
                           ('Замосць', 50.722, 23.252),
                           ('Белжец', 50.385, 23.438),
                           ('Любыча-Крулевска', 50.341, 23.520),
                           ('Лубачув', 50.157, 23.123),
                           ('Ярослав', 50.017, 22.678),
                           ('Перемышль (левый берег)', 49.783, 22.760),
                           ('Медыка', 49.805, 22.930),
                           ('Леско', 49.470, 22.331),
                           ('Устшики-Дольне', 49.431, 22.594),
                           ('Санок', 49.556, 22.206)):
        print(f'   {city:26s} {"внутри" if g.contains(Point(lon, lat)) else "вне   "}')
    if APPROX:
        print('   ПРИБЛИЖЕНИЯ (точек нет в OSM):')
        for name, pt, why in APPROX:
            print(f'     - {name}: {pt[1]:.4f}, {pt[0]:.4f} - {why}')


if __name__ == '__main__':
    main()
