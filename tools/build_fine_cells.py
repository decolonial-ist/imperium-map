"""Ячейки крупного масштаба (неделя 3 архитектуры, 24.09.2026).

  python tools/build_fine_cells.py          пересобрать ячейки задетых дат
  python tools/build_fine_cells.py --all    все ячейки с нуля

ЗАЧЕМ. С масштаба 8 (FULL_Z) карта брала полный срез на дату: 0,25-3,5 МБ
сжатыми на каждую остановку ползунка, по всему миру, хотя на экране кусок в
пару градусов. Здесь точные срезы (0,001°) нарезаны сеткой 10°, и в ячейке
лежат ВСЕ даты одной топологией: соседние даты делят дуги. Карта качает только
ячейки под окном, и дальше ползунок на этом месте идёт без сети.

КАК. Точный срез даты объединяется (без отброса мелочи: на этом масштабе
видны мелкие острова Соловков, их и вернула обрезка 24.09) и режется
прямоугольниками ячеек; куски кэшируются в
build/cache/fine_clip/<ячейка>/<дата>.geojson; ячейка - geo2topo -q 1e5 по
кускам всех дат (шаг ~10 м). Ячейка тяжелее BUDGET сжатыми делится на четыре,
пока сторона не станет MIN.

ШОВ. Линии сетки сдвинуты на OFF = 0,00037° от круглых градусов (кроме ±180):
вершины срезов стоят на сетке 0,001°, и настоящая граница не может лечь
ребром на линию ячейки. Поэтому обводка (index.html, outlineOf) выбрасывает
рёбра, у которых обе вершины на одной линии сетки, - это разрез ячейки, а не
граница. Круглые линии заняты настоящими границами: Сахалин 1905-1945 по 50° с. ш.

Пересборка по правке: даты со сменившейся отметкой (mtime, размер) режутся
заново; пересобираются ячейки, которых эти даты касались до или после правки.
Опись - data/fine_manifest.json.
"""
import argparse
import gzip
import json
import os
import subprocess
import sys
from multiprocessing import get_context

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(DATA, 'fine_cells')
CACHE = os.path.join(ROOT, 'build', 'cache')
CLIP = os.path.join(CACHE, 'fine_clip')
STATE = os.path.join(CACHE, 'fine_cells.json')
BIN = os.path.join(ROOT, 'node_modules', '.bin')
BASE = 10.0
MIN = 2.5
OFF = 0.00037
Q = '1e5'
BUDGET = 200 * 1024
SAME = 1e-8                    # град², ~100 м²: кусок «тот же»
PARAMS = {'base': BASE, 'min': MIN, 'off': OFF, 'q': Q, 'budget': BUDGET, 'v': 2}


def key_date(k):
    p = str(k).split('-')
    return (int(p[0]), int(p[1]) if len(p) > 1 else 1, int(p[2]) if len(p) > 2 else 1)


def stamp(k):
    st = os.stat(os.path.join(DATA, 'years', k + '.geojson'))
    return [st.st_mtime_ns, st.st_size]


def edges(lo, hi, size, off):
    """Линии сетки шага size со сдвигом off внутри [lo, hi], концы - сами lo и hi."""
    import math
    out = [lo]
    k = math.floor((lo - off) / size) + 1
    while k * size + off < hi:
        v = round(k * size + off, 6)
        if v - lo > 1e-3 and hi - v > 1e-3:      # без щелей в 0,00037° у ±180
            out.append(v)
        k += 1
    out.append(hi)
    return out


def cell_id(box):
    return '_'.join(f'{v:.5f}'.rstrip('0').rstrip('.') for v in box)


BASE_CELLS = [(x0, y0, x1, y1)
              for xs in [edges(-180.0, 180.0, BASE, OFF)] for ys in [edges(-90.0, 90.0, BASE, OFF)]
              for x0, x1 in zip(xs, xs[1:]) for y0, y1 in zip(ys, ys[1:])]


def write_fc(path, geom):
    from shapely.geometry import mapping
    feats = [] if geom is None or geom.is_empty else [
        {'type': 'Feature', 'properties': {}, 'geometry': mapping(geom)}]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': feats}, f, separators=(',', ':'))


