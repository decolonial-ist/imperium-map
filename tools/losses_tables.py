#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Курируемые таблицы потерь контроля в CSV (27.09.2026, по слову куратора
«переноси всё в CSV для лёгкого редактирования людьми»).

Раньше жили литералами Python в tools/build_losses.py: RAIDS (рейды 2023-2024
на территорию РФ), EPISODE_META (имена крупных эпизодов серой зоны DeepState),
PRE20 с частями (досоветские потери контроля: походы Гиреев, Наполеон, Крымская
война...), NOT_CONFIRMED и PRE20_NOT_ENTERED (проверенные и отклонённые
эпизоды). Теперь - data/losses/*.csv; сборщик читает их отсюда (load).

  losses_raids.csv       key, kind, name, lon, lat, km, frm, to, note, source, comment
      kind=raid - пункт занят; contested - под ударом, но удержан (без выреза).
      Круг радиусом km вокруг точки, окно [frm; to].
  losses_episodes.csv    date, slug, name, note, source, comment
      имя и разбор крупного эпизода серой зоны DeepState по дате её снимка.
  losses_pre20.csv       slug, name, style, confidence, source, comment
      досоветский эпизод; style - календарь дат («даты старого стиля» и т. п.).
  losses_pre20_parts.csv episode, name, kind, frm, to, geom, note, comment
      части эпизода (episode = slug); geom - литерал Python, список фигур:
      ('route', 'папка/маршрут', км) - полоса вдоль маршрута data/losses/routes.csv,
      ('circle', lon, lat, км), ('ne', admin, [названия]), ('ne_box', admin,
      [названия], (lon0, lat0, lon1, lat1)), ('file', путь) - см. part_geom
      в tools/build_losses.py.
  losses_rejected.csv    period, name, why, comment
      проверено и НЕ заведено: period=raids (2023-2024) или pre20 (до 1920).

Запуск:
  python tools/losses_tables.py --validate
  python tools/losses_tables.py --export PY OUT
"""
import ast
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import csv_tables as ct  # noqa: E402

DIR = os.path.join(ct.ROOT, 'data', 'losses')
TABLES = {
    'RAIDS': ('losses_raids.csv', ['key', 'kind', 'name', 'lon', 'lat', 'km', 'frm', 'to',
                                   'note', 'source', 'comment'], ()),
    'EPISODE_META': ('losses_episodes.csv', ['date', 'slug', 'name', 'note', 'source',
                                             'comment'], ()),
    'PRE20': ('losses_pre20.csv', ['slug', 'name', 'style', 'confidence', 'source',
                                   'comment'], ()),
    'PRE20_PARTS': ('losses_pre20_parts.csv', ['episode', 'name', 'kind', 'frm', 'to', 'geom',
                                               'note', 'comment'], ()),
    'REJECTED': ('losses_rejected.csv', ['period', 'name', 'why', 'comment'], ()),
}


def read_rows(name, d=None):
    fn, cols, nullable = TABLES[name]
    return ct.read_rows(os.path.join(d or DIR, fn), cols, nullable)


def load(name, d=None):
    """Таблица в том виде, в каком её держал литерал в коде."""
    if name in ('NOT_CONFIRMED', 'PRE20_NOT_ENTERED'):
        period = 'raids' if name == 'NOT_CONFIRMED' else 'pre20'
        return {r['name']: r['why'] for r in read_rows('REJECTED', d) if r['period'] == period}
    rows = read_rows(name, d)
    if name == 'RAIDS':
        return [dict(key=r['key'], kind=r['kind'], name=r['name'], lon=float(r['lon']),
                     lat=float(r['lat']), km=float(r['km']), frm=r['frm'], to=r['to'],
                     note=r['note'], source=r['source']) for r in rows]
    if name == 'EPISODE_META':
        return {r['date']: dict(slug=r['slug'], name=r['name'], note=r['note'],
                                source=r['source']) for r in rows}
    if name == 'PRE20':
        parts = {}
        for p in read_rows('PRE20_PARTS', d):
            parts.setdefault(p['episode'], []).append(
                dict(name=p['name'], kind=p['kind'], frm=p['frm'], to=p['to'],
                     geom=ct.lit(p['geom']), note=p['note']))
        return [dict(slug=r['slug'], name=r['name'], style=r['style'],
                     confidence=r['confidence'], source=r['source'],
                     parts=parts.get(r['slug'], [])) for r in rows]
    raise KeyError(name)


def _d(s):
    p = [int(x) for x in str(s).split('-')]
    return date(p[0], p[1], p[2])


def validate(d=None):
    err = []
    keys = set()
    for r in read_rows('RAIDS', d):
        if r['kind'] not in ('raid', 'contested'):
            err.append(f'losses_raids.csv {r["key"]}: kind «{r["kind"]}» (raid|contested)')
        if r['key'] in keys:
            err.append(f'losses_raids.csv: ключ {r["key"]} дважды')
        keys.add(r['key'])
        try:
            float(r['lon']), float(r['lat']), float(r['km'])
            if _d(r['frm']) > _d(r['to']):
                err.append(f'losses_raids.csv {r["key"]}: окно {r["frm"]} - {r["to"]} пустое')
        except ValueError as e:
            err.append(f'losses_raids.csv {r["key"]}: {e}')
        if not r['source'].strip():
            err.append(f'losses_raids.csv {r["key"]}: без источника')
    for r in read_rows('EPISODE_META', d):
        try:
            _d(r['date'])
        except ValueError:
            err.append(f'losses_episodes.csv: дата «{r["date"]}» не разбирается')
    slugs = set()
    for r in read_rows('PRE20', d):
        if r['slug'] in slugs:
            err.append(f'losses_pre20.csv: slug {r["slug"]} дважды')
        slugs.add(r['slug'])
        if r['confidence'] not in ('high', 'medium', 'low'):
            err.append(f'losses_pre20.csv {r["slug"]}: confidence «{r["confidence"]}»')
        if not r['source'].strip():
            err.append(f'losses_pre20.csv {r["slug"]}: без источника')
    for p in read_rows('PRE20_PARTS', d):
        if p['episode'] not in slugs:
            err.append(f'losses_pre20_parts.csv: эпизод {p["episode"]} не заведён')
        try:
            g = ct.lit(p['geom'])
            if not (isinstance(g, list) and all(isinstance(x, tuple) and x[0] in
                                                ('route', 'circle', 'ne', 'ne_box', 'file')
                                                for x in g)):
                err.append(f'losses_pre20_parts.csv {p["episode"]} «{p["name"]}»: geom непонятен')
            if _d(p['frm']) > _d(p['to']):
                err.append(f'losses_pre20_parts.csv {p["episode"]} «{p["name"]}»: окно пустое')
        except (ValueError, SyntaxError) as e:
            err.append(f'losses_pre20_parts.csv {p["episode"]} «{p["name"]}»: {e}')
    for r in read_rows('REJECTED', d):
        if r['period'] not in ('raids', 'pre20'):
            err.append(f'losses_rejected.csv «{r["name"]}»: period «{r["period"]}» (raids|pre20)')
    return err


def export(py, out):
    src = open(py, encoding='utf-8').read()
    com = ct.comments(src)
    tree = ast.parse(src)
    sp = ct.spans(tree, {'RAIDS', 'EPISODE_META', 'PRE20', 'NOT_CONFIRMED', 'PRE20_NOT_ENTERED'})
    mod = ct.import_file(py, '_losses_lit')
    rows = {}
    c = ct.notes(sp['RAIDS'], com)
    rows['RAIDS'] = [dict(r, comment=c[i]) for i, r in enumerate(mod.RAIDS)]
    c = ct.notes(sp['EPISODE_META'], com)
    rows['EPISODE_META'] = [dict(date=k, comment=c[i], **v)
                            for i, (k, v) in enumerate(mod.EPISODE_META.items())]
    c = ct.notes(sp['PRE20'], com)
    rows['PRE20'], rows['PRE20_PARTS'] = [], []
    for i, (ep, node) in enumerate(zip(mod.PRE20, sp['PRE20'][0].value.elts)):
        rows['PRE20'].append(dict(slug=ep['slug'], name=ep['name'], style=ep['style'],
                                  confidence=ep['confidence'], source=ep['source'],
                                  comment=c[i]))
        lst = ct.keyword_list(node, 'parts')
        pc = ct.notes((lst, [e.end_lineno for e in lst.elts]), com) if lst is not None else []
        for j, p in enumerate(ep['parts']):
            rows['PRE20_PARTS'].append(dict(episode=ep['slug'], name=p['name'], kind=p['kind'],
                                            frm=p['frm'], to=p['to'], geom=repr(p['geom']),
                                            note=p['note'], comment=pc[j] if j < len(pc) else ''))
    rej = []
    for period, nm in (('raids', 'NOT_CONFIRMED'), ('pre20', 'PRE20_NOT_ENTERED')):
        c = ct.notes(sp[nm], com)
        rej += [dict(period=period, name=k, why=v, comment=c[i])
                for i, (k, v) in enumerate(getattr(mod, nm).items())]
    rows['REJECTED'] = rej
    for nm, rs in rows.items():
        fn, cols, _ = TABLES[nm]
        ct.write_rows(os.path.join(out, fn), cols, rs)
    bad = [nm for nm in ('RAIDS', 'EPISODE_META', 'PRE20', 'NOT_CONFIRMED', 'PRE20_NOT_ENTERED')
           if load(nm, out) != getattr(mod, nm)]
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
    print(f'таблицы потерь: ошибок {len(err)}')
    sys.exit(1 if err else 0)


if __name__ == '__main__':
    main()
