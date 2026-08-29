#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Регрессия помесячной линии контроля на Донбассе: города point-in-polygon.

Тем же способом, что `tools/check_ww2.py`, `tools/check_postsoviet.py` и
`tools/check_expansion.py`: берём населённый пункт с координатами и датой,
спрашиваем НАШУ карту попаданием точки в полигон и сверяем с ожиданием.

Правило показа - такое же, как в `index.html` и в `check_postsoviet.py`:

    в империи = (точка внутри контура ядра И не в активном вырезе)
                ИЛИ внутри активной красной заливки эпизода

ДВЕ ТАБЛИЦЫ, и это принципиально.

1. `data/crosscheck/donbas_checks.csv` - ОЖИДАНИЯ. Города здесь по большей
   части НЕ являются якорями слоя: это проверка на удержанных данных. Плюс
   контрольные точки, которых в модели нет вообще (Киев, Львов, Одесса,
   Ростов-на-Дону) - карта обязана про них молчать или, наоборот, всегда
   говорить одно и то же. Именно эта таблица ловит враньё.

2. `data/crosscheck/donbas_cities.csv` - ЯКОРЯ, из которых слой построен.
   Проверка по ним запускается ключом `--anchors`: она почти тавтологична (в
   точке якоря формула по определению даёт его сторону) и ловит не даты, а
   поломки конвейера - растеризацию, упрощение, обрезку рамкой театра,
   попадание строки в реестр эпизодов. Проверяются ГРАНИЦЫ СРЕЗОВ: последний
   день перед событием (слой обязан показать прежнюю сторону) и первый срез,
   начинающийся не раньше события (новую).

Запуск (из корня репозитория):

    .venv/bin/python tools/check_donbas.py             # только ошибки + итог
    .venv/bin/python tools/check_donbas.py --all       # вся таблица
    .venv/bin/python tools/check_donbas.py --anchors   # плюс проверка по якорям
