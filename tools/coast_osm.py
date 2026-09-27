"""Один берег на все даты - маска суши OpenStreetMap (25.09.2026).

  python tools/coast_osm.py --extras     выгрузить из OSM искусственный берег и заливы-море
  python tools/coast_osm.py --mask       собрать маску из выгрузки OSM (раз на выгрузку)
  python tools/coast_osm.py              привести берег срезов, у которых сменилась отметка
  python tools/coast_osm.py --all        все срезы манифеста заново
  python tools/coast_osm.py --keys a,b --dry   замер на датах, срезы не пишутся

ЗАЧЕМ. Куратор 25.09.2026: «по началу границы берега какие-то одни, а потом
где-то после второй мировой границы континента и всех берегов становятся
другими ... едва ли берега двигались». Берег красного приходил из источника
контура своей эпохи: атласы 1800 и 1815, контуры 1886 и 1905, реконструкция
1917-1921 по регионам, замороженный 1922, CShapes с 1940. Обрезка по суше
Natural Earth admin-1 шла с припуском 5 км (без него в воду уходили Ситка,
Батуми, Анадырь - NE грубее настоящего берега), поэтому навес над морем в
пределах 5 км оставался свой у каждой эпохи, а зазор, где берег источника
проходит внутри суши, не заполнял никто. Замер на одном куске берега у
Петербурга: красного над морем 323 км² в 1800-1879, 28 в 1886-1917, 564 в
1929, 22-30 после 1940; у Анадыря, Охотска, Нижнеколымска и крепости Бурной
город стоял на суше вне красного (розыск:
WORKFILES/newbuild_2026-09-24/coast/ROZYSK_BEREG_2026-09-25.md).

КАК. Один берег на все даты - суша OSM (land-polygons-split-4326 с
osmdata.openstreetmap.de, из той же береговой линии natural=coastline, что и
вода подложки на крупном масштабе), упрощённая до SIMP и разложенная по
клеткам в 1°. Маска - cache/osm_land/mask.pkl, только клетки, где красное
бывало хоть в одну дату (по облегчённым срезам, с запасом в клетку).
Каждый срез:
  1) красное над морем OSM снимается - навесов больше нет ни в одной эпохе;
  2) зазор заливается: кусок суши OSM без красного идёт в красное, если он
     касается красного, выходит к морю OSM или лежит в море маски NE (русло
     Колымы у Нижнеколымска NE считает морем), и ВЕСЬ лежит ближе G к красному
     или в море NE. Последнее - защита намеренных вырезов, упёртых в берег:
     Кинбурн, взятый 17.10.1855, фронты, оккупации - это не зазор шириной
     в километры, а земля, и она не заливается. Кусок больше CAP_KM2 не
     заливается совсем. Остров (кусок, не касающийся красного) идёт в
     красное, если весь лежит ближе G_ISLE к красному: Котлин с Кронштадтом
     был красным в 1929 и не красным в 1800 и 1968 - по источнику эпохи;
  3) залитое не выходит за чужие границы: то, что легло в зону clip_foreign
     без разрешения на дату среза, снимается (как в шаге обрезки).
Озёра - суша OSM: дыры красного под озёрами к морю не выходят и остаются.
Геометрию не выдумываем: суша - OSM, контроль - тот же срез.

Пересборка по правке: срез проверяется, только если сменилась его отметка
(mtime, размер) или параметры/маска. Кэш - build/cache/coast_osm.json.
Шаг идёт в rebuild.py после обрезки и ПМВ, до потерь, острогов и облегчённых
срезов.
"""
import argparse
import json
import math
import os
import pickle
import sys
import time
from multiprocessing import get_context

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
DATA = os.path.join(ROOT, 'data')
YEARS = os.path.join(DATA, 'years')
NE = os.path.join(ROOT, 'cache')
OSM_DIR = os.path.join(ROOT, 'cache', 'osm_land')
SHP = os.path.join(OSM_DIR, 'land-polygons-split-4326', 'land_polygons.shp')
URL = 'https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip'
MASK = os.path.join(OSM_DIR, 'mask.pkl')
STATE = os.path.join(ROOT, 'build', 'cache', 'coast_osm.json')

