"""Сборка карты по таблицам ядра (неделя 2 новой архитектуры, 24.09.2026).

  python -u tools/rebuild.py --changed      правка таблиц: задетые даты целиком
  python -u tools/rebuild.py --all          полная сборка с нуля (около часа)
  python -u tools/rebuild.py --changed --dry-run   только показать, что задето

Таблицы - data/core/*.csv (tools/core_tables.py). Состояние последней сборки -
build/state/: копия таблиц, отпечатки входов слоёв войн и производных, список
ключей. --changed сравнивает таблицы строками и входы отпечатками:

  строка adds/subs/late_edits    -> даты внутри её окна [с, по)
  строка resist                  -> даты до её дня
  строка republics               -> даты с её дня (распад СССР, обрезка)
  строка late_new                -> её ключ и ключи, скопированные с него
  строка foreign                 -> даты с её since (пустое - все даты)
  строка regions                 -> окна всех строк, где регион стоит,
                                    и слои войн, в коде которых он назван
  новые и снятые ключи           -> сами ключи

Каждая задетая дата собирается ЗАНОВО от основы: ранняя - build(), поздняя -
основа источника (CShapes, замороженный 1922), копия или срез распада, для
срезов пакта и ВМВ - их сырой вывод из build/tmp, затем правки своей даты и
обрезка по чужим границам. Слой войны пересобирается, если сменился его вход
(код, таблица якорей, контур) или его основа (пакт - 1922, ВМВ - пакт, ПМВ -
1914-04-04, новые ключи окна ПМВ). Потом производные: облегчённые срезы только
задетых дат, топология, пакеты среднего уровня и ячейки крупного масштаба
(только задетые), потери
(без эпизодов 2022+, если правка их не задела), остроги (кэш попаданий по
срезам), восстания, сфера (если сменилась), пакет старта. Сводка - build/SUMMARY.md.

Код ядра (build_expansion.py, build_data.py, geoclean.py, clip_foreign.py,
rebuild.py) --changed не отслеживает: после правки кода - --all.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from multiprocessing import get_context

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
PY = sys.executable
DATA = os.path.join(ROOT, 'data')
YEARS = os.path.join(DATA, 'years')
BUILD = os.path.join(ROOT, 'build')
TMP = os.path.join(BUILD, 'tmp')
STATE = os.path.join(BUILD, 'state')
FROZEN_1922 = os.path.join(DATA, 'atlas', 'ussr_1922_frozen_2026-09-24.geojson')
SIMP = 0.001
CORE_CODE = ['build_expansion.py', 'build_data.py', 'geoclean.py', 'clip_foreign.py',
             'core_tables.py', 'rebuild.py']

# слои войн и производные: скрипт, свои модули, ключи-основы
LAYERS = {
    'zones': ('build_zones_1917_1921.py', ['build_ww1.py'], []),
    'pact': ('build_pact_1939.py', ['build_border_1939.py'], ['1922']),
    'ww2': ('build_ww2.py', [], []),                  # основа - вывод пакта
    'ww1': ('build_ww1.py', ['build_ww2.py'], ['1914-04-04']),
    'sphere': ('build_sphere.py', [], []),
}

_M = {}


def mods():
    if not _M:
        import build_data as bd
        import build_expansion as BE
        import clip_foreign as cf
        import geoclean as gc
        from shapely.geometry import shape
        from shapely.ops import unary_union
        base_path = BE.years_path
        # служебные основы ('__src_1946', '__war_1940-03-12') живут в build/tmp
        BE.years_path = lambda k: (os.path.join(TMP, f'{k}.geojson')
                                   if k.startswith('__') else base_path(k))
        _M.update(bd=bd, BE=BE, cf=cf, gc=gc, shape=shape, uu=unary_union)
    return _M


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save(path, fc):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(fc, f, ensure_ascii=False)


def union_fc(fc):
    m = mods()
    return m['uu']([m['shape'](f['geometry']).buffer(0)
                    for f in fc['features'] if f.get('geometry')]).buffer(0)


def simp_fc(fc):
    m = mods()
    for f in fc['features']:
        if f.get('geometry'):
            g = m['shape'](f['geometry']).buffer(0).simplify(SIMP).buffer(0)
            f['geometry'] = m['BE']._round_n(g.__geo_interface__, m['BE'].LATE_DIGITS)
    return fc


def war_raw(key):
    return os.path.join(TMP, f'__war_{key}.geojson')


# ---- ключи ------------------------------------------------------------------
def early_keys(BE):
    keys = sorted(set(BE.SRC_ORDER) | {x['frm'] for x in BE.ADDS}
                  | {x['to'] for x in BE.ADDS if x['to']}
                  | {s['frm'] for s in BE.SUBS if s['frm']}
                  | {s['to'] for s in BE.SUBS if s['to']},
                  key=lambda k: (BE.key_date(k), 0 if k in BE.SRC else 1, len(k), k))
    seen, out = set(), []
    for k in keys:
        if BE.key_date(k) < BE.RECON_FROM and BE.key_date(k) not in seen:
            seen.add(BE.key_date(k))
            out.append(k)
    return out


def ww1_window(BE, k):
    return BE.d('1914-07-19') <= BE.key_date(k) < BE.d('1917-12-25')


# ---- сборка одного ключа ----------------------------------------------------
def early_key(key):
    m = mods()
    t = time.perf_counter()
    fc, log, nparts = m['BE'].build(key)
    if fc is None:
        return key, None, time.perf_counter() - t
    save(os.path.join(YEARS, f'{key}.geojson'), m['gc'].sanitize_obj(fc))
    return key, nparts, time.perf_counter() - t


_CS = {}


def source_base(key):
    """Основа позднего ключа: корень цепочки копий из источника.

    1922 - замороженный боевой срез; ключ, который пишет слой войны (пакт,
    ВМВ), - его сырой вывод до правок позднего окна (Ханко 23.03.1940 -
    копия среза пакта 12.03.1940, пачка 11)."""
    m = mods()
    BE, bd, gc = m['BE'], m['bd'], m['gc']
    chain = {k: b for k, b, _ in BE.LATE_NEW if b != 'ww2'}
    while key in chain:
        key = chain[key]
    if os.path.exists(war_raw(key)):
        return load(war_raw(key))
    if key == '1922':
        return simp_fc(load(FROZEN_1922))
    if 'ru' not in _CS:
        d = load(bd.fetch_cshapes())
        _CS['ru'] = [f for f in d['features'] if f['properties'].get('gwcode') == 365]
    y, mm, dd = bd.CSHAPES_SLICES[key]
    hit = bd.cshapes_at(_CS['ru'], (y, mm, dd))[-1]
    fc = {'type': 'FeatureCollection', 'features': [{
        'type': 'Feature', 'geometry': hit['geometry'],
        'properties': {'name': hit['properties']['cntry_name'], 'year': key,
                       'role': 'core', 'source': 'CShapes 2.0'}}]}
    return simp_fc(gc.sanitize_obj(fc))


def late_kind(key):
    m = mods()
    BE = m['BE']
    if os.path.exists(war_raw(key)):
        return 'war'
    new = {k: b for k, b, _ in BE.LATE_NEW}
    if key in new:
        return 'ww2new' if new[key] == 'ww2' else 'copy'
    if key in {r[2] for r in BE.REPUBLICS} or key == BE.USSR_END:
        return 'ussr'
    if key == '1922' or key in m['bd'].CSHAPES_SLICES:
        return 'base'
    return 'unknown'


def late_key(args):
    key, kind = args
    m = mods()
    BE, gc = m['BE'], m['gc']
    t = time.perf_counter()
    path = BE.years_path(key)
    if kind == 'war':
        shutil.copyfile(war_raw(key), path)
    elif kind == 'copy':
        chain = {k: b for k, b, _ in BE.LATE_NEW}
        g = union_fc(source_base(chain[key]))
        save(path, gc.sanitize_obj({'type': 'FeatureCollection', 'features': [{
            'type': 'Feature',
            'geometry': BE._round_n(gc.finish(g, BE.CACHE).__geo_interface__,
                                    BE.LATE_DIGITS),
            'properties': {'name': 'Российская империя', 'year': key, 'role': 'core',
                           'reconstruction': True, 'approximate': True,
                           'expansion': True, 'base': f'основа {chain[key]}',
                           'source': 'КУРИРУЕМЫЙ СРЕЗ ПОЗДНЕГО ОКНА (сборка по '
                                     'таблицам, tools/rebuild.py)'}}]}))
    elif kind == 'ussr':
        src = BE.years_path('__src_1946')
        if not os.path.exists(src):
            save(src, source_base('1946'))
        gone = [r for r in BE.REPUBLICS if r[2] <= key]
        BE.write_ussr_slice(key, gone, '__src_1946', final=(key == BE.USSR_END))
    elif kind == 'base':
        save(path, source_base(key))
    elif kind == 'ww2new':
        why = {k: w for k, b, w in BE.LATE_NEW}[key]
        if not BE.ww2_slice(key, why):
            return key, 'не собран', time.perf_counter() - t
    else:
        return key, 'неизвестно, откуда собирать', time.perf_counter() - t
    adds, subs = BE.late_edits_for(BE.key_date(key))
    if adds or subs:
        BE.patch_slice(key, adds, subs)
    return key, kind, time.perf_counter() - t


_F = {}


_PROT = {}


def protected():
    # защищённые регионы (EARLY_PROTECT, LATE_PROTECT: Соловки, полоса Яика, города
    # ГДР 1953) чистка ниже выбрасывала как тонкие куски и крапинки: полоса Яика
    # 1772-1824 и Галле на 30.06.1953 пропадали (приёмка пачек 24.09.2026) -
    # возвращаем то, что от них было в срезе до обрезки
    if 'g' not in _PROT:
        _PROT['g'] = mods()['uu']([mods()['BE'].reg_geom(r) for r in
                                  sorted(mods()['BE'].EARLY_PROTECT | mods()['BE'].LATE_PROTECT)]).buffer(0)
    return _PROT['g']


def clip_key(key):
    """Шаг clip_foreign.main для одного среза - его же функциями."""
    m = mods()
    cf, gc, BE, shape, uu = m['cf'], m['gc'], m['BE'], m['shape'], m['uu']
    t = time.perf_counter()
    if 'f' not in _F:
        _F['f'] = cf.foreign_geom()
        cf.relevant(_F['f'])
    foreign = _F['f']
    path = os.path.join(YEARS, f'{key}.geojson')
    fc = load(path)
    if any((f.get('properties') or {}).get('ww2') or (f.get('properties') or {}).get('ww1')
           for f in fc['features']):
        return key, 0.0, time.perf_counter() - t
    g = union_fc(fc)
    zone = foreign
    ex = cf.foreign_since_geom(cf.key_date(key))
    if ex is not None:
        zone = uu([foreign, ex])
    bleed = g.intersection(zone)
    if bleed.is_empty or bleed.area < 1e-6:
        return key, 0.0, time.perf_counter() - t
    allowed = cf.allowed_at(cf.key_date(key), foreign)
    cut = bleed.difference(allowed) if allowed is not None else bleed
    if cut.is_empty or cut.area < 1e-6:
        return key, 0.0, time.perf_counter() - t
    feats = []
    for x in fc['features']:
        if not x.get('geometry'):
            feats.append(x)
            continue
        g0 = shape(x['geometry'])
        if not g0.is_valid:
            g0 = g0.buffer(0)
        gg = g0.difference(cut)
        if gg.is_empty:
            continue
        gg, _ = gc.drop_thin_parts(gg)
        gg, _, _ = gc.despeckle(gg, BE.CACHE)
        # buffer(0) оставляет только площади: на касаниях пересечение даёт линии,
        # и difference падал в GEOS (первый прогон --all 24.09.2026)
        keep = g0.intersection(protected()).buffer(0).difference(cut.buffer(0))
        if not keep.is_empty:
            gg = uu([gg, keep]).buffer(0)
        if gg.is_empty:
            continue
        y = dict(x)
        y['geometry'] = gg.__geo_interface__
        feats.append(y)
    fc['features'] = feats
    save(path, fc)
    return key, cut.area, time.perf_counter() - t


def area_of(key):
    path = os.path.join(YEARS, f'{key}.geojson')
    if not os.path.exists(path):
        return key, None
    return key, union_fc(load(path)).area


# ---- состояние и дифф -------------------------------------------------------
def sha(path):
    if not os.path.exists(path):
        return None
    with open(path, 'rb') as f:
        return hashlib.sha1(f.read()).hexdigest()


# потери: эпизоды 2022+ режутся по срезам после распада СССР и разбирают
# 1500 снимков DeepState (~1 мин на правку, 24.09.2026). Правка, не задевшая
# эти срезы и входы потерь, обходится --pre20 (курируемые эпизоды до XX века)
LOSSES_FROM = '1991-12-26'


def losses_sig():
    h = hashlib.sha1()
    for f in ('tools/build_losses.py', 'tools/geoclean.py', 'data/losses/routes.csv',
              'cache/cshapes20.geojson', 'cache/ne_admin1.geojson'):
        h.update(str(sha(os.path.join(ROOT, f))).encode())
    days = os.path.join(DATA, 'deepstate', 'days')
    for fn in sorted(os.listdir(days)) if os.path.isdir(days) else ():
        h.update(f'{fn}:{os.path.getsize(os.path.join(days, fn))};'.encode())
    return h.hexdigest()


_DATA_INDEX = {}


def data_index():
    """Имя файла -> пути под data/ (без срезов и снимков фронта)."""
    if not _DATA_INDEX:
        skip = {'years', 'years_mid', 'years_lite', 'days', 'months_lite', 'core',
                'years_prev_run1', 'cells'}
        for dp, dns, fns in os.walk(DATA):
            dns[:] = [d for d in dns if d not in skip]
            for fn in fns:
                if fn.endswith(('.csv', '.geojson', '.json')) and fn != 'manifest.json':
                    _DATA_INDEX.setdefault(fn, []).append(os.path.join(dp, fn))
    return _DATA_INDEX


def layer_inputs(name):
    script, extra, _ = LAYERS[name]
    files = [os.path.join(TOOLS, script)] + [os.path.join(TOOLS, x) for x in extra]
    text = open(files[0], encoding='utf-8').read()
    for fn in sorted(set(re.findall(r"'([A-Za-z0-9_.-]+\.(?:csv|geojson))'", text))):
        files += data_index().get(fn, [])
    return {os.path.relpath(p, ROOT): sha(p) for p in files}


def layer_regs(name, reg_ids):
    text = open(os.path.join(TOOLS, LAYERS[name][0]), encoding='utf-8').read()
    return {r for r in reg_ids if f"'{r}'" in text}


def read_core(core):
    import core_tables as ct
    out = {}
    for name, (fn, cols, _) in ct.TABLES.items():
        path = os.path.join(core, fn)
        rows = []
        if os.path.exists(path):
            with open(path, encoding='utf-8', newline='') as f:
                for r in csv.DictReader(f):
                    rows.append(tuple((c, r[c]) for c in cols if c != 'comment'))
        out[name] = rows
    return out


def row_windows(name, row, lo, hi):
    """Окна дат [с, по), которые задевает строка таблицы."""
    r = dict(row)
    nz = lambda v: v or None                           # noqa: E731
    early_hi = '1917-12-25'          # RECON_FROM: дальше build() не строит
    if name in ('ADDS', 'SUBS'):
        a, b = nz(r['frm']) or lo, nz(r['to']) or hi
        return [(a, min(b, early_hi))] if a < early_hi else []
    if name == 'LATE_EDITS':
        return [(nz(r['frm']) or lo, nz(r['to']) or hi)]
    if name == 'RESIST':
        return [(lo, min(r['until'], early_hi))]
    if name == 'REPUBLICS':
        return [(r['date'], hi)]
    if name == 'FOREIGN':
        return [(nz(r['since']) or lo, hi)]
    if name == 'LATE_NEW':
        return [('=' + r['key'], None)]
    return []


def changed(state_core):
    """Изменённые строки: {таблица: [строки, которых нет по другую сторону]}."""
    old, new = read_core(state_core), read_core(os.path.join(DATA, 'core'))
    diff = {}
    for name in new:
        a, b = old.get(name, []), new[name]
        sa, sb = set(a), set(b)
        rows = [r for r in a if r not in sb] + [r for r in b if r not in sa]
        if rows:
            diff[name] = rows
    return diff, old, new


def plan(state, BE):
    """Что пересобрать: ключи, слои, снятые ключи, причины."""
    lo, hi = '0001-01-01', '9999-12-31'
    diff, old, new = changed(os.path.join(state, 'core'))
    wins, why = [], {}
    for name, rows in diff.items():
        if name == 'REG':
            continue
        for r in rows:
            for w in row_windows(name, r, lo, hi):
                wins.append(w)
                why.setdefault(name, 0)
                why[name] += 1
    reg_changed = {dict(r)['id'] for r in diff.get('REG', [])}
    if reg_changed:
        for name in ('ADDS', 'SUBS', 'RESIST', 'LATE_EDITS'):
            for r in old[name] + new[name]:
                rd = dict(r)
                rid = rd.get('reg') or (eval(rd['provider'])[1] if name == 'LATE_EDITS'
                                        and eval(rd['provider'])[0] == 'reg' else None)
                if rid in reg_changed:
                    wins += row_windows(name, r, lo, hi)
    # ключи сейчас и в прошлой сборке
    try:
        old_keys = set(load(os.path.join(state, 'keys.json'))['keys'])
    except FileNotFoundError:
        old_keys = set()
    mf_keys = set(map(str, load(os.path.join(DATA, 'manifest.json'))['years']))
    e_new = set(early_keys(BE))
    late_new = ({k for k, b, _ in BE.LATE_NEW} | {r[2] for r in BE.REPUBLICS}
                | {BE.USSR_END})
    ussr_old_new = {dict(r)['key'] for r in old.get('LATE_NEW', [])} | \
        {dict(r)['date'] for r in old.get('REPUBLICS', [])}
    # снятые: ключи ранних дат и позднего окна, которых таблицы больше не дают
    derived_old = {k for k in old_keys if BE.key_date(k) < BE.RECON_FROM
                   and not ww1_window(BE, k)} | (ussr_old_new & old_keys)
    removed = sorted((derived_old - e_new - late_new) & mf_keys, key=BE.key_date)
    all_keys = (mf_keys - set(removed)) | e_new | late_new
    added = sorted(all_keys - mf_keys, key=BE.key_date)

    def hit(k):
        dk = str(BE.key_date(k))
        for a, b in wins:
            if a.startswith('='):
                if k == a[1:]:
                    return True
                continue
            if str(BE.key_date(a)) <= dk < str(BE.key_date(b)):
                return True
        return False

    touched = {k for k in all_keys if hit(k)} | set(added)
    # копии с задетого ключа
    chain = {k: b for k, b, _ in BE.LATE_NEW}
    grew = True
    while grew:
        grew = False
        for k, b in chain.items():
            if b in touched and k not in touched:
                touched.add(k)
                grew = True
    # слои войн
    try:
        inputs_old = load(os.path.join(state, 'inputs.json'))
    except FileNotFoundError:
        inputs_old = {}
    layers = {}
    for name in LAYERS:
        cur = layer_inputs(name)
        reason = []
        if inputs_old.get(name) != cur:
            ch = [p for p in cur if (inputs_old.get(name) or {}).get(p) != cur[p]]
            reason.append('сменился вход: ' + ', '.join(os.path.basename(p) for p in ch[:4]))
        regs = layer_regs(name, reg_changed)
        if regs:
            reason.append('сменился регион ' + ', '.join(sorted(regs)))
        for dk in LAYERS[name][2]:
            if dk in touched:
                reason.append(f'сменилась основа {dk}')
        if name == 'ww1' and any(ww1_window(BE, k) for k in added + removed):
            reason.append('новые или снятые ключи окна')
        if reason:
            layers[name] = reason
    if 'pact' in layers and 'ww2' not in layers:
        layers['ww2'] = ['пересобран пакт']
    return dict(diff=diff, why=why, touched=touched, added=added, removed=removed,
                layers=layers, all_keys=all_keys, reg_changed=reg_changed,
                core_code={f: sha(os.path.join(TOOLS, f)) for f in CORE_CODE},
                core_code_old=(load(os.path.join(state, 'code.json'))
                               if os.path.exists(os.path.join(state, 'code.json')) else {}))


def save_state(BE, inputs):
    os.makedirs(os.path.join(STATE, 'core'), exist_ok=True)
    for fn in os.listdir(os.path.join(DATA, 'core')):
        if fn.endswith('.csv'):
            shutil.copyfile(os.path.join(DATA, 'core', fn), os.path.join(STATE, 'core', fn))
    save(os.path.join(STATE, 'inputs.json'), inputs)
    save(os.path.join(STATE, 'keys.json'),
         {'keys': sorted(map(str, load(os.path.join(DATA, 'manifest.json'))['years']),
                         key=BE.key_date)})
    save(os.path.join(STATE, 'code.json'),
         {f: sha(os.path.join(TOOLS, f)) for f in CORE_CODE})


# ---- оркестровка ------------------------------------------------------------
def run(label, script, *args):
    t = time.perf_counter()
    print(f'### {label} начат {time.strftime("%H:%M:%S")}', flush=True)
    r = subprocess.run([PY, '-u', os.path.join(TOOLS, script), *args], cwd=ROOT)
    dt = time.perf_counter() - t
    if r.returncode != 0:
        print(f'### УПАЛО: {label} (код {r.returncode})', flush=True)
        sys.exit(1)
    return dt


def mtimes():
    return {f[:-8]: os.path.getmtime(os.path.join(YEARS, f))
            for f in os.listdir(YEARS) if f.endswith('.geojson')}


def set_manifest(BE, add, drop):
    path = os.path.join(DATA, 'manifest.json')
    mf = load(path)
    mf['years'] = sorted((set(map(str, mf['years'])) | set(add)) - set(drop), key=BE.key_date)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(mods()['gc'].sanitize_obj(mf), f, ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--all', action='store_true')
    g.add_argument('--changed', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    os.makedirs(TMP, exist_ok=True)
    T0 = time.perf_counter()
    times = []
    ctx = get_context('spawn')

    r = subprocess.run([PY, os.path.join(TOOLS, 'core_tables.py')], cwd=ROOT,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit('таблицы ядра с ошибками - сборка не начата')

    if a.all:
        if not a.dry_run:
            # с нуля: прошлые срезы и служебные основы - в сторону (не удаляются)
            stamp = time.strftime('%Y%m%d_%H%M%S')
            for src, dst in ((YEARS, os.path.join(BUILD, f'years_prev_{stamp}')),
                             (TMP, os.path.join(BUILD, f'tmp_prev_{stamp}'))):
                if os.path.exists(src) and os.listdir(src):
                    os.replace(src, dst)
                os.makedirs(src, exist_ok=True)
            times.append(('основы (build_data)', run('основы', 'build_data.py')))
        state = os.path.join(BUILD, 'state_empty')          # пустое: задето всё
    else:
        state = STATE
        if not os.path.exists(os.path.join(STATE, 'keys.json')):
            sys.exit('нет build/state - сначала rebuild.py --all')
    m = mods()
    BE = m['BE']
    p = plan(state, BE)
    if a.all:
        p['touched'] = set(p['all_keys'])
    if 'pact' in p['layers']:
        # пакт читает срез 1922 до обрезки - собрать его заново перед пактом
        p['touched'].add('1922')
    if not a.all and p['core_code_old'] and p['core_code_old'] != p['core_code']:
        ch = [f for f in CORE_CODE if p['core_code_old'].get(f) != p['core_code'][f]]
        print('!!! сменился код ядра (' + ', '.join(ch) + '): --changed его не '
              'отслеживает, итог сверять с --all', flush=True)
    touched = p['touched']
    e_all = early_keys(BE)
    early = [k for k in e_all if k in touched and not ww1_window(BE, k)]
    late = sorted([k for k in touched if BE.key_date(k) >= BE.LATE_FROM],
                  key=BE.key_date)
    print(f'### строк изменено: ' + (', '.join(f'{k} {v}' for k, v in p['why'].items())
                                     or 'нет') +
          (f'; регионов {len(p["reg_changed"])}' if p['reg_changed'] else ''))
    print(f'### задето ключей {len(touched)}: ранних {len(early)}, поздних {len(late)}, '
          f'новых {len(p["added"])}, снятых {len(p["removed"])}')
    for name, reason in p['layers'].items():
        print(f'### слой {name}: ' + '; '.join(reason))
    if a.dry_run:
        print('задеты:', ', '.join(sorted(touched, key=BE.key_date)[:60]),
              '…' if len(touched) > 60 else '')
        return
    if not touched and not p['layers']:
        print('### нечего пересобирать')
        return
    area_before = {}
    if not a.all:
        with ctx.Pool(a.workers) as pool:
            area_before = dict(pool.map(area_of, sorted(touched), chunksize=1))

    per_key = {}
    t = time.perf_counter()
    if early:
        with ctx.Pool(a.workers) as pool:
            res = pool.map(early_key, early, chunksize=1)
        for k, n, dt in res:
            per_key[k] = dt
        times.append((f'ранние даты ({len(early)})', time.perf_counter() - t))

    # 1922 и слои войн
    t = time.perf_counter()
    before = mtimes()
    if '1922' in touched:
        late_key(('1922', 'base'))
    rewritten = set()
    ww2new = [k for k, b, _ in BE.LATE_NEW if b == 'ww2']
    ww2_base = __import__('build_ww2').BASE_PRE
    need_ww2 = 'ww2' in p['layers'] or any(k in touched for k in ww2new)
    for name, label in (('zones', 'зоны 1917-1921'), ('pact', 'пакт 1939'), ('ww2', 'ВМВ')):
        if name == 'ww2' and need_ww2 and 'pact' not in p['layers'] \
                and os.path.exists(war_raw(ww2_base)):
            # ВМВ читает срез пакта ДО правок позднего окна и обрезки (иначе
            # Тува 1944 года - прогон 1 недели 1): вернуть сырой, потом заново
            shutil.copyfile(war_raw(ww2_base), os.path.join(YEARS, f'{ww2_base}.geojson'))
            rewritten.add(ww2_base)
        if name in p['layers']:
            b0 = mtimes()
            times.append((label, run(label, LAYERS[name][0])))
            w = {k for k, mt in mtimes().items() if b0.get(k) != mt}
            rewritten |= w
            if name in ('pact', 'ww2'):
                for k in w:                       # сырой вывод - основа правок
                    shutil.copyfile(os.path.join(YEARS, f'{k}.geojson'), war_raw(k))
            if name == 'zones':
                BE.update_manifest(sorted(w))
    ww2done = set()
    if need_ww2:
        why = {k: w for k, b, w in BE.LATE_NEW}
        for k in ww2new:
            BE.ww2_slice(k, why[k])
        ww2done = set(ww2new)
    late_todo = sorted((set(late) | ww2done | {k for k in rewritten
                                               if BE.key_date(k) >= BE.LATE_FROM})
                       - {'1922'}, key=BE.key_date)
    if late_todo:
        save(BE.years_path('__src_1946'), source_base('1946'))
        # ww2new уже собраны моделью ВМВ: им только правки своей даты
        jobs = [(k, 'patch_only' if k in ww2done else late_kind(k)) for k in late_todo]
        with ctx.Pool(a.workers) as pool:
            res = pool.map(late_job, jobs, chunksize=1)
        bad = [(k, kind) for k, kind, _ in res if kind in ('не собран',
                                                           'неизвестно, откуда собирать')]
        if bad:
            sys.exit('### не собраны: ' + ', '.join(f'{k} ({kind})' for k, kind in bad))
        for k, kind, dt in res:
            per_key[k] = per_key.get(k, 0) + dt
        BE.update_manifest([k for k, kind, _ in res])
        BE.dump_subs()
    times.append((f'поздние даты и слои войн ({len(late_todo)})', time.perf_counter() - t))

    # снятые ключи - вон из манифеста, файлы в build/removed (не удаляются)
    if p['removed']:
        os.makedirs(os.path.join(BUILD, 'removed'), exist_ok=True)
        for k in p['removed']:
            # облегчённые копии уходят вместе со срезом, иначе лежат сиротами
            for sub, dst in (('years', ''), ('years_lite', 'lite'), ('years_mid', 'mid')):
                src = os.path.join(DATA, sub, f'{k}.geojson')
                if os.path.exists(src):
                    os.makedirs(os.path.join(BUILD, 'removed', dst), exist_ok=True)
                    os.replace(src, os.path.join(BUILD, 'removed', dst, f'{k}.geojson'))
    # ранние даты окна ПМВ (строки таблиц 1914-1917) не строятся ранним окном -
    # их строит слой ПМВ по манифесту; без записи сюда полная сборка их теряла
    # (03.09.1914 и 22.06.1915, --all 24.09.2026)
    set_manifest(BE, [k for k in early if os.path.exists(os.path.join(YEARS, f'{k}.geojson'))]
                 + [k for k in e_all if ww1_window(BE, k)], p['removed'])

    t = time.perf_counter()
    clip = sorted((set(early) | set(late_todo) | rewritten
                   | ({'1922'} if '1922' in touched else set()))
                  & set(mtimes()), key=BE.key_date)
    with ctx.Pool(a.workers) as pool:
        res = pool.map(clip_key, clip, chunksize=1)
    for k, c, dt in res:
        per_key[k] = per_key.get(k, 0) + dt
    times.append((f'обрезка ({len(clip)})', time.perf_counter() - t))

    if 'ww1' in p['layers']:
        times.append(('ПМВ', run('ПМВ', 'build_ww1.py', '--workers', str(a.workers))))
    if 'sphere' in p['layers']:
        times.append(('сфера', run('сфера', 'build_sphere.py')))
    lite_keys = sorted(set(clip) | set(p['added']) | (
        {k for k in mtimes() if ww1_window(BE, k)} if 'ww1' in p['layers'] else set()),
        key=BE.key_date)
    lsig_path = os.path.join(STATE, 'losses.json')
    lsig = losses_sig()
    late_hit = [k for k in lite_keys + p['removed']
                if BE.key_date(k) >= BE.key_date(LOSSES_FROM)]
    full_losses = (a.all or late_hit or not os.path.exists(lsig_path)
                   or load(lsig_path).get('sig') != lsig)
    print('### потери: ' + ('полностью' if full_losses else
                            '--pre20 (срезы после 1991 и входы потерь не задеты)'), flush=True)
    for label, script, *args in [('потери', 'build_losses.py',
                                  *([] if full_losses else ['--pre20'])),
                                 ('остроги', 'build_ostrogs.py'),
                                 ('lite', 'build_lite.py', '--keys', ','.join(lite_keys)),
                                 ('mid', 'build_lite.py', '--level', 'mid',
                                  '--keys', ','.join(lite_keys)),
                                 ('пакеты mid', 'build_mid_packs.py'),
                                 ('ячейки', 'build_fine_cells.py'),
                                 ('пакет старта', 'build_start_bundle.py'),
                                 ('восстания', 'build_uprisings.py')]:
        if a.all:
            args = [x for x in args if x != '--keys' and x != ','.join(lite_keys)]
        times.append((label, run(label, script, *args)))
    save(lsig_path, {'sig': lsig})

    with ctx.Pool(a.workers) as pool:
        area_after = dict(pool.map(area_of, sorted(touched | rewritten), chunksize=1))
    save_state(BE, {name: layer_inputs(name) for name in LAYERS})
    total = time.perf_counter() - T0
    write_summary(a, p, times, total, per_key, area_before, area_after, rewritten, BE)
    print(f'### СБОРКА ГОТОВА {time.strftime("%H:%M:%S")}, {total / 60:.1f} мин', flush=True)


def late_job(args):
    key, kind = args
    if kind == 'patch_only':
        m = mods()
        BE = m['BE']
        t = time.perf_counter()
        adds, subs = BE.late_edits_for(BE.key_date(key))
        if adds or subs:
            BE.patch_slice(key, adds, subs)
        return key, 'ww2new', time.perf_counter() - t
    return late_key(args)


def write_summary(a, p, times, total, per_key, before, after, rewritten, BE):
    os.makedirs(BUILD, exist_ok=True)
    mode = '--all' if a.all else '--changed'
    lines = [f'# Сборка {mode} ({time.strftime("%d.%m.%Y %H:%M")}, {a.workers} процесса)',
             '', f'Всего: {total / 60:.1f} мин. Срезов в манифесте: '
             f'{len(load(os.path.join(DATA, "manifest.json"))["years"])}.', '']
    if p['why']:
        lines.append('Изменено строк: ' + ', '.join(f'{k} {v}' for k, v in p['why'].items())
                     + (f'; регионов {len(p["reg_changed"])}' if p['reg_changed'] else '')
                     + '.')
    lines.append(f'Задето ключей: {len(p["touched"])}; новых {len(p["added"])}'
                 + (f' ({", ".join(p["added"][:12])}{"…" if len(p["added"]) > 12 else ""})'
                    if p['added'] else '')
                 + f'; снятых {len(p["removed"])}'
                 + (f' ({", ".join(p["removed"])})' if p['removed'] else '') + '.')
    for name, reason in p['layers'].items():
        lines.append(f'Слой {name} пересобран: ' + '; '.join(reason) + '.')
    lines += ['', '| стадия | мин |', '|---|---|']
    lines += [f'| {label} | {dt / 60:.1f} |' for label, dt in times]
    ch = []
    for k in sorted(set(before) | set(after), key=BE.key_date):
        b, c = before.get(k), after.get(k)
        if b is None or c is None or abs(c - b) > 1e-3:
            ch.append((k, b, c))
    lines += ['', f'Площадь изменилась у {len(ch)} ключей (град²):', '',
              '| ключ | было | стало | разница |', '|---|---|---|---|']
    for k, b, c in ch[:80]:
        lines.append(f'| {k} | {"-" if b is None else f"{b:.3f}"} | '
                     f'{"-" if c is None else f"{c:.3f}"} | '
                     f'{"" if b is None or c is None else f"{c - b:+.3f}"} |')
    slow = sorted(per_key.items(), key=lambda kv: -kv[1])[:10]
    lines += ['', 'Самые долгие ключи, с: ' + ', '.join(f'{k} {v:.0f}' for k, v in slow)]
    with open(os.path.join(BUILD, 'SUMMARY.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
