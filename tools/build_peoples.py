import geoclean as gc
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Заготовка слоя «поглощённые народы внутри РФ»: по файлу на народ.

В каждом файле до нескольких фич, различаются полем kind:

- kind="current_stub" — современный субъект РФ из Natural Earth admin-1
  (cache/ne_admin1.geojson). Это НЕ контур народа: нынешние границы автономий
  сами по себе результат имперского кромсания. Пример: Бурят-Монгольская АССР
  1923 г. включала Усть-Ордынский и Агинский округа, в 1937 их отрезали в
  Иркутскую и Читинскую области, в 2008 ликвидировали как автономии, и
  нынешняя республика - огрызок. Эту оговорку скрипт кладёт в поле caveat.

- kind="historical_max" — максимальная признанная государственность народа.
  ГЕОМЕТРИЯ НЕ ВЫДУМЫВАЕТСЯ И НЕ ОЦИФРОВЫВАЕТСЯ ВРУЧНУЮ ЗДЕСЬ: фичи этого
  kind собираются исключительно из сырья, скачанного заранее в cache/
  (см. HIST_MAX_SOURCES ниже и data/peoples/RESEARCH.md, раздел «ДОПОЛНЕНИЕ
  18.08.2026»). Если нужного файла в cache/ нет, фича не создаётся, скрипт
  печатает «TODO ...» - как и раньше, ничего не выдумывает.

  Важно для повторяемости конвейера: скрипт КАЖДЫЙ РАЗ пересобирает
  historical_max заново из cache/, а не читает существующий <slug>.geojson.
  Поэтому перезапуск ничего не затирает произвольно - результат детерминирован
  содержимым cache/. Если когда-нибудь понадобится добавить historical_max,
  оцифрованный руками (не из этих трёх источников), его нужно завести через
  HIST_MAX_SOURCES/новый loader, а не правкой готового geojson - иначе следующий
  прогон его удалит.

Поиск субъекта — по паре полей admin='Russia' + name (латинское имя NE);
если имя в NE другое или региона нет, скрипт НЕ выдумывает геометрию,
а печатает «SKIP ...» и идёт дальше.

Поле "absorbed" везде null — дату поглощения заполняет куратор.

Запуск (current_stub можно собрать системным python3; для historical_max
нужен shapely+pyshp из .venv в корне репо):

    cd ~/tmp/imperium-map && .venv/bin/python3 tools/build_peoples.py

Сырьё под historical_max (см. RESEARCH.md за командами скачивания):
    cache/heidata_1926/1926SovietUnion.{shp,shx,dbf} - heiDATA Transcultural
        Empire (Sablin et al.), CC-BY 4.0, doi.org/10.11588/data/10064.
    cache/ohm/rel_<id>.json - OpenHistoricalMap Overpass ("out geom"), CC0.

