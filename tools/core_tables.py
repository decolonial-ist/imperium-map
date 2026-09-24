"""Таблицы ядра карты в CSV (неделя 2 новой архитектуры, 24.09.2026).

Раньше таблицы жили литералами Python в tools/build_expansion.py (REG, ADDS,
SUBS, RESIST, REPUBLICS, LATE_EDITS, LATE_NEW) и tools/clip_foreign.py
(FOREIGN, FOREIGN_SINCE, KEEP). Теперь они в data/core/*.csv, по строке на
окно; сборщики читают их отсюда (load), структура та же, что у литералов.

Правила файлов:
  - CRLF, UTF-8, даты ISO; пустая ячейка в колонках-датах = None (окно открыто);
  - колонки spec, provider, campaigns - литерал Python (как было в коде):
    [('ne', 'Russia', ['Tver\\'']), ...] - читается ast.literal_eval;
  - comment - комментарии, стоявшие в коде над строкой и внутри неё
    (источники, разборы, история правок); сборка его не читает.

Запуск:
  python tools/core_tables.py --validate          проверка таблиц
  python tools/core_tables.py --export PY OUT     литералы файла PY -> CSV в OUT
                                                  (перенос; build_expansion.py
                                                  или clip_foreign.py)
"""
import ast
import csv
import importlib.util
import io
import os
import sys
import tokenize
from datetime import date

TOOLS = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(os.path.dirname(TOOLS), 'data', 'core')

# имя таблицы -> файл, колонки, колонки-даты с пустым = None
TABLES = {
    'REG': ('regions.csv', ['id', 'spec', 'comment'], ()),
    'ADDS': ('adds.csv', ['reg', 'frm', 'to', 'kind', 'name', 'act', 'src', 'clip',
                          'comment'], ('to', 'clip')),
    'SUBS': ('subs.csv', ['reg', 'frm', 'to', 'name', 'why', 'comment'], ('frm', 'to')),
    'RESIST': ('resist.csv', ['reg', 'until', 'name', 'event', 'src', 'campaigns',
                              'domain', 'painted', 'note', 'comment'], ('domain',)),
    'REPUBLICS': ('republics.csv', ['gwcode', 'name', 'date', 'act', 'src', 'comment'], ()),
    'LATE_EDITS': ('late_edits.csv', ['op', 'provider', 'frm', 'to', 'name', 'why',
                                      'comment'], ('to',)),
    'LATE_NEW': ('late_new.csv', ['key', 'base', 'why', 'comment'], ()),
    'FOREIGN': ('foreign.csv', ['country', 'since', 'comment'], ('since',)),
    'KEEP': ('keep.csv', ['lon', 'lat', 'key', 'why', 'comment'], ()),
}
LITERAL = {'spec', 'provider', 'campaigns'}
BE_TABLES = ('REG', 'ADDS', 'SUBS', 'RESIST', 'REPUBLICS', 'LATE_EDITS', 'LATE_NEW')
CF_TABLES = ('FOREIGN', 'KEEP')


# ---- чтение -----------------------------------------------------------------
def read_rows(name, core=None):
    fn, cols, nullable = TABLES[name]
    path = os.path.join(core or CORE, fn)
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


def _lit(s):
    return ast.literal_eval(s)


def load(name, core=None):
    """Таблица в том виде, в каком её держал литерал в коде."""
    rows = read_rows(name, core)
    if name == 'REG':
        return {r['id']: _lit(r['spec']) for r in rows}
    if name == 'ADDS':
        return [dict(reg=r['reg'], frm=r['frm'], to=r['to'], name=r['name'], act=r['act'],
                     src=r['src'], clip=r['clip'], kind=r['kind']) for r in rows]
    if name == 'SUBS':
        return [dict(reg=r['reg'], frm=r['frm'], to=r['to'], name=r['name'], why=r['why'])
                for r in rows]
    if name == 'RESIST':
        return [dict(reg=r['reg'], until=r['until'], name=r['name'], event=r['event'],
                     src=r['src'], campaigns=_lit(r['campaigns']), domain=r['domain'],
                     painted=r['painted'], note=r['note']) for r in rows]
    if name == 'REPUBLICS':
        return [(int(r['gwcode']), r['name'], r['date'], r['act'], r['src']) for r in rows]
    if name == 'LATE_EDITS':
        return [(r['op'], _lit(r['provider']), r['frm'], r['to'], r['name'], r['why'])
                for r in rows]
    if name == 'LATE_NEW':
        return [(r['key'], r['base'], r['why']) for r in rows]
    if name == 'FOREIGN':
        return ([r['country'] for r in rows if r['since'] is None],
                {r['country']: r['since'] for r in rows if r['since'] is not None})
    if name == 'KEEP':
        return [((float(r['lon']), float(r['lat'])), r['key'], r['why']) for r in rows]
    raise KeyError(name)


