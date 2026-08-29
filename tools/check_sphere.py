#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Регрессионный тест слоя советской сферы влияния.

Тот же метод, что в `tools/check_expansion.py` и `tools/check_cities.py`:
курируемая таблица ожиданий + point-in-polygon по тому, что реально лежит в
`data/sphere.geojson`. Падает с кодом 1, если карта врёт.

`data/crosscheck/sphere_checks.csv`:

    place,lat,lon,date,expect,why,source,note

`expect` — либо тип зависимости из закрытого списка (`occupation`, `bloc`,
`client_treaty`, `client_military`, `client_aid`, `intervention`), либо `none`:
на эту дату слой обязан МОЛЧАТЬ про эту точку. Отрицательных проверок в
таблице примерно половина, и держат они три вещи:

  * РАЗРЫВЫ — Каир 15.03.1976 (денонсация договора), Могадишо 14.11.1977
    (высылка советских военных), Тирана 04.12.1961 (разрыв отношений),
    Кабул 17.04.1992 (падение Наджибуллы);
  * СПОРНЫЕ СЛУЧАИ — Пекин, Белград, Хельсинки, Дели, Багдад, Триполи, Алжир,
    Сана, Уагадугу, Ниамей, Хартум, Каракас: они лежат в
    `data/sphere/disputed.csv`, В ПОКАЗ НЕ ИДУТ и обязаны быть чёрными, пока
    куратор не решит иначе. Если кто-то перенесёт строку из disputed в
    registry не подумав — тест это поймает;
  * СТЫК СО СЛОЕМ ВТОРОЙ МИРОВОЙ — Варшава и Лейпциг 01.08.1945: занятую
    Европу до 31.12.1945 включительно ведёт ЯДРО, сфера обязана молчать,
    иначе на стыке будет двойной показ.

Плюс проверки на саму рамку: Москва сферой не красится никогда (это ядро),
Стокгольм и Тегеран — никогда вообще, Инсбрук в 1950 году чёрный, а Вена
красная (советская зона Австрии — восточная треть, а не страна целиком).

Запуск (из корня репозитория):

    python3 tools/check_sphere.py           # только ошибки + итог
    python3 tools/check_sphere.py --all     # вся таблица
    python3 tools/check_sphere.py --md data/crosscheck/sphere_report.md
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import crosscheck as cc          # noqa: E402  (hits — оттуда)
import build_sphere as bs        # noqa: E402  (KINDS — оттуда)

ROOT = cc.ROOT
CSV = os.path.join(cc.CC, 'sphere_checks.csv')
LAYER = os.path.join(ROOT, 'data', 'sphere.geojson')
NEAR = 0.02        # тот же допуск на береговую линию, что в index.html и попапе


def load():
    with open(LAYER, encoding='utf-8') as f:
        return json.load(f)


def active(fc, date):
    """Фичи слоя, действующие на дату (по под-окну контура gfrom/gto)."""
    out = []
    for f in fc['features']:
        p = f['properties']
        a = p.get('gfrom') or p['from']
        b = p.get('gto') or p['to']
        if date < a:
            continue
        if b and date > b:
            continue
        out.append(f)
    return {'type': 'FeatureCollection', 'features': out}


def hit_near(lon, lat, fc):
    """Попадание с допуском на береговую линию (как hitNear в index.html)."""
    if cc.hits(lon, lat, fc):
        return True
    n = 0
    for dx, dy in ((NEAR, 0), (-NEAR, 0), (0, NEAR), (0, -NEAR)):
        if cc.hits(lon + dx, lat + dy, fc):
            n += 1
    return n >= 3


