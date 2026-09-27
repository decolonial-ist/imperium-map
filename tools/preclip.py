#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Куски с готовым берегом (v4, 27.09.2026): берег режется ОДИН РАЗ в исходниках.

Куратор 27.09.2026: «договорились же, что один раз фиксируем берег, а дальше
только раскрашиваем». До этого маска суши OSM (tools/coast_osm.py) прикладывалась
к КАЖДОМУ срезу при каждой пересборке: срез собирался из грубых контуров
источника и регионов Natural Earth, потом его резали маской и заливали щели до
берега - 74 минуты на полную сборку, и так двадцать раз.

Теперь маской режется то, из чего срез собирается: контур источника
(historical-basemaps, CShapes) и регион (regions.csv). Один раз, с теми же
правилами, что coast_fc (снять море, залить щели до берега G, острова в G_ISLE,
куски не крупнее CAP_KM2), без проверки чужих границ - её делает шаг обрезки.
Результат лежит в cache/preclipped/<вид>__<имя>__<хеш>.wkb; хеш - от сырой
геометрии, подписи маски и правил, так что новая маска или новый контур дают
новый файл сами.

Срез = объединение и вычитание готовых кусков: кромка у всех одна - линия
маски, швов по берегу нет, шаг берега для таких срезов пропускается
(свойство fc['coast'] = 'pieces').
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'cache', 'preclipped')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_sig = {}
# Кусок упрощается до допуска самого среза (build_expansion.SIMPLIFY = 0.005°):
# полная детальность берега OSM на срезе всё равно срезается, а объединения
# и заливки на ней шли в 6-20 раз дольше (проба 27.09: 1886 год - 17 минут)
SIMP = 0.005


def rules():
    """Подпись маски и правил заливки - часть имени куска."""
    if 'r' not in _sig:
        import coast_osm as co
        _sig['r'] = json.dumps({'mask': co.mask_sig(), 'G': co.G, 'G_ISLE': co.G_ISLE,
                                'CAP': co.CAP_KM2, 'simp': SIMP, 'v': 2}, sort_keys=True, ensure_ascii=False)
    return _sig['r']


def _path(kind, ident, h):
    safe = ''.join(ch if ch.isalnum() or ch in '-_.' else '_' for ch in str(ident))
    return os.path.join(OUT, f'{kind}__{safe}__{h}.wkb')


def ne_sha():
    """Хеш файла Natural Earth admin-1 (часть подписи регионов), раз на процесс."""
    import slice_sigs as ss
    return ss.sha_file(os.path.join(ROOT, 'cache', 'ne_admin1.geojson'))


def piece_sig(kind, ident, sig, make):
    """Кусок по ПОДПИСИ ВХОДОВ: sig - JSON-представимое описание того, из чего
    кусок строится (спецификация региона и хеши файлов, хеш сырого контура и
    список более поздних регионов для заливки). Есть файл - сырая геометрия не
    строится вовсе; нет - make() её строит, и она режется как в piece().
    Профиль 27.09.2026: без этого 81 с из 101 на срез уходили на fill_coast
    контура источника ради хеша уже готового куска, ещё 23 с - на сборку
    регионов из NE."""
    from shapely import wkb
    os.makedirs(OUT, exist_ok=True)
    h = hashlib.sha1((json.dumps(sig, sort_keys=True, ensure_ascii=False, default=str)
                      + rules()).encode('utf-8')).hexdigest()[:16]
    path = _path(kind, ident, h)
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return wkb.loads(f.read())
    return _cut_save(make(), path)


def piece(kind, ident, geom):
    """Кусок с готовым берегом для сырой геометрии geom (shapely).

    kind - 'src' (контур источника) или 'reg' (регион), ident - ключ/имя.
    Кэш - по хешу самой геометрии; если сырую геометрию строить дорого,
    берите piece_sig.
    """
    from shapely import wkb
    os.makedirs(OUT, exist_ok=True)
    raw = wkb.dumps(geom)
    h = hashlib.sha1(raw + rules().encode('utf-8')).hexdigest()[:16]
    path = _path(kind, ident, h)
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return wkb.loads(f.read())
    return _cut_save(geom, path)


def _cut_save(geom, path):
    """Срезать морем маски, залить щели до берега, упростить, записать."""
    from shapely import wkb
    from shapely.geometry import mapping, shape
    import coast_osm as co
    g = geom if geom.is_valid else geom.buffer(0)
    fc = {'type': 'FeatureCollection',
          'features': [{'type': 'Feature', 'properties': {}, 'geometry': mapping(g)}]}
    co.coast_fc(fc, None, foreign=False)
    if fc['features'] and fc['features'][0].get('geometry'):
        out = shape(fc['features'][0]['geometry'])
        if not out.is_valid:
            out = out.buffer(0)
        out = out.simplify(SIMP, preserve_topology=True)
        if not out.is_valid:
            out = out.buffer(0)
    else:
        from shapely.geometry import GeometryCollection
        out = GeometryCollection()
    tmp = f'{path}.{os.getpid()}.tmp'          # свой tmp на процесс: гонка при прогреве пулом
    with open(tmp, 'wb') as f:
        f.write(wkb.dumps(out))
    os.replace(tmp, path)
    return out