# ---- проверка ---------------------------------------------------------------
def _d(s):
    p = [int(x) for x in str(s).split('-')]
    return date(p[0], p[1] if len(p) > 1 else 1, p[2] if len(p) > 2 else 1)


def validate(core=None):
    """Ошибки таблиц списком строк (пустой - всё хорошо)."""
    err = []
    reg = load('REG', core)
    for r in read_rows('REG', core):
        spec = _lit(r['spec'])
        if not isinstance(spec, list) or not all(isinstance(p, tuple) and p for p in spec):
            err.append(f'regions.csv {r["id"]}: spec не список кортежей')
    rootdata = os.path.join(os.path.dirname(core or CORE))
    for rid, spec in reg.items():
        for p in spec:
            if p[0] in ('file', 'and_file', 'minus_file', 'file_where'):
                if not os.path.exists(os.path.join(rootdata, p[1])):
                    err.append(f'regions.csv {rid}: нет файла data/{p[1]}')

    def dates(tab, row, cols):
        for c in cols:
            if row[c] is not None:
                try:
                    _d(row[c])
                except ValueError:
                    err.append(f'{tab}: дата «{row[c]}» не разбирается ({row.get("reg") or row.get("key")})')
                    return False
        return True

    for tab, key, cols in (('ADDS', 'reg', ('frm', 'to')), ('SUBS', 'reg', ('frm', 'to')),
                           ('RESIST', 'reg', ('until',))):
        fn = TABLES[tab][0]
        for r in read_rows(tab, core):
            if r[key] not in reg:
                err.append(f'{fn}: регион {r[key]} не заведён в regions.csv')
            if not dates(fn, r, cols):
                continue
            if r.get('frm') and r.get('to') and _d(r['frm']) >= _d(r['to']):
                err.append(f'{fn}: {r[key]} окно {r["frm"]} - {r["to"]} пустое')
            src = r.get('src', r.get('why', r.get('event')))
            if not (src or '').strip():
                err.append(f'{fn}: {r[key]} ({r.get("frm")}) без источника')
    for r in read_rows('LATE_EDITS', core):
        prov = _lit(r['provider'])
        if r['op'] not in ('add', 'sub'):
            err.append(f'late_edits.csv: вид «{r["op"]}» (нужно add или sub)')
        if prov[0] == 'reg' and prov[1] not in reg:
            err.append(f'late_edits.csv: регион {prov[1]} не заведён в regions.csv')
        if dates('late_edits.csv', r, ('frm', 'to')) and r['to'] and _d(r['frm']) >= _d(r['to']):
            err.append(f'late_edits.csv: {prov} окно {r["frm"]} - {r["to"]} пустое')
        if not r['why'].strip():
            err.append(f'late_edits.csv: {prov} ({r["frm"]}) без источника')
    keys = set()
    for r in read_rows('LATE_NEW', core):
        dates('late_new.csv', r, ('key',))
        if r['key'] in keys:
            err.append(f'late_new.csv: ключ {r["key"]} дважды')
        keys.add(r['key'])
    # окна одного региона одного вида не должны пересекаться
    by = {}
    for r in load('ADDS', core):
        by.setdefault((r['reg'], r['kind']), []).append(r)
    for (rid, kind), rs in by.items():
        rs = sorted(rs, key=lambda r: _d(r['frm']))
        for a, b in zip(rs, rs[1:]):
            if a['to'] is None or _d(b['frm']) < _d(a['to']):
                err.append(f'adds.csv: окна {rid} ({kind}) {a["frm"]}-{a["to"]} и '
                           f'{b["frm"]}-{b["to"]} пересекаются')
    return err


# ---- перенос литералов в CSV ------------------------------------------------
def _comments(src):
    out = {}
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            out[tok.start[0]] = tok.string[1:].strip()
    return out