SIMP = 0.001           # ~100 м, как упрощение поздних срезов (rebuild.SIMP)
ISLE_KM2 = 0.1         # островки мельче - вон из маски (было 0,01: шхеры Аландов и Турку
                       # давали ячейки крупного масштаба по 500 КБ, 26.09.2026)
EXTRA = os.path.join(OSM_DIR, 'extra')
ART_ZONE = 0.004       # зона вокруг искусственного берега, где суша проверяется на толщину
ART_R = 0.0015         # раскрытие: в зоне уходит суша уже 2·ART_R (дамба, мол, пирс)
# ИСКУССТВЕННЫЙ БЕРЕГ НЕ ТЕРРИТОРИЯ (куратор 26.09.2026: «дамба в 1800 охуеть»).
# Дамба Кронштадта 1979-2011 годов в OSM - береговая линия с man_made=embankment,
# и маска суши держала её сушей во все эпохи: красная нитка через залив в 1800
# году. Возле береговых линий с любым man_made (из 998 в охвате 533 - причалы на
# настоящем берегу) суша раскрывается радиусом ART_R: уходит то, что тоньше
# ~170-330 м (дамба, мол, пирс, волнолом), широкая земля у причалов остаётся.
# Для всех дат одинаково - сооружение не земля ни в какую эпоху.
# ЗАЛИВ ПОВЕРХ БЕРЕГОВОЙ ЛИНИИ - МОРЕ. Бугский лиман в OSM - natural=bay,
# часть Днепровско-Бугского лимана, но береговая линия проведена ниже по течению,
# и маска считала его сушей (рекой): красное легло на воду лимана. Залив берётся
# морем там, где под ним вода OSM (SEA_EXTRA: отношение залива, отношение воды).
SEA_EXTRA = [('bug_liman', 9953396, 12380714)]
PAD = 0.02             # запас за край клетки при упрощении маски
G = 0.05               # зазор у красного, градусы (Анадырь - 0,049° по долготе)
G_ISLE = 0.1           # остров целиком ближе этого к красному - красный (Котлин)
CAP_KM2 = 1500.0       # кусок крупнее - не зазор
EPS = 1e-7
PARAMS = {'simp': SIMP, 'isle': ISLE_KM2, 'g': G, 'g_isle': G_ISLE, 'cap': CAP_KM2, 'v': 4}

_M = {}


def km2(g):
    if g.is_empty:
        return 0.0
    lat = (g.bounds[1] + g.bounds[3]) / 2
    return g.area * 111.32 ** 2 * math.cos(math.radians(lat))


def parts(g):
    if g.is_empty:
        return []
    if g.geom_type == 'Polygon':
        return [g]
    return [p for p in getattr(g, 'geoms', []) if p.geom_type == 'Polygon']


