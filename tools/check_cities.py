#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Регрессионный тест реконструкции 1917-1921: города point-in-polygon.

Тем же способом, каким куратор поймал брак первой версии реконструкции
(18.08.2026): берём таблицу «город, дата, кто контролировал» из
`data/crosscheck/cities_civilwar.csv`, для каждой строки спрашиваем НАШУ карту
попаданием точки в полигон действующего среза и сверяем с ожиданием.

СЕМАНТИКА СМЕНИЛАСЬ 26.08.2026 вместе с рамкой слоя: раньше проверяли «под
советской властью / нет», теперь - «в империи / вне империи». Белые (Комуч,
Колчак, ВСЮР, Врангель, Северная область, Семёнов, ДВР) - имперская фракция,
их территория обязана быть КРАСНОЙ. Прежняя таблица ожиданий сохранена рядом
как `cities_civilwar_soviet_zone.csv` - она остаётся историей вопроса.

Колонка `expected`:
  empire      - в этот день точка внутри империи, наш срез обязан её накрыть;
  not_empire  - в этот день точка вне империи, срез накрывать не должен.

Вердикты: ok - совпало; ОШИБКА - карта врёт; вне-периода - на эту дату нет
среза реконструкции (значит проверять нечего, строка вне окна 12.1917-03.1921).

Запуск (из корня репозитория):

    python3 tools/check_cities.py          # только ошибки + итог
    python3 tools/check_cities.py --all    # вся таблица
    python3 tools/check_cities.py --md data/crosscheck/cities_report.md