"""
import argparse
import csv
import os
import sys
from datetime import date, timedelta

from shapely.geometry import Point, shape
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_donbas as bd         # noqa: E402  (parse_changes: `lost` = потерян Украиной)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CC = os.path.join(DATA, 'crosscheck')
PS = os.path.join(DATA, 'postsoviet.geojson')
CORE = os.path.join(DATA, 'years', '1992.geojson')
CHECKS = os.path.join(CC, 'donbas_checks.csv')
ANCHORS = os.path.join(CC, 'donbas_cities.csv')
REPORT = os.path.join(CC, 'donbas_report.md')

E, N = 'empire', 'not_empire'
# окно, в котором наш слой вообще что-то обещает: от первого среза до стыка с
# посуточной линией DeepStateMAP
NEAR = 0.02                  # допуск на границу, как в index.html
BORDER = 0.03                # ближе этого к краю рамки якорь не проверяем
WIN_FROM = date(2014, 4, 6)
WIN_TO = date(2022, 4, 2)


def d(s):
    p = [int(x) for x in str(s).strip().split('-')]
    return date(p[0], p[1], p[2])


class Map:
    """Слой постсоветских эпизодов плюс контур ядра - как его читает показ."""

    def __init__(self):
        import json
        with open(PS, encoding='utf-8') as f:
            self.feats = [(ft['properties'], shape(ft['geometry']).buffer(0))
                          for ft in json.load(f)['features']]
        with open(CORE, encoding='utf-8') as f:
            self.core = unary_union([shape(ft['geometry']).buffer(0)
                                     for ft in json.load(f)['features']])
        # даты срезов реконструкции - границы, на которых карта меняет картинку
        self.stops = sorted({d(p['from']) for p, _ in self.feats
                             if p['territory'].startswith('donbas_')
                             or p['territory'] == 'ordlo'})

    def active(self, day):
        out = []
        for p, g in self.feats:
            if d(p['from']) > day:
                continue
            if p['to'] and d(p['to']) < day:
                continue
            out.append((p, g))
        return out

    def hit(self, g, lon, lat):
        """Попадание точки с допуском на границу - как `hitNear` в index.html.

        Точка сама либо 3 из 4 соседних в 0.02° (~2 км). Без допуска приграничные
        пункты (Меловое стоит вплотную к границе, Изварино - пункт пропуска)
        оказываются снаружи полигона из-за точности контуров Natural Earth, а не
        из-за ошибки в датах.
        """
        if g.contains(Point(lon, lat)):
            return True
        n = sum(1 for dx, dy in ((NEAR, 0), (-NEAR, 0), (0, NEAR), (0, -NEAR))
                if g.contains(Point(lon + dx, lat + dy)))
        return n >= 3

    def ask(self, lon, lat, day):
        pt = Point(lon, lat)
        act = [(p, g) for p, g in self.active(day) if self.hit(g, lon, lat)]
        cut = [p for p, _ in act if p['paint'] == 'cut']
        red = [p for p, _ in act if p['paint'] == 'red']
        got = E if ((self.core.contains(pt) and not cut) or red) else N
        names = '; '.join(sorted({p['name_ru'] for p, _ in act})) or '—'
        return got, names


def run(rows, mp):
    out = []
    for r in rows:
        day = d(r['date'])
        got, eps = mp.ask(float(r['lon']), float(r['lat']), day)
        exp = r['expected'].strip()
        out.append(dict(city=r['city'], date=r['date'], expected=exp, got=got,
                        verdict='ok' if got == exp else 'ОШИБКА', episodes=eps,
                        phase=r.get('phase', ''), source=r.get('source', ''),
                        note=r.get('note', '')))
    return out


def anchor_rows(mp, path=ANCHORS):
    """Из таблицы якорей - проверки НА ГРАНИЦАХ СРЕЗОВ.

    Срезы редкие (помесячные и событийные), поэтому спрашивать «через неделю
    после взятия города» бессмысленно: срез на эту дату ещё прежний, и любая
    карта провалит тест. Правильная пара - последний день перед событием и
    первый срез, начинающийся не раньше события.

    ПРИГРАНИЧНЫЕ ЯКОРЯ НЕ ПРОВЕРЯЮТСЯ. Меловое стоит вплотную к границе,
    Изварино - это пункт пропуска на ней же. Полигон среза обрезан контуром
    Natural Earth и упрощён до 0.008° (~800 м), так что такая точка оказывается
    снаружи из-за точности контура, а не из-за ошибки в датах. Проверять на них
    нечего: пропускаем всё, что ближе BORDER° к краю рамки театра, и говорим
    сколько пропустили.
    """
    rows, stops, skipped = [], mp.stops, []
    edge = bd.clip_geom(date(2022, 3, 1))[0].boundary
    with open(path, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r.get('anchor', 'yes').strip() != 'yes':
                continue
            pt = Point(float(r['lon']), float(r['lat']))
            if edge.distance(pt) < BORDER:
                skipped.append(r['city'])
                continue
            # разбор дат берём у билдера: здесь `lost` = пункт ПОТЕРЯН
            # УКРАИНОЙ (+1), а не «потерян империей», как в таблице ВМВ
            start, ch = bd.parse_changes(r)
            side0 = 'empire' if start == 1 else 'foreign'
            ev = [(day, 'empire' if v == 1 else 'foreign') for day, v in ch]

            def row(day, want, why):
                rows.append(dict(
                    city=f'{r["city"]} ({why})', lat=r['lat'], lon=r['lon'],
                    date=day.isoformat(),
                    expected=E if want == 'empire' else N,
                    phase=r.get('region', ''), source=r.get('source', ''),
                    note=r.get('note', '')))

            for i, (when, side) in enumerate(ev):
                prev = side0 if i == 0 else ev[i - 1][1]
                since = WIN_FROM if i == 0 else ev[i - 1][0]
                nxt = ev[i + 1][0] if i + 1 < len(ev) else None
                before = when - timedelta(days=1)
                act = max((k for k in stops if k <= before), default=None)
                if WIN_FROM <= before <= WIN_TO and act and act >= since:
                    row(before, prev, 'накануне')
                after = next((k for k in stops if k >= when), None)
                if after and WIN_FROM <= after <= WIN_TO and \
                        (nxt is None or nxt > after):
                    row(after, side, 'следующий срез')
    if skipped:
        print(f'приграничных якорей пропущено: {len(skipped)} '
              f'({", ".join(sorted(set(skipped)))})')
    return rows


def table(res, only_bad, title):
    rows = [r for r in res if r['verdict'] != 'ok'] if only_bad else res
    if rows:
        w = max(len(r['city']) for r in rows)
        print(f'\n{title}')
        for r in rows:
            print(f'{r["city"].ljust(w)}  {r["date"]}  ждём '
                  f'{r["expected"].ljust(10)} вышло {r["got"].ljust(10)} '
                  f'{r["verdict"]}  [{r["episodes"]}]')
    counts = {}
    for r in res:
        counts[r['verdict']] = counts.get(r['verdict'], 0) + 1
    print(f'{title}: '
          + ', '.join(f'{k} - {v}' for k, v in sorted(counts.items()))
          + f' (всего {len(res)})')
    return counts


def markdown(res, counts, anc, anc_counts, path, stops):
    lines = [
        '# Проверка помесячной линии контроля на Донбассе', '',
        'Собрано `tools/check_donbas.py` из `data/crosscheck/donbas_checks.csv` '
        '(ожидания)', 'и `data/crosscheck/donbas_cities.csv` (якоря). Файл '
        'перезаписывается при каждом прогоне - правки вносить в CSV.', '',
        'Правило показа: **в империи = (точка в контуре ядра И не в активном '
        'вырезе) ИЛИ в активной красной заливке эпизода** - так же, как в '
        '`index.html`.', '',
        'Срезы слоя: ' + ', '.join(k.isoformat() for k in stops), '',
        'Итог по ожиданиям: '
        + ', '.join(f'{k} - {v}' for k, v in sorted(counts.items()))
        + f' (всего {len(res)})']
    if anc_counts:
        lines.append('Итог по якорям: '
                     + ', '.join(f'{k} - {v}'
                                 for k, v in sorted(anc_counts.items()))
                     + f' (всего {len(anc)})')
    lines += ['', '| пункт | дата | период | ждём | карта | вердикт | эпизоды '
              'на дату | источник |',
              '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for r in res:
        lines.append(f'| {r["city"]} | {r["date"]} | {r["phase"]} | '
                     f'{r["expected"]} | {r["got"]} | {r["verdict"]} | '
                     f'{r["episodes"]} | {r["source"].replace("|", "/")} |')
    bad = [r for r in anc if r['verdict'] != 'ok']
    if bad:
        lines += ['', '## Ошибки по якорям', '',
                  '| пункт | дата | ждём | карта |', '| --- | --- | --- | --- |']
        for r in bad:
            lines.append(f'| {r["city"]} | {r["date"]} | {r["expected"]} | '
                         f'{r["got"]} |')
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
    ap.add_argument('--md', default=REPORT)
    args = ap.parse_args()

    mp = Map()
    with open(args.checks, encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f) if r.get('city')]
    res = run(rows, mp)
    counts = table(res, only_bad=not args.all, title='ОЖИДАНИЯ')

    anc, anc_counts = [], {}
    if args.anchors:
        anc = run(anchor_rows(mp), mp)
        anc_counts = table(anc, only_bad=not args.all, title='ЯКОРЯ')

    markdown(res, counts, anc, anc_counts, args.md, mp.stops)
    return 1 if (counts.get('ОШИБКА') or anc_counts.get('ОШИБКА')) else 0


if __name__ == '__main__':
    sys.exit(main())
