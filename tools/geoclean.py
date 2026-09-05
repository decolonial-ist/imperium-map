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


def fill_sea_holes(geom, cache_dir, max_km2=500.0, share=0.6):
    """Залить внутренние кольца не крупнее max_km2, которые больше чем на share
    - океан по NE 10m (карманы губ и устьев, замкнутые лентой шва: Обская
    губа, Енисейский залив, Хатанга на срезах 1929+). -> (геометрия, сколько)."""
    import math
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    tree, sea = _sea_tree(cache_dir)
    polys = list(geom.geoms) if geom.geom_type == 'MultiPolygon' else [geom]
    out, n = [], 0
    for p in polys:
        if not p.interiors:
            out.append(p)
            continue
        keep = []
        for r in p.interiors:
            hp = Polygon(r)
            if hp.area <= 0:
                continue
            km2 = hp.area * 111.32 ** 2 * math.cos(math.radians(hp.centroid.y))
            if km2 > max_km2:
                keep.append(r)
                continue
            idx = tree.query(hp)
            water = unary_union([sea[i] for i in idx]).intersection(hp).area if len(idx) else 0.0
            if water / hp.area > share:
                n += 1
            else:
                keep.append(r)
        out.append(Polygon(p.exterior, keep) if len(keep) != len(p.interiors) else p)
    return (unary_union(out).buffer(0) if n else geom), n


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


# ---- капли: черви, крапинки, точечные дырки ---------------------------------
# ЗАЧЕМ (04.09.2026). Куратор, глядя на срезы 1601-1945: «шо за вздроч идёт,
# капли». Замер по его точкам: отдельные куски по 12-150 км² шириной 1-3 км
# вдоль рек и границ вычитаний (Купянск 1610, Кузбасс 1634, Абакан 1711, Тикси
# 1700), крапинки-отростки на краю ядра (Ямал 1601, Магадан 1700) и дырки в
# доли квадратного километра внутри красного - пунктир швов на срезах Второй
# мировой (Волынь, Прут 1945). Прежний drop_thin_parts их не брал: компактность
# червя 0,17-0,36 выше порога 0,12. Здесь одно правило на все сборщики:
#   1) дырки меньше HOLE_MIN_KM2 закрываются всегда - это не озёра, а швы;
#   2) отдельный кусок меньше SPECK_KM2 снимается, если он либо сидит внутри
#      материка (кольцо вокруг него больше чем наполовину суша: обрезок ядра, а
#      не остров), либо это лента (компактность < 0,35 и средняя ширина < 2 км);
#      настоящие малые острова у берега окружены водой и компактны - остаются;
#   3) морфологическое раскрытие радиусом OPEN_DEG снимает отростки тоньше
#      ~1,3 км с края ядра (крапинки); углы округляются на сотни метров,
#      что при упрощении 0,005° незаметно.
HOLE_MIN_KM2 = 2.0
SPECK_KM2 = 200.0
OPEN_DEG = 0.006
SLIT_WIDTH_KM = 2.5      # дырка уже этого и меньше SLIT_MAX_KM2 - щель шва, не озеро
SLIT_MAX_KM2 = 100.0
THIN_MIN_DEG2 = 1e-5     # тонкие обрезки мельче ~0,1 км² снимаются без разбора
NECK_KM2 = 20.0          # тело, ради связи с которым перешеек сохраняется


def _hole_is_noise(hp, lim):
    import math
    lat = hp.centroid.y
    k = 111.32 ** 2 * math.cos(math.radians(lat))
    a = hp.area * k
    if a < lim:
        return True
    perim = hp.length * 111.32 * math.sqrt((1 + math.cos(math.radians(lat)) ** 2) / 2)
    return a < SLIT_MAX_KM2 and perim > 0 and 2 * a / perim < SLIT_WIDTH_KM


