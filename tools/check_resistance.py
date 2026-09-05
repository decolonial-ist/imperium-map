#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Регрессия трёх новых слоёв: сопротивление, депортации, ликвидированные автономии.

Гоняет 82 проверки и падает с кодом 1, если карта врёт. Главные из них -
point-in-polygon по тому же правилу, по которому карта красит: территория,
которую сопротивление УДЕРЖАЛО, в годы удержания красной быть не должна, а до и
после - должна. Именно так поймана бы регрессия, если кто-нибудь снесёт вырез
или сдвинет окно.

Как считается «красное». Ровно как в index.html: контур ядра на дату
(`data/years/<ключ>.geojson`, ключ - последний из `data/manifest.json`, не позже
даты) минус все активные на дату вырезы - наши удержания
(`data/resistance/cuts.geojson`) и постсоветские эпизоды с paint=cut
(`data/postsoviet.geojson`: Ичкерия 1996-1999 и обе чеченские войны). Имамат и
Черкесия отдельного выреза не требуют: они вычтены из самого контура ядра
(`RESIST` в `tools/build_expansion.py`), и проверки по Грозному и Гунибу это
подтверждают - если тот механизм сломают, здесь станет красным.

Запуск: .venv/bin/python tools/check_resistance.py
Отчёт:  data/resistance/check_report.md
"""
import csv
import json
import os
import sys

from shapely.geometry import Point, shape
from shapely.ops import unary_union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
REPORT = os.path.join(DATA, 'resistance', 'check_report.md')

RESULTS = []


def ok(name, got, want, note=''):
    RESULTS.append((got == want, name, repr(got), repr(want), note))


# ---- модель показа ----------------------------------------------------------
_c = {}


def _norm(s):
    p = str(s).split('-')
    while len(p) < 3:
        p.append('01')
    return '%04d-%02d-%02d' % (int(p[0]), int(p[1]), int(p[2]))


def js(path):
    if path not in _c:
        with open(os.path.join(DATA, path), encoding='utf-8') as f:
            _c[path] = json.load(f)
    return _c[path]


def core_at(iso):
    keys = js('manifest.json')['years']
    best = None
    for k in keys:
        if _norm(k) <= iso:
            best = k
    if best is None:
        raise SystemExit(f'нет среза ядра на {iso}')
    key = ('core', best)
    if key not in _c:
        _c[key] = unary_union([shape(ft['geometry']).buffer(0)
                               for ft in js('years/%s.geojson' % best)['features']
                               if ft.get('geometry')])
    return best, _c[key]


def cuts_at(iso):
    """Все вырезы, активные на дату: наши удержания + постсоветские эпизоды."""
    out = []
    for ft in js('resistance/cuts.geojson')['features']:
        p = ft['properties']
        if _norm(p['hold_from']) <= iso <= _norm(p['hold_to']):
            out.append((p['name'], shape(ft['geometry']).buffer(0)))
    ps = os.path.join(DATA, 'postsoviet.geojson')
    if os.path.exists(ps):
        for ft in js('postsoviet.geojson')['features']:
            p = ft['properties']
            if p.get('paint') != 'cut':
                continue
            if _norm(p['from']) <= iso and (not p.get('to')
                                            or iso <= _norm(p['to'])):
                out.append((p['territory'], shape(ft['geometry']).buffer(0)))
    return out


def red(lon, lat, iso):
    """Красная ли точка на дату - по тому же правилу, что и карта."""
    iso = _norm(iso)
    _, ck = core_at(iso)
    pt = Point(lon, lat)
    if not ck.contains(pt):
        return False
    return not any(g.contains(pt) for _, g in cuts_at(iso))


def cut_names(lon, lat, iso):
    pt = Point(lon, lat)
    return sorted(n for n, g in cuts_at(_norm(iso)) if g.contains(pt))


# опорные точки (lon, lat)
P = {
    'Астрахань': (48.035, 46.348),
    'Москва': (37.614, 55.754),
    'Казань': (49.107, 55.789),
    'Уфа': (55.968, 54.744),
    'Оренбург': (55.097, 51.769),
    'Астана': (71.430, 51.133),
    'Караганда': (73.100, 49.807),
    'Тамбов': (41.452, 52.721),
    'Тобольск': (68.254, 58.199),
    'Кронштадт': (29.767, 59.996),
    'Грозный': (45.688, 43.312),
    'Гуниб': (46.918, 42.386),
    'Элиста': (44.270, 46.308),
    'Симферополь': (34.100, 44.952),
    'Маркс (Марксштадт)': (46.750, 51.711),
    'Нальчик': (43.608, 43.485),
    'Теберда': (41.740, 43.443),
    'Владивосток': (131.874, 43.131),
    'Львов': (24.032, 49.842),
}


def inside(fc_path, pred, lon, lat):
    """Есть ли среди фич файла такая, что pred(props) и точка внутри."""
    pt = Point(lon, lat)
    for ft in js(fc_path)['features']:
        if pred(ft['properties']) and shape(ft['geometry']).buffer(0).contains(pt):
            return True
    return False


def main():
    # ---- 1. реестр сопротивления -------------------------------------------
    with open(os.path.join(DATA, 'resistance', 'registry.csv'),
              encoding='utf-8') as f:
        up = list(csv.DictReader(f))
    ok('реестр сопротивления: строк', len(up), 148)
    ok('реестр сопротивления: имена уникальны',
       len({r['name'] for r in up}), len(up))
    ok('реестр сопротивления: у всех есть источник',
       sum(1 for r in up if not r['source'].strip()), 0)
    ok('реестр сопротивления: у всех есть дата начала',
       sum(1 for r in up if not r['from'].strip()), 0)
    ok('реестр сопротивления: «по» не раньше «с»',
       sum(1 for r in up
           if r['to'].strip() and _norm(r['to']) < _norm(r['from'])), 0)
    KINDS = {'national', 'urban', 'peasant', 'cossack', 'religious', 'military',
             'camp', 'underground', 'worker', 'satellite'}
    ok('реестр сопротивления: тип из закрытого списка',
       sorted({r['kind'] for r in up} - KINDS), [])
    ok('реестр сопротивления: без геометрии только алеутское восстание',
       [r['name'] for r in up if not r['geo'].strip()], ['aleut_1763'])
    ok('реестр сопротивления: hold_from всегда с hold_to',
       sum(1 for r in up if r['hold_from'].strip() and not r['hold_to'].strip()), 0)
    ok('реестр сопротивления: окно удержания не вывернуто',
       sum(1 for r in up if r['hold_from'].strip()
           and _norm(r['hold_to']) <= _norm(r['hold_from'])), 0)
    for sec in ('18', '31', '37', '42', '51'):
        ok('реестр сопротивления: раздел атласа %s представлен' % sec,
           sum(1 for r in up if ('розд. %s,' % sec) in r['source']) > 0, True)
    ok('реестр сопротивления: строк из пяти разделов атласа',
       sum(1 for r in up
           if any(('розд. %s,' % s) in r['source'].split(';')[0]
                  for s in ('18', '31', '37', '42', '51'))), 132,
       'источник строки - именно раздел атласа, а не ссылка на него в примечании')
    ok('реестр сопротивления: удержавших территорию',
       sorted(r['name'] for r in up if r['hold_from'].strip()),
       ['alibek_1877', 'bashkir_1704', 'baysangur_1860', 'ichkeria_1991',
        'imamate_1828', 'kenesary_1837', 'kholodny_yar_1919', 'makhno_1918',
        'razin_1667', 'tungus_1924'])

    # ---- 2. собранные слои --------------------------------------------------
    upg = js('resistance/uprisings.geojson')['features']
    ok('слой сопротивления: фич', len(upg), 147)
    ok('слой сопротивления: все геометрии валидны',
       sum(1 for f in upg if not shape(f['geometry']).buffer(0).is_valid), 0)
    ok('слой сопротивления: все помечены approximate',
       sum(1 for f in upg if not f['properties']['approximate']), 0)
    cuts = js('resistance/cuts.geojson')['features']
    # 02.09.2026: махновский район и Холодный Яр заведены по решению куратора
    # («махно - це черное, бо он точно был не за империю»)
    ok('вырезы: сколько', len(cuts), 6)
    ok('вырезы: какие', sorted(f['properties']['name'] for f in cuts),
       ['alibek_1877', 'baysangur_1860', 'kenesary_1837', 'kholodny_yar_1919',
        'makhno_1918', 'razin_1667'])
    ok('вырезы: доля внутри контура империи не ниже 20 %',
       sum(1 for f in cuts if f['properties']['inside_share'] < 0.2), 0)
    # Тунгусская республика 1924-1925 добавлена 28.08.2026: землю она удержала,
    # но вырез из красного делает слой потерь контроля (эпизод tungus-1924 в
    # tools/build_losses.py), поэтому здесь она тоже shown_elsewhere.
    ok('вырезы: имамат, Ичкерия и тунгусская республика второй раз не '
       'вычитаются',
       sorted(f['properties']['name'] for f in upg
              if f['properties']['paint'] == 'shown_elsewhere'),
       ['bashkir_1704', 'ichkeria_1991', 'imamate_1828', 'tungus_1924'])

    # ---- 3. territория не красная в годы удержания -------------------------
    ok('Астрахань 01.01.1671 - не красная (казацкий круг держит город)',
       red(*P['Астрахань'], '1671-01-01'), False,
       'вырез razin_1667, 24.06.1670 - 27.11.1671')
    ok('Астрахань 01.01.1669 - красная (до удержания)',
       red(*P['Астрахань'], '1669-01-01'), True)
    ok('Астрахань 01.01.1673 - красная (после удержания)',
       red(*P['Астрахань'], '1673-01-01'), True)
    ok('Астрахань 01.01.1671 - вырезом накрыта именно она',
       cut_names(*P['Астрахань'], '1671-01-01'), ['razin_1667'])
    ok('Москва 01.01.1671 - красная (вырез Разина её не задел)',
       red(*P['Москва'], '1671-01-01'), True)
    ok('Уфа 01.01.1710 - не красная (Башкирская орда)',
       red(*P['Уфа'], '1710-01-01'), False,
       'земля чёрная до 1740 года; в эти годы у орды был ещё и свой хан')
    # С 28.08.2026 башкирская земля чёрная до 1740 года (аудит «акт против
    # контроля»), поэтому Уфа не краснеет ни до объявления орды, ни после её
    # поражения: вырез 1708-1711 внутри большего вычитания.
    ok('Уфа 01.01.1706 - не красная (земля чёрная до 1740)',
       red(*P['Уфа'], '1706-01-01'), False)
    ok('Уфа 01.01.1713 - не красная (земля чёрная до 1740)',
       red(*P['Уфа'], '1713-01-01'), False)
    ok('Уфа 01.01.1750 - красная (после войны 1735-1740)',
       red(*P['Уфа'], '1750-01-01'), True)
    ok('Казань 01.01.1710 - красная (вырез до неё не доходит)',
       red(*P['Казань'], '1710-01-01'), True)
    ok('Астана (Акмолинск) 01.01.1843 - не красная (ханство Кенесары)',
       red(*P['Астана'], '1843-01-01'), False,
       'вырез kenesary_1837, 09.1841 - 01.1845')
    ok('Караганда 01.01.1843 - не красная (та же степь)',
       red(*P['Караганда'], '1843-01-01'), False)
    ok('Астана (Акмолинск) 01.01.1838 - красная (до избрания ханом)',
       red(*P['Астана'], '1838-01-01'), True)
    ok('Астана (Акмолинск) 01.01.1846 - красная (укрепления в степи)',
       red(*P['Астана'], '1846-01-01'), True)

    # ---- 4. не удержавшие территорию карту не перекрашивают -----------------
    ok('Оренбург 01.06.1774 - красный: осаду город выдержал',
       red(*P['Оренбург'], '1774-06-01'), True,
       '«Пугачёвщина» удержания не прошла - осада полгода, город не сдался')
    ok('Казань 01.08.1774 - красная: захвачена на сутки',
       red(*P['Казань'], '1774-08-01'), True)
    ok('Уфа 01.06.1774 - красная: «Пугачёвщина» выреза не даёт',
       red(*P['Уфа'], '1774-06-01'), True)
    ok('Тамбов 01.03.1921 - вырезов нет: города остались за империей',
       cut_names(*P['Тамбов'], '1921-03-01'), [])
    ok('Кронштадт 05.03.1921 - вырезов нет: восемнадцать дней',
       cut_names(*P['Кронштадт'], '1921-03-05'), [])
    ok('Тобольск 01.03.1921 - вырезов нет: шесть с половиной недель',
       cut_names(*P['Тобольск'], '1921-03-01'), [])
    ok('Астрахань 01.01.1706 - вырезов нет: восемь месяцев казацкого круга',
       cut_names(*P['Астрахань'], '1706-01-01'), [])

    # ---- 5. что уже работало, работать не перестало -------------------------
    ok('Грозный 01.01.1845 - не красный (имамат, RESIST в build_expansion)',
       red(*P['Грозный'], '1845-01-01'), False)
    ok('Гуниб 01.01.1857 - не красный (имамат)',
       red(*P['Гуниб'], '1857-01-01'), False)
    ok('Грозный 01.01.1997 - не красный (Ичкерия, слой постсоветских эпизодов)',
       red(*P['Грозный'], '1997-01-01'), False)
    ok('Грозный 01.01.1880 - красный (после падения имамата)',
       red(*P['Грозный'], '1880-01-01'), True)

    # ---- 6. депортации ------------------------------------------------------
    with open(os.path.join(DATA, 'deportations', 'registry.csv'),
              encoding='utf-8') as f:
        dep = list(csv.DictReader(f))
    ok('реестр депортаций: строк', len(dep), 30)
    ok('реестр депортаций: у всех есть акт',
       sum(1 for r in dep if not r['decree'].strip()), 0)
    ok('реестр депортаций: у всех есть источник',
       sum(1 for r in dep if not r['source'].strip()), 0)
    ok('реестр депортаций: позиций атласа',
       len({r['source'] for r in dep}), 28)
    depg = js('deportations/deportations.geojson')['features']
    ok('слой депортаций: фич', len(depg), 30)
    ok('слой депортаций: все геометрии валидны',
       sum(1 for f in depg if not shape(f['geometry']).buffer(0).is_valid), 0)
    ok('депортация чеченцев и ингушей: дата',
       [f['properties']['date'] for f in depg
        if f['properties']['people'] == 'chechens_ingush'], ['1944-02-23'])
    ok('депортация крымских татар: дата',
       [f['properties']['date'] for f in depg
        if f['properties']['people'] == 'crimean_tatars'], ['1944-05-18'])
    ok('депортация калмыков: дата (расхождение с атласом снято)',
       [f['properties']['date'] for f in depg
        if f['properties']['people'] == 'kalmyks'], ['1943-12-28'])
    ok('депортация карачаевцев: дата',
       [f['properties']['date'] for f in depg
        if f['properties']['people'] == 'karachays'], ['1943-11-02'])
    ok('депортация балкарцев: дата',
       [f['properties']['date'] for f in depg
        if f['properties']['people'] == 'balkars'], ['1944-03-08'])
    ok('депортация немцев Поволжья: дата',
       [f['properties']['date'] for f in depg
        if f['properties']['people'] == 'volga_germans'], ['1941-08-28'])
    ok('депортация корейцев: дата',
       [f['properties']['date'] for f in depg
        if f['properties']['people'] == 'koreans'], ['1937-08-21'])
    ok('Грозный внутри контура депортации чеченцев и ингушей',
       inside('deportations/deportations.geojson',
              lambda p: p['people'] == 'chechens_ingush', *P['Грозный']), True)
    ok('Элиста внутри контура депортации калмыков',
       inside('deportations/deportations.geojson',
              lambda p: p['people'] == 'kalmyks', *P['Элиста']), True)
    ok('Симферополь внутри контура депортации крымских татар',
       inside('deportations/deportations.geojson',
              lambda p: p['people'] == 'crimean_tatars', *P['Симферополь']), True)
    ok('Марксштадт внутри контура депортации немцев Поволжья',
       inside('deportations/deportations.geojson',
              lambda p: p['people'] == 'volga_germans',
              *P['Маркс (Марксштадт)']), True)
    ok('Нальчик внутри контура депортации балкарцев',
       inside('deportations/deportations.geojson',
              lambda p: p['people'] == 'balkars', *P['Нальчик']), True)
    ok('Владивосток внутри контура депортации корейцев',
       inside('deportations/deportations.geojson',
              lambda p: p['people'] == 'koreans', *P['Владивосток']), True)
    ok('Львов внутри контура операции «Запад» 1947 года',
       inside('deportations/deportations.geojson',
              lambda p: p['people'] == 'oun_families', *P['Львов']), True)
    ok('Москва под депортации не попадает ни разу',
       inside('deportations/deportations.geojson',
              lambda p: True, *P['Москва']), False)
    ok('депортации основную заливку не трогают: Грозный красный 01.01.1950',
       red(*P['Грозный'], '1950-01-01'), True,
       'землю у империи депортация не отнимает - показ бинарный')

    # ---- 7. ликвидированные автономии ---------------------------------------
    with open(os.path.join(DATA, 'peoples', 'abolished.csv'),
              encoding='utf-8') as f:
        ab = list(csv.DictReader(f))
    ok('реестр автономий: строк (семёрка атласа)', len(ab), 7)
    ok('реестр автономий: у всех есть акт упразднения',
       sum(1 for r in ab if not r['decree_abolished'].strip()), 0)
    ok('реестр автономий: восстановлены 09.01.1957',
       sorted(r['slug'] for r in ab if r['restored'].strip() == '1957-01-09'),
       sorted(['kabardino_balkar_assr', 'kalmyk_assr', 'karachay_ao',
               'checheno_ingush_assr', 'kizlyar_okrug']))
    ok('реестр автономий: АССР немцев Поволжья не восстановлена',
       [r['restored'] for r in ab if r['slug'] == 'volga_german_assr'], [''])
    ok('реестр автономий: Крымская АССР восстановлена только в 1991',
       [r['restored'] for r in ab if r['slug'] == 'crimean_assr'],
       ['1991-02-12'])
    abg = js('peoples/abolished.geojson')['features']
    ok('слой автономий: фич (у Кизлярского округа контура нет)', len(abg), 6)
    ok('слой автономий: все геометрии валидны',
       sum(1 for f in abg if not shape(f['geometry']).buffer(0).is_valid), 0)
    ok('Грозный внутри контура Чечено-Ингушской АССР',
       inside('peoples/abolished.geojson',
              lambda p: p['slug'] == 'checheno_ingush_assr', *P['Грозный']), True)
    ok('Нальчик внутри контура Кабардино-Балкарской АССР',
       inside('peoples/abolished.geojson',
              lambda p: p['slug'] == 'kabardino_balkar_assr', *P['Нальчик']), True)
    ok('Элиста внутри контура Калмыцкой АССР',
       inside('peoples/abolished.geojson',
              lambda p: p['slug'] == 'kalmyk_assr', *P['Элиста']), True)
    ok('Симферополь внутри контура Крымской АССР',
       inside('peoples/abolished.geojson',
              lambda p: p['slug'] == 'crimean_assr', *P['Симферополь']), True)
    ok('Теберда внутри контура Карачаевской автономной области',
       inside('peoples/abolished.geojson',
              lambda p: p['slug'] == 'karachay_ao', *P['Теберда']), True)
    ok('автономии основную заливку не трогают: Элиста красная 01.01.1945',
       red(*P['Элиста'], '1945-01-01'), True)

    # ---- отчёт ---------------------------------------------------------------
    bad = [r for r in RESULTS if not r[0]]
    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write('# Регрессия слоёв сопротивления, депортаций и автономий\n\n')
        f.write('Прогон `tools/check_resistance.py`. Всего проверок: %d, '
                'провалов: %d.\n\n' % (len(RESULTS), len(bad)))
        f.write('| | проверка | получили | ждали | примечание |\n')
        f.write('|---|---|---|---|---|\n')
        for good, name, got, want, note in RESULTS:
            f.write('| %s | %s | `%s` | `%s` | %s |\n'
                    % ('OK' if good else 'ПРОВАЛ', name, got, want, note))
    print('проверок: %d, провалов: %d' % (len(RESULTS), len(bad)))
    for good, name, got, want, note in bad:
        print('  ПРОВАЛ: %s -> получили %s, ждали %s' % (name, got, want))
    print('отчёт: %s' % REPORT)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