def read_geom(path):
    from shapely.geometry import shape
    from shapely.ops import unary_union
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        fc = json.load(f)
    gs = [shape(ft['geometry']) for ft in fc['features'] if ft.get('geometry')]
    return unary_union(gs) if gs else None


def polys_only(g):
    from shapely.geometry import MultiPolygon, Polygon
    if g is None or g.is_empty:
        return None
    if isinstance(g, (Polygon, MultiPolygon)):
        return g
    ps = [p for p in getattr(g, 'geoms', []) if isinstance(p, (Polygon, MultiPolygon))]
    if not ps:
        return None
    from shapely.ops import unary_union
    return unary_union(ps)


def clip_key(args):
    """Дата -> куски по базовым ячейкам: (дата, ячейки с куском, ячейки, где кусок
    сменился, {ячейка: двойник}).

    Правка строки меняет дату в одном углу карты, а срез переписывается целиком
    (и не байт в байт: сборка недетерминирована). Кусок, совпавший с прежним по
    геометрии, не переписывается, и его ячейка не пересобирается. Кусок НОВОЙ
    даты, совпавший с куском предыдущей даты (prev), - двойник: в ячейку
    дописывается ссылка на те же дуги, без geo2topo."""
    k, prev, was = args                         # was - ячейки, где дата лежала по описи
    import shapely
    from shapely.geometry import box
    from shapely.geometry import shape
    from shapely.ops import unary_union
    src = os.path.join(DATA, 'years', k + '.geojson')
    fu = os.path.join(CACHE, 'full_union', k + '.geojson')
    if os.path.exists(fu) and os.path.getmtime(fu) >= os.path.getmtime(src):
        g = read_geom(fu)                       # объединение уже посчитал build_mid_packs.py
    else:
        with open(src, encoding='utf-8') as f:
            fc = json.load(f)
        parts = [shape(ft['geometry']).buffer(0) for ft in fc['features'] if ft.get('geometry')]
        g = unary_union([p for p in parts if not p.is_empty]).buffer(0) if parts else None
    hit, moved, twin = [], [], {}
    if g is not None and not g.is_empty:
        b = g.bounds
        for c in BASE_CELLS:
            if c[2] < b[0] or c[0] > b[2] or c[3] < b[1] or c[1] > b[3]:
                continue
            piece = polys_only(shapely.intersection(g, box(*c)))
            if piece is None or piece.area < 1e-9:
                continue
            path = os.path.join(CLIP, cell_id(c), k + '.geojson')
            hit.append(cell_id(c))
            old = read_geom(path) if cell_id(c) in was else None
            # порог ~100 м²: сборка недетерминирована, пересобранный срез
            # отличается от прежнего крохами у берегов; настоящая правка - км²
            if old is not None and not old.is_empty and \
                    old.buffer(0).symmetric_difference(piece).area < SAME:
                continue
            write_fc(path, piece)
            if old is not None and not old.is_empty:
                print(f'   {k} {cell_id(c)}: кусок сменился на '
                      f'{old.buffer(0).symmetric_difference(piece).area:.2e} град²', flush=True)
            try:                                # кусок prev могут писать рядом - тогда не двойник
                twin_g = read_geom(os.path.join(CLIP, cell_id(c), prev + '.geojson')) \
                    if prev and (old is None or old.is_empty) else None
            except ValueError:
                twin_g = None
            if twin_g is not None and not twin_g.is_empty and \
                    twin_g.buffer(0).symmetric_difference(piece).area < SAME:
                twin[cell_id(c)] = prev
            else:
                moved.append(cell_id(c))
    return k, hit, moved, twin


def topo(box_, keys):
    env = dict(os.environ, NODE_OPTIONS='--max-old-space-size=8000')
    d = os.path.join(CLIP, cell_id(box_))
    r = subprocess.run([os.path.join(BIN, 'geo2topo'), '-q', Q]
                       + [os.path.join(d, k + '.geojson') for k in keys],
                       stdout=subprocess.PIPE, check=True, env=env)
    return r.stdout


