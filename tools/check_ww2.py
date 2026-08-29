#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Регрессионный тест слоя Второй мировой: города point-in-polygon.

Тем же способом, что `tools/check_expansion.py` и `tools/check_cities.py`:
берём город с координатами и датой, спрашиваем НАШУ карту попаданием точки в
полигон действующего среза и сверяем с ожиданием.

ДВЕ ТАБЛИЦЫ, и это принципиально.

1. `data/crosscheck/ww2_checks.csv` - ОЖИДАНИЯ. Города здесь по большей части
   НЕ являются якорями слоя: это проверка на удержанных данных. Плюс сюда
   заведены контрольные точки, которых в модели нет вообще (Стокгольм, Анкара,
   Тегеран, Токио, Пекин - карта обязана молчать про них всегда) и глубокий
   тыл (Свердловск, Новосибирск, Владивосток - обязан быть красным всю войну).
   Именно эта таблица ловит враньё.

2. `data/crosscheck/ww2_cities.csv` - ЯКОРЯ, из которых слой и построен.
   Проверка по ним запускается ключом `--anchors` и печатается отдельно: она
   почти тавтологична (в точке якоря формула по определению даёт его сторону)
   и ловит не даты, а поломки конвейера - растеризацию, упрощение, пересечение
   с контуром-основой, попадание ключа в манифест. Города, «утонувшие» за
   береговой линией после упрощения, ловятся именно здесь.

Колонка `expected`: `empire` - на эту дату точка внутри имперской зоны,
`not_empire` - вне.

Попадание считается так же, как в попапе истории точки (`hitNear` в
index.html) и в двух других регрессиях: сама точка либо 3 из 4 соседних в
0.02° - иначе контуры мирового масштаба топят приморские города.

Запуск (из корня репозитория):

    .venv/bin/python tools/check_ww2.py             # только ошибки + итог
    .venv/bin/python tools/check_ww2.py --all       # вся таблица
    .venv/bin/python tools/check_ww2.py --anchors   # плюс проверка по якорям