def _local_land(tree, sea, bounds, pad=0.05):
    """Суша в прямоугольнике bounds с запасом pad: коробка минус куски океана."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    b = box(bounds[0] - pad, bounds[1] - pad, bounds[2] + pad, bounds[3] + pad)
    idx = tree.query(b)
    if not len(idx):
        return b
    return b.difference(unary_union([sea[i] for i in idx]))


def despeckle(geom, cache_dir):
    """-> (геометрия, снято кусков, закрыто дырок).

    04.09.2026. Три вида мусора на срезах: (3) тонкие отростки и перешейки
    главного полигона (ленты между контуром источника и вычитанием), (1)
    точечные дырки и щели швов, (2) отдельные крапинки и ленты. Раскрытие
    buffer(-OPEN).buffer(+OPEN) снимает всё тоньше ~1,3 км, но тонкой бывает и
    настоящая земля: Арабатская стрелка, Куршская коса, Федотова коса. Поэтому
    снятые раскрытием куски возвращаются там, где тонка сама суша: если
    раскрытая маска суши покрывает кусок меньше чем наполовину - это коса,
    кусок остаётся; если суша вокруг широка - это обрезок, кусок снимается.
    """
    import math
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    if geom.is_empty:
        return geom, 0, 0
    tree, sea = _sea_tree(cache_dir)
    # 3) раскрытие: тонкие отростки, с возвратом кос
    opened = geom.buffer(-OPEN_DEG).buffer(OPEN_DEG).buffer(0)
    if not opened.is_empty:
        thin = geom.difference(opened)
        back = []
        oparts = list(opened.geoms) if opened.geom_type == 'MultiPolygon' else [opened]
        # тела, между которыми тонкий кусок может быть перешейком (>= NECK_KM2)
        bodies = [(p, p.area * 111.32 ** 2 * math.cos(math.radians(p.centroid.y))) for p in oparts]
        bodies = [p for p, a in bodies if a >= NECK_KM2]
        for t in (thin.geoms if thin.geom_type == 'MultiPolygon' else [thin]):
            if t.is_empty or t.geom_type != 'Polygon' or t.area < THIN_MIN_DEG2:
                continue
            # перешеек: тонкий кусок соединяет два тела (Абакан 1704: 463 км²
            # отрезались от ядра щелью 1,7 км; Арабатская стрелка у основания)
            tb = t.buffer(1e-4)
            if sum(1 for b in bodies if tb.intersects(b)) >= 2:
                back.append(t)
                continue
            land = _local_land(tree, sea, t.bounds)
            land_open = land.buffer(-OPEN_DEG).buffer(OPEN_DEG)
            cover = t.intersection(land_open).area / t.area if not land_open.is_empty else 0.0
            if cover < 0.5:
                back.append(t)
        geom = unary_union([opened] + back).buffer(0) if back else opened
    parts = list(geom.geoms) if geom.geom_type == 'MultiPolygon' else [geom]
    # 1) точечные дырки и щели
    holes = 0
    fixed = []
    for p in parts:
        if not p.interiors:
            fixed.append(p)
            continue
        keep = []
        for r in p.interiors:
            if _hole_is_noise(Polygon(r), HOLE_MIN_KM2):
                holes += 1
            else:
                keep.append(r)
        fixed.append(Polygon(p.exterior, keep) if len(keep) != len(p.interiors) else p)
    parts = fixed
    if len(parts) < 2:
        return unary_union(parts), 0, holes
    # 2) крапинки и ленты
    out, dropped = [], 0
    biggest = max(parts, key=lambda p: p.area)
    for p in parts:
        if p is biggest:
            out.append(p)
            continue
        lat = (p.bounds[1] + p.bounds[3]) / 2
        k = 111.32 ** 2 * math.cos(math.radians(lat))
        km2 = p.area * k
        if km2 >= SPECK_KM2 or p.length <= 0:
            out.append(p)
            continue
        compact = 4 * math.pi * p.area / p.length ** 2
        width_km = 2 * km2 / (p.length * 111.32)
        ribbon = compact < 0.35 and width_km < 2.0
        ring = p.buffer(0.02).difference(p)
        idx = tree.query(ring)
        water = unary_union([sea[i] for i in idx]).intersection(ring).area if len(idx) else 0.0
        mainland = ring.area > 0 and water / ring.area < 0.5
        if ribbon or mainland:
            dropped += 1
            continue
        out.append(p)
    return unary_union(out), dropped, holes


def close_pinholes(geom, min_km2=None):
    """Закрыть дырки меньше min_km2 (по умолчанию HOLE_MIN_KM2) во всех частях."""
    import math
    from shapely.geometry import Polygon, MultiPolygon
    lim = HOLE_MIN_KM2 if min_km2 is None else min_km2
    if geom.is_empty or geom.geom_type not in ('Polygon', 'MultiPolygon'):
        return geom
    parts = list(geom.geoms) if geom.geom_type == 'MultiPolygon' else [geom]
    out, changed = [], False
    for p in parts:
        if not p.interiors:
            out.append(p); continue
        keep = []
        for r in p.interiors:
            if _hole_is_noise(Polygon(r), lim):
                changed = True
            else:
                keep.append(r)
        out.append(Polygon(p.exterior, keep) if changed else p)
    if not changed:
        return geom
    return out[0] if len(out) == 1 else MultiPolygon(out)

def finish(geom, cache_dir):
    """Полная чистка готового контура перед записью: обрезка по суше, куски в
    воде, ободки, капли (04.09.2026 - одна точка входа для всех сборщиков)."""
    geom, _ = clip_to_land(geom, cache_dir)
    geom, _ = drop_sea_parts(geom, cache_dir)
    geom, _ = drop_thin_parts(geom)
    geom, _, _ = despeckle(geom, cache_dir)
    return geom


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


# ---- озёра-дырки ------------------------------------------------------------
# ЗАЧЕМ (03.09.2026, луп по артефактам). У срезов на основе CShapes (1886-2010)
# Байкал, Ладога, Онега и Балхаш сидели дырками с красной обводкой по берегу -
# «империя обошла озеро». Для historical-basemaps то же лечили в hb_core
# (fill_water), а cs_core и поздняя стадия озёра не заливали. Теперь заливка
# стоит здесь, в общей чистке перед записью, и работает во всех сборщиках.
# Правило то же: дырку заливаем, только если она вода. Маска - Natural Earth
# 10m lakes; кэш объединения на диске. Дырки крупнее LAKE_MAX_KM2 не трогаем:
# Каспий и Арал - море, красить их нельзя (Байкал 31,7 тыс. км², Ладога 17,7,
# Балхаш 16,4, Онега 9,7; Арал 68 тыс.).
LAKE_MAX_KM2 = 40000.0
LAKE_SHARE = 0.6
_lakes = {}


def lakes_mask(cache_dir=None):
    if 'g' not in _lakes:
        import json
        import os
        from shapely import wkb as _wkb
        from shapely.geometry import shape
        from shapely.ops import unary_union
        from shapely.strtree import STRtree
        if cache_dir is None:
            cache_dir = os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), 'cache')
        path = os.path.join(cache_dir, 'ne_10m_lakes_union.wkb')
        if os.path.exists(path):
            with open(path, 'rb') as f:
                g = _wkb.loads(f.read())
        else:
            src = os.path.join(cache_dir, 'ne_10m_lakes.geojson')
            if not os.path.exists(src):
                _lakes['g'] = None
                return None
            with open(src, encoding='utf-8') as f:
                g = unary_union([shape(ft['geometry']).buffer(0)
                                 for ft in json.load(f)['features']])
            with open(path, 'wb') as f:
                f.write(g.wkb)
        parts = list(g.geoms) if g.geom_type == 'MultiPolygon' else [g]
        _lakes['g'] = g
        _lakes['parts'] = parts
        _lakes['tree'] = STRtree(parts)
    return _lakes['g']


def fill_lake_holes(g):
    """Залить внутренние кольца, которые больше чем на LAKE_SHARE - озеро
    (и не крупнее LAKE_MAX_KM2). -> (геометрия, сколько дырок залито)."""
    import math
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    if lakes_mask() is None:
        return g, 0
    tree, parts = _lakes['tree'], _lakes['parts']
    polys = list(g.geoms) if g.geom_type == 'MultiPolygon' else [g]
    out, n = [], 0
    for p in polys:
        if not p.interiors:
            out.append(p)
            continue
        keep = []
        for r in p.interiors:
            hp = Polygon(r)
            if hp.area <= 0:
                continue
            lat = hp.centroid.y
            km2 = hp.area * 111.32 ** 2 * math.cos(math.radians(lat))
            if km2 > LAKE_MAX_KM2:
                keep.append(r)
                continue
            idx = tree.query(hp)
            water = unary_union([parts[i] for i in idx]).intersection(hp).area if len(idx) else 0.0
            if water / hp.area > LAKE_SHARE:
                n += 1
            else:
                keep.append(r)
        out.append(Polygon(p.exterior, keep) if len(keep) != len(p.interiors) else p)
    return (unary_union(out).buffer(0) if n else g), n


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
        g = unary_union(parts)
        g, _ = fill_lake_holes(g)
        # 04.09.2026: buffer(0) над округлённым до 3-4 знаков кольцом превращает
        # петли самопересечения в дырки 0,002-0,5 км² (Карпаты 1944-1945,
        # пунктир вдоль границы на кадрах куратора). Это последний писатель
        # перед json.dump, поэтому крапинки закрываются здесь.
        g = close_pinholes(g)
        return sort_polygons(clean_rings(mapping(g)))
    except Exception:
        return geom


def merge_core_features(fc, roles=('core',)):
    """Слить соприкасающиеся фичи ядра в одну: внутренние швы обводки.

    ЗАЧЕМ (03.09.2026). Срез 1922 (оцифровка атласа) лежал 51 фичей, из них
    21 пара соприкасается; поздняя стадия дописывала куски отдельными фичами.
    Обводка рисовала каждую границу куска как границу империи - красные линии
    внутри красного (Ненецкий округ 1929, север 1930, Маньчжурия 1945).
    Все фичи с role из roles объединяются в одну; свойства берутся у самой
    крупной, имена остальных - в списке merged_from.
    """
    try:
        from shapely.geometry import mapping, shape
        from shapely.ops import unary_union
    except Exception:
        return fc
    feats = fc.get('features') or []
    core = [f for f in feats if f.get('geometry') and (f.get('properties') or {}).get('role') in roles]
    if len(core) < 2:
        return fc
    rest = [f for f in feats if f not in core]
    geoms = [(shape(f['geometry']).buffer(0), f) for f in core]
    geoms.sort(key=lambda gf: -gf[0].area)
    # волосяные зазоры после округления закрываем буфером в 1e-4° туда-обратно
    g = unary_union([x for x, _ in geoms]).buffer(1e-4).buffer(-1e-4).buffer(0)
    main = dict(geoms[0][1])
    props = dict(main.get('properties') or {})
    props['merged_from'] = [((f.get('properties') or {}).get('late_fix')
                             or (f.get('properties') or {}).get('name') or '?')
                            for _, f in geoms[1:]]
    main['properties'] = props
    main['geometry'] = sort_polygons(clean_rings(mapping(g)))
    out = dict(fc)
    out['features'] = [main] + rest
    return out


def sort_polygons(geom):
    """Полигоны в MultiPolygon - от крупного к мелкому.

    ЗАЧЕМ. MapLibre режет фичу на тайлы и решает, где внешнее кольцо, а где
    дырка, разбирая кольца тайла по порядку, начиная с первого. Крошечный
    полигон в начале списка сбивает этот разбор, и заливка пропадает целым
    прямоугольником по границам тайла - обводка при этом остаётся. Так
    30.08.2026 на срезах 1945 года исчезала вся европейская часть с Казахстаном
    и Средней Азией; виновата была Куршская коса - полоса шириной в 400 метров,
    стоявшая в списке первой. Крупнейший полигон сбить разбор не может.

    ВТОРАЯ ПРИЧИНА: unary_union отдаёт полигоны в произвольном порядке, и от
    прогона к прогону он гуляет - отсюда часть недетерминизма сборки, из-за
    которого md5-приёмка пересборок не работала (находка 29.08.2026).
    Сортировка этот порядок закрепляет.

    Тот же порядок наводит index.html (sortPolys) при загрузке, чтобы правка
    работала и на срезах, собранных раньше.
    """
    if not isinstance(geom, dict) or geom.get('type') != 'MultiPolygon':
        return geom
    polys = geom.get('coordinates')
    if not isinstance(polys, list) or len(polys) < 2:
        return geom

    def area(poly):
        if not poly or len(poly[0]) < 4:
            return 0.0
        ring = poly[0]
        s = 0.0
        for i in range(len(ring) - 1):
            s += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
        return abs(s) / 2.0

    out = dict(geom)
    out['coordinates'] = sorted(polys, key=area, reverse=True)
    return out


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