def _import(path):
    d = os.path.dirname(os.path.abspath(path))
    sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location('_lit_' + str(abs(hash(path))), path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.path.remove(d)
    return m


def _write(name, rows, out):
    fn, cols, nullable = TABLES[name]
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, fn), 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, lineterminator='\r\n')
        w.writerow(cols)
        for r in rows:
            for c in cols:
                v = r[c]
                if c in nullable:
                    assert v != '', (name, c, r)
                elif v is None:
                    raise ValueError(f'{name}.{c}: None в колонке без пустых')
            w.writerow(['' if r[c] is None else r[c] for c in cols])


def export(py, out):
    """Литералы таблиц файла py -> CSV в out, с комментариями строк."""
    src = open(py, encoding='utf-8').read()
    com = _comments(src)
    tree = ast.parse(src)
    mod = _import(py)
    spans = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
            nm = n.targets[0].id
            if nm in TABLES or nm == 'FOREIGN_SINCE':
                elts = n.value.keys if isinstance(n.value, ast.Dict) else n.value.elts
                spans[nm] = (n, elts)

    def notes(nm):
        n, elts = spans[nm]
        res, prev = [], n.lineno
        for i, e in enumerate(elts):
            end = e.end_lineno
            if isinstance(n.value, ast.Dict):
                end = n.value.values[i].end_lineno
            last = i == len(elts) - 1
            hi = n.end_lineno if last else end
            res.append('\n'.join(com[ln] for ln in range(prev + 1, hi + 1) if ln in com))
            prev = end
        return res

    rows = {}
    if 'REG' in spans:
        c = notes('REG')
        rows['REG'] = [dict(id=k, spec=repr(v), comment=c[i])
                       for i, (k, v) in enumerate(mod.REG.items())]
        c = notes('ADDS')
        rows['ADDS'] = [dict(r, comment=c[i]) for i, r in enumerate(mod.ADDS)]
        c = notes('SUBS')
        lit = mod.SUBS[:len(spans['SUBS'][1])]          # хвост SUBS - из RESIST, кодом
        rows['SUBS'] = [dict(r, comment=c[i]) for i, r in enumerate(lit)]
        c = notes('RESIST')
        rows['RESIST'] = [dict(r, campaigns=repr(r['campaigns']), comment=c[i])
                          for i, r in enumerate(mod.RESIST)]
        c = notes('REPUBLICS')
        rows['REPUBLICS'] = [dict(gwcode=g, name=nm, date=dt, act=a, src=s, comment=c[i])
                             for i, (g, nm, dt, a, s) in enumerate(mod.REPUBLICS)]
        c = notes('LATE_EDITS')
        rows['LATE_EDITS'] = [dict(op=o, provider=repr(p), frm=f, to=t, name=nm, why=w,
                                   comment=c[i])
                              for i, (o, p, f, t, nm, w) in enumerate(mod.LATE_EDITS)]
        c = notes('LATE_NEW')
        rows['LATE_NEW'] = [dict(key=k, base=b, why=w, comment=c[i])
                            for i, (k, b, w) in enumerate(mod.LATE_NEW)]
    if 'FOREIGN' in spans:
        n, elts = spans['FOREIGN_SINCE']
        c = notes('FOREIGN_SINCE')
        fr = [dict(country=x, since=None, comment='') for x in mod.FOREIGN]
        fr[0]['comment'] = '\n'.join(com[ln] for ln in range(spans['FOREIGN'][0].lineno - 3,
                                                              spans['FOREIGN'][0].lineno)
                                     if ln in com)
        fr += [dict(country=k, since=v, comment=c[i])
               for i, (k, v) in enumerate(mod.FOREIGN_SINCE.items())]
        rows['FOREIGN'] = fr
        c = notes('KEEP')
        rows['KEEP'] = [dict(lon=repr(p[0]), lat=repr(p[1]), key=k, why=w, comment=c[i])
                        for i, (p, k, w) in enumerate(mod.KEEP)]
    for nm, rs in rows.items():
        _write(nm, rs, out)
    # сверка «всё против всего»: прочитанное из CSV равно литералам
    bad = []
    for nm in rows:
        got = load(nm, out)
        if nm == 'SUBS':
            want = mod.SUBS[:len(spans['SUBS'][1])]
        elif nm == 'FOREIGN':
            want = (mod.FOREIGN, mod.FOREIGN_SINCE)
        else:
            want = getattr(mod, nm)
        if got != want or repr(got) != repr(want):
            bad.append(nm)
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
    print(f'таблицы ядра: ошибок {len(err)}')
    sys.exit(1 if err else 0)


if __name__ == '__main__':
    main()
