#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборка данных карты расползания российской империи.

Источник границ: aourednik/historical-basemaps (GPL-3.0) через jsDelivr.
Ядро империи — по годовым файлам (NAME из ALLOWLIST + колонии по SUBJECTO);
советская сфера влияния — черновой курируемый список поверх форм 1960/2000 гг.

Запуск:  python3 tools/build_data.py   (из корня репозитория)
"""
import json
import os
import sys as _sys
import time
import urllib.request

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geoclean as gc     # noqa: E402  (чистка колец от нулевых отрезков)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'cache')
OUT = os.path.join(ROOT, 'data')
CDN = "https://cdn.jsdelivr.net/gh/aourednik/historical-basemaps@master/geojson/"

# год -> имена ядра империи в файле этого года (NAME).
# 1930 исключён: файл битый (внутри картина ~1920 г. — ДВР, независимые
# Армения/Грузия/Азербайджан, СССР отсутствует). Найдено кросс-чеком 17.08.2026.
# эти NAME не включать в ядро, даже если их SUBJECTO имперский (живут в сфере)
CORE_EXCLUDE = {"Korea (USSR)", "Germany (Soviet)"}

# historical-basemaps — только доимперская эпоха и XIX век до начала CShapes
#
# РАННЕЕ ПОКРЫТИЕ (26.08.2026, сверка с атласом УІФ). Покрытие карты начиналось
# с 1500 года, то есть завоевание Новгорода (Шелонь 14.07.1471, капитуляция
# города 15.01.1478) оставалось за краем. Куратор: «покрытие давай с 1450-го».
# Что есть у источника на ранние даты — проверено по CDN 26.08.2026:
#   * ЕСТЬ файлы world_1200, world_1279, world_1300, world_1400, world_1492;
#   * НЕТ файлов на 1450, 1470, 1478 — таких срезов у источника не существует;
#   * world_1400 для нас НЕПРИГОДЕН: Московского княжества в нём нет вообще,
#     его место занимает фича «Blue Horde» (SUBJECTO «Mongol Empire»). Тот же
#     класс дефекта, что у world_1930 (см. note_1930 ниже);
#   * world_1300 Москву знает, но это контур 0,8 град² — княжество до начала
#     «собирания земель», и между ним и 1492 годом у источника пусто.
# Поэтому в CORE заведён 1492 год (Москва уже с Новгородом и Тверью, ещё без
# Пскова и Рязани), а окно 1450–1492 собирает tools/build_expansion.py: тот же
# контур 1492 года МИНУС то, чего у Москвы на дату ещё нет (новгородская земля
# до 15.01.1478, Тверь до 12.09.1485, Вятка до 16.08.1489, Вологда до
# 11.08.1471). Новгородская земля до 1478 года на карте НЕ красная: это другой
# субъект, у атласа УІФ — «новгородський тип колоніалізму» (розд. 2),
# отдельный от московского.
CORE = {
    1492: ["Grand Duchy of Moscow"],
    1500: ["Grand Duchy of Moscow"],
    1530: ["Tsardom of Muscovy"],
    1600: ["Tsardom of Muscovy"],
    1650: ["Tsardom of Muscovy"],
    1700: ["Tsardom of Muscovy"],
    1715: ["Tsardom of Muscovy"],
    1783: ["Russian Empire"],
    1800: ["Russian Empire"],
    1815: ["Russian Empire"],
    1880: ["Russian Empire"],
}

# С 1886 — CShapes 2.0 (ETH Zürich, Weidmann; датированные границы 1886–2019).
# gwcode 365 = Россия/СССР. Ключ среза = дата, с которой контур показывается у
# нас ('YYYY' = 1 января этого года, 'YYYY-MM-DD' = этот день); значение — дата,
# на которую берётся полигон CShapes.
# Срез 2014+ НЕ используем: CShapes рисует Крым российским де-факто — оккупации
# пойдут отдельным слоем, а не ядром.
#
# ВАЖНО (18.08.2026, разбор по жалобе куратора): CShapes даёт границы ДЕ-ЮРЕ —
# членство в межгосударственной системе, а не фактический контроль. Отсюда:
#  * Царство Польское числится российским до 11.11.1918, хотя Варшава под
#    немцами с 1915 -> срез «1918» берём датой 11.11.1918 (Польша, Финляндия,
#    Прибалтика уже вне полигона). Более раннего честного контура у CShapes нет;
#    контур 06.12.1917–10.11.1918 с красной Варшавой не используем.
#  * Тот же контур 11.11.1918–01.02.1920 действует весь 1919 г. — отдельный
#    срез 1919 был его дубликатом, убран (файл data/years/1919.geojson остаётся
#    на диске, но в манифест не попадает).
#  * Западную Украину и Западную Беларусь (оккупация с 17.09.1939) CShapes
#    отдаёт СССР только с 08.05.1945 — среза «осень 1939» у него нет вообще,
#    см. ограничение 9 в README. 1939 г. поэтому идёт по контуру Риги.
#  * В окне 12.1917-03.1921 срезы CShapes ИЗ ПОКАЗА УБРАНЫ (решение куратора
#    18.08.2026): де-юре контур накрывал всю Украину в дни, когда там стояли
#    немцы, Директория, деникинцы и поляки. Вместо них - реконструкция зоны
#    контроля датированными срезами, см. RECON и tools/build_zones_1917_1921.py.
#    CShapes возвращается с 18.03.1921 (линия Рижского мира).
CSHAPES_URL = "https://icr.ethz.ch/data/cshapes/CShapes-2.0.geojson"
CSHAPES_SLICES = {
    '1886': (1886, 1, 2),
    '1905': (1905, 10, 1),
    '1914': (1914, 5, 1),
    '1921-03-18': (1921, 6, 1),   # линия Риги; контур стабилен до 11.03.1940
    # ВНИМАНИЕ: эти два среза перезаписываются ЧИСТЫМИ контурами источника, а
    # tools/build_pact_1939.py потом добавляет в них Западную Украину и
    # Западную Беларусь (17.09.1939) и Виленский край. Прогонять его ПОСЛЕ.
    '1940-03-12': (1940, 3, 12),  # после Зимней войны: Карельский перешеек
    '1940-06-28': (1940, 6, 28),  # Бессарабия; Балтия уехала на срез 1940-06-15
    '1946': (1946, 1, 1),        # послевоенный СССР
    '1992': (1992, 1, 1),        # РФ после распада
}

# Реконструкция ЗОНЫ ИМПЕРИИ 1917-1921 (черновик): файлы
# data/years/<дата>.geojson собирает tools/build_zones_1917_1921.py (нужен
# shapely). Здесь только регистрация в манифесте - геометрию не трогаем.
#
# Редакция 2 (18.08.2026): реконструкция распространена с украинского театра на
# ВСЁ пространство (восточный фронт, Север, Дон и Кубань, Закавказье, Средняя
# Азия, Дальний Восток).
# Редакция 3 (26.08.2026, смена рамки): слой строит зону ИМПЕРИИ, а не зону
# советского контроля. Белые - имперская фракция, их территория красная;
# чёрным остаётся только реально вышедшее из империи. Срезов 29: добавлены
# 1918-04-18 (немцы в Крыму) и 1918-11-18 (переворот Колчака закрывает окно
# самостоятельности Сибири). См. WINDOWS в билдере и tools/check_cities.py.
RECON = [
    '1917-12-25', '1918-02-08', '1918-03-02', '1918-04-18', '1918-06-10',
    '1918-08-15', '1918-10-10', '1918-11-15', '1918-11-18', '1919-01-03',
    '1919-02-06', '1919-04-20', '1919-05-27', '1919-06-01', '1919-06-25', '1919-07-20', '1919-08-28',
    '1919-08-31', '1919-10-15', '1919-11-20', '1919-12-17', '1920-02-08',
    '1920-03-20', '1920-05-08', '1920-07-01', '1920-11-01', '1920-11-17',
    '1920-12-02', '1921-02-25',
]

# Советская сфера влияния — ЧЕРНОВИК 18.08.2026, В СБОРКУ БОЛЬШЕ НЕ ИДЁТ.
# 26.08.2026 сфера переведена на источниковую таблицу
# `data/sphere/registry.csv` (`tools/build_sphere.py`): строка на ЭПИЗОД
# отношений, с датами, типом зависимости, событием на входе и выходе,
# ссылкой и оценкой достоверности. Список ниже оставлен КАК ИСТОРИЯ ВОПРОСА —
# это то, с чего слой начинался: собран навскидку, без единой ссылки, с
# упрощёнными датировками, без Южного Йемена и с единым Вьетнамом на
# 1954–1976 (государств было два). Сравнение старого списка с новой таблицей —
# в README, раздел «Сфера влияния».
# (имя в файле форм, год_с, год_по, файл форм)
SPHERE_DRAFT_2026_08_18 = [
    # оккупационные зоны и блок
    ("Germany (Soviet)", 1946, 1949, 1945),
    ("Korea (USSR)", 1946, 1948, 1945),
    # СТЫК СО СЛОЕМ ВТОРОЙ МИРОВОЙ (26.08.2026, tools/build_ww2.py). Слой ВМВ
    # красит военную оккупацию ядром до 28.06.1945, дальше её обязана
    # подхватить сфера - иначе Польша проваливалась бы в чёрное до 1947 года,
    # Чехословакия до 1948, Венгрия до 1949, Румыния до 1948, Маньчжурия
    # вообще. Ядро красит оккупацию ПО 31.12.1945 включительно, поэтому окна
    # ниже начинаются с 1946 года: так у стыка нет ни двойного показа, ни
    # провала. Это ПРИСУТСТВИЕ СОВЕТСКИХ ВОЙСК, а не датировка сателлитного
    # статуса (она осталась в строках ниже, как была). ЗА КУРАТОРОМ: Австрия
    # (советская зона до 1955) сюда не заведена - в файлах форм есть только
    # Австрия целиком, а зона была лишь восточной третью.
    ("Poland", 1946, 1946, 1945),          # советская военная администрация
    ("Czechoslovakia", 1946, 1947, 1945),  # войска выведены в декабре 1945
    ("Hungary", 1946, 1948, 1945),         # СКК до мирного договора 1947
    ("Romania", 1946, 1947, 1945),         # с 23.08.1944, СКК до 1947
    ("Manchuria", 1946, 1946, 1945),       # вывод завершён в мае 1946
    ("Poland", 1947, 1989, 1960),
    ("East Germany", 1949, 1990, 1960),
    ("Czechoslovakia", 1948, 1989, 1960),
    ("Hungary", 1949, 1989, 1960),
    ("Romania", 1948, 1989, 1960),
    ("Bulgaria", 1946, 1990, 1960),
    ("Albania", 1946, 1961, 1960),
    ("Mongolia", 1924, 1990, 1960),
    ("Korea, Democratic People's Republic of", 1948, 1991, 1960),
    ("Cuba", 1961, 1991, 1960),
    ("North Vietnam", 1954, 1976, 1960),
    ("Vietnam", 1976, 1991, 2000),
    ("Laos", 1975, 1991, 2000),
    ("Cambodia", 1979, 1989, 2000),
    ("Afghanistan", 1978, 1989, 2000),
    # Ближний Восток (Южный Йемен 1969–1990 выпущен: в файлах форм нет НДРЙ —
    # в 1960 «Yemen» это северное королевство, к 1994 Йемен объединён; в README)
    ("Syria", 1971, 1991, 2000),
    ("Egypt", 1955, 1972, 1960),
    # Африка
    ("Somalia", 1969, 1977, 2000),
    ("Ethiopia", 1974, 1991, 2000),
    ("Angola", 1975, 1991, 2000),
    ("Mozambique", 1975, 1991, 2000),
    ("Congo", 1969, 1991, 2000),
    ("Benin", 1975, 1989, 2000),
    ("Madagascar", 1975, 1991, 2000),
    ("Guinea", 1960, 1978, 2000),
    ("Mali", 1960, 1968, 2000),
    # Современная РФ (черновик; кандидаты Ливия/Судан — в README):
    ("Syria", 2015, 2024, 2000),                   # интервенция — до падения Асада 12.2024
    # Беларусь убрана из сферы 18.08.2026 по решению куратора: она красится
    # непрерывно с распада СССР отдельным слоем «несуверенна» (build_belarus),
    # а не бледным черновиковым пунктиром сферы с окном 1997–2025.
    ("Central African Republic", 2018, 2025, 2000),  # Вагнер
    ("Mali", 2021, 2025, 2000),                    # Вагнер/«Африканский корпус»
]


def fetch(year):
    path = os.path.join(CACHE, f'world_{year}.geojson')
    if os.path.exists(path) and os.path.getsize(path) > 10000:
        return path
    url = f"{CDN}world_{year}.geojson"
    req = urllib.request.Request(url, headers={"User-Agent": "decolonial.ist imperium-map builder"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, 'wb') as f:
        f.write(r.read())
    time.sleep(1)
    return path


def props_of(f):
    p = f.get('properties') or {}
    return {k.upper(): v for k, v in p.items()}


def name_of(f):
    return str(props_of(f).get('NAME') or '')


def subj_of(f):
    return str(props_of(f).get('SUBJECTO') or '')


def slice_date(key):
    """Ключ среза -> (год, месяц, день), с которых он показывается на карте.

    '1918' = 1 января 1918, '1940-06-28' = этот день. Тот же разбор в index.html.
    """
    p = [int(x) for x in str(key).split('-')]
    return (p[0], p[1] if len(p) > 1 else 1, p[2] if len(p) > 2 else 1)


def build_core():
    years_out = []
    for year, names in sorted(CORE.items()):
        d = json.load(open(fetch(year), encoding='utf-8'))
        feats, missing = [], set(names)
        for f in d['features']:
            n, s = name_of(f), subj_of(f)
            if n in CORE_EXCLUDE:
                continue
            if n in names or s in names:
                if n in missing:
                    missing.discard(n)
                feats.append({
                    "type": "Feature",
                    "geometry": f["geometry"],
                    "properties": {"name": n, "subjecto": s, "year": year,
                                   "role": "core" if n in names else "colony"},
                })
        if missing:
            print(f"!! {year}: не найдены имена: {sorted(missing)}")
        colonies = [f['properties']['name'] for f in feats if f['properties']['role'] == 'colony']
        if colonies:
            print(f"   {year}: колонии по SUBJECTO: {colonies}")
        # чистим кольца от отрезков нулевой длины: см. tools/geoclean.py -
        # на них ломается триангулятор MapLibre и рисует лишние полосы
        for f in feats:
            if f.get('geometry'):
                f['geometry'] = gc.clean_rings(f['geometry'])
        out = {"type": "FeatureCollection", "features": feats}
        with open(os.path.join(OUT, 'years', f'{year}.geojson'), 'w', encoding='utf-8') as fp:
            json.dump(gc.sanitize_obj(out), fp, ensure_ascii=False)
        years_out.append(str(year))
        print(f"OK {year}: {len(feats)} фич")
    return years_out


def fetch_cshapes():
    path = os.path.join(CACHE, 'cshapes20.geojson')
    if os.path.exists(path) and os.path.getsize(path) > 1000000:
        return path
    req = urllib.request.Request(CSHAPES_URL, headers={"User-Agent": "decolonial.ist imperium-map builder"})
    with urllib.request.urlopen(req, timeout=300) as r, open(path, 'wb') as f:
        f.write(r.read())
    return path


def cshapes_at(feats, key):
    """Полигоны CShapes, действующие на дату key=(год, месяц, день).

    Интервалы у gwcode 365 непересекающиеся, но полагаться на порядок в файле
    нельзя: собираем все попадания и предупреждаем, если их больше одного.
    """
    hits = []
    for f in feats:
        p = f['properties']
        start = (p['gwsyear'], p['gwsmonth'], p['gwsday'])
        end = (p['gweyear'], p['gwemonth'], p['gweday'])
        if start <= key <= end:
            hits.append(f)
    if len(hits) > 1:
        print(f"!! cshapes: на {key} подходит {len(hits)} интервалов — беру последний")
    return hits


def build_cshapes_core():
    d = json.load(open(fetch_cshapes(), encoding='utf-8'))
    ru = [f for f in d['features'] if f['properties'].get('gwcode') == 365]
    years_out = []
    for label, (y, m, dd) in sorted(CSHAPES_SLICES.items(), key=lambda kv: slice_date(kv[0])):
        hits = cshapes_at(ru, (y, m, dd))
        hit = hits[-1] if hits else None
        if not hit:
            print(f"!! cshapes: нет полигона на {label} ({y}-{m:02d}-{dd:02d})")
            continue
        out = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": hit["geometry"],
            "properties": {"name": hit['properties']['cntry_name'], "year": label,
                           "role": "core", "source": "CShapes 2.0"}}]}
        with open(os.path.join(OUT, 'years', f'{label}.geojson'), 'w', encoding='utf-8') as fp:
            json.dump(gc.sanitize_obj(out), fp, ensure_ascii=False)
        years_out.append(label)
        print(f"OK {label} (CShapes, площадь {hit['properties']['area']} км²)")
    return years_out


# слои, оцифрованные из атласа УІФ (tools/georef_atlas.py + digitize_atlas.py
# + компоновщики): год -> файл в data/atlas/. Приоритетнее CShapes: наш срез
# 1922 знает Туву, Юж. Сахалин, Карс — CShapes-контур 1921 живёт до 03.1940 и
# всего этого не знает.
ATLAS_LAYERS = {
    1922: ('atlas/ussr_1922.geojson', 'СССР 1922–1923, атлас УІФ розд. 44'),
}


def build_atlas_core():
    years_out = []
    for year, (rel, note) in sorted(ATLAS_LAYERS.items()):
        src = os.path.join(OUT, rel)
        if not os.path.exists(src):
            print(f"!! атлас: нет {rel} — срез {year} пропущен (собери конвейером атласа)")
            continue
        d = json.load(open(src, encoding='utf-8'))
        feats = [{"type": "Feature", "geometry": f["geometry"],
                  "properties": {**f.get("properties", {}),
                                 "year": year, "role": "core",
                                 "source": note}}
                 for f in d['features']]
        # 03.09.2026: 51 фича атласного среза сливается в одну - иначе обводка
        # рисует границы кусков как границы империи (внутренние швы), а два
        # пустых полигона файла роняли проверки (см. geoclean.merge_core_features)
        fc = gc.merge_core_features(gc.sanitize_obj(
            {"type": "FeatureCollection", "features": feats}))
        with open(os.path.join(OUT, 'years', f'{year}.geojson'), 'w', encoding='utf-8') as fp:
            json.dump(fc, fp, ensure_ascii=False)
        years_out.append(str(year))
        print(f"OK {year} (атлас УІФ): {len(feats)} фич -> {len(fc['features'])}")
    return years_out


# Беларусь: несуверенная, подконтрольная империи — решение куратора 18.08.2026.
# Красится непрерывно от распада СССР (26.12.1991) до сегодня, отдельным слоем
# в красной гамме (не бледная «сфера»), но отличимо от ядра РФ: это сателлит,
# а не территория РФ. Контур — CShapes 2.0, gwcode 370, последний интервал.
BELARUS = {'gwcode': 370, 'from': '1991-12-26',
           'note': 'Беларусь - несуверенна (реш. куратора 18.08.2026)'}


def build_belarus():
    d = json.load(open(fetch_cshapes(), encoding='utf-8'))
    by = [f for f in d['features'] if f['properties'].get('gwcode') == BELARUS['gwcode']]
    if not by:
        print('!! Беларусь: в CShapes нет gwcode 370 — слой не собран')
        return
    hit = sorted(by, key=lambda f: (f['properties']['gweyear'], f['properties']['gwemonth'],
                                    f['properties']['gweday']))[-1]
    out = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": hit['geometry'],
        "properties": {"name": "Беларусь", "status": "несуверенна",
                       "from": BELARUS['from'], "note": BELARUS['note'],
                       "source": "CShapes 2.0, gwcode 370 (контур 2019 г.)"}}]}
    with open(os.path.join(OUT, 'belarus.geojson'), 'w', encoding='utf-8') as fp:
        json.dump(gc.sanitize_obj(out), fp, ensure_ascii=False)
    print(f"OK Беларусь: контур CShapes {hit['properties']['cntry_name']}, "
          f"показ с {BELARUS['from']}")


def build_recon_core():
    """Регистрация срезов реконструкции 1917-1921 (геометрию не пересобираем)."""
    keys, missing = [], []
    for key in sorted(RECON, key=slice_date):
        path = os.path.join(OUT, 'years', f'{key}.geojson')
        if not os.path.exists(path):
            missing.append(key)
            continue
        d = json.load(open(path, encoding='utf-8'))
        recon = any(f['properties'].get('reconstruction')
                    for f in d.get('features', []))
        if not recon:
            print(f"!! {key}: файл есть, но без reconstruction=true — пропущен")
            continue
        keys.append(key)
    if missing:
        print(f"!! реконструкция 1917-1921: нет файлов {missing} — собери "
              f".venv/bin/python tools/build_zones_1917_1921.py")
    if keys:
        print(f"OK реконструкция 1917-1921: срезов {len(keys)} "
              f"({keys[0]}..{keys[-1]})")
    return keys


def build_expansion_core():
    """Регистрация курируемых срезов расползания 1552-1914 (геометрия не наша).

    Их собирает tools/build_expansion.py: контур источника + приобретения по
    актам - территории, которых на дату у империи ещё или уже нет. Здесь
    только сканируем data/years на свойство `expansion` и заводим ключи в
    манифест. ВАЖНО: build_core() и build_cshapes_core() выше только что
    перезаписали срезы источника (1650, 1700, 1783, 1800, 1815, 1880, 1886,
    1905, 1914) ЧИСТЫМИ контурами - приобретения из них стёрты, поэтому после
    этого скрипта надо снова прогнать build_expansion.py.
    """
    keys = []
    d = os.path.join(OUT, 'years')
    for fn in sorted(os.listdir(d)):
        if not fn.endswith('.geojson'):
            continue
        key = fn[:-len('.geojson')]
        try:
            fc = json.load(open(os.path.join(d, fn), encoding='utf-8'))
        except Exception:
            continue
        if any(f.get('properties', {}).get('expansion')
               for f in fc.get('features', [])):
            keys.append(key)
    if keys:
        print(f'OK расползание 1552-1914: срезов {len(keys)} '
              f'({keys[0]}..{keys[-1]})')
        print('!! срезы источника перезаписаны чистыми контурами - прогони '
              'снова .venv/bin/python tools/build_expansion.py')
    return keys


def build_sphere():
    """Сфера влияния собирается ОТДЕЛЬНЫМ билдером из курируемой таблицы.

    26.08.2026: `data/sphere/registry.csv` + `tools/build_sphere.py`. Раньше
    слой строился здесь по списку SPHERE_DRAFT_2026_08_18 (см. выше) — теперь
    этот прогон таблицу НЕ ЗАТИРАЕТ, а вызывает новый билдер, иначе полный
    порядок пересборки («build_data.py первым») уничтожал бы источниковые
    данные черновиком.
    """
    try:
        import build_sphere as bs
    except ImportError as e:      # shapely только в .venv
        print(f'!! сфера НЕ пересобрана ({e}): tools/build_sphere.py требует '
              f'shapely. Запусти .venv/bin/python tools/build_sphere.py. '
              f'data/sphere.geojson оставлен как есть — ничего не затёрто.')
        return
    rows = bs.read_rows()
    feats = bs.build(rows)
    with open(os.path.join(OUT, 'sphere.geojson'), 'w', encoding='utf-8') as fp:
        json.dump({"type": "FeatureCollection", "features": feats}, fp,
                  ensure_ascii=False)
    print(f'OK сфера: {len(feats)} фич из {len(rows)} эпизодов таблицы '
          f'data/sphere/registry.csv')


def main():
    os.makedirs(os.path.join(OUT, 'years'), exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    years = sorted(set(build_core() + build_cshapes_core() + build_atlas_core()
                       + build_recon_core() + build_expansion_core()),
                   key=slice_date)
    build_sphere()
    build_belarus()
    manifest = {
        "years": years,
        "sphere": True,
        "belarus": True,
        "source": "aourednik/historical-basemaps (GPL-3.0), формы сферы — файлы 1945/1960/2000",
        "note_years": ("ключ среза = дата, с которой он показывается: «1918» —"
                       " 1 января 1918, «1940-06-28» — этот день"),
        "note_1930": "world_1930 исключён: содержимое соответствует ~1920 году (битые данные источника)",
        "note_1400": ("world_1400 исключён: Московского княжества в нём нет"
                      " вообще, его место занимает фича «Blue Horde». Ранних"
                      " срезов на 1450, 1470 и 1478 у источника не"
                      " существует, поэтому окно 1450–1492 собрано"
                      " курируемыми вычитаниями из контура 1492 г."
                      " (tools/build_expansion.py)"),
        "note_1450": ("покрытие карты начинается с 1450 года (решение куратора"
                      " 26.08.2026 при сверке с атласом УІФ): раньше начиналось"
                      " с 1500 и завоевание Новгорода оставалось за краем."
                      " Новгородская земля до 15.01.1478 в контур НЕ входит —"
                      " это другой субъект (атлас УІФ, розд. 2"
                      " «Новгородський тип колоніалізму»)"),
        "note_1917_1921": ("окно 12.1917-03.1921 идёт по РЕКОНСТРУКЦИИ советской"
                           " зоны контроля (черновик, tools/build_zones_1917_1921.py):"
                           " де-юре срезы CShapes из показа убраны, они накрывали"
                           " всю Украину при немцах, Директории, Деникине и поляках."
                           " CShapes возвращается с 18.03.1921 (линия Риги)"),
        "note_1939": ("Западную Украину и Западную Беларусь (17.09.1939) CShapes"
                      " отдаёт СССР только с 08.05.1945 — своего среза осени"
                      " 1939 у него нет. Дыра закрыта 26.08.2026 курируемыми"
                      " срезами: tools/build_pact_1939.py (17.09.1939,"
                      " 15.06.1940, 29.06.1945) — ПРОГНАТЬ ПОСЛЕ этого"
                      " скрипта, он перезаписывает 1940-03-12 и 1940-06-28"
                      " чистыми контурами и стирает приобретения"),
        "built": "см. git log",
    }
    with open(os.path.join(OUT, 'manifest.json'), 'w', encoding='utf-8') as fp:
        json.dump(gc.sanitize_obj(manifest), fp, ensure_ascii=False, indent=1)
    print("manifest OK")


if __name__ == '__main__':
    main()
