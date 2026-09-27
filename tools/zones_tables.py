#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Таблицы реконструкции 1917-1921 в CSV (27.09.2026, по слову куратора
«переноси всё в CSV для лёгкого редактирования людьми»).

Раньше жили литералами Python в tools/build_zones_1917_1921.py: REG (71
регион), WINDOWS + WHO (79 окон и держатели), ADDS (Хива и Бухара), SLICES и
WEST_KEYS (72 среза). Теперь - data/zones_1917_1921/*.csv, по строке на
регион, окно, срез; сборщик читает их отсюда (load). Правила те же, что у
tools/core_tables.py: CRLF, UTF-8, даты ISO, пустая ячейка в колонках-датах =
None, колонка comment - комментарии из кода (сборка её не читает).

  zones_regions.csv  id, spec, comment
      spec - литерал Python: ('Ukraine', ['Kiev', ...]) - страна и области
      Natural Earth admin-1 (None = вся страна; третьим элементом - список
      iso_3166_2); [(...), (...)] - группа из нескольких; 'file:ukraine/x.geojson'
      - курируемый файл в data/.
  zones_windows.csv  group, frm, to, kind, cut, who, why, comment
      окно [frm; to) держателя who у региона group; kind=out - территория вне
      империи (вычитается, чёрное), kind=in - держала другая фракция империи
      (красное, только для попапа); cut=yes/no - резать ли геометрию (у out
      по умолчанию yes, у украинского театра - no: его режут срезы).
      frm пустой - с начала окна реконструкции, to пустой - до 18.03.1921.
  zones_adds.csv     name, frm, why - добавления к основе (Хива, Бухара).
  zones_slices.csv   key, west, minus, note, anchor, comment
      срез key; minus - группы регионов, вычитаемые на этом срезе (через ;);
      west=yes - срез западного театра (дата якорей; minus у него берётся у
      ближайшего предыдущего среза не-west, как было в WEST_KEYS).

Запуск:
  python tools/zones_tables.py --validate
  python tools/zones_tables.py --export PY OUT   литералы файла PY -> CSV в OUT
"""
import ast
import csv
import io
import os
import sys
import tokenize
from datetime import date

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
DIR = os.path.join(ROOT, 'data', 'zones_1917_1921')

TABLES = {
    'REG': ('zones_regions.csv', ['id', 'spec', 'comment'], ()),
    'WINDOWS': ('zones_windows.csv', ['group', 'frm', 'to', 'kind', 'cut', 'who', 'why',
                                      'comment'], ('frm', 'to')),
    'ADDS': ('zones_adds.csv', ['name', 'frm', 'why', 'comment'], ()),
    'SLICES': ('zones_slices.csv', ['key', 'west', 'minus', 'note', 'anchor', 'comment'], ()),
}


def read_rows(name, d=None):
    fn, cols, nullable = TABLES[name]
    path = os.path.join(d or DIR, fn)
    with open(path, encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    for i, r in enumerate(rows, 2):
        if list(r) != cols:
            sys.exit(f'{fn}: колонки {list(r)}, ожидались {cols}')
        for c in cols:
            if r[c] is None:
                sys.exit(f'{fn}, строка {i}: не хватает ячеек')
            if c in nullable and r[c] == '':
                r[c] = None
    return rows


def _spec(s):
    s = s.strip()
    if s.startswith('file:'):
        return s
    return ast.literal_eval(s)


def load(name, d=None):
    """Таблица в том виде, в каком её держал литерал в коде."""
    rows = read_rows(name, d)
    if name == 'REG':
        return {r['id']: _spec(r['spec']) for r in rows}
    if name == 'WINDOWS':
        return [dict(group=r['group'], frm=r['frm'], to=r['to'], why=r['why'],
                     kind=r['kind'], cut=(r['cut'] == 'yes'), who=r['who']) for r in rows]
    if name == 'ADDS':
        return [dict(name=r['name'], frm=r['frm'], why=r['why']) for r in rows]
    if name == 'SLICES':
        base = []
        out = []
        for r in rows:
            if r['west'] == 'yes':
                prev = [s for s in base if s['key'] < r['key']]
                if not prev:
                    sys.exit(f'zones_slices.csv: {r["key"]} (west) раньше первого среза окна')
                out.append(dict(key=r['key'], minus=list(prev[-1]['minus']),
                                note=r['note'], anchor=r['anchor'], west=True))
            else:
                sl = dict(key=r['key'], minus=[x for x in r['minus'].split(';') if x],
                          note=r['note'], anchor=r['anchor'])
                base.append(sl)
                out.append(sl)
        return out
    raise KeyError(name)


# ---- проверка ---------------------------------------------------------------
def _d(s):
    p = [int(x) for x in str(s).split('-')]
    return date(p[0], p[1], p[2])


def validate(d=None):
    err = []
    reg = load('REG', d)
    for rid, spec in reg.items():
        if isinstance(spec, str):
            if not os.path.exists(os.path.join(ROOT, 'data', spec[5:])):
                err.append(f'zones_regions.csv {rid}: нет файла data/{spec[5:]}')
        elif isinstance(spec, tuple):
            if not (2 <= len(spec) <= 3 and isinstance(spec[0], str)):
                err.append(f'zones_regions.csv {rid}: кортеж не (страна, области[, iso])')
        elif isinstance(spec, list):
            if not all(isinstance(p, tuple) and 2 <= len(p) <= 3 for p in spec):
                err.append(f'zones_regions.csv {rid}: список не из кортежей (страна, области)')
        else:
            err.append(f'zones_regions.csv {rid}: spec непонятен')
    seen = set()
    for r in read_rows('WINDOWS', d):
        if r['group'] not in reg:
            err.append(f'zones_windows.csv: регион {r["group"]} не заведён')
        if r['kind'] not in ('out', 'in'):
            err.append(f'zones_windows.csv {r["group"]} {r["frm"]}: kind «{r["kind"]}» (out|in)')
        if r['cut'] not in ('yes', 'no'):
            err.append(f'zones_windows.csv {r["group"]} {r["frm"]}: cut «{r["cut"]}» (yes|no)')
        for c in ('frm', 'to'):
            if r[c] is not None:
                try:
                    _d(r[c])
                except ValueError:
                    err.append(f'zones_windows.csv {r["group"]}: дата «{r[c]}» не разбирается')
        if r['frm'] and r['to'] and r['frm'] >= r['to']:
            err.append(f'zones_windows.csv {r["group"]}: окно {r["frm"]} - {r["to"]} пустое')
        if not r['who'].strip():
            err.append(f'zones_windows.csv {r["group"]} {r["frm"]}: без держателя (who)')
        if not r['why'].strip():
            err.append(f'zones_windows.csv {r["group"]} {r["frm"]}: без обоснования (why)')
        k = (r['group'], r['frm'])
        if k in seen:
            err.append(f'zones_windows.csv: окно {k} дважды')
        seen.add(k)
    keys = set()
    for r in read_rows('SLICES', d):
        try:
            _d(r['key'])
        except ValueError:
            err.append(f'zones_slices.csv: ключ «{r["key"]}» не дата')
        if r['key'] in keys:
            err.append(f'zones_slices.csv: срез {r["key"]} дважды')
        keys.add(r['key'])
        if r['west'] not in ('yes', ''):
            err.append(f'zones_slices.csv {r["key"]}: west «{r["west"]}» (yes или пусто)')
        for g in r['minus'].split(';'):
            if g and g not in reg:
                err.append(f'zones_slices.csv {r["key"]}: группа {g} не заведена')
        if not r['anchor'].strip():
            err.append(f'zones_slices.csv {r["key"]}: без якоря (anchor)')
    for r in read_rows('ADDS', d):
        _d(r['frm'])
    return err


# ---- перенос литералов в CSV ------------------------------------------------
def _comments(src):
    out = {}
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            out[tok.start[0]] = tok.string[1:].strip()
    return out


def _spans(tree, names):
    spans = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) \
                and n.targets[0].id in names:
            v = n.value
            elts = v.keys if isinstance(v, ast.Dict) else v.elts
            ends = [v.values[i].end_lineno if isinstance(v, ast.Dict) else e.end_lineno
                    for i, e in enumerate(elts)]
            spans[n.targets[0].id] = (n, ends)
    return spans


def _notes(spans, com, nm):
    n, ends = spans[nm]
    res, prev = [], n.lineno
    for i, end in enumerate(ends):
        hi = n.end_lineno if i == len(ends) - 1 else end
        res.append('\n'.join(com[ln] for ln in range(prev + 1, hi + 1) if ln in com))
        prev = end
    return res


def _write(name, rows, out):
    fn, cols, nullable = TABLES[name]
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, fn), 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, lineterminator='\r\n')
        w.writerow(cols)
        for r in rows:
            w.writerow(['' if r[c] is None else r[c] for c in cols])


def export(py, out):
    """Литералы таблиц файла py -> CSV в out, с комментариями строк."""
    import importlib.util
    src = open(py, encoding='utf-8').read()
    com = _comments(src)
    spans = _spans(ast.parse(src), {'REG', 'WINDOWS', 'WHO', 'ADDS', 'SLICES', 'WEST_KEYS'})
    sys.path.insert(0, os.path.dirname(os.path.abspath(py)))
    spec = importlib.util.spec_from_file_location('_zones_lit', py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows = {}
    c = _notes(spans, com, 'REG')
    rows['REG'] = [dict(id=k, spec=(v if isinstance(v, str) else repr(v)), comment=c[i])
                   for i, (k, v) in enumerate(mod.REG.items())]
    cw = _notes(spans, com, 'WINDOWS')
    who_c = dict(zip(mod.WHO.keys(), _notes(spans, com, 'WHO')))
    rows['WINDOWS'] = []
    for i, w in enumerate(mod.WINDOWS):
        extra = who_c.get((w['group'], w['frm']), '')
        rows['WINDOWS'].append(dict(group=w['group'], frm=w['frm'], to=w['to'], kind=w['kind'],
                                    cut='yes' if w['cut'] else 'no', who=w['who'], why=w['why'],
                                    comment='\n'.join(x for x in (cw[i], extra) if x)))
    c = _notes(spans, com, 'ADDS')
    rows['ADDS'] = [dict(a, comment=c[i]) for i, a in enumerate(mod.ADDS)]
    cs = _notes(spans, com, 'SLICES')
    cwk = _notes(spans, com, 'WEST_KEYS')
    n_base = len(spans['SLICES'][1])
    base = mod.SLICES[:n_base]                 # хвост SLICES - из WEST_KEYS
    sl = [dict(key=s['key'], west='', minus=';'.join(s.get('minus', [])), note=s['note'],
               anchor=s['anchor'], comment=cs[i]) for i, s in enumerate(base)]
    sl += [dict(key=k, west='yes', minus='', note=note, anchor=anchor, comment=cwk[i])
           for i, (k, note, anchor) in enumerate(mod.WEST_KEYS)]
    rows['SLICES'] = sorted(sl, key=lambda r: r['key'])
    for nm, rs in rows.items():
        _write(nm, rs, out)
    bad = []
    if load('REG', out) != mod.REG:
        bad.append('REG')
    if load('WINDOWS', out) != mod.WINDOWS:
        bad.append('WINDOWS')
    if load('ADDS', out) != mod.ADDS:
        bad.append('ADDS')
    want = sorted(mod.SLICES, key=lambda s: s['key'])
    if load('SLICES', out) != want:
        bad.append('SLICES')
    return {nm: len(rs) for nm, rs in rows.items()}, bad


def main():
    if '--export' in sys.argv:
        i = sys.argv.index('--export')
        n, bad = export(sys.argv[i + 1], sys.argv[i + 2])
        print('перенесено:', ', '.join(f'{k} {v}' for k, v in n.items()))
        print('сверка с литералами:', 'РАСХОДИТСЯ ' + ', '.join(bad) if bad else 'совпадает')
        sys.exit(1 if bad else 0)
    err = validate()
    for e in err:
        print(e)
    print(f'таблицы зон 1917-1921: ошибок {len(err)}')
    sys.exit(1 if err else 0)


if __name__ == '__main__':
    main()