"""
import argparse
import csv
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import crosscheck as cc   # noqa: E402  (Map, parse_date, in_geom - оттуда)

ROOT = cc.ROOT
CSV = os.path.join(cc.CC, 'cities_civilwar.csv')

RECON_FROM, RECON_TO = cc.date(1917, 12, 25), cc.date(1921, 3, 18)


def ask(mp, row):
    """-> (наш ответ 'empire'|'not_empire'|None, ключ среза)."""
    day, _ = cc.parse_date(row['date'])
    key = mp.core_slice(day)
    if not key:
        return None, '-'
    fc = mp.geo(os.path.join('years', key + '.geojson'))
    # только реконструкция зоны контроля 1917-1921: у срезов расползания
    # 1552-1914 (tools/build_expansion.py) флаг `reconstruction` тоже стоит,
    # но они про приобретения по актам, а не про контроль в Гражданскую
    recon = any(f['properties'].get('reconstruction')
                and not f['properties'].get('expansion')
                for f in fc.get('features', []))
    if not recon:
        return None, key
    inside = bool(cc.hits(float(row['lon']), float(row['lat']), fc))
    return ('empire' if inside else 'not_empire'), key


def run(rows, mp):
    out = []
    for r in rows:
        got, key = ask(mp, r)
        exp = r['expected'].strip()
        if got is None:
            verdict = 'вне-периода'
        elif got == exp:
            verdict = 'ok'
        else:
            verdict = 'ОШИБКА'
        out.append(dict(city=r['city'], date=r['date'], controller=r['controller'],
                        expected=exp, got=got or '-', slice=key, verdict=verdict,
                        source=r['source'], note=r['note']))
    return out


def table(res, only_bad):
    rows = [r for r in res if r['verdict'] != 'ok'] if only_bad else res
    if rows:
        w = max(len(r['city']) for r in rows)
        wc = max(len(r['controller']) for r in rows)
        print(f'{"город".ljust(w)}  {"дата".ljust(10)}  {"контролёр".ljust(wc)}  '
              f'{"ждём".ljust(10)}  {"карта".ljust(10)}  вердикт / срез')
        for r in rows:
            print(f'{r["city"].ljust(w)}  {r["date"].ljust(10)}  '
                  f'{r["controller"].ljust(wc)}  {r["expected"].ljust(10)}  '
                  f'{r["got"].ljust(10)}  {r["verdict"]} / {r["slice"]}')
    counts = {}
    for r in res:
        counts[r['verdict']] = counts.get(r['verdict'], 0) + 1
    print('итог: ' + ', '.join(f'{k} - {v}' for k, v in sorted(counts.items()))
          + f' (всего {len(res)})')
    return counts


def markdown(res, counts, path):
    lines = ['# Проверка реконструкции 1917-1921 по городам (в империи / вне империи)', '',
             'Собрано `tools/check_cities.py` из '
             '`data/crosscheck/cities_civilwar.csv`.',
             'Файл перезаписывается при каждом прогоне - правки вносить в CSV.', '',
             'Метод: point-in-polygon по срезу, действующему на дату строки.',
             '`empire` - срез обязан накрыть город, `not_empire` - не должен.', '',
             'Итог: ' + ', '.join(f'{k} - {v}' for k, v in sorted(counts.items())),
             '',
             '| город | дата | контролёр | ждём | карта | вердикт | срез | источник |',
             '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for r in res:
        lines.append(f'| {r["city"]} | {r["date"]} | {r["controller"]} | '
                     f'{r["expected"]} | {r["got"]} | {r["verdict"]} | '
                     f'{r["slice"]} | {r["source"].replace("|", "/")} |')
    lines += ['', '## Примечания к строкам', '']
    for r in res:
        if r['note']:
            lines.append(f'- **{r["city"]}, {r["date"]}** - '
                         f'{r["note"].replace("|", "/")}')
    lines.append('')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'OK {os.path.relpath(path, ROOT)}')


WEST = os.path.join(cc.CC, 'zones_west_cities.csv')
WEST_FROM = cc.date(1918, 2, 18)   # раньше - фронт слоя ПМВ, не эти якоря


def anchor_rows(mp, path=WEST):
    """Якоря западного театра (22.09.2026) - на границах срезов, как у ПМВ и
    ВМВ: накануне смены - прежняя сторона, первый срез не раньше смены - новая.
    Срезы до 18.02.1918 рисует фронт слоя ПМВ, их сверяет check_ww1."""
    rows = []
    keys = [d for d, k in mp.slices if WEST_FROM <= d < RECON_TO]
    with open(path, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if (r.get('anchor') or 'yes').strip() != 'yes':
                continue
            ev = []
            for p in (r.get('changes') or '').split(';'):
                if p.strip():
                    day, side = p.split(':')
                    ev.append((cc.date(*map(int, day.strip().split('-'))),
                               side.strip()))
            ev.sort()

            def row(day, want, why):
                rows.append(dict(
                    city=f'{r["city"]} ({why})', lat=r['lat'], lon=r['lon'],
                    date=day.isoformat(),
                    expected='empire' if want == 'empire' else 'not_empire',
                    phase=r['theatre'], source=r['source'], note=r['note']))

            start = r['start'].strip()
            # start_day - день, к которому относится сторона start (у якорей
            # Волыни 1920 года - 01.07.1920); раньше якорь не проверяется
            sd = (r.get('start_day') or '').strip()
            first_day = cc.date(*map(int, sd.split('-'))) if sd else WEST_FROM
            # end_day - последний день, когда якорь решает землю (у якорей
            # Волыни - окно WEST_IN_WINDOWS до 16.11.1920 включительно)
            ed = (r.get('end_day') or '').strip()
            last_day = cc.date(*map(int, ed.split('-'))) if ed else RECON_TO
            ks = [k for k in keys if first_day <= k <= last_day]
            if ks:
                prev = start
                for when, side in ev:
                    if when <= ks[0]:
                        prev = side
                row(ks[0], prev, 'начало модели')
            for i, (when, side) in enumerate(ev):
                prev = start if i == 0 else ev[i - 1][1]
                since = first_day if i == 0 else ev[i - 1][0]
                nxt = ev[i + 1][0] if i + 1 < len(ev) else None
                before = when - timedelta(days=1)
                act = max((k for k in ks if k <= before), default=None)
                if act and act >= since and first_day <= before <= last_day:
                    row(before, prev, 'накануне')
                after = next((k for k in ks if k >= when), None)
                if after and (nxt is None or nxt > after):
                    row(after, side, 'следующий срез')
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cities', default=CSV)
    ap.add_argument('--all', action='store_true', help='печатать всю таблицу')
    ap.add_argument('--anchors', action='store_true',
                    help='плюс проверка по якорям западного театра '
                         '(data/crosscheck/zones_west_cities.csv)')
    ap.add_argument('--md', default=os.path.join(cc.CC, 'cities_report.md'))
    args = ap.parse_args()

    mp = cc.Map()
    with open(args.cities, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    res = run(rows, mp)
    counts = table(res, only_bad=not args.all)
    markdown(res, counts, args.md)
    anc_counts = {}
    if args.anchors:
        from check_ww2 import run as run_near, table as table_near
        anc = run_near(anchor_rows(mp), mp)
        anc_counts = table_near(anc, only_bad=not args.all,
                                title='ЯКОРЯ ЗАПАДНОГО ТЕАТРА')
    return 1 if (counts.get('ОШИБКА') or anc_counts.get('ОШИБКА')) else 0


if __name__ == '__main__':
    sys.exit(main())
