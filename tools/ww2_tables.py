#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Курируемые таблицы слоя Второй мировой в CSV (27.09.2026).

Раньше жили литералами Python в tools/build_ww2.py: ABROAD (куда Красная армия
входила за границу 1941 года - маска театра) и EXTRA_SRC (изолированные
театры: Северный Иран, Финнмарк, Борнхольм, Маньчжурия, Северная Корея, Южный
Сахалин, Курилы). Теперь - data/ww2/*.csv; сборщик читает их отсюда (load).

  ww2_abroad.csv  admin, names, comment
      страна Natural Earth admin-1 и области через ; (пусто = вся страна).
  ww2_extra.csv   id, frm, until, name, act, geom_note, comment
      изолированный театр: окно [frm; until) (until пустой - до конца слоя),
      акт и описание геометрии. Сама геометрия по id - extra_geom в
      tools/build_ww2.py (новый id требует ветки там).

Запуск:
  python tools/ww2_tables.py --validate
  python tools/ww2_tables.py --export PY OUT
"""
import ast
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import csv_tables as ct  # noqa: E402

DIR = os.path.join(ct.ROOT, 'data', 'ww2')
TABLES = {
    'ABROAD': ('ww2_abroad.csv', ['admin', 'names', 'comment'], ()),
    'EXTRA_SRC': ('ww2_extra.csv', ['id', 'frm', 'until', 'name', 'act', 'geom_note',
                                    'comment'], ('until',)),
    'CUTS': ('ww2_cuts.csv', ['id', 'frm', 'until', 'file', 'name', 'act', 'comment'], ('until',)),
}


def read_rows(name, d=None):
    fn, cols, nullable = TABLES[name]
    return ct.read_rows(os.path.join(d or DIR, fn), cols, nullable)


def load(name, d=None):
    rows = read_rows(name, d)
    if name == 'ABROAD':
        return [(r['admin'], [x for x in r['names'].split(';') if x] or None) for r in rows]
    if name == 'EXTRA_SRC':
        return [dict(id=r['id'], frm=r['frm'], until=r['until'], name=r['name'], act=r['act'],
                     geom_note=r['geom_note']) for r in rows]
    if name == 'CUTS':
        return [dict(id=r['id'], frm=r['frm'], until=r['until'], file=r['file'], name=r['name'],
                     act=r['act']) for r in rows]
    raise KeyError(name)


def _d(s):
    p = [int(x) for x in str(s).split('-')]
    return date(p[0], p[1], p[2])


def validate(d=None):
    err = []
    for r in read_rows('ABROAD', d):
        if not r['admin'].strip():
            err.append('ww2_abroad.csv: пустая страна')
    ids = set()
    for r in read_rows('EXTRA_SRC', d):
        if r['id'] in ids:
            err.append(f'ww2_extra.csv: id {r["id"]} дважды')
        ids.add(r['id'])
        try:
            _d(r['frm'])
            if r['until'] and _d(r['until']) <= _d(r['frm']):
                err.append(f'ww2_extra.csv {r["id"]}: окно {r["frm"]} - {r["until"]} пустое')
        except ValueError:
            err.append(f'ww2_extra.csv {r["id"]}: дата не разбирается')
        if not r['act'].strip():
            err.append(f'ww2_extra.csv {r["id"]}: без акта')
    ids = set()
    for r in read_rows('CUTS', d):
        if r['id'] in ids:
            err.append(f'ww2_cuts.csv: id {r["id"]} дважды')
        ids.add(r['id'])
        try:
            _d(r['frm'])
            if r['until'] and _d(r['until']) <= _d(r['frm']):
                err.append(f'ww2_cuts.csv {r["id"]}: окно пустое')
        except ValueError:
            err.append(f'ww2_cuts.csv {r["id"]}: дата не разбирается')
        f = r['file']
        if not f.startswith('NE:') and not os.path.exists(os.path.join(d or DIR, f)):
            err.append(f'ww2_cuts.csv {r["id"]}: нет файла {f}')
        if not r['act'].strip():
            err.append(f'ww2_cuts.csv {r["id"]}: без акта')
    return err


def export(py, out):
    src = open(py, encoding='utf-8').read()
    com = ct.comments(src)
    sp = ct.spans(ast.parse(src), {'ABROAD', 'EXTRA_SRC'})
    mod = ct.import_file(py, '_ww2_lit')
    rows = {}
    c = ct.notes(sp['ABROAD'], com)
    rows['ABROAD'] = [dict(admin=a, names=';'.join(n or []), comment=c[i])
                      for i, (a, n) in enumerate(mod.ABROAD)]
    c = ct.notes(sp['EXTRA_SRC'], com)
    rows['EXTRA_SRC'] = [dict(e, comment=c[i]) for i, e in enumerate(mod.EXTRA_SRC)]
    for nm, rs in rows.items():
        fn, cols, _ = TABLES[nm]
        ct.write_rows(os.path.join(out, fn), cols, rs)
    bad = [nm for nm in rows if load(nm, out) != getattr(mod, nm)]
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
    print(f'таблицы ВМВ: ошибок {len(err)}')
    sys.exit(1 if err else 0)


if __name__ == '__main__':
    main()