На выходе: data/peoples/<slug>.geojson (FeatureCollection).
"""
import json
import os

try:
    import shapefile  # pyshp - разбор heiDATA .shp/.dbf
    from shapely.geometry import LineString, mapping, shape
    from shapely.ops import polygonize, unary_union
    HAVE_GIS = True
except ImportError:
    HAVE_GIS = False

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
SRC = os.path.join(ROOT, 'cache', 'ne_admin1.geojson')
OUT_DIR = os.path.join(ROOT, 'data', 'peoples')

SRC_REL = 'cache/ne_admin1.geojson'
STATUS = 'черновик, в показ не вклеен, список и даты утверждает куратор'

CAVEAT = ('современная административная нарезка РФ, а не контур народа: '
          'границы автономий кроила империя, нынешний субъект - результат '
          'этого кромсания; максимальную государственность см. kind='
          '"historical_max" и data/peoples/RESEARCH.md')

# отдельные примечания к источнику там, где контур особенно условный
NOTES = {
    'buryatia': ('границы Бурятии куратору неизвестны, контур взят из '
                 'Natural Earth admin-1 как есть, без правки'),
    'ichkeria': 'контур современной ЧР, а не границы Ичкерии 1991-1999',
}

# что именно кроили: (название максимальной государственности, годы).
# Геометрии тут нет и не будет, пока куратор не утвердит источник оцифровки, -
# это только текст для поля hist_max_todo и для печати TODO.
HISTORICAL_MAX = {
    'sakha': ('Якутская АССР 1922 г.', '1922'),
    'chukotka': ('Чукотский национальный округ 1930 г.', '1930'),
    'buryatia': ('Бурят-Монгольская АССР с Усть-Ордынским и Агинским '
                 'округами', '1923-1937'),
    'ichkeria': ('Чечено-Ингушская АССР с Пригородным районом / де-факто '
                 'Ичкерия', '1936-1944, 1957-1991, 1991-1999'),
    'tuva': ('Тувинская Народная Республика, независимое государство',
             '1921-1944'),
    'tatarstan': ('Татарская АССР 1920 г.', '1920'),
    'bashkortostan': ('Башкирская АССР, до передач территорий 1922-1924 гг.',
                      '1919-1922'),
    'kalmykia': ('Калмыцкая АССР до депортации и ликвидации', '1935-1943'),
    'adygea': ('Адыгейская (Черкесская) АО', '1922'),
    'kabardino-balkaria': ('Кабардино-Балкарская АССР до депортации балкарцев',
                           '1936-1944'),
    'karachay-cherkessia': ('Карачаевская АО до депортации карачаевцев',
                            '1926-1943'),
    'karelia': ('Карело-Финская ССР, союзная республика', '1940-1956'),
}

# --- historical_max: готовая векторная геометрия из cache/ (18.08.2026) -----
#
# Источники разобраны в data/peoples/RESEARCH.md, раздел «ДОПОЛНЕНИЕ
# 18.08.2026». Для части народов достающийся отсюда контур - не итоговый
# «максимум» из HISTORICAL_MAX выше, а его более ранний предшественник
# (единственное, что существует готовой геометрией); это помечено в поле
# gap_todo - расхождение печатается отдельной строкой TODO, чтобы не потерять
# задачу на будущую ручную оцифровку.
HEIDATA_SHP = os.path.join(ROOT, 'cache', 'heidata_1926', '1926SovietUnion.shp')
HEIDATA_SOURCE = ('Transcultural Empire / heiDATA 10.11588/data/10064, '
                   'CC-BY 4.0')
OHM_DIR = os.path.join(ROOT, 'cache', 'ohm')


def _ohm_source(rel_id):
    return ('OpenHistoricalMap relation %d, overpass-api.openhistoricalmap.'
            'org/api/interpreter, CC0' % rel_id)


HIST_MAX_SOURCES = {
    'buryatia': [{
        'kind': 'heidata', 'names': ['Buryat-Mongol ASSR'], 'year': 1926,
        'source': HEIDATA_SOURCE,
        'note': ('доразделительный контур 1926 г., до отрезания '
                 'Усть-Ордынского и Агинского округов в 1937 г.; сверка '
                 'округов с живым OSM - cache/buryat_okruga/'),
    }],
    'sakha': [{
        'kind': 'heidata', 'names': ['Yakut ASSR'], 'year': 1926,
        'source': HEIDATA_SOURCE,
    }],
    'tatarstan': [{
        'kind': 'heidata', 'names': ['Tatar ASSR'], 'year': 1926,
        'source': HEIDATA_SOURCE,
    }],
    'bashkortostan': [{
        'kind': 'heidata', 'names': ['Bashkir ASSR'], 'year': 1926,
        'source': HEIDATA_SOURCE,
        'note': '"Большая Башкирия" 1926 г., уже после передач 1922-1924 гг.',
    }],
    'karelia': [
        {
            'kind': 'heidata', 'names': ['Karelian ASSR'], 'year': 1926,
            'source': HEIDATA_SOURCE,
            'note': ('контур Карельской АССР 1926 г., отдельно от '
                     'Карело-Финской ССР 1940-1956 (см. вторую фичу)'),
        },
        {
            'kind': 'ohm', 'rel': 2852352, 'year': 1940,
            'name_hist': 'Карело-Финская ССР',
            'source': _ohm_source(2852352),
            'note': ('союзная республика 1940-03-31..1956-07-16, включает '
                     'территории по Московскому миру 1940 г. (Выборг, '
                     'Сортавала, Салла-Куусамо)'),
        },
    ],
    'kalmykia': [{
        'kind': 'heidata', 'names': ['Kalmyk AR'], 'year': 1926,
        'source': HEIDATA_SOURCE,
        'gap_todo': ('это Калмыцкая АО 1926 г., а не Калмыцкая АССР '
                     '1935-1943 гг. до депортации - тот контур ещё не '
                     'оцифрован (нужен скан БСАМ, см. RESEARCH.md)'),
    }],
    'karachay-cherkessia': [{
        'kind': 'heidata', 'names': ['Karachai AR', 'Cherkess AR'],
        'year': 1926, 'name_hist': 'Карачаевская АО + Черкесская АО (объединены)',
        'source': HEIDATA_SOURCE,
        'note': ('к 1926 г. единая Карачаево-Черкесская АО 1922 г. уже '
                 'разделена (26.04.1926) на Карачаевскую АО и Черкесский '
                 'нацокруг; здесь их геометрия объединена обратно как '
                 'приближение дореазделительного контура'),
        'gap_todo': ('контур до депортации карачаевцев 1943 г. (12.10.1943 '
                     'Карачаевская АО упразднена) ещё не оцифрован'),
    }],
    'kabardino-balkaria': [{
        'kind': 'heidata', 'names': ['Kabardino-Balkar AR'], 'year': 1926,
        'source': HEIDATA_SOURCE,
        'gap_todo': ('это Кабардино-Балкарская АО 1926 г., а не КБАССР '
                     '1936-1944 гг. до депортации балкарцев - тот контур '
                     'ещё не оцифрован (нужен скан БСАМ, см. RESEARCH.md)'),
    }],
    'adygea': [{
        'kind': 'heidata', 'names': ['Adygei-Cherkess AR'], 'year': 1926,
        'source': HEIDATA_SOURCE,
    }],
    'ichkeria': [{
        'kind': 'heidata', 'names': ['Chechen AR', 'Ingush AR'], 'year': 1926,
        'name_hist': 'Чеченская АО + Ингушская АО (объединены)',
        'source': HEIDATA_SOURCE,
        'note': ('предшественники: контур 1926 г., ДО объединения в '
                 'Чечено-Ингушскую АО (1934) и ЧИАССР (1936); это НЕ ЧИАССР '
                 'и НЕ де-факто Ичкерия 1991-1999'),
        'gap_todo': ('ЧИАССР 1936-1944 с Пригородным районом и де-факто '
                     'Ичкерия 1991-1999 ещё не оцифрованы (нужны сканы '
                     'БСАМ/OSM-прокси, см. RESEARCH.md)'),
    }],
    'tuva': [{
        'kind': 'ohm', 'rel': 2849759, 'year': 1921,
        'name_hist': 'Тувинская Народная Республика',
        'source': _ohm_source(2849759),
        'note': 'независимое государство вне СССР, признано СССР и МНР; до 1944 г.',
    }],
    'chukotka': [{
        'kind': 'ohm', 'rel': 2890470, 'year': 1930,
        'name_hist': 'Чукотский национальный округ',
        'source': _ohm_source(2890470),
    }],
}


def _load_heidata_index():
    """NameENG -> shapely-геометрия, или None если сырья нет в cache/."""
    if not HAVE_GIS or not os.path.isfile(HEIDATA_SHP):
        return None
    sf = shapefile.Reader(HEIDATA_SHP)
    idx = {}
    for sr in sf.shapeRecords():
        name = sr.record['NameENG'].strip()
        name_rus = sr.record['NameRUS'].strip()
        idx[name] = (shape(sr.shape.__geo_interface__), name_rus)
    return idx


def _load_ohm_relation(rel_id):
    """Собирает мультиполигон из кэша Overpass rel_<id>.json (роли outer)."""
    path = os.path.join(OHM_DIR, 'rel_%d.json' % rel_id)
    if not HAVE_GIS or not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    rel = next((e for e in data['elements'] if e['type'] == 'relation'), None)
    if rel is None:
        return None
    lines = []
    for m in rel['members']:
        if m.get('role') != 'outer' or 'geometry' not in m:
            continue
        pts = [(pt['lon'], pt['lat']) for pt in m['geometry']]
        if len(pts) >= 2:
            lines.append(LineString(pts))
    polys = list(polygonize(lines))
    if not polys:
        return None
    geom = unary_union(polys)
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom


def _round_geom(geom, nd=4):
    """Округляет координаты до nd знаков, чинит невалидность после округления."""
    from shapely.geometry import MultiPolygon, Polygon

    def rc(coords):
        return [(round(x, nd), round(y, nd)) for x, y in coords]

    def rpoly(poly):
        return Polygon(rc(poly.exterior.coords),
                        [rc(r.coords) for r in poly.interiors])

    if geom.geom_type == 'Polygon':
        out = rpoly(geom)
    elif geom.geom_type == 'MultiPolygon':
        out = MultiPolygon([rpoly(p) for p in geom.geoms])
    else:
        out = geom
    if not out.is_valid:
        out = out.buffer(0)
    return out


def build_historical_max(slug, people, log):
    """Возвращает список готовых GeoJSON-фич kind=historical_max для slug.

    Ничего не выдумывает: если нужного файла нет в cache/, для этого элемента
    печатает TODO и пропускает его, остальные элементы slug'а всё равно
    собираются.
    """
    specs = HIST_MAX_SOURCES.get(slug)
    if not specs:
        return []

    if not HAVE_GIS:
        log.append('TODO %-20s historical_max: нет shapely/pyshp в '
                    'окружении - запусти .venv/bin/python3 tools/'
                    'build_peoples.py' % slug)
        return []

    heidata_idx = _load_heidata_index()
    feats = []
    for spec in specs:
        year = spec['year']
        source = spec['source']
        if spec['kind'] == 'heidata':
            if heidata_idx is None:
                log.append('TODO %-20s historical_max %s: нет cache/heidata_1926/'
                            '1926SovietUnion.shp - см. RESEARCH.md как скачать'
                            % (slug, year))
                continue
            names = spec['names']
            missing = [n for n in names if n not in heidata_idx]
            if missing:
                log.append('TODO %-20s historical_max %s: в heiDATA нет %r'
                            % (slug, year, missing))
                continue
            geoms = [heidata_idx[n][0] for n in names]
            name_hist = spec.get('name_hist') or heidata_idx[names[0]][1]
            geom = geoms[0] if len(geoms) == 1 else unary_union(geoms)
        elif spec['kind'] == 'ohm':
            geom = _load_ohm_relation(spec['rel'])
            if geom is None:
                log.append('TODO %-20s historical_max %s: нет cache/ohm/rel_%d'
                            '.json - см. RESEARCH.md как скачать'
                            % (slug, year, spec['rel']))
                continue
            name_hist = spec['name_hist']
        else:
            continue

        geom = _round_geom(geom)
        if not geom.is_valid:
            log.append('TODO %-20s historical_max %s: геометрия невалидна '
                        'после сборки, пропущено' % (slug, year))
            continue

        props = {
            'people': people,
            'kind': 'historical_max',
            'year': year,
            'name_hist': name_hist,
            'source': source,
            'absorbed': None,
            'status': STATUS,
        }
        note = spec.get('note')
        if note:
            props['note'] = note
        feature = {
            'type': 'Feature',
            'properties': props,
            'geometry': mapping(geom),
        }
        feats.append((feature, geom.area, geom.bounds))
        gap = spec.get('gap_todo')
        if gap:
            log.append('TODO %-20s historical_max %s: добавлен предшественник, '
                        'но не итоговый максимум - %s' % (slug, year, gap))
    return feats


# slug -> (значение поля name в NE, название народа, название субъекта)
PEOPLES = [
    ('sakha', 'Sakha (Yakutia)', 'саха', 'Республика Саха (Якутия)'),
    ('chukotka', 'Chukchi Autonomous Okrug', 'чукчи',
     'Чукотский автономный округ'),
    ('buryatia', 'Buryat', 'буряты', 'Республика Бурятия'),
    ('ichkeria', 'Chechnya', 'чеченцы (Ичкерия)', 'Чеченская Республика'),
    ('tuva', 'Tuva', 'тувинцы', 'Республика Тыва'),
    ('tatarstan', 'Tatarstan', 'татары', 'Республика Татарстан'),
    ('bashkortostan', 'Bashkortostan', 'башкиры', 'Республика Башкортостан'),
    ('kalmykia', 'Kalmyk', 'калмыки', 'Республика Калмыкия'),
    ('adygea', 'Adygey', 'адыги (Адыгея)', 'Республика Адыгея'),
    ('kabardino-balkaria', 'Kabardin-Balkar', 'кабардинцы и балкарцы',
     'Кабардино-Балкарская Республика'),
    ('karachay-cherkessia', 'Karachay-Cherkess', 'карачаевцы и черкесы',
     'Карачаево-Черкесская Республика'),
    ('karelia', 'Karelia', 'карелы', 'Республика Карелия'),
]


def bbox(geom):
    """Габарит геометрии: (lon_min, lat_min, lon_max, lat_max)."""
    lons, lats = [], []

    def walk(node):
        if not node:
            return
        if isinstance(node[0], (int, float)):
            lons.append(node[0])
            lats.append(node[1])
        else:
            for child in node:
                walk(child)

    walk(geom.get('coordinates'))
    if not lons:
        return None
    return (min(lons), min(lats), max(lons), max(lats))


def main():
    with open(SRC, encoding='utf-8') as fh:
        src = json.load(fh)

    # индекс по латинскому имени, только российские admin-1
    index = {}
    for feat in src['features']:
        pr = feat['properties']
        if pr.get('admin') != 'Russia':
            continue
        if pr.get('name'):
            index[pr['name']] = feat

    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)

    written, skipped = 0, 0
    hist_log = []
    hist_rows = []  # (slug, people, year, area, bbox) для итоговой таблицы
    for slug, ne_name, people, region_ru in PEOPLES:
        feat = index.get(ne_name)
        if feat is None:
            print("SKIP %s: в %s нет admin-1 с admin='Russia' и name=%r"
                  % (slug, SRC_REL, ne_name))
            skipped += 1
            continue

        geom = feat.get('geometry')
        if not geom or not geom.get('coordinates'):
            print('SKIP %s: у фичи name=%r пустая геометрия'
                  % (slug, ne_name))
            skipped += 1
            continue

        pr = feat['properties']
        source = ("контур Natural Earth admin-1, %s, найден по "
                  "admin='Russia' + name=%r (name_ru=%r, adm1_code=%r, "
                  "iso_3166_2=%r)"
                  % (SRC_REL, ne_name, pr.get('name_ru'),
                     pr.get('adm1_code'), pr.get('iso_3166_2')))
        note = NOTES.get(slug)
        if note:
            source += '; ' + note

        # historical_max собирается заново из cache/ при каждом прогоне -
        # см. docstring и HIST_MAX_SOURCES. Ничего из старого файла не
        # читается и не переносится, поэтому перезапуск не может "забыть"
        # добавленную ранее фичу, пока цела raw-сырьё в cache/.
        hist_feats = build_historical_max(slug, people, hist_log)

        hist_name, hist_years = HISTORICAL_MAX[slug]
        if hist_feats:
            years_done = ', '.join(str(f[0]['properties']['year'])
                                    for f in hist_feats)
            hist_max_todo = ('%s (%s) - собрано за %s из готовой векторной '
                              'геометрии (heiDATA/OSM), см. RESEARCH.md'
                              % (hist_name, hist_years, years_done))
        else:
            hist_max_todo = '%s (%s) - контур не оцифрован' % (hist_name,
                                                                 hist_years)

        out = {
            'type': 'FeatureCollection',
            'features': [{
                'type': 'Feature',
                'properties': {
                    'people': people,
                    'kind': 'current_stub',
                    'region_ru': region_ru,
                    'source': source,
                    'caveat': CAVEAT,
                    'hist_max_todo': hist_max_todo,
                    'absorbed': None,
                    'status': STATUS,
                },
                'geometry': geom,
            }],
        }
        for feature, area, bnds in hist_feats:
            out['features'].append(feature)
            hist_rows.append((slug, people, feature['properties']['year'],
                               area, bnds))

        path = os.path.join(OUT_DIR, slug + '.geojson')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(gc.sanitize_obj(out), fh, ensure_ascii=False)

        box = bbox(geom)
        print('OK %-20s current_stub %-22s bbox lon %.2f..%.2f lat %.2f..%.2f'
              % (slug, people, box[0], box[2], box[1], box[3]))
        written += 1

    print('OK записано файлов: %d, пропущено: %d, каталог: %s'
          % (written, skipped, OUT_DIR))

    print()
    for line in hist_log:
        print(line)

    if hist_rows:
        print()
        print('historical_max собраны из cache/ (валидация):')
        print('%-22s %-6s %10s   %s' % ('народ', 'year', 'площадь,кв.град',
                                         'bbox lon/lat'))
        for slug, people, year, area, bnds in hist_rows:
            print('%-22s %-6s %10.3f   lon %.4f..%.4f lat %.4f..%.4f'
                  % (slug, year, area, bnds[0], bnds[2], bnds[1], bnds[3]))
    if not HAVE_GIS:
        print()
        print('OK historical_max не собран: в этом окружении нет shapely/'
              'pyshp, запусти .venv/bin/python3 tools/build_peoples.py')


if __name__ == '__main__':
    main()
