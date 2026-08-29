#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Слой антиколониального сопротивления: 143 выступления с датами и геометрией.

ЗАЧЕМ. У атласа УІФ сопротивлению отдано пять полноценных разделов (18, 31, 37,
42, 51), на нашей карте этого сюжета не было как класса: из всего массива
показаны были три вычитания из контура по принципу «акт против контроля»
(RESIST в tools/build_expansion.py) - горная Чечня, горный Дагестан и
левобережье Кубани. Разбор - data/crosscheck/atlas_sync.md, раздел «В».

ФОРМА ПОКАЗА (задача куратора 26.08.2026, правило «красное = империя
контролировала»). Показ бинарный, штриховок у нас нет, поэтому выступления
делятся надвое:

  * УДЕРЖАЛИ территорию - вычитаем из красного на срок удержания. Это тот же
    механизм, которым уже показаны имамат (RESIST в tools/build_expansion.py) и
    Ичкерия 1996-1999 (paint=cut в tools/build_postsoviet.py): дырка в полигоне
    ядра, подложка видна насквозь;
  * НЕ УДЕРЖАЛИ - заливкой не показываем вовсе. Такое выступление живёт строкой
    в попапе истории точки: «на этой земле в такие-то годы шло восстание такое-то
    (источник)». Так карта не врёт и сюжет не теряется.

КРИТЕРИЙ УДЕРЖАНИЯ - три условия сразу, решение по фактам, не по масштабу:
  1) на территории работала СВОЯ государственность или администрация, а не
     только войско в поле;
  2) удержание длилось не меньше года подряд;
  3) территория на эту дату внутри контура империи - иначе вычитать нечего.

Кто прошёл критерий (колонки hold_from/hold_to в реестре):
  * Астрахань 24.06.1670 - 27.11.1671 (восстание Разина): полтора года городом
    распоряжался казацкий круг;
  * Башкортостан 1708-1711 (восстание 1704-1711 гг.): объявлена Башкирская орда
    со своим ханом, атлас прямо пишет о фактической независимости;
  * степи Среднего жуза 1841-1845 (восстание Кенесары Касымова): Кенесары избран
    ханом всех казахов, контроль империя вернула только после постройки шести
    укреплений в 1845-1847 гг.
Кто НЕ прошёл и почему - в колонке note реестра: «Пугачёвщина» (Оренбург, Уфа и
Яицкая крепость осаду выдержали, Казань удержана сутки), Булавин (два месяца),
Астраханское восстание 1705-1706 гг. (восемь месяцев), Кронштадт (восемнадцать
дней), Тамбов и басмачество (сёла держали, города и железные дороги - нет),
Западно-Сибирское 1921 г. (Тобольск шесть с половиной недель), Андижанское
(проиграно в первом бою), Среднеазиатское 1916 г. (Тургай не захвачен).
Имамат и Ичкерия удержание прошли, но УЖЕ показаны другими механизмами -
второй раз то же самое не вычитаем (paint=shown_elsewhere).

ГЕОМЕТРИЯ - только машиночитаемая, ничего не рисуется от руки. Спецификация
лежит в колонке `geo` реестра (и `hold_geo` - для выреза, если он у́же):
  * `city:Москва`        - точка из data/gazetteer.json плюс круг CITY_R;
  * `ne:Russia:Tambov|Pskov` - объединение областей Natural Earth admin-1;
  * `ne:Poland:*`        - вся страна из того же Natural Earth;
  * `file:data/...geojson` - курируемая геометрия из OpenStreetMap;
  * несколько кусков через `;`.
Всё помечено approximate: административная нарезка сегодняшнего дня - не
граница выступления XVII века, она даёт только «эта земля, примерно».

Вход:  data/resistance/registry.csv (143 строки, курируется руками)
Выход: data/resistance/uprisings.geojson - все выступления, для попапа;
       data/resistance/cuts.geojson      - только удержания, обрезанные
                                           контуром ядра, для выреза из красного;
       data/resistance/report.md         - таблица для куратора.

