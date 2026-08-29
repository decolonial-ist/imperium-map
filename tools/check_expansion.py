#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Регрессионный тест расползания империи: приобретения point-in-polygon.

Тот же метод, что в `tools/check_cities.py` (регрессия периода 1917-1921), но
по всей истории: таблица `data/crosscheck/expansion.csv` перечисляет
приобретения империи (что, когда, каким актом), опорный город каждого и то,
что НАША карта обязана про него сказать на указанную дату.

Колонка `expect_in_empire`:
  yes - на эту дату город обязан быть внутри контура империи;
  no  - на эту дату город обязан быть ВНЕ контура (проверка «не покрасили
        раньше времени» и «отдали, когда потеряли» - Аляска после 1867).

Вердикты: ok - совпало; ОШИБКА - карта врёт; нет-среза - на эту дату у нас
слоёв нет (раньше 1500 года).

Попадание считается так же, как в попапе истории точки (`hitNear` в
index.html): сама точка либо 3 из 4 соседних в 0.02° - иначе контуры мирового
масштаба «топят» приморские города (Батуми, Владивосток, Хельсинки).

Запуск (из корня репозитория):

    python3 tools/check_expansion.py          # только ошибки + итог
    python3 tools/check_expansion.py --all    # вся таблица
    python3 tools/check_expansion.py --md data/crosscheck/expansion_report.md
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import crosscheck as cc   # noqa: E402  (Map, parse_date, hits - оттуда)

ROOT = cc.ROOT
CSV = os.path.join(cc.CC, 'expansion.csv')
NEAR = 0.02          # тот же допуск на береговую линию, что в index.html


def hit_near(lon, lat, fc):
    """Попадание с допуском на береговую линию (как hitNear в index.html)."""
    if cc.hits(lon, lat, fc):
        return True
    n = 0
    for dx, dy in ((NEAR, 0), (-NEAR, 0), (0, NEAR), (0, -NEAR)):
        if cc.hits(lon + dx, lat + dy, fc):
            n += 1
    return n >= 3


def ask(mp, row):
    """-> (наш ответ 'yes'|'no'|None, ключ среза)."""
    day, _ = cc.parse_date(row['date'])
    key = mp.core_slice(day)
    if not key:
        return None, '-'
    fc = mp.geo(os.path.join('years', key + '.geojson'))
    return ('yes' if hit_near(float(row['lon']), float(row['lat']), fc)
            else 'no'), key


def run(rows, mp):
    out = []
    for r in rows:
        got, key = ask(mp, r)
        exp = r['expect_in_empire'].strip()
        if got is None:
            verdict = 'нет-среза'
        elif got == exp:
            verdict = 'ok'
        else:
            verdict = 'ОШИБКА'
        out.append(dict(acquisition=r['acquisition'], date=r['date'],
                        act=r['act'], city=r['city'], expected=exp,
                        got=got or '-', slice=key, verdict=verdict,
                        source=r['source'], note=r['note']))
    return out


def table(res, only_bad):
    rows = [r for r in res if r['verdict'] != 'ok'] if only_bad else res
    if rows:
        w = max(len(r['acquisition']) for r in rows)
        wc = max(len(r['city']) for r in rows)
        print(f'{"приобретение".ljust(w)}  {"дата".ljust(10)}  '
              f'{"город".ljust(wc)}  {"ждём".ljust(5)}  {"карта".ljust(5)}  '
              f'вердикт / срез')
        for r in rows:
            print(f'{r["acquisition"].ljust(w)}  {r["date"].ljust(10)}  '
                  f'{r["city"].ljust(wc)}  {r["expected"].ljust(5)}  '
                  f'{r["got"].ljust(5)}  {r["verdict"]} / {r["slice"]}')
    counts = {}
    for r in res:
        counts[r['verdict']] = counts.get(r['verdict'], 0) + 1
    print('итог: ' + ', '.join(f'{k} - {v}' for k, v in sorted(counts.items()))
          + f' (всего {len(res)})')
    return counts


def markdown(res, counts, path):
    lines = ['# Проверка расползания империи по приобретениям', '',
             'Собрано `tools/check_expansion.py` из '
             '`data/crosscheck/expansion.csv`.',
             'Файл перезаписывается при каждом прогоне - правки вносить в CSV.',
             '',
             'Метод: point-in-polygon по срезу ядра, действующему на дату '
             'строки, с допуском на',
             'береговую линию (0.02°, 3 из 4 соседних точек - как `hitNear` в '
             'index.html).',
             '`yes` - срез обязан накрыть город, `no` - не должен.', '',
             'Итог: ' + ', '.join(f'{k} - {v}' for k, v in sorted(counts.items()))
             + f' (всего {len(res)})',
             '',
             '| приобретение | дата | акт | город | ждём | карта | вердикт | '
             'срез | источник |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for r in res:
        lines.append(f'| {r["acquisition"]} | {r["date"]} | '
                     f'{r["act"].replace("|", "/")} | {r["city"]} | '
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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--csv', default=CSV)
    ap.add_argument('--all', action='store_true', help='печатать всю таблицу')
    ap.add_argument('--md', default=os.path.join(cc.CC, 'expansion_report.md'))
    args = ap.parse_args()

    with open(args.csv, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    res = run(rows, cc.Map())
    counts = table(res, only_bad=not args.all)
    markdown(res, counts, args.md)
    return 1 if counts.get('ОШИБКА') else 0


if __name__ == '__main__':
    sys.exit(main())