# ---- маска ------------------------------------------------------------------
def footprint():
    """Клетки в 1°, где красное бывало хоть в одну дату, с запасом в клетку."""
    from shapely.geometry import box, shape
    from shapely.strtree import STRtree
    with open(os.path.join(DATA, 'manifest.json'), encoding='utf-8') as f:
        keys = [str(k) for k in json.load(f)['years']]
    cells = set()
    for k in keys:
        p = os.path.join(DATA, 'years_lite', f'{k}.geojson')
        if not os.path.exists(p):
            p = os.path.join(YEARS, f'{k}.geojson')
        with open(p, encoding='utf-8') as f:
            fc = json.load(f)
        for ft in fc['features']:
            if not ft.get('geometry'):
                continue
            for part in parts(shape(ft['geometry']).buffer(0)):
                x0, y0, x1, y1 = part.bounds
                cand = [(x, y) for x in range(math.floor(x0), math.ceil(x1))
                        for y in range(math.floor(y0), math.ceil(y1))]
                if len(cand) <= 4:
                    cells.update(cand)
                    continue
                tr = STRtree([box(x, y, x + 1, y + 1) for x, y in cand])
                cells.update(cand[i] for i in tr.query(part, predicate='intersects'))
    ext = {((x + dx + 180) % 360 - 180, y + dy) for x, y in cells
           for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    return {c for c in ext if -90 <= c[1] < 90}


def fetch_extras():
    """Выгрузить из OSM искусственный берег и заливы SEA_EXTRA в cache/osm_land/extra."""
    from fetch_borders import ask
    os.makedirs(EXTRA, exist_ok=True)
    ways = []
    for s, w, n, e in [(32, -180, 80, -110), (32, 10, 80, 40), (32, 40, 80, 70),
                       (32, 70, 80, 110), (32, 110, 80, 150), (32, 150, 80, 180)]:
        r = ask(f'[out:json][timeout:600];way["natural"="coastline"]["man_made"]({s},{w},{n},{e});out tags geom;')
        ways += [{'id': x['id'], 'man_made': x['tags'].get('man_made'), 'name': x['tags'].get('name'),
                  'coords': [[p['lon'], p['lat']] for p in x['geometry']]}
                 for x in r['elements'] if x['type'] == 'way' and x.get('geometry')]
    with open(os.path.join(EXTRA, 'manmade_coastline.json'), 'w') as f:
        json.dump(ways, f)
    for slug, bay, water in SEA_EXTRA:
        for rid, suf in ((bay, ''), (water, '_water')):
            r = ask(f'[out:json][timeout:180];rel({rid});out geom;')
            with open(os.path.join(EXTRA, f'{slug}{suf}.json'), 'w') as f:
                json.dump(r, f)
    print('искусственных береговых линий', len(ways))


def _rel_poly(path):
    from shapely.geometry import LineString
    from shapely.ops import linemerge, polygonize, unary_union
    with open(path) as f:
        r = json.load(f)
    rel = [e for e in r['elements'] if e['type'] == 'relation'][0]
    outer, inner = [], []
    for m in rel['members']:
        if m['type'] == 'way' and m.get('geometry'):
            (inner if m.get('role') == 'inner' else outer).append(
                LineString([(p['lon'], p['lat']) for p in m['geometry']]))
    g = unary_union(list(polygonize(linemerge(unary_union(outer)))))
    if inner:
        g = g.difference(unary_union(list(polygonize(linemerge(unary_union(inner))))))
    return g.buffer(0)


def extras():
    """-> (STRtree зон искусственного берега, зоны, STRtree заливов-моря, заливы)."""
    from shapely.geometry import LineString
    from shapely.strtree import STRtree
    zones, pieces = [], []
    mm = os.path.join(EXTRA, 'manmade_coastline.json')
    if not os.path.exists(mm):
        sys.exit(f'нет {mm}: сначала --extras')
    with open(mm) as f:
        for w in json.load(f):
            if len(w['coords']) > 1:
                zones.append(LineString(w['coords']).buffer(ART_ZONE, quad_segs=2))
    for slug, _, _ in SEA_EXTRA:
        pieces.append(_rel_poly(os.path.join(EXTRA, f'{slug}.json')).intersection(
            _rel_poly(os.path.join(EXTRA, f'{slug}_water.json'))).buffer(0))
    return STRtree(zones), zones, STRtree(pieces), pieces


def build_mask():
    import shapefile
    from shapely.geometry import box, shape
    from shapely.ops import unary_union
    import geoclean as gc
    if not os.path.exists(SHP):
        sys.exit(f'нет {SHP}: скачать {URL} в {OSM_DIR} и распаковать')
    t = time.perf_counter()
    cells = footprint()
    print(f'клеток охвата: {len(cells)} ({time.perf_counter() - t:.0f} с)', flush=True)
    pieces = {}
    sf = shapefile.Reader(SHP)
    n = kept = 0
    for sh in sf.iterShapes():
        n += 1
        x0, y0, x1, y1 = sh.bbox
        hit = [(x, y) for x in range(math.floor(x0), max(math.ceil(x1), math.floor(x0) + 1))
               for y in range(math.floor(y0), max(math.ceil(y1), math.floor(y0) + 1))
               if (x, y) in cells]
        if not hit:
            continue
        g = shape(sh.__geo_interface__).buffer(0)
        if g.is_empty:
            continue
        kept += 1
        for c in hit:
            pieces.setdefault(c, []).append(g)
    print(f'кусков суши OSM: {n}, в охвате {kept} ({time.perf_counter() - t:.0f} с)', flush=True)
    tree, sea = gc._sea_tree(NE)
    ztree, zps, xtree, xps = extras()
    out = {}
    for (x, y) in sorted(cells):
        bx = box(x, y, x + 1, y + 1)
        # упрощать с запасом PAD за край клетки и резать по краю потом: иначе
        # суша соседних клеток сходилась не встык, и вдоль границы клетки
        # оставалась морская щель в 0,0001° - красное резалось по сетке в 1°
        # (Петербург по 30°, Тикси, Махачкала; пробный прогон 25.09.2026)
        E = box(x - PAD, y - PAD, x + 1 + PAD, y + 1 + PAD)
        ps = {}
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for g in pieces.get((x + dx, y + dy), []):
                    ps[id(g)] = g
        ps = [g for g in ps.values() if g.intersects(E)]
        land = unary_union(ps).intersection(E).buffer(0) if ps else None
        if land is not None and not land.is_empty:
            zs = [zps[i] for i in ztree.query(E)]
            if zs:
                Z = unary_union(zs).intersection(E)
                near = land.intersection(Z)
                opened = near.buffer(-ART_R).buffer(ART_R).intersection(Z)
                land = unary_union([land.difference(Z), opened]).buffer(0)
            xs = [xps[i] for i in xtree.query(E)]
            if xs:
                land = land.difference(unary_union(xs)).buffer(0)
        if land is not None and not land.is_empty:
            land = land.simplify(SIMP, preserve_topology=True).buffer(0)
            land = unary_union([p for p in parts(land) if km2(p) >= ISLE_KM2]).intersection(bx).buffer(0)
        if land is None or land.is_empty:
            kind, land, seag = 'S', None, bx
        elif land.area >= bx.area * (1 - 1e-9):
            kind, seag = 'L', None
            if any(sea[i].intersects(bx) and sea[i].intersection(bx).area > 1e-9
                   for i in tree.query(bx)):
                kind = 'LN'                 # суша OSM, а NE кладёт в море (устья)
            land = bx
        else:
            kind, seag = 'C', bx.difference(land).buffer(0)
        out[(x, y)] = (kind, land.wkb if land is not None else None,
                       seag.wkb if seag is not None else None)
    import collections
    cnt = collections.Counter(v[0] for v in out.values())
    meta = {'source': URL, 'simp': SIMP, 'isle_km2': ISLE_KM2, 'pad': PAD, 'art': [ART_ZONE, ART_R],
            'sea_extra': SEA_EXTRA, 'built': time.strftime('%Y-%m-%d'),
            'shp_mtime': os.path.getmtime(SHP), 'kinds': dict(cnt)}
    hdr = os.path.join(OSM_DIR, 'headers.txt')
    if os.path.exists(hdr):
        with open(hdr, encoding='utf-8', errors='replace') as f:
            meta['http'] = [ln.strip() for ln in f if ln.lower().startswith(('last-modified', 'content-length'))]
    with open(MASK, 'wb') as f:
        pickle.dump({'meta': meta, 'cells': out}, f)
    print(f'маска: {dict(cnt)}, {os.path.getsize(MASK) / 1048576:.1f} МБ, '
          f'{time.perf_counter() - t:.0f} с')


def mask():
    if 'm' not in _M:
        from shapely import wkb
        from shapely.geometry import box
        from shapely.strtree import STRtree
        with open(MASK, 'rb') as f:
            m = pickle.load(f)
        keys = sorted(m['cells'])
        boxes = [box(x, y, x + 1, y + 1) for x, y in keys]
        kind = [m['cells'][c][0] for c in keys]
        land = [wkb.loads(m['cells'][c][1]) if m['cells'][c][1] else None for c in keys]
        sea = [wkb.loads(m['cells'][c][2]) if m['cells'][c][2] else None for c in keys]
        _M['m'] = (m['meta'], keys, boxes, STRtree(boxes), kind, land, sea)
    return _M['m']


BAND = 0.06            # береговая полоса облегчённых уровней: море и суша до BAND от него
BAND_PATH = os.path.join(ROOT, 'build', 'cache', 'coast_band.pkl')


def coast_band():
    """Море охвата и суша ближе BAND к нему - одним полигоном (build_lite.py:
    у моря контур упрощается грубее, чем сухопутные границы). Кэш на диске,
    ключ - маска и BAND."""
    if 'band' in _M:
        return _M['band']
    import shapely
    from shapely import wkb
    from shapely.ops import unary_union
    sig = {'mask': mask_sig(), 'band': BAND, 'v': 1}
    try:
        with open(BAND_PATH, 'rb') as f:
            c = pickle.load(f)
        if c.get('sig') == sig:
            _M['band'] = wkb.loads(c['wkb'])
            shapely.prepare(_M['band'])
            return _M['band']
    except (OSError, ValueError, EOFError, pickle.UnpicklingError):
        pass
    meta, keys, boxes, tree, kind, land, sea = mask()
    seaish = [i for i in range(len(keys)) if kind[i] in ('S', 'C')]
    near = set(tree.query(unary_union([boxes[i] for i in seaish]).buffer(BAND, join_style=2)))
    pieces = []
    for i in near:
        b = boxes[i]
        if kind[i] == 'S':
            pieces.append(b)
            continue
        E = b.buffer(BAND, join_style=2)
        ss = [shapely.clip_by_rect(sea[j], *E.bounds) for j in tree.query(E)
              if kind[j] in ('S', 'C') and sea[j] is not None]
        ss = [x for x in ss if not x.is_empty]
        if not ss:
            continue
        band = unary_union(ss).simplify(0.005).buffer(BAND, quad_segs=2)
        piece = shapely.clip_by_rect(band, *b.bounds)
        if not piece.is_empty:
            pieces.append(piece)
    try:
        g = shapely.coverage_union_all(pieces)
    except Exception:                          # noqa: BLE001
        g = unary_union(pieces)
    os.makedirs(os.path.dirname(BAND_PATH), exist_ok=True)
    with open(BAND_PATH, 'wb') as f:
        pickle.dump({'sig': sig, 'wkb': g.wkb}, f)
    shapely.prepare(g)
    _M['band'] = g
    return g


def mask_sig():
    meta = mask()[0]
    return {k: meta.get(k) for k in ('source', 'simp', 'isle_km2', 'pad', 'art', 'sea_extra', 'shp_mtime')}


# ---- срез -------------------------------------------------------------------
def _clip(g, x0, y0, x1, y1):
    """clip_by_rect, а на кривой геометрии - честное пересечение: clip_by_rect
    валидности не обещает, и повторная вырезка из вырезанного падала на кольце
    из трёх точек (срез ПМВ, 26.09.2026)."""
    import shapely
    from shapely.geometry import box
    try:
        return shapely.clip_by_rect(g, x0, y0, x1, y1)
    except shapely.errors.GEOSException:
        return g.buffer(0).intersection(box(x0, y0, x1, y1))


def coast_fc(fc, key):
    """Привести берег среза. -> (снято км², залито км², снято чужого км²)."""
    import shapely
    from shapely.geometry import shape
    from shapely.ops import unary_union
    import geoclean as gc
    meta, keys, boxes, tree, kind, land, sea = mask()
    geoms = [shape(f['geometry']) if f.get('geometry') else None for f in fc['features']]
    geoms = [g if g is None or g.is_valid else g.buffer(0) for g in geoms]
    live = [g for g in geoms if g is not None and not g.is_empty]
    if not live:
        return 0.0, 0.0, 0.0
    red = unary_union(live)
    # 1) снять красное над морем OSM
    hit = tree.query(red, predicate='intersects')
    seacells = [i for i in hit if kind[i] in ('S', 'C')]
    cut = 0.0
    if seacells:
        try:                                   # клетки не перекрываются - быстрый путь
            SEA = shapely.coverage_union_all([sea[i] for i in seacells])
        except Exception:                      # noqa: BLE001
            SEA = unary_union([sea[i] for i in seacells])
        shapely.prepare(SEA)
        for j, g in enumerate(geoms):
            if g is None or g.is_empty or not SEA.intersects(g):
                continue
            ng = g.difference(SEA)
            cut += km2(g) - km2(ng)
            geoms[j] = ng
        red = unary_union([g for g in geoms if g is not None and not g.is_empty])
    # 2) залить зазор
    fill = 0.0
    alien = 0.0
    # клетки у края красного и в G_ISLE от него (острова в соседней клетке)
    eidx = tree.query(red.boundary, predicate='dwithin', distance=G_ISLE)
    fcells = [i for i in eidx if kind[i] in ('C', 'LN')]
    add = {}
    if fcells:
        sea_tree, ne_sea = gc._sea_tree(NE)
        near_sea = [sea[i] for i in set(seacells) | set(fcells) if sea[i] is not None]
        SEAn = unary_union(near_sea) if near_sea else None
        if SEAn is not None:
            shapely.prepare(SEAn)
        shapely.prepare(red)
        cand = unary_union([land[i].difference(_clip(red, *boxes[i].bounds))
                            for i in fcells])
        # красное вокруг клетки и море NE - раз на клетку; буфер - только вокруг
        # куска (замер 25.09: буфер на клетку - 153 с из 190 на срез 1855 года)
        red_c, ne_c = {}, {}

        def red_cell(i):
            if i not in red_c:
                b = boxes[i].bounds
                p = 2 * G_ISLE
                red_c[i] = _clip(red, b[0] - p, b[1] - p, b[2] + p, b[3] + p)
            return red_c[i]

        def red_near(c, cells_c, d):
            x0, y0, x1, y1 = c.bounds
            rs = [_clip(red_cell(i), x0 - d, y0 - d, x1 + d, y1 + d) for i in cells_c]
            rs = [r for r in rs if not r.is_empty]
            if not rs:
                return None
            if len(rs) == 1:
                return rs[0]
            try:
                return unary_union(rs)
            except shapely.errors.GEOSException:
                # вырезка бывает невалидной (Турку, срезы ПМВ, 26.09.2026)
                return unary_union([r.buffer(0) for r in rs])

        def ne_of(i):
            if i not in ne_c:
                q = sea_tree.query(boxes[i])
                ne_c[i] = (unary_union([ne_sea[k] for k in q]).intersection(boxes[i])
                           if len(q) else None)
            return ne_c[i]
        def within(c, r, d, ne=None):
            """Весь кусок ближе d к красному r (или в море NE): по точкам контура
            и внутренней точке - буфер красного на кусок стоил минуты на срез."""
            import numpy as np
            pts = shapely.get_coordinates(c)
            if len(pts) > 400:
                pts = pts[::len(pts) // 400 + 1]
            P = shapely.points(np.vstack([pts, shapely.get_coordinates(c.representative_point())]))
            if ne is not None:
                shapely.prepare(ne)
                P = P[~shapely.intersects(ne, P)]
            if not len(P):
                return True
            if r is None:
                return False
            return float((shapely.distance(P, r) > d).mean()) <= 0.01

        live_j = [j for j, g in enumerate(geoms) if g is not None and not g.is_empty]
        for c in parts(cand):
            if c.area < 1e-9 or km2(c) > CAP_KM2:
                continue
            cells_c = tree.query(c, predicate='intersects')
            if not red.intersects(c):
                # остров: целиком ближе G_ISLE к красному
                r = red_near(c, cells_c, 2 * G_ISLE)
                if r is None or r.distance(c) > G_ISLE:
                    continue
                if within(c, r, G_ISLE):
                    j = live_j[0] if len(live_j) == 1 else min(
                        live_j, key=lambda j: geoms[j].distance(c))
                    add.setdefault(j, []).append(c)
                continue
            nes = [ne_of(i) for i in cells_c]
            nes = [g for g in nes if g is not None and not g.is_empty]
            ne = unary_union(nes) if nes else None
            touch = SEAn is not None and SEAn.intersects(c)
            in_ne = ne is not None and ne.intersection(c).area >= 0.5 * c.area
            if not (touch or in_ne):
                continue
            if not within(c, red_near(c, cells_c, 2 * G), G, ne):
                continue
            if len(live_j) == 1:
                j = live_j[0]
            else:
                cb = c.buffer(1e-5)
                j = max(live_j, key=lambda j: geoms[j].intersection(cb).area)
            add.setdefault(j, []).append(c)
    if add:
        # 3) чужие границы: как шаг обрезки (rebuild.clip_key)
        import clip_foreign as cf
        if 'f' not in _M:
            _M['f'] = cf.foreign_geom()
            cf.relevant(_M['f'])
        foreign = _M['f']
        zone = foreign
        ex = cf.foreign_since_geom(cf.key_date(key))
        if ex is not None:
            zone = unary_union([foreign, ex])
        allowed, got = None, False
        for j, cs in add.items():
            pc = unary_union(cs)
            bleed = pc.intersection(zone)
            if not bleed.is_empty and bleed.area > 1e-9:
                if not got:
                    allowed, got = cf.allowed_at(cf.key_date(key), foreign), True
                bad = bleed.difference(allowed) if allowed is not None else bleed
                if not bad.is_empty:
                    alien += km2(bad)
                    pc = pc.difference(bad).buffer(0)
            if pc.is_empty:
                continue
            fill += km2(pc)
            # внахлёст на 2e-6° (0,2 м): встык оставался волосяной шов
            geoms[j] = unary_union([geoms[j], pc.buffer(2e-6, join_style=2)])
    for j, g in enumerate(geoms):
        if fc['features'][j].get('geometry') and g is not None:
            fc['features'][j]['geometry'] = g.__geo_interface__
    fc['features'] = [f for f, g in zip(fc['features'], geoms)
                      if not f.get('geometry') or (g is not None and not g.is_empty)]
    return cut, fill, alien


def stamp(k):
    st = os.stat(os.path.join(YEARS, k + '.geojson'))
    return [st.st_mtime_ns, st.st_size]


def coast_key(args):
    k, dry = args
    t = time.perf_counter()
    path = os.path.join(YEARS, k + '.geojson')
    with open(path, encoding='utf-8') as f:
        fc = json.load(f)
    cut, fill, alien = coast_fc(fc, k)
    if not dry and (cut > 0 or fill > 0):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(fc, f, ensure_ascii=False)
    return k, cut, fill, alien, stamp(k), time.perf_counter() - t


def keys_of():
    with open(os.path.join(DATA, 'manifest.json'), encoding='utf-8') as f:
        return [str(k) for k in json.load(f)['years']
                if os.path.exists(os.path.join(YEARS, f'{k}.geojson'))]


def load_state(full=False):
    try:
        with open(STATE, encoding='utf-8') as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    sig = {'params': PARAMS, 'mask': mask_sig()}
    if full or st.get('sig') != sig:
        st = {'sig': sig, 'stamps': {}}
    return st


def pending():
    """Срезы, которые шаг проверит при следующем запуске (для rebuild.py)."""
    if not os.path.exists(MASK):
        return []
    st = load_state()
    return [k for k in keys_of() if st['stamps'].get(k) != stamp(k)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mask', action='store_true')
    ap.add_argument('--extras', action='store_true')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--keys')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    if a.extras:
        fetch_extras()
        return
    if a.mask:
        build_mask()
        return
    if not os.path.exists(MASK):
        sys.exit(f'нет маски {MASK}: сначала --mask')
    mask()                                      # маску проверить до первой записи
    st = load_state(a.all)
    keys = keys_of()
    if a.keys:
        todo = [k for k in a.keys.split(',') if k in set(keys)]
    else:
        todo = [k for k in keys if st['stamps'].get(k) != stamp(k)]
    t = time.perf_counter()
    res = []
    if todo:
        with get_context('spawn').Pool(a.workers) as pool:
            for r in pool.imap_unordered(coast_key, [(k, a.dry) for k in todo]):
                res.append(r)
                if not a.dry:
                    st['stamps'][r[0]] = r[4]
                if a.dry or a.keys:
                    print(f'   {r[0]}: снято над морем {r[1]:.0f} км², залито {r[2]:.0f} км²'
                          + (f', снято чужого {r[3]:.1f} км²' if r[3] else '') + f' ({r[5]:.0f} с)',
                          flush=True)
    if not a.dry:
        st['stamps'] = {k: v for k, v in st['stamps'].items() if k in set(keys)}
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, 'w', encoding='utf-8') as f:
            json.dump(st, f)
    if res:
        print(f'срезов {len(res)} из {len(keys)}: снято над морем {sum(r[1] for r in res):.0f} км², '
              f'залито {sum(r[2] for r in res):.0f} км², чужого снято {sum(r[3] for r in res):.1f} км², '
              f'{time.perf_counter() - t:.0f} с')
    else:
        print(f'срезов к проверке нет (из {len(keys)})')


if __name__ == '__main__':
    main()
