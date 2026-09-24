"""Пакеты среднего уровня по времени (неделя 3 архитектуры, 24.09.2026).

  python tools/build_mid_packs.py          пересобрать пакеты, где сменились срезы
  python tools/build_mid_packs.py --all    все пакеты с нуля

ЗАЧЕМ. На масштабе 4,5-8 карта берёт средний срез (data/years_mid, 0,002°)
на каждую остановку ползунка: 60-150 КБ сжатыми, на 3G 2-3 с на дату. Соседние
даты делят почти все границы, но каждый средний срез упрощён сам по себе,
поэтому одна граница ложится у разных дат разными вершинами и в топологию не
склеивается (вся средняя история одной топологией - 8,4 МБ сжатыми).

КАК. Точные срезы (data/years) объединяются по дате, режутся на дуги
geo2topo, общие для всех дат пакета; каждая дуга упрощается ОДИН раз
(Дуглас-Пекер 0,002°, концы дуг на месте), затем topoquantize. Замер
24.09.2026: 1450-1800 - 138 дат в 403 КБ сжатыми (поштучно 10,2 МБ);
1914-1921 - 146 дат в 565 КБ (поштучно 12,2 МБ). Поздние срезы (с 1922)
упрощены сборщиком каждый отдельно и дуг почти не делят: 87 дат - 5,5 МБ
(поштучно 8,9 МБ), выигрыш там в дробление, а не в сжатие.

Пакет не больше BUDGET сжатыми: эпоха, что не влезает, делится пополам, пока
не влезет. Карта (index.html, coreLoadMid) первую остановку берёт средним
срезом, как раньше, а пакет эпохи качает следом; дальше ползунок внутри
эпохи идёт без сети. Опись - поле packs в data/mid_manifest.json (его пишет
build_lite.py --level mid, поэтому этот сборщик идёт после него).

Пересборка по правке: пакет пересобирается, только если сменился его список
дат или отметка (mtime, размер) хоть одного его точного среза. Кэш -
build/cache/mid_packs.json и объединённые срезы в build/cache/mid_union/.
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
OUT = os.path.join(DATA, 'mid_packs')
CACHE = os.path.join(ROOT, 'build', 'cache')
UNION = os.path.join(CACHE, 'mid_union')
FULL_UNION = os.path.join(CACHE, 'full_union')
STATE = os.path.join(CACHE, 'mid_packs.json')
BIN = os.path.join(ROOT, 'node_modules', '.bin')
TOL = 0.002                    # как средний уровень (build_lite.TOL_MID)
Q = '1e6'                      # шаг сетки ~0,0004° на охвате империи
BUDGET = 450 * 1024            # сжатыми; ~5 с на медленном 3G, фоном
# эпохи - верхний уровень нарезки: внутри них даты делят дуги, на стыках нет
ERAS = ['1914-07-19', '1922', '1992']
PARAMS = {'tol': TOL, 'q': Q, 'budget': BUDGET, 'eras': ERAS, 'v': 1}


def key_date(k):
    p = str(k).split('-')
    return (int(p[0]), int(p[1]) if len(p) > 1 else 1, int(p[2]) if len(p) > 2 else 1)


def stamp(k):
    st = os.stat(os.path.join(DATA, 'years', k + '.geojson'))
    return [st.st_mtime_ns, st.st_size]


def union_one(k):
    """Точный срез -> один полигон даты (как средний срез, без упрощения)."""
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union
    import geoclean as gc
    from build_domain_bundle import drop_slivers
    with open(os.path.join(DATA, 'years', k + '.geojson'), encoding='utf-8') as f:
        fc = json.load(f)
    parts = []
    for ft in fc.get('features', []):
        if ft.get('geometry'):
            try:
                s = shape(ft['geometry']).buffer(0)
            except Exception:                            # noqa: BLE001
                continue
            if not s.is_empty:
                parts.append(s)
    g = unary_union(parts).buffer(0) if parts else None
    # объединение без отброса мелочи - ячейкам крупного масштаба (build_fine_cells.py)
    os.makedirs(FULL_UNION, exist_ok=True)
    with open(os.path.join(FULL_UNION, k + '.geojson'), 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': [] if g is None or g.is_empty else [
            {'type': 'Feature', 'properties': {}, 'geometry': mapping(g)}]}, f, separators=(',', ':'))
    g = drop_slivers(g, TOL * TOL * 4) if g is not None and not g.is_empty else None
    feats = [] if g is None or g.is_empty else [
        {'type': 'Feature', 'properties': {'mid': True}, 'geometry': mapping(g)}]
    out = {'type': 'FeatureCollection', 'features': feats}
    with open(os.path.join(UNION, k + '.geojson'), 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj(out), f, separators=(',', ':'))
    return k, stamp(k)


def build_pack(keys):
    """Топология дат keys: общие дуги, упрощение по дугам, квантование."""
    from shapely.geometry import LineString
    env = dict(os.environ, NODE_OPTIONS='--max-old-space-size=12000')
    tmp = os.path.join(CACHE, '_pack_raw.topo.json')
    with open(tmp, 'wb') as f:
        subprocess.run([os.path.join(BIN, 'geo2topo')]
                       + [os.path.join(UNION, k + '.geojson') for k in keys],
                       stdout=f, check=True, env=env)
    with open(tmp, encoding='utf-8') as f:
        t = json.load(f)
    arcs = []
    for a in t['arcs']:
        if len(a) > 2:
            s = LineString(a).simplify(TOL, preserve_topology=False).coords
            a = [list(p) for p in s] if len(s) >= 2 else [a[0], a[-1]]
        arcs.append(a)
    t['arcs'] = arcs
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(t, f, separators=(',', ':'))
    r = subprocess.run([os.path.join(BIN, 'topoquantize'), Q, tmp],
                       stdout=subprocess.PIPE, check=True, env=env)
    os.remove(tmp)
    return r.stdout


def pack_name(keys):
    return f'{keys[0]}_{keys[-1]}.topo.json'


def fit(keys, out):
    """Собрать пакет; не влез в бюджет - пополам."""
    raw = build_pack(keys)
    gz = len(gzip.compress(raw, 9))
    if gz > BUDGET and len(keys) > 1:
        h = len(keys) // 2
        fit(keys[:h], out)
        fit(keys[h:], out)
        return
    with open(os.path.join(OUT, pack_name(keys)), 'wb') as f:
        f.write(raw)
    out.append({'keys': keys, 'gz': gz})
    print(f'   пакет {keys[0]} .. {keys[-1]}: дат {len(keys)}, {gz // 1024} КБ сжатых', flush=True)


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
    os.makedirs(UNION, exist_ok=True)
    try:
        with open(STATE, encoding='utf-8') as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    if a.all or st.get('params') != PARAMS:
        st = {'params': PARAMS, 'stamps': {}, 'packs': []}
    now = {k: stamp(k) for k in keys}

    # объединённые срезы: только те, чья отметка сменилась
    redo = [k for k in keys if st['stamps'].get(k) != now[k]
            or not os.path.exists(os.path.join(UNION, k + '.geojson'))
            or not os.path.exists(os.path.join(FULL_UNION, k + '.geojson'))]
    if redo:
        with get_context('spawn').Pool(a.workers) as pool:
            for k, s in pool.imap_unordered(union_one, redo):
                now[k] = s
    print(f'объединено срезов: {len(redo)} из {len(keys)}', flush=True)

    # группы: прежние пакеты (новые даты - в пакет, чей диапазон их накрывает),
    # без кэша - эпохи
    if st['packs']:
        groups = [[k for k in p['keys'] if k in now] for p in st['packs']]
        firsts = [p['keys'][0] for p in st['packs']]
        known = {k for g in groups for k in g}
        for k in keys:
            if k in known:
                continue
            i = max([j for j, f in enumerate(firsts) if key_date(f) <= key_date(k)] or [0])
            groups[i].append(k)
        groups = [sorted(g, key=key_date) for g in groups if g]
    else:
        bounds = [key_date(e) for e in ERAS]
        groups = [[] for _ in range(len(ERAS) + 1)]
        for k in keys:
            groups[sum(key_date(k) >= b for b in bounds)].append(k)
        groups = [g for g in groups if g]

    old = {tuple(p['keys']): p for p in st['packs']}
    packs, built = [], 0
    for g in groups:
        p = old.get(tuple(g))
        if (p and all(st['stamps'].get(k) == now[k] for k in g)
                and os.path.exists(os.path.join(OUT, pack_name(g)))):
            packs.append(p)
            continue
        built += 1
        fit(g, packs)
    packs.sort(key=lambda p: key_date(p['keys'][0]))

    # снятые файлы пакетов - в build/removed (не удаляются)
    live = {pack_name(p['keys']) for p in packs}
    for fn in os.listdir(OUT):
        if fn.endswith('.topo.json') and fn not in live:
            os.makedirs(os.path.join(ROOT, 'build', 'removed', 'mid_packs'), exist_ok=True)
            os.replace(os.path.join(OUT, fn), os.path.join(ROOT, 'build', 'removed', 'mid_packs', fn))

    mpath = os.path.join(DATA, 'mid_manifest.json')
    with open(mpath, encoding='utf-8') as f:
        man = json.load(f)
    man['packs'] = [{'file': 'data/mid_packs/' + pack_name(p['keys']), 'keys': p['keys']}
                    for p in packs]
    man['packs_note'] = ('пакеты среднего уровня по времени: общие дуги точных срезов, '
                         'упрощение %.3f° по дугам, квантование %s; '
                         'сборка tools/build_mid_packs.py' % (TOL, Q))
    with open(mpath, 'w', encoding='utf-8') as f:
        json.dump(man, f, ensure_ascii=False, separators=(',', ':'))
    with open(STATE, 'w', encoding='utf-8') as f:
        json.dump({'params': PARAMS, 'stamps': now, 'packs': packs}, f)
    import geoclean as gc
    gc.write_stamp('mid_packs')             # версия данных для service worker
    total = sum(p['gz'] for p in packs)
    print(f'пакетов {len(packs)} (пересобрано групп {built}), всего {total / 1048576:.2f} МБ '
          f'сжатых, крупнейший {max(p["gz"] for p in packs) // 1024} КБ')


if __name__ == '__main__':
    main()