def sub_boxes(c):
    # шаг - по номинальной стороне (10, 5, 2,5): ячейки у ±180 шире на OFF, а линии
    # деления обязаны лечь на общую сетку MIN - по ней обводка узнаёт разрез
    import math
    size = c[2] - c[0]
    half = MIN * 2 ** round(math.log2(size / MIN)) / 2
    xs = edges(c[0], c[2], half, OFF)
    ys = edges(c[1], c[3], half, OFF)
    if len(xs) < 3 or len(ys) < 3:                  # у ±180 и полюсов - по серединам
        xm, ym = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2
        xs, ys = [c[0], xm, c[2]], [c[1], ym, c[3]]
    return [(x0, y0, x1, y1) for x0, x1 in zip(xs, xs[1:]) for y0, y1 in zip(ys, ys[1:])]


def build_cell(c, keys, out):
    """Ячейка c из кусков дат keys; тяжелее бюджета - на четыре."""
    import shapely
    from shapely.geometry import box
    if not keys:
        return
    raw = topo(c, keys)
    gz = len(gzip.compress(raw, 9))
    if gz > BUDGET and (c[2] - c[0]) > MIN + 1e-9:
        for s in sub_boxes(c):
            sk = []
            for k in keys:
                g = read_geom(os.path.join(CLIP, cell_id(c), k + '.geojson'))
                piece = polys_only(shapely.intersection(g, box(*s))) if g is not None else None
                if piece is None or piece.area < 1e-9:
                    continue
                write_fc(os.path.join(CLIP, cell_id(s), k + '.geojson'), piece)
                sk.append(k)
            build_cell(s, sk, out)
        return
    name = cell_id(c) + '.topo.json'
    with open(os.path.join(OUT, name), 'wb') as f:
        f.write(raw)
    out.append({'box': list(c), 'file': 'data/fine_cells/' + name, 'gz': gz, 'n': len(keys)})