def ask(fc, row):
    """-> (множество типов зависимости в точке, список подписей эпизодов)."""
    lon, lat = float(row['lon']), float(row['lat'])
    act = active(fc, row['date'])
    kinds, eps = set(), []
    for f in act['features']:
        one = {'type': 'FeatureCollection', 'features': [f]}
        if hit_near(lon, lat, one):
            p = f['properties']
            kinds.add(p['kind'])
            label = f"{p['name_ru']} · {p['kind']} · {p['from']}..{p['to'] or '…'}"
            if label not in eps:
                eps.append(label)
    return kinds, eps


def run(rows, fc):
    out = []
    for r in rows:
        exp = r['expect'].strip()
        if exp != 'none' and exp not in bs.KINDS:
            raise SystemExit(f'{r["place"]} {r["date"]}: expect «{exp}» не из '
                             f'списка {sorted(bs.KINDS)} и не none')
        kinds, eps = ask(fc, r)
        got = ', '.join(sorted(kinds)) if kinds else 'none'
        ok = (not kinds) if exp == 'none' else (exp in kinds)
        out.append(dict(place=r['place'], date=r['date'], expected=exp,
                        got=got, eps='; '.join(eps),
                        verdict='ok' if ok else 'ОШИБКА',
                        why=r['why'], source=r['source'], note=r['note']))
    return out


def table(res, only_bad):
    rows = [r for r in res if r['verdict'] != 'ok'] if only_bad else res
    if rows:
        w = max(len(r['place']) for r in rows)
        wg = max(max(len(r['got']) for r in rows), 15)
        print(f'{"точка".ljust(w)}  {"дата".ljust(10)}  {"ждём".ljust(15)}  '
              f'{"карта".ljust(wg)}  вердикт')
        for r in rows:
            print(f'{r["place"].ljust(w)}  {r["date"].ljust(10)}  '
                  f'{r["expected"].ljust(15)}  {r["got"].ljust(wg)}  '
                  f'{r["verdict"]}')
    counts = {}
    for r in res:
        counts[r['verdict']] = counts.get(r['verdict'], 0) + 1
    print('итог: ' + ', '.join(f'{k} - {v}' for k, v in sorted(counts.items()))
          + f' (всего {len(res)})')
    return counts


def markdown(res, counts, path):
    lines = ['# Проверка слоя советской сферы влияния', '',
             'Собрано `tools/check_sphere.py` из '
             '`data/crosscheck/sphere_checks.csv`.',
             'Файл перезаписывается при каждом прогоне — правки вносить в CSV.',
             '',
             'Метод: point-in-polygon по `data/sphere.geojson` (курируемая '
             'таблица `data/sphere/registry.csv`,',
             'билдер `tools/build_sphere.py`) с допуском на береговую линию '
             '0.02°, как в попапе карты.',
             '`none` — на эту дату слой обязан молчать про точку.', '',
             'Итог: ' + ', '.join(f'{k} — {v}' for k, v in sorted(counts.items()))
             + f' (всего {len(res)})', '',
             '| точка | дата | ждём | карта | вердикт | эпизоды в точке | почему проверяем |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for r in res:
        lines.append(f'| {r["place"]} | {r["date"]} | {r["expected"]} | '
                     f'{r["got"]} | {r["verdict"]} | '
                     f'{r["eps"].replace("|", "/") or "—"} | '
                     f'{r["why"].replace("|", "/")} |')
    lines += ['', '## Примечания к строкам', '']
    for r in res:
        if r['note']:
            lines.append(f'- **{r["place"]}, {r["date"]}** — '
                         f'{r["note"].replace("|", "/")}')
    lines.append('')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'OK {os.path.relpath(path, ROOT)}')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--csv', default=CSV)
    ap.add_argument('--all', action='store_true', help='печатать всю таблицу')
    ap.add_argument('--md', default=os.path.join(cc.CC, 'sphere_report.md'))
    args = ap.parse_args()

    with open(args.csv, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    res = run(rows, load())
    counts = table(res, only_bad=not args.all)
    markdown(res, counts, args.md)
    return 1 if counts.get('ОШИБКА') else 0


if __name__ == '__main__':
    sys.exit(main())
