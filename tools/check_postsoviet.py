#!/usr/bin/env python3
"""Регрессия слоя постсоветских эпизодов: point-in-polygon по датам.

Гоняет таблицу CHECKS: «город, дата, ждём ли точку в империи, почему». Считает
ровно то же, что рисует карта:

    в империи = (точка внутри контура ядра И не попала в активный вырез)
                ИЛИ попала в активную красную заливку эпизода

Вырез (`paint: cut`) - территория, которую империя считала своей, но контроля
на дату не имела: Ичкерия 1996-1999, обе чеченские войны. Красная заливка
(`paint: red`) - ЧУЖАЯ территория, которой империя распоряжается: Приднестровье,
Абхазия, Южная Осетия, Крым, ОРДЛО, буферные зоны в Грузии 2008.

Падает с кодом 1, если карта врёт. Отчёт - data/crosscheck/postsoviet_report.md.

Запуск: .venv/bin/python tools/check_postsoviet.py
Ключ --all печатает всю таблицу, а не только провалы.
"""
import json
import os
import sys
from datetime import date

from shapely.geometry import Point, shape
from shapely.ops import unary_union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
PS = os.path.join(DATA, 'postsoviet.geojson')
CORE = os.path.join(DATA, 'years', '1992.geojson')
REPORT = os.path.join(DATA, 'crosscheck', 'postsoviet_report.md')

E, N = 'empire', 'not_empire'

# город, широта/долгота, дата, ждём, чего ждём от эпизода (kind или '' - всё
# равно), пояснение. Даты - те, на которых карта обязана показывать эпизод,
# а не только правовой акт.
# Таблица живёт в data/crosscheck/postsoviet_points.csv (27.09.2026):
# city, lon, lat, date, want (empire|not_empire), want_kind, why, comment.
import csv_tables as _ct   # noqa: E402
CHECKS = [(r['city'], float(r['lon']), float(r['lat']), r['date'], r['want'], r['want_kind'], r['why'])
          for r in _ct.read_rows(os.path.join(DATA, 'crosscheck', 'postsoviet_points.csv'),
                                 ['city', 'lon', 'lat', 'date', 'want', 'want_kind', 'why', 'comment'])]
for _r in CHECKS:
    if _r[4] not in (E, N):
        raise SystemExit(f'postsoviet_points.csv {_r[0]} {_r[3]}: want «{_r[4]}» (empire|not_empire)')


def d(s):
    p = [int(v) for v in s.split('-')]
    return date(p[0], p[1], p[2])


def main():
    show_all = '--all' in sys.argv
    with open(PS, encoding='utf-8') as f:
        ps = json.load(f)['features']
    with open(CORE, encoding='utf-8') as f:
        core = unary_union([shape(ft['geometry']).buffer(0)
                            for ft in json.load(f)['features']])
    feats = [(ft['properties'], shape(ft['geometry']).buffer(0)) for ft in ps]

    def active(t):
        out = []
        for p, g in feats:
            if d(p['from']) > t:
                continue
            if p['to'] and d(p['to']) < t:
                continue
            out.append((p, g))
        return out

    rows, fails = [], 0
    for name, x, y, ds, want, want_kind, why in CHECKS:
        t, pt = d(ds), Point(x, y)
        act = [(p, g) for p, g in active(t) if g.contains(pt)]
        cut = [p for p, _ in act if p['paint'] == 'cut']
        red = [p for p, _ in act if p['paint'] == 'red']
        in_core = core.contains(pt)
        got = E if ((in_core and not cut) or red) else N
        kinds = {p['kind'] for p, _ in act}
        ok = got == want and (not want_kind or want_kind in kinds)
        if not ok:
            fails += 1
        eps = '; '.join(sorted(f"{p['kind']}:{p['name_ru']}" for p, _ in act)) or '—'
        rows.append((ok, name, ds, want, got, want_kind, eps, why))
    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write('# Постсоветские эпизоды: регрессия\n\n')
        f.write(f'`tools/check_postsoviet.py`, {len(CHECKS)} проверок, '
                f'провалов: {fails}.\n\n')
        f.write('Правило показа: **в империи = (точка в контуре ядра И не в '
                'активном вырезе) ИЛИ в активной красной заливке эпизода**.\n\n')
        f.write('| | точка | дата | ждём | вышло | тип эпизода | эпизоды на дату | почему |\n')
        f.write('|---|---|---|---|---|---|---|---|\n')
        for ok, name, ds, want, got, wk, eps, why in rows:
            f.write(f'| {"ок" if ok else "**ВРЁТ**"} | {name} | {ds} | {want} | '
                    f'{got} | {wk or "—"} | {eps} | {why} |\n')
    for ok, name, ds, want, got, wk, eps, why in rows:
        if show_all or not ok:
            print(f'{"ок  " if ok else "ВРЁТ"} {name:16} {ds}  ждём {want:10} '
                  f'вышло {got:10} {wk or "":22} {eps}')
    print(f'\n{len(CHECKS)} проверок, провалов: {fails}')
    print(f'отчёт: {REPORT}')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
