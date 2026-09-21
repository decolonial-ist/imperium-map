#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Регрессионный тест слоя Первой мировой: города point-in-polygon.

Устроен как `tools/check_ww2.py` (оттуда же попадание точки и таблица
вывода), две таблицы:

1. `data/crosscheck/ww1_checks.csv` - ОЖИДАНИЯ на удержанных данных: города,
   которые якорями слоя не являются, плюс контрольные точки вне модели
   (Берлин, Вена, Константинополь - карта обязана молчать про них всегда) и
   глубокий тыл (Петроград, Москва, Киев - красные всю войну).
2. `data/crosscheck/ww1_cities.csv` - ЯКОРЯ, из которых слой построен.
   Проверка по ним (ключ `--anchors`) почти тавтологична и ловит поломки
   конвейера: растеризацию, упрощение, пересечение с основой, ключи манифеста.

Даты - старый стиль, как в таблицах и в ключах срезов.

Запуск (из корня репозитория):

    .venv/bin/python tools/check_ww1.py             # только ошибки + итог
    .venv/bin/python tools/check_ww1.py --all       # вся таблица
    .venv/bin/python tools/check_ww1.py --anchors   # плюс проверка по якорям
"""
import argparse
import csv
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import crosscheck as cc          # noqa: E402  (Map)
import build_expansion as be     # noqa: E402  (d)
from check_ww2 import run, table  # noqa: E402  (попадание с допуском 0.02°)

ROOT = cc.ROOT
CHECKS = os.path.join(cc.CC, 'ww1_checks.csv')
ANCHORS = os.path.join(cc.CC, 'ww1_cities.csv')

WAR_FROM = be.d('1914-07-19')
WAR_TO = be.d('1917-12-24')      # 25.12.1917 - уже реконструкция 1917-1921


def anchor_rows(mp, path=ANCHORS):
    """Из таблицы якорей - проверки на границах срезов, как у ВМВ: накануне
    смены - прежняя сторона, первый срез не раньше смены - новая."""
    rows = []
    keys = [d for d, _ in mp.slices]
    with open(path, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if (r.get('anchor') or 'yes').strip() != 'yes':
                continue
            start = r['start'].strip()
            ev = []
            for p in (r.get('changes') or '').split(';'):
                if p.strip():
                    day, side = p.split(':')
                    ev.append((be.d(day.strip()), side.strip()))
            ev.sort()

            def row(day, want, why):
                rows.append(dict(
                    city=f'{r["city"]} ({why})', lat=r['lat'], lon=r['lon'],
                    date=day.isoformat(),
                    expected='empire' if want == 'empire' else 'not_empire',
                    phase=r['theatre'], source=r['source'], note=r['note']))

            # сторона на начало войны - первый срез окна
            first = next((k for k in keys if k >= WAR_FROM), None)
            if first and (not ev or ev[0][0] > first):
                row(first, start, 'начало войны')
            for i, (when, side) in enumerate(ev):
                prev = start if i == 0 else ev[i - 1][1]
                since = WAR_FROM if i == 0 else ev[i - 1][0]
                nxt = ev[i + 1][0] if i + 1 < len(ev) else None
                before = when - timedelta(days=1)
                act = max((k for k in keys if k <= before), default=None)
                if WAR_FROM <= before <= WAR_TO and act and act >= since:
                    row(before, prev, 'накануне')
                after = next((k for k in keys if k >= when), None)
                if after and WAR_FROM <= after <= WAR_TO and \
                        (nxt is None or nxt > after):
                    row(after, side, 'следующий срез')
    return rows


def markdown(res, counts, anc, anc_counts, path):
    lines = ['# Проверка слоя Первой мировой войны (в империи / вне империи)',
             '',
             'Собрано `tools/check_ww1.py` из `data/crosscheck/ww1_checks.csv` '
             '(ожидания) и `data/crosscheck/ww1_cities.csv` (якоря).',
             'Файл перезаписывается при каждом прогоне - правки вносить в CSV. '
             'Даты - старый стиль.', '',
             'Итог по ожиданиям: '
             + ', '.join(f'{k} - {v}' for k, v in sorted(counts.items()))
             + f' (всего {len(res)})']
    if anc_counts:
        lines.append('Итог по якорям: '
                     + ', '.join(f'{k} - {v}'
                                 for k, v in sorted(anc_counts.items()))
                     + f' (всего {len(anc)})')
    lines += ['', '| город | дата | фаза | ждём | карта | вердикт | срез | '
              'источник |', '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for r in res:
        lines.append(f'| {r["city"]} | {r["date"]} | {r["phase"]} | '
                     f'{r["expected"]} | {r["got"]} | {r["verdict"]} | '
                     f'{r["slice"]} | {r["source"].replace("|", "/")} |')
    bad = [r for r in anc if r['verdict'] != 'ok']
    if bad:
        lines += ['', '## Ошибки по якорям', '',
                  '| город | дата | ждём | карта | срез |',
                  '| --- | --- | --- | --- | --- |']
        for r in bad:
            lines.append(f'| {r["city"]} | {r["date"]} | {r["expected"]} | '
                         f'{r["got"]} | {r["slice"]} |')
    lines.append('')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'OK {os.path.relpath(path, ROOT)}')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--checks', default=CHECKS)
    ap.add_argument('--all', action='store_true', help='печатать всю таблицу')
    ap.add_argument('--anchors', action='store_true',
                    help='плюс проверка по таблице якорей')
    ap.add_argument('--md', default=os.path.join(cc.CC, 'ww1_report.md'))
    args = ap.parse_args()

    mp = cc.Map()
    with open(args.checks, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    res = run(rows, mp)
    counts = table(res, only_bad=not args.all, title='ОЖИДАНИЯ')

    anc, anc_counts = [], {}
    if args.anchors:
        anc = run(anchor_rows(mp), mp)
        anc_counts = table(anc, only_bad=not args.all, title='ЯКОРЯ')

    markdown(res, counts, anc, anc_counts, args.md)
    return 1 if (counts.get('ОШИБКА') or anc_counts.get('ОШИБКА')) else 0


if __name__ == '__main__':
    sys.exit(main())