def seam_cells(pieces, any_piece=False):
    """Клетки маски (виды C, LN), где сходятся границы двух и более кусков -
    там заливка щелей до берега по одному куску не видит землю, близкую к
    их сумме (дельта Волги, Сиваш, Анадырский лиман - проба 27.09.2026).
    any_piece=True - клетки у границы любого куска (дельта к готовому срезу)."""
    import collections
    import coast_osm as co
    meta, keys, boxes, tree, kind, land, sea = co.mask()
    cnt = collections.Counter()
    for p in pieces:
        if p is None or p.is_empty:
            continue
        for i in tree.query(p.boundary, predicate='intersects'):
            cnt[int(i)] += 1
    need = 1 if any_piece else 2
    return {i for i, c in cnt.items() if c >= need and kind[i] in ('C', 'LN')}


def fill_seams(geom, key, cells):
    """Залить щели до берега в клетках cells на готовом объединении.

    Поклеточно (27.09.2026, профиль среза 1886: общее окно на все клетки шва
    давало 14,6 тыс. объединений по 4 мс и буферы по 3 с на геометрии всего
    окна - 100+ с на срез). Каждой клетке - своя вырезка среза с запасом
    3·G_ISLE (coast_fc смотрит на красное в соседних клетках в пределах
    2·G_ISLE), заливка считается на ней, а приращения вливаются в срез одним
    объединением."""
    from shapely.geometry import box, mapping, shape
    from shapely.ops import unary_union
    import shapely
    import coast_osm as co
    if not cells:
        return geom, 0.0
    meta, keys, boxes, tree, kind, land, sea = co.mask()
    pad = 3 * co.G_ISLE
    total = 0.0
    incs = []
    for i in sorted(cells):
        b = boxes[i].bounds
        try:
            local = shapely.clip_by_rect(geom, b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad)
        except shapely.errors.GEOSException:
            local = geom.intersection(box(b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad))
        local = polys(local)
        if local.is_empty:
            continue
        if not local.is_valid:
            local = local.buffer(0)
        fc = {'type': 'FeatureCollection',
              'features': [{'type': 'Feature', 'properties': {}, 'geometry': mapping(local)}]}
        _, fill, _ = co.coast_fc(fc, key, foreign=False, cells={i})
        if fill > 0 and fc['features']:
            g = shape(fc['features'][0]['geometry'])
            inc = polys((g if g.is_valid else g.buffer(0)).difference(local))
            if not inc.is_empty:
                incs.append(inc)
                total += fill
    if not incs:
        return geom, 0.0
    g = polys(unary_union([geom, unary_union(incs)]))
    return (g if g.is_valid else g.buffer(0)), total


def polys(g):
    """Только полигональная часть геометрии (объединение кусков даёт и линии)."""
    from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
    from shapely.ops import unary_union
    if g is None or g.is_empty:
        return GeometryCollection()
    if isinstance(g, (Polygon, MultiPolygon)):
        return g
    parts = [x for x in getattr(g, 'geoms', []) if isinstance(x, (Polygon, MultiPolygon)) and not x.is_empty]
    return unary_union(parts) if parts else GeometryCollection()


def cut_sea(g):
    """Снять с геометрии море маски OSM (клетки S целиком, C - их морем).
    Нужно приращениям заливок: fill_water/fill_source_gaps смыкают кольцо
    красного вокруг залива и красят его (Кизлярский залив, проба 27.09.2026);
    раньше это срезал шаг берега, шедший после них."""
    import shapely
    from shapely.ops import unary_union
    import coast_osm as co
    if g is None or g.is_empty:
        return g
    meta, keys, boxes, tree, kind, land, sea = co.mask()
    idx = [int(i) for i in tree.query(g, predicate='intersects') if kind[int(i)] in ('S', 'C')]
    if not idx:
        return g
    S = unary_union([sea[i] for i in idx if sea[i] is not None])
    return polys(g.difference(S))


def _warm(job):
    import time
    import build_expansion as BE
    kind, name = job
    t = time.perf_counter()
    try:
        (BE.src_geom if kind == 'src' else BE.reg_geom)(name)
        return kind, name, time.perf_counter() - t, ''
    except SystemExit as e:                      # пустой регион и т. п.
        return kind, name, time.perf_counter() - t, str(e)


def main():
    """Прогреть кэш пулом: все контуры источника и все регионы. Без прогрева
    первый же пул сборки режет одни и те же куски в каждом процессе."""
    import argparse
    import time
    from multiprocessing import get_context
    import build_expansion as BE
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()
    jobs = [('src', k) for k in BE.SRC_ORDER] + [('reg', n) for n in BE.REG]
    t = time.perf_counter()
    n = 0
    with get_context('spawn').Pool(a.workers) as pool:
        for kind, name, dt, err in pool.imap_unordered(_warm, jobs):
            n += 1
            if dt > 20 or err:
                print(f'  {kind} {name}: {dt:.0f} с {err}', flush=True)
    print(f'OK preclip: кусков {n}, {(time.perf_counter() - t) / 60:.1f} мин, {OUT}', flush=True)


if __name__ == '__main__':
    main()