def build_base(args):
    c, keys = args
    out = []
    build_cell(c, keys, out)
    return cell_id(c), out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    if not os.path.exists(os.path.join(BIN, 'geo2topo')):
        sys.exit('geo2topo не найден: `npm ci` в корне репо')
    with open(os.path.join(DATA, 'manifest.json'), encoding='utf-8') as f:
        keys = [str(k) for k in json.load(f)['years']]
    keys = sorted((k for k in keys if os.path.exists(os.path.join(DATA, 'years', k + '.geojson'))),
                  key=key_date)
    os.makedirs(OUT, exist_ok=True)
    try:
        with open(STATE, encoding='utf-8') as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    fresh = a.all or st.get('params') != PARAMS
    if fresh:
        st = {'params': PARAMS, 'stamps': {}, 'key_cells': {}, 'cells': {}}
    now = {k: stamp(k) for k in keys}
    changed = [k for k in keys if st['stamps'].get(k) != now[k]]
    gone = [k for k in st['key_cells'] if k not in now]
    key_cells = {k: v for k, v in st['key_cells'].items() if k in now}

    # куски изменённых дат; прежние куски в ячейках, где даты больше нет, пустеют
    touched = set()
    for k in gone:                              # куски снятой даты пустеют
        for cid in st['key_cells'].get(k, []):
            write_fc(os.path.join(CLIP, cid, k + '.geojson'), None)
    twins = {}                                  # ячейка -> {новая дата: двойник}
    if changed:
        # двойник - предыдущая дата; где её кусок сменился, ячейка и так
        # пересобирается целиком (touched), и правка готовой топологии её не трогает
        prev = dict(zip(keys, [None] + keys[:-1]))
        with get_context('spawn').Pool(a.workers) as pool:
            for k, hit, moved, twin in pool.imap_unordered(
                    clip_key, [(k, None if fresh else prev[k], set(st['key_cells'].get(k, [])))
                               for k in changed]):
                for cid in set(st['key_cells'].get(k, [])) - set(hit):
                    write_fc(os.path.join(CLIP, cid, k + '.geojson'), None)
                    touched.add(cid)
                key_cells[k] = hit
                touched |= set(moved)
                for cid, p in twin.items():
                    twins.setdefault(cid, {})[k] = p
    if fresh:                                   # с нуля - все ячейки, где есть куски
        touched = {cid for v in key_cells.values() for cid in v}
    print(f'нарезано дат: {len(changed)} из {len(keys)}, снятых {len(gone)}; '
          f'задето базовых ячеек: {len(touched)}', flush=True)

    # ячейки, где только двойники и снятые даты: правка готовой топологии
    patch = {cid: tw for cid, tw in twins.items() if cid not in touched and cid in st['cells']}
    touched |= set(twins) - set(patch)
    for k in gone:
        for cid in st['key_cells'].get(k, []):
            if cid in patch or cid in touched:
                continue
            patch[cid] = {}
    touched -= set(patch)
    for cid, tw in patch.items():
        for x in st['cells'][cid]:
            path = os.path.join(ROOT, x['file'])
            with open(path, encoding='utf-8') as f:
                t = json.load(f)
            for k in gone:
                t['objects'].pop(k, None)
            for k, p in sorted(tw.items(), key=lambda kv: key_date(kv[0])):
                if p in t['objects']:
                    t['objects'][k] = t['objects'][p]
            raw = json.dumps(t, separators=(',', ':')).encode()
            with open(path, 'wb') as f:
                f.write(raw)
            x['gz'], x['n'] = len(gzip.compress(raw, 9)), len(t['objects'])
    if patch:
        print(f'поправлено ячеек без пересборки (двойники, снятые даты): {len(patch)}', flush=True)

    by_cell = {}
    for k in keys:
        for cid in key_cells.get(k, []):
            by_cell.setdefault(cid, []).append(k)
    boxes = {cell_id(c): c for c in BASE_CELLS}
    jobs = [(boxes[cid], by_cell.get(cid, [])) for cid in sorted(touched) if cid in boxes]
    cells = {cid: v for cid, v in st['cells'].items() if cid not in touched}
    if jobs:
        with get_context('spawn').Pool(a.workers) as pool:
            for cid, out in pool.imap_unordered(build_base, jobs):
                cells[cid] = out
    cells = {cid: v for cid, v in cells.items() if v}

    # файлы ячеек, которых больше нет в описи, - в build/removed (не удаляются)
    live = {os.path.basename(x['file']) for v in cells.values() for x in v}
    for fn in os.listdir(OUT):
        if fn.endswith('.topo.json') and fn not in live:
            os.makedirs(os.path.join(ROOT, 'build', 'removed', 'fine_cells'), exist_ok=True)
            os.replace(os.path.join(OUT, fn), os.path.join(ROOT, 'build', 'removed', 'fine_cells', fn))

    flat = sorted((x for v in cells.values() for x in v), key=lambda x: (x['box'][1], x['box'][0]))
    man = {'note': ('ячейки крупного масштаба: точные срезы сеткой %g° (дробление до %g°), '
                    'все даты ячейки одной топологией; линии сетки сдвинуты на %g° от '
                    'круглых градусов, кроме ±180; сборка tools/build_fine_cells.py'
                    % (BASE, MIN, OFF)),
           'off': OFF, 'min': MIN,
           'cells': [x['box'] + [x['file']] for x in flat]}
    with open(os.path.join(DATA, 'fine_manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(man, f, ensure_ascii=False, separators=(',', ':'))
    with open(STATE, 'w', encoding='utf-8') as f:
        json.dump({'params': PARAMS, 'stamps': now, 'key_cells': key_cells, 'cells': cells}, f)
    import geoclean as gc
    gc.write_stamp('fine_cells')            # версия данных для service worker
    gzs = sorted(x['gz'] for x in flat)
    print(f'ячеек {len(flat)} (пересобрано базовых {len(jobs)}), всего {sum(gzs) / 1048576:.1f} МБ '
          f'сжатых; медиана {gzs[len(gzs) // 2] // 1024} КБ, крупнейшая {gzs[-1] // 1024} КБ')


if __name__ == '__main__':
    main()