Запуск:  .venv/bin/python tools/build_uprisings.py
Проверка: .venv/bin/python tools/check_resistance.py
"""
import csv
import json
import os
import sys

import geoclean as gc
from datetime import date

from shapely.geometry import Point, mapping, shape
from shapely.ops import unary_union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'cache')
DATA = os.path.join(ROOT, 'data')
REG = os.path.join(DATA, 'resistance', 'registry.csv')
OUT = os.path.join(DATA, 'resistance', 'uprisings.geojson')
OUT_CUTS = os.path.join(DATA, 'resistance', 'cuts.geojson')
REPORT = os.path.join(DATA, 'resistance', 'report.md')

CITY_R = 0.35          # радиус круга вокруг города, градусы (~30 км)
SIMPLIFY = 0.03        # слой в отрисовку не идёт, нужен только point-in-polygon
SIMPLIFY_CUT = 0.005   # вырезы рисуются, им нужна точность
ND = 3                 # знаков после запятой

KINDS = {
    'national': 'антиколониальное национальное выступление',
    'urban': 'выступление горожан',
    'peasant': 'крестьянское выступление',
    'cossack': 'казацкое выступление',
    'religious': 'религиозное выступление',
    'military': 'выступление войск',
    'camp': 'восстание в лагере',
    'underground': 'вооружённое подполье',
    'worker': 'выступление рабочих',
    'satellite': 'выступление в стране под контролем империи',
}

# ---- источники геометрии ----------------------------------------------------
_cache = {}


def _ne():
    if 'ne' not in _cache:
        with open(os.path.join(CACHE, 'ne_admin1.geojson'), encoding='utf-8') as f:
            _cache['ne'] = json.load(f)['features']
    return _cache['ne']


def _gaz():
    if 'gaz' not in _cache:
        with open(os.path.join(DATA, 'gazetteer.json'), encoding='utf-8') as f:
            _cache['gaz'] = {c['n']: (c['x'], c['y']) for c in json.load(f)}
    return _cache['gaz']


def _heidata():
    """NameENG -> геометрия из heiDATA-1926 (см. data/peoples/RESEARCH.md)."""
    if 'hei' not in _cache:
        import shapefile
        path = os.path.join(CACHE, 'heidata_1926', '1926SovietUnion.shp')
        if not os.path.isfile(path):
            raise SystemExit(f'нет {path}: см. data/peoples/RESEARCH.md, '
                             f'раздел «Скачано и вписано 18.08»')
        rd = shapefile.Reader(path)
        flds = [f[0] for f in rd.fields[1:]]
        i = flds.index('NameENG')
        out = {}
        for sr in rd.shapeRecords():
            out[sr.record[i]] = shape(sr.shape.__geo_interface__).buffer(0)
        _cache['hei'] = out
    return _cache['hei']


def resolve_geo(spec, where=''):
    """Спецификация геометрии из таблицы -> shapely-геометрия (или None)."""
    spec = (spec or '').strip()
    if not spec:
        return None
    parts = []
    for chunk in spec.split(';'):
        chunk = chunk.strip()
        if not chunk:
            continue
        kind, _, rest = chunk.partition(':')
        if kind == 'city':
            xy = _gaz().get(rest)
            if xy is None:
                raise SystemExit(f'{where}: города «{rest}» нет в '
                                 f'data/gazetteer.json')
            parts.append(Point(*xy).buffer(CITY_R))
        elif kind == 'ne':
            admin, _, names = rest.partition(':')
            want = None if names.strip() == '*' else set(names.split('|'))
            sel = [f for f in _ne()
                   if f['properties'].get('admin') == admin
                   and (want is None or f['properties'].get('name') in want)]
            if want is not None:
                miss = want - {f['properties'].get('name') for f in sel}
                if miss:
                    raise SystemExit(f'{where}: в Natural Earth admin-1 нет '
                                     f'{sorted(miss)} ({admin})')
            if not sel:
                raise SystemExit(f'{where}: пустая выборка Natural Earth '
                                 f'{admin} {names}')
            parts.append(unary_union([shape(f['geometry']).buffer(0)
                                      for f in sel]))
        elif kind == 'file':
            # курируемый geojson из OpenStreetMap: нарезки районного уровня в
            # Natural Earth нет (Аяно-Майский район). Источник - в properties.
            with open(os.path.join(ROOT, rest), encoding='utf-8') as fh:
                fc = json.load(fh)
            parts.append(unary_union([shape(f['geometry']).buffer(0)
                                      for f in fc['features']]))
        elif kind == 'heidata':
            idx = _heidata()
            want = rest.split('|')
            miss = [n for n in want if n not in idx]
            if miss:
                raise SystemExit(f'{where}: в heiDATA-1926 нет {miss}')
            parts.append(unary_union([idx[n] for n in want]))
        else:
            raise SystemExit(f'{where}: неизвестный вид геометрии «{kind}»')
    g = parts[0] if len(parts) == 1 else unary_union(parts)
    return g.buffer(0)


# ---- ядро империи на дату ---------------------------------------------------
def core_key(iso):
    """Ключ среза ядра, действующего на дату (последний не позже неё)."""
    if 'keys' not in _cache:
        with open(os.path.join(DATA, 'manifest.json'), encoding='utf-8') as f:
            _cache['keys'] = list(json.load(f)['years'])
    best = None
    for k in _cache['keys']:
        if _norm(k) <= iso:
            best = k
    return best


def core(key):
    if ('core', key) not in _cache:
        with open(os.path.join(DATA, 'years', key + '.geojson'),
                  encoding='utf-8') as f:
            _cache[('core', key)] = unary_union(
                [shape(ft['geometry']).buffer(0)
                 for ft in json.load(f)['features'] if ft.get('geometry')])
    return _cache[('core', key)]


def _norm(s):
    """«1547» -> «1547-01-01», «1670-06» -> «1670-06-01»; для сравнения дат."""
    p = str(s).split('-')
    while len(p) < 3:
        p.append('01')
    return '%04d-%02d-%02d' % (int(p[0]), int(p[1]), int(p[2]))


def _d(iso):
    y, m, dd = (int(x) for x in _norm(iso).split('-'))
    return date(y, m, dd)




def _dump(geom, nd=ND):
    """mapping() с округлением координат - файл иначе распухает."""
    def walk(node):
        if isinstance(node[0], (int, float)):
            return [round(node[0], nd), round(node[1], nd)]
        return [walk(x) for x in node]
    m = mapping(geom)
    return {'type': m['type'], 'coordinates': walk(m['coordinates'])}


def main():
    if not os.path.exists(REG):
        raise SystemExit(f'нет таблицы {REG}')
    with open(REG, encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f)
                if r.get('name') and not r['name'].startswith('#')]

    feats, cuts, report, bad, nogeo = [], [], [], [], []
    for i, r in enumerate(rows, 2):
        name = r['name'].strip()
        kind = r['kind'].strip()
        if kind not in KINDS:
            bad.append(f'строка {i} ({name}): kind «{kind}» не из списка '
                       f'{sorted(KINDS)}')
            continue
        if not r.get('source', '').strip():
            bad.append(f'строка {i} ({name}): пустой источник')
        if not r.get('from', '').strip():
            bad.append(f'строка {i} ({name}): пустая дата начала')
            continue
        frm, to = _norm(r['from']), _norm(r.get('to') or r['from'])
        if to < frm:
            bad.append(f'строка {i} ({name}): «по» раньше «с»')
        hf = r.get('hold_from', '').strip()
        ht = r.get('hold_to', '').strip()
        if hf and not ht:
            bad.append(f'строка {i} ({name}): есть hold_from без hold_to')
        # чем показываем
        if hf and r.get('hold_geo', '').strip():
            paint = 'cut'
        elif hf:
            paint = 'shown_elsewhere'   # имамат, Ичкерия - уже на карте
        else:
            paint = 'none'

        geom = resolve_geo(r.get('geo'), f'строка {i} ({name})')
        if geom is None:
            nogeo.append(name)
        props = {
            'name': name, 'name_ru': r['name_ru'].strip(),
            'people': r.get('people', '').strip(),
            'from': frm, 'to': to,
            'from_raw': r['from'].strip(), 'to_raw': (r.get('to') or '').strip(),
            'territory': r.get('territory', '').strip(),
            'kind': kind, 'kind_ru': KINDS[kind],
            'event': r.get('event', '').strip(),
            'source': r.get('source', '').strip(),
            'confidence': r.get('confidence', '').strip(),
            'note': r.get('note', '').strip(),
            'paint': paint,
            'hold_from': hf, 'hold_to': ht,
            'hold_note': r.get('hold_note', '').strip(),
            'geometry_source': r.get('geo', '').strip(),
            'approximate': True,
        }
        if geom is not None:
            feats.append({'type': 'Feature', 'properties': props,
                          'geometry': _dump(geom.simplify(
                              SIMPLIFY, preserve_topology=True))})
        # вырез: геометрия удержания, обрезанная контуром ядра на дату начала
        if paint == 'cut':
            hg = resolve_geo(r['hold_geo'], f'строка {i} ({name}) hold_geo')
            key = core_key(_norm(hf))
            ck = core(key)
            clipped = hg.intersection(ck).buffer(0)
            share = clipped.area / hg.area if hg.area else 0
            if clipped.is_empty:
                bad.append(f'строка {i} ({name}): удержанная территория целиком '
                           f'вне контура империи на {hf} (срез {key}) - '
                           f'вычитать нечего')
                continue
            if share < 0.2:
                bad.append(f'строка {i} ({name}): внутри контура империи только '
                           f'{share:.0%} удержанной территории (срез {key}) - '
                           f'проверь geo и даты')
            cuts.append({'type': 'Feature', 'properties': dict(
                props, core_key=key, inside_share=round(share, 3),
                geometry_source=r['hold_geo'].strip() +
                f' ∩ ядро на срезе {key}'),
                'geometry': _dump(clipped.simplify(
                    SIMPLIFY_CUT, preserve_topology=True))})
        report.append((frm, to, r['name_ru'].strip(), KINDS[kind], paint,
                       r.get('people', '').strip(),
                       r.get('source', '').strip()))

    if bad:
        print('ОШИБКИ ТАБЛИЦЫ:')
        for b in bad:
            print(' ', b)
        sys.exit(1)

    feats.sort(key=lambda f: (f['properties']['from'], f['properties']['name']))
    cuts.sort(key=lambda f: f['properties']['hold_from'])
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj({'type': 'FeatureCollection',
                   'note': 'антиколониальное сопротивление, '
                           'tools/build_uprisings.py; в отрисовку слой не идёт, '
                           'нужен попапу истории точки',
                   'features': feats}), f, ensure_ascii=False,
                  separators=(',', ':'))
    with open(OUT_CUTS, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj({'type': 'FeatureCollection',
                   'note': 'территории, которые сопротивление УДЕРЖАЛО: '
                           'вычитаются из красного на срок удержания',
                   'features': cuts}), f, ensure_ascii=False,
                  separators=(',', ':'))
    report.sort()
    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write('# Антиколониальное сопротивление: что показывает карта\n\n')
        f.write('Собрано `tools/build_uprisings.py` из '
                '`data/resistance/registry.csv`.\n\n'
                'Колонка «показ»: `cut` - территория вычитается из красного на '
                'срок удержания; `shown_elsewhere` - удержание уже показано '
                'другим механизмом (имамат - `RESIST` в '
                '`tools/build_expansion.py`, Ичкерия - слой постсоветских '
                'эпизодов); `none` - заливкой не показываем, выступление живёт '
                'строкой в попапе истории точки.\n\n')
        f.write('| с | по | выступление | тип | показ | народ | источник |\n')
        f.write('|---|---|---|---|---|---|---|\n')
        for row in report:
            f.write('| ' + ' | '.join(x.replace('|', '/') for x in row) + ' |\n')

    print(f'{OUT}: {len(feats)} выступлений с геометрией из {len(rows)} строк')
    if nogeo:
        print(f'  БЕЗ ГЕОМЕТРИИ (в попапе не найдутся): {nogeo}')
    print(f'{OUT_CUTS}: {len(cuts)} удержаний')
    for c in cuts:
        p = c['properties']
        print(f'  {p["hold_from"]}..{p["hold_to"]} {p["name_ru"]} '
              f'(срез {p["core_key"]}, внутри контура {p["inside_share"]:.0%})')
    print(f'{REPORT}: таблица для куратора')
    print('\nдальше: .venv/bin/python tools/check_resistance.py')


if __name__ == '__main__':
    main()