"""
import argparse
import csv
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import crosscheck as cc          # noqa: E402  (Map, parse_date, hits)
import build_expansion as be     # noqa: E402  (d, key_date)

ROOT = cc.ROOT
CHECKS = os.path.join(cc.CC, 'ww2_checks.csv')
ANCHORS = os.path.join(cc.CC, 'ww2_cities.csv')
NEAR = 0.02

WAR_FROM = be.d('1941-06-22')
WAR_TO = be.d('1945-09-03')


def hit_near(lon, lat, fc):
    if cc.hits(lon, lat, fc):
        return True
    n = 0
    for dx, dy in ((NEAR, 0), (-NEAR, 0), (0, NEAR), (0, -NEAR)):
        if cc.hits(lon + dx, lat + dy, fc):
            n += 1
    return n >= 3


def ask(mp, lon, lat, day):
    key = mp.core_slice(day)
    if not key:
        return None, '-'
    fc = mp.geo(os.path.join('years', key + '.geojson'))
    return ('empire' if hit_near(lon, lat, fc) else 'not_empire'), key


def run(rows, mp):
    out = []
    for r in rows:
        day, _ = cc.parse_date(r['date'])
        got, key = ask(mp, float(r['lon']), float(r['lat']), day)
        exp = r['expected'].strip()
        verdict = ('нет-среза' if got is None
                   else 'ok' if got == exp else 'ОШИБКА')
        out.append(dict(city=r['city'], date=r['date'], expected=exp,
                        got=got or '-', slice=key, verdict=verdict,
                        phase=r.get('phase', ''), source=r.get('source', ''),
                        note=r.get('note', '')))
    return out


def anchor_rows(mp, path=ANCHORS):
    """Из таблицы якорей - проверки НА ГРАНИЦАХ СРЕЗОВ.

    Срезы помесячные, поэтому проверять «через неделю после взятия города»
    бессмысленно: срез на эту дату ещё прежний, и любая карта провалит тест.
    Правильная пара - последний день перед событием (там слой обязан показать
    ПРЕЖНЮЮ сторону) и первый срез, начинающийся не раньше события (там -
    НОВУЮ). Именно это слой и обещает при помесячной дробности.
    """
    rows = []
    keys = [d for d, _ in mp.slices]
    with open(path, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            start = r['start'].strip()
            ev = []
            if r['changes'].strip():
                for p in r['changes'].split(';'):
                    day, side = p.split(':')
                    ev.append((be.d(day.strip()), side.strip()))
            else:
                if r['lost'].strip():
                    ev.append((be.d(r['lost'].strip()), 'foreign'))
                if r['liberated'].strip():
                    ev.append((be.d(r['liberated'].strip()), 'empire'))
            ev.sort()

            def row(day, want, why):
                rows.append(dict(
                    city=f'{r["city"]} ({why})', lat=r['lat'], lon=r['lon'],
                    date=day.isoformat(),
                    expected='empire' if want == 'empire' else 'not_empire',
                    phase=r['theatre'], source=r['source'], note=r['note']))

            for i, (when, side) in enumerate(ev):
                prev = start if i == 0 else ev[i - 1][1]
                since = WAR_FROM if i == 0 else ev[i - 1][0]
                nxt = ev[i + 1][0] if i + 1 < len(ev) else None
                # НАКАНУНЕ: только если срез, действующий в этот день, начался
                # уже ПОСЛЕ предыдущей смены. Иначе проверяем срез, который про
                # предыдущее событие ещё не знает, и любая помесячная карта
                # провалит тест не по своей вине.
                before = when - timedelta(days=1)
                act = max((k for k in keys if k <= before), default=None)
                if WAR_FROM <= before <= WAR_TO and act and act >= since:
                    row(before, prev, 'накануне')
                # СЛЕДУЮЩИЙ СРЕЗ: только если до него не случилось обратной
                # смены. Ельца (взят 04.12.1941, отбит 09.12) помесячная сетка
                # показать не может, и требовать этого от неё нечестно.
                after = next((k for k in keys if k >= when), None)
                if after and WAR_FROM <= after <= WAR_TO and \
                        (nxt is None or nxt > after):
                    row(after, side, 'следующий срез')
    return rows


def table(res, only_bad, title):
    rows = [r for r in res if r['verdict'] != 'ok'] if only_bad else res
    if rows:
        w = max(len(r['city']) for r in rows)
        print(f'\n{title}')
        print(f'{"город".ljust(w)}  {"дата".ljust(10)}  {"ждём".ljust(10)}  '
              f'{"карта".ljust(10)}  вердикт / срез')
        for r in rows:
            print(f'{r["city"].ljust(w)}  {r["date"].ljust(10)}  '
                  f'{r["expected"].ljust(10)}  {r["got"].ljust(10)}  '
                  f'{r["verdict"]} / {r["slice"]}')
    counts = {}
    for r in res:
        counts[r['verdict']] = counts.get(r['verdict'], 0) + 1
    print(f'{title}: '
          + ', '.join(f'{k} - {v}' for k, v in sorted(counts.items()))
          + f' (всего {len(res)})')
    return counts


def markdown(res, counts, anc, anc_counts, path):
    lines = ['# Проверка слоя Второй мировой войны (в империи / вне империи)', '',
             'Собрано `tools/check_ww2.py` из `data/crosscheck/ww2_checks.csv` '
             '(ожидания)', 'и `data/crosscheck/ww2_cities.csv` (якоря).',
             'Файл перезаписывается при каждом прогоне - правки вносить в CSV.',
             '',
             'Метод: point-in-polygon по срезу, действующему на дату строки, с '
             'допуском на',
             'береговую линию (0.02°, 3 из 4 соседних точек - как `hitNear` в '
             'index.html).', '',
             'Таблица ожиданий держится на УДЕРЖАННЫХ данных: города в ней по '
             'большей части',
             'не являются якорями слоя, плюс заведены контрольные точки вне '
             'модели вообще',
             '(Стокгольм, Анкара, Тегеран, Токио, Пекин) и глубокий тыл. '
             'Проверка по якорям',
             'почти тавтологична и ловит не даты, а поломки конвейера.', '',
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
    lines += ['', '## Примечания к строкам', '']
    for r in res:
        if r['note']:
            lines.append(f'- **{r["city"]}, {r["date"]}** - '
                         f'{r["note"].replace("|", "/")}')
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
    ap.add_argument('--md', default=os.path.join(cc.CC, 'ww2_report.md'))
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
