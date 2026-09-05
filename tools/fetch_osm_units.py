#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Курируемая геометрия из районов OpenStreetMap вместо прямоугольных рамок.

ЗАЧЕМ (01.09.2026). Куратор, посмотрев карту: «странные артефакты на границе».
Прямые углы на Кавказе давали вырезы `ne_box` в tools/build_expansion.py:
регион пересекался с прямоугольником по координатам, и на карте появлялась
идеальная горизонталь или вертикаль там, где никакой границы не было. Рамка
ставилась как быстрый приём: отрезать приteречную полосу от воюющей Чечни,
приморскую от горного Дагестана. Смысл верный, геометрия - брак.

Здесь то же самое собирается из настоящих единиц: районы OpenStreetMap
(admin_level=6). Тем же приёмом 29.08.2026 уже собрана кумыкская плоскость -
data/dagestan/kumyk_plain.geojson.

Выгрузка через Overpass, ответ кладётся в data/<путь>.geojson с провенансом:
список единиц и дата выгрузки пишутся в свойства фичи, чтобы через год было
видно, откуда взялась геометрия.

Запуск: .venv/bin/python tools/fetch_osm_units.py <группа>
Группы описаны в GROUPS ниже; без имени - список групп.
"""
import json, os, sys, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
# Зеркала: основной сервер отдаёт 504 на запросах покрупнее, у зеркал
# лимиты другие. Перебираем по кругу, три попытки на каждое.
APIS = ['https://overpass-api.de/api/interpreter',
        'https://overpass.kumi.systems/api/interpreter',
        'https://overpass.private.coffee/api/interpreter']
UA = 'imperium-map-research/1.0 (+https://decolonial.ist; contact@decolonial.ist)'

GROUPS = {
    # Терские станицы: левобережье Терека, у империи с Кизлярской линии
    # 1735 года. Из воюющей Чечни их надо вычесть - там красное по делу
    'chechnya_tersk': {
        'out': 'chechnya/tersk_stanitsy.geojson',
        'label': 'Наурский и Шелковской районы (терские станицы)',
        'bbox': (42.5, 44.5, 44.5, 47.0),
        'names': ['Наурский район', 'Шелковской район'],
    },
    # Приморская полоса Дагестана: Дербент взят в 1806-м, побережье за
    # империей по Гюлистану 1813 года. Ядро имамата - горы, а не берег
    'dagestan_primorye': {
        'out': 'dagestan/primorskaya_polosa.geojson',
        'label': 'Приморская полоса Дагестана с Дербентом',
        'bbox': (41.5, 46.5, 43.4, 48.5),
        'names': ['Дербентский район', 'Каякентский район',
                  'Карабудахкентский район', 'городской округ Дербент',
                  'городской округ Махачкала', 'городской округ Каспийск',
                  'городской округ Избербаш',
                  'городской округ Дагестанские Огни'],
    },
    # Низовья Терека и Ногайская степь: Кизляр 1735 года и станицы вокруг
    'dagestan_nizovya': {
        'out': 'dagestan/nizovya_tereka.geojson',
        'label': 'Низовья Терека и Ногайская степь',
        'bbox': (43.4, 44.5, 45.0, 47.5),
        'names': ['Кизлярский район', 'Тарумовский район', 'Ногайский район',
                  'городской округ Кизляр', 'городской округ Южно-Сухокумск'],
    },
    # Левобережье Кубани: то, что империя взяла войной к 1864 году, в
    # отличие от правобережья с Екатеринодаром (казачья земля с 1793 г.).
    # Анапский район и Новороссийск сюда НЕ входят - Анапа с Суджук-кале
    # получены по Адрианопольскому миру 1829 года, у них своя строка
    'kuban_levoberezhye': {
        'out': 'kuban/levoberezhye.geojson',
        'label': 'Левобережье Кубани (без Анапы и Новороссийска)',
        'bbox': (43.5, 37.5, 45.3, 41.0),
        'names': ['Апшеронский район', 'Белореченский район',
                  'Северский район', 'Абинский район', 'Крымский район',
                  'Туапсинский муниципальный округ',
                  'городской округ Геленджик', 'городской округ Сочи',
                  'муниципальный округ Горячий Ключ'],
    },
    # Анапа с Суджук-кале: получены по Адрианопольскому миру 1829 года,
    # отдельной строкой от Черкесии, которую взяли войной к 1864-му
    'anapa_sudzhuk': {
        'out': 'kuban/anapa_sudzhuk.geojson',
        'label': 'Анапа и Суджук-кале (Новороссийск)',
        'bbox': (44.4, 36.8, 45.4, 38.6),
        'names': ['муниципальный округ Анапа', 'городской округ Новороссийск'],
    },
    # Горная Осетия: общества, которых имперская администрация не держала до
    # экспедиции Абхазова 1830 года. Равнина с Владикавказом и Моздоком
    # краснеет раньше и сюда не входит
    'ossetia_mtn': {
        'out': 'ossetia/gornaya.geojson',
        'label': 'Горная Осетия (Алагирский и Ирафский районы)',
        'bbox': (42.5, 43.0, 43.5, 45.0),
        'names': ['Алагирский район', 'Ирафский район'],
    },
}


def fetch(group):
    g = GROUPS[group]
    s, w, n, e = g['bbox']
    names = '|'.join(g['names'])
    q = ('[out:json][timeout:180];'
         'relation["boundary"="administrative"]["admin_level"="6"]'
         f'["name"~"^({names})$"]({s},{w},{n},{e});'
         'out geom;')
    last = None
    for api in APIS:
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    api + '?' + urllib.parse.urlencode({'data': q}),
                    headers={'User-Agent': UA})
                with urllib.request.urlopen(req, timeout=300) as f:
                    return json.load(f)
            except Exception as e:                       # noqa: BLE001
                last = '%s: %s' % (api.split('/')[2], e)
                print('   ...', last)
                time.sleep(8)
    raise SystemExit('Overpass не ответил ни на одном зеркале: ' + str(last))


def rings(el):
    """Собрать замкнутые кольца из way-ов отношения (роль outer)."""
    segs = [m['geometry'] for m in el.get('members', [])
            if m.get('type') == 'way' and m.get('role') in ('outer', '')
            and m.get('geometry')]
    out, pool = [], [[(p['lon'], p['lat']) for p in s] for s in segs]
    while pool:
        cur = pool.pop(0)
        changed = True
        while changed and cur[0] != cur[-1]:
            changed = False
            for i, s in enumerate(pool):
                if s[0] == cur[-1]:
                    cur += s[1:]; pool.pop(i); changed = True; break
                if s[-1] == cur[-1]:
                    cur += s[::-1][1:]; pool.pop(i); changed = True; break
                if s[-1] == cur[0]:
                    cur = s[:-1] + cur; pool.pop(i); changed = True; break
                if s[0] == cur[0]:
                    cur = s[::-1][:-1] + cur; pool.pop(i); changed = True; break
        if len(cur) > 3 and cur[0] == cur[-1]:
            out.append(cur)
    return out


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in GROUPS:
        print('группы: ' + ', '.join(sorted(GROUPS)))
        return 1
    from shapely.geometry import Polygon, mapping
    from shapely.ops import unary_union
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import geoclean as gc

    name = sys.argv[1]
    g = GROUPS[name]
    d = fetch(name)
    got = {}
    polys = []
    for el in d.get('elements', []):
        nm = el.get('tags', {}).get('name')
        rr = [Polygon(r).buffer(0) for r in rings(el)]
        if not rr:
            continue
        got[nm] = True
        polys.append(unary_union(rr))
    miss = [n for n in g['names'] if n not in got]
    if miss:
        raise SystemExit('НЕ НАЙДЕНЫ единицы: ' + ', '.join(miss)
                         + ' — проверь имена в OSM, геометрия НЕ записана')
    geom = unary_union(polys).buffer(0)
    fc = {'type': 'FeatureCollection', 'features': [{
        'type': 'Feature', 'geometry': gc.clean_rings(mapping(geom)),
        'properties': {
            'group': name, 'label': g['label'],
            'units': sorted(got),
            'source': 'OpenStreetMap, отношения admin_level=6, выгрузка '
                      + time.strftime('%d.%m.%Y'),
        }}]}
    out = os.path.join(DATA, g['out'])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(fc, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    print('OK %s: единиц %d, bbox %s, %d КБ' % (
        g['out'], len(got), [round(v, 2) for v in geom.bounds],
        os.path.getsize(out) // 1024))
    return 0


if __name__ == '__main__':
    sys.exit(main())
