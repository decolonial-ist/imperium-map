#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Чистка колец GeoJSON от отрезков нулевой длины.

ЗАЧЕМ (27.08.2026). Куратор увидел на карте яркие прямые и клинья ПОВЕРХ уже
закрашенного красного - «дебильная прямая внутри закрашенного»: полоса из
Курской области к Ливнам, клин от Волгограда до Алтая на срезе 1921-08-14.
Это не граница и не данные источника, а дефект отрисовки.

Механика. Координаты пишутся с округлением (у срезов - три знака, около 110 м).
Две соседние вершины ближе этого расстояния после округления СОВПАДАЮТ, и в
кольце появляется отрезок нулевой длины. Shapely такое кольцо считает валидным
(`is_valid == True`), поэтому обычные проверки геометрии молчат. А триангулятор
MapLibre - earcut - на вырожденном отрезке ошибается и выдаёт лишний
треугольник: он рисуется поверх заливки вторым слоем и читается как яркая
прямая. На кольце в 15 561 вершину хватало ОДНОЙ дублирующей пары.

Проверено на срезе 1921-08-14: убрали единственный дубль - клин исчез.

Пользуются: build_expansion (и через него build_ww2), build_zones_1917_1921,
build_postsoviet, build_losses, build_sphere, build_data.
"""


def dedup_ring(ring):
    """Убирает подряд идущие одинаковые вершины и замыкает кольцо.

    Кольцо, в котором после чистки осталось меньше четырёх точек, возвращается
    пустым: рисовать там нечего.
    """
    if not ring:
        return []
    out = [ring[0]]
    for p in ring[1:]:
        if p[0] != out[-1][0] or p[1] != out[-1][1]:
            out.append(p)
    if len(out) > 2 and (out[0][0] != out[-1][0] or out[0][1] != out[-1][1]):
        out.append([out[0][0], out[0][1]])
    return out if len(out) >= 4 else []


def clean_rings(geom):
    """Чистит все кольца геометрии GeoJSON (Polygon или MultiPolygon).

    Полигон, у которого рассыпалось внешнее кольцо, выбрасывается целиком;
    рассыпавшиеся дырки просто исчезают. Геометрии других типов возвращаются
    как есть.
    """
    t = geom.get('type')
    if t == 'Polygon':
        polys = [geom['coordinates']]
    elif t == 'MultiPolygon':
        polys = geom['coordinates']
    else:
        return geom
    out = []
    for poly in polys:
        rings = [dedup_ring(list(r)) for r in poly]
        if not rings or not rings[0]:
            continue
        out.append([r for r in rings if r])
    if not out:
        return {'type': 'Polygon', 'coordinates': []}
    if t == 'Polygon':
        return {'type': 'Polygon', 'coordinates': out[0]}
    return {'type': 'MultiPolygon', 'coordinates': out}


def count_degenerate(geom):
    """Сколько отрезков нулевой длины в геометрии (для проверок и отчётов)."""
    t = geom.get('type')
    if t == 'Polygon':
        rings = geom['coordinates']
    elif t == 'MultiPolygon':
        rings = [r for p in geom['coordinates'] for r in p]
    else:
        return 0
    n = 0
    for r in rings:
        for a, b in zip(r, r[1:]):
            if a[0] == b[0] and a[1] == b[1]:
                n += 1
    return n


# ---- обрезка по суше --------------------------------------------------------
# ЗАЧЕМ (28.08.2026). Куратор: «что там за вздроч на берегу северного ледовитого
# океана?» и следом «такие же артефакты на побережье есть в магаданской области
# камчатке и чукотке. проверяй все». Контуры источников (historical-basemaps,
# CShapes) и муниципальные границы OpenStreetMap рисуют берег грубее или вовсе
# включают акваторию: курильские округа, например, тянутся далеко в море. На
# карте это читалось как владения империи в открытой воде. Поэтому каждый
# готовый контур режется по суше Natural Earth admin-1.
_land = {}


def admin1_features(cache_dir):
    """Разобранные фичи Natural Earth admin-1, один раз на процесс.

    Файл весит 40 МБ; до 29.08.2026 его парсили дважды за прогон - свой кэш
    был и здесь (land_mask), и в build_expansion (ne_feats). Теперь загрузчик
    один, потребители берут отсюда.
    """
    if 'feats' not in _land:
        import json
        import os
        path = os.path.join(cache_dir, 'ne_admin1.geojson')
        with open(path, encoding='utf-8') as f:
            _land['feats'] = json.load(f)['features']
    return _land['feats']


def land_mask(cache_dir):
    """Суша по Natural Earth admin-1: объединение всех единиц всех стран."""
    if 'g' not in _land:
        from shapely.geometry import shape
        from shapely.ops import unary_union
        _land['g'] = unary_union([shape(f['geometry']).buffer(0)
                                  for f in admin1_features(cache_dir)])
    return _land['g']


def clip_to_land(geom, cache_dir, min_area=2e-5, margin=0.05):
    """Отрезать от контура воду; куски мельче min_area (~0,25 км²) снять.

    Возвращает (геометрия, сколько кусков снято).
    """
    from shapely.ops import unary_union
    # Припуск margin (~5 км): береговая линия Natural Earth грубее реальной, и
    # без него в воду уходили Ситка, Батуми, Кунашир и Гельсингфорс - точки на
    # самом берегу. Морские навесы в десятки километров припуск не спасает, они
    # по-прежнему срезаются.
    # Буфер маски кэшируется: без этого он считался на КАЖДОМ срезе, и сборщик
    # реконструкции 1917-1921 висел больше часа вместо двух минут (28.08.2026).
    # Готовая маска с припуском лежит на диске (29.08.2026). Без этого КАЖДЫЙ
    # запуск сборщика заново разбирал 40 МБ ne_admin1, объединял всю мировую
    # сушу и раздувал её буфером - около двух минут на процесс, а сборщиков
    # контура четыре. Куратор: «это же пиздец, какие 13 минут на сборку».
    # Файл живёт до обновления Natural Earth; удалить - пересчитается сам.
    key = ('buf', round(margin, 4))
    if key not in _land:
        import os
        from shapely import wkb as _wkb
        path = os.path.join(cache_dir, f'ne_admin1_land_buf{margin:g}.wkb')
        if os.path.exists(path):
            with open(path, 'rb') as f:
                _land[key] = _wkb.loads(f.read())
        else:
            _land[key] = land_mask(cache_dir).buffer(margin)
            with open(path, 'wb') as f:
                f.write(_land[key].wkb)
    land = _land[key]
    if not geom.intersects(land):
        return geom, 0
    cut = geom.intersection(land).buffer(0)
    parts = list(cut.geoms) if cut.geom_type == 'MultiPolygon' else [cut]
    keep = [p for p in parts if p.area >= min_area]
    before = len(list(geom.geoms) if geom.geom_type == 'MultiPolygon' else [geom])
    out = unary_union(keep) if keep else cut
    after = len(list(out.geoms) if out.geom_type == 'MultiPolygon' else [out])
    return out, max(0, before - after)


# ---- куски, лежащие в открытой воде -----------------------------------------
# ЗАЧЕМ (29.08.2026). Куратор на срезе 1721 года: «это что за побережная хуйня?
# ты чинишь одно и возникает другое». Вдоль арктических берегов и в дельте Лены
# у контура торчали красные ленты в море. clip_to_land их не снимает и не может:
# он режет по СУШЕ Natural Earth admin-1, раздутой припуском margin=0.05 (~5 км),
# а припуск обязателен - без него в воду уходят Ситка, Батуми, Херсон, Анадырь и
# Тикси, точки на самом урезе (проверено 29.08.2026 на маске NE 10m). То есть
# лента шириной меньше припуска переживает обрезку по определению.
# Снимаем её другим признаком: кусок выбрасывается, если под ним НЕТ СУШИ по
# точной береговой линии NE 10m. Настоящие острова так не теряются, даже если
# контур эпохи раздут в море: под Симуширом, Урупом и островом Св. Лаврентия
# суша есть, и они остаются.
_sea = {}


def sea_mask(cache_dir):
    """Океан по Natural Earth 10m. Готовая маска кэшируется на диск: сборка
    её из geojson занимает больше минуты, чтения WKB - доли секунды."""
    if 'g' not in _sea:
        import os
        from shapely import wkb as _wkb
        path = os.path.join(cache_dir, 'ne_10m_ocean_union.wkb')
        if os.path.exists(path):
            with open(path, 'rb') as f:
                _sea['g'] = _wkb.loads(f.read())
        else:
            import json
            from shapely.geometry import shape
            from shapely.ops import unary_union
            parts = []
            with open(os.path.join(cache_dir, 'ne_10m_ocean.geojson'),
                      encoding='utf-8') as f:
                for ft in json.load(f)['features']:
                    g = shape(ft['geometry']).buffer(0)
                    parts.extend(g.geoms if g.geom_type == 'MultiPolygon' else [g])
            _sea['g'] = unary_union(parts)
            with open(path, 'wb') as f:
                f.write(_sea['g'].wkb)
    return _sea['g']


def _sea_tree(cache_dir, tile=5.0):
    """Маска океана, НАРЕЗАННАЯ на тайлы, плюс индекс по ним.

    После unary_union океан - это два полигона на 447 тысяч вершин, и вычитание
    из крошечного куска контура шло по всей мировой воде: профиль показал 32
    секунды на срез. Режем маску сеткой в 5 градусов и кэшируем нарезку на диск;
    дальше difference видит только свой квадрат.
    """
    if 'tree' not in _sea:
        import os
        from shapely import wkb as _wkb
        from shapely.geometry import box
        from shapely.strtree import STRtree
        path = os.path.join(cache_dir, f'ne_10m_ocean_tiles{tile:g}.wkb')
        if os.path.exists(path):
            with open(path, 'rb') as f:
                g = _wkb.loads(f.read())
            parts = list(g.geoms) if g.geom_type == 'GeometryCollection' else [g]
        else:
            from shapely.geometry import GeometryCollection
            whole = sea_mask(cache_dir)
            x0, y0, x1, y1 = whole.bounds
            parts = []
            gx = x0
            while gx < x1:
                gy = y0
                while gy < y1:
                    cell = whole.intersection(box(gx, gy, gx + tile, gy + tile))
                    if not cell.is_empty:
                        parts.extend(cell.geoms if cell.geom_type.startswith('Multi')
                                     else [cell])
                    gy += tile
                gx += tile
            parts = [p for p in parts if p.geom_type == 'Polygon' and p.area > 0]
            with open(path, 'wb') as f:
                f.write(GeometryCollection(parts).wkb)
        _sea['parts'] = parts
        _sea['tree'] = STRtree(parts)
    return _sea['tree'], _sea['parts']


def drop_sea_parts(geom, cache_dir, trim_km2=700.0, min_keep_km2=5.0,
                   max_area_km2=5000.0):
    """Убрать из контура воду по точной береговой линии. -> (геометрия, правок).

    Мелкий кусок (меньше trim_km2) ОБРЕЗАЕТСЯ по берегу, а не выбрасывается
    целиком: по абсолютной площади суши остров от мусора не отличить - под
    лентой в дельте Лены 2,1 км² суши, ровно столько же под куском острова
    Св. Лаврентия (замерено 29.08.2026). После обрезки остров остаётся собой,
    только без морского навеса, а лента, под которой суши нет, исчезает.
    Кусок, от которого осталось меньше min_keep_km2, снимается совсем: клочок
    суши в километр-два на мировом масштабе читается не как территория, а как
    грязь у берега (после первой обрезки такие остались в дельте Лены).
    Настоящие острова порог переживают: у Кунашира после обрезки 94 км², у
    острова Св. Лаврентия 51, у Симушира 36, у Урупа 13.

    Куски крупнее trim_km2 не трогаем: там материк и большие острова, а на их
    урезе стоят Ситка, Батуми, Херсон, Анадырь и Тикси - города, которые
    точная маска считает лежащими в воде, и обрезка стёрла бы их с карты.
    """
    import math
    from shapely.ops import unary_union
    parts = list(geom.geoms) if geom.geom_type == 'MultiPolygon' else [geom]
    if len(parts) < 2:
        return geom, 0
    tree, sea = _sea_tree(cache_dir)
    out, fixed = [], 0
    for p in parts:
        lat = (p.bounds[1] + p.bounds[3]) / 2
        k = 111.32 ** 2 * math.cos(math.radians(lat))
        if p.area * k >= trim_km2:
            out.append(p)
            continue
        idx = tree.query(p)
        q = p.difference(unary_union([sea[i] for i in idx])) if len(idx) else p
        q = q.buffer(0)
        if q.is_empty or q.area * k < min_keep_km2:
            fixed += 1
            continue
        if q.area < p.area * 0.98:
            fixed += 1
        out.append(q)
    if not out:
        return geom, 0
    return unary_union(out), fixed


def drop_thin_parts(geom, max_compact=0.08, max_area_km2=6000.0):
    """Снять куски-ободки: длинные и тонкие, но не острова.

    ЗАЧЕМ (28.08.2026). Вдоль Енисея, Амура и арктических берегов тянулись
    красные ниточки - шов между контуром эпохи и современной нарезкой, которой
    мы вычитаем. Первая версия резала по толщине и снесла вместе с ободками
    Ситку, батумскую заплату и Кунашир: остров тоже узкий. Поэтому смотрим на
    ФОРМУ - компактность 4*pi*S/P^2: у ободка она около 0,05, у Кунашира 0,3,
    у Ситки ещё выше. Снимаем кусок, только если он и невыразительной формы, и
    мал по площади.
    """
    import math
    from shapely.ops import unary_union
    parts = list(geom.geoms) if geom.geom_type == 'MultiPolygon' else [geom]
    if len(parts) < 2:
        return geom, 0
    keep = []
    for p in parts:
        if p.length <= 0:
            continue
        lat = (p.bounds[1] + p.bounds[3]) / 2
        km2 = p.area * (111.32 ** 2) * math.cos(math.radians(lat))
        compact = 4 * math.pi * p.area / (p.length ** 2)
        if compact < max_compact and km2 < max_area_km2:
            continue
        # Мелкие ленты режем строже (29.08.2026). После обрезки по берегу вдоль
        # арктических побережий остались нити СУШИ шириной в километр - шов
        # между контуром эпохи и береговой линией, на карте неотличимый от
        # прежних морских полосок. Тридцать девять таких мест, часть держалась
        # на сотне срезов. Настоящих островов правило не касается: у них
        # компактность на порядок выше (Кунашир 0.48, Симушир 0.94).
        if compact < 0.12 and km2 < 300.0:
            continue
        keep.append(p)
    if not keep:
        return geom, 0
    return unary_union(keep), len(parts) - len(keep)


# ---- штампы порядка сборки --------------------------------------------------
# Двадцать сборщиков пишут в общий data/manifest.json, порядок запуска
# (HANDOFF.md) до 29.08.2026 ничем не проверялся: запустишь не в том порядке -
# получишь тихо неверную карту. Каждый сборщик цепочки в конце main() зовёт
# write_stamp('имя'); tools/check_build_order.py сверяет времена с каноном.


def write_stamp(name, data_dir=None):
    """Записать штамп «сборщик name отработал сейчас» в data/build_stamps.json."""
    import datetime
    import json
    import os
    if data_dir is None:
        data_dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), 'data')
    path = os.path.join(data_dir, 'build_stamps.json')
    stamps = {}
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                stamps = json.load(f)
        except Exception:
            stamps = {}
    stamps[name] = datetime.datetime.now().isoformat(timespec='seconds')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(stamps, f, ensure_ascii=False, indent=1)


# ---- общая чистка всего, что пишется на диск --------------------------------
# Куратор 28.08.2026: «добавляй функцию очистки на каждую сборку». Прогоняется
# перед каждой записью geojson во всех сборщиках: чинит невалидные кольца,
# снимает нулевые отрезки, выбрасывает куски нулевой площади.
_GEOM_TYPES = {'Polygon', 'MultiPolygon', 'LineString', 'MultiLineString',
               'Point', 'MultiPoint', 'GeometryCollection'}


def sanitize_geom(geom):
    """Почистить одну геометрию GeoJSON; при любой беде вернуть как было."""
    try:
        from shapely.geometry import mapping, shape
        from shapely.ops import unary_union
        if geom.get('type') not in ('Polygon', 'MultiPolygon'):
            return clean_rings(geom) if geom.get('type') in _GEOM_TYPES else geom
        g = shape(geom)
        if not g.is_valid:
            g = g.buffer(0)
        if g.is_empty:
            return geom
        parts = list(g.geoms) if g.geom_type == 'MultiPolygon' else [g]
        parts = [p for p in parts if p.area > 0]
        if not parts:
            return geom
        return clean_rings(mapping(unary_union(parts)))
    except Exception:
        return geom


def sanitize_obj(obj):
    """Пройти по объекту GeoJSON и почистить все геометрии внутри.

    Всё, что не похоже на geojson, возвращается нетронутым - функцию можно
    ставить перед любым json.dump без разбора, что именно пишется.
    """
    if isinstance(obj, list):
        return [sanitize_obj(x) for x in obj]
    if not isinstance(obj, dict):
        return obj
    t = obj.get('type')
    if t == 'FeatureCollection' and isinstance(obj.get('features'), list):
        out = dict(obj)
        out['features'] = [sanitize_obj(f) for f in obj['features']]
        return out
    if t == 'Feature' and isinstance(obj.get('geometry'), dict):
        out = dict(obj)
        out['geometry'] = sanitize_geom(obj['geometry'])
        return out
    if t in _GEOM_TYPES and 'coordinates' in obj:
        return sanitize_geom(obj)
    return {k: sanitize_obj(v) for k, v in obj.items()}
