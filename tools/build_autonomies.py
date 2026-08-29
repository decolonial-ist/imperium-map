#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Слой ликвидированных автономий 1938-1945 и восстановленных в 1957 году.

ЗАЧЕМ. Атлас УІФ (розд. 50) перечисляет девять ликвидированных национальных
образований; семь из них - это те самые республики, которые упразднили вместе с
депортациями народов (пп. 3-9 легенды). У нашей карты сюжета не было
(data/crosscheck/atlas_sync.md, «Что делать дальше», п. 6), а заготовка слоя
народов (data/peoples/, tools/build_peoples.py) дат упразднения не знала: поле
`absorbed` там стоит пустым, и записка RESEARCH.md прямо говорит, что даты
заводит куратор.

Здесь эти даты заведены - с номерами указов и с контурами из того же
машиночитаемого сырья, что уже разобрано в RESEARCH.md (heiDATA-1926).

ФОРМА ПОКАЗА (задача куратора 26.08.2026). В основную заливку слой не идёт:
упразднение автономии не меняет того, кто контролирует землю, - земля как была
за империей, так и осталась, у народа отняли не территорию, а субъектность.
Поэтому слой живёт отдельным переключателем (по умолчанию выключенным) и
строкой в попапе истории точки.

ГРАНИЦЫ ЧЕСТНОСТИ. Контуры - heiDATA-1926, то есть автономии в границах
1926 года, а не 1940-х: Калмыцкая автономная область, а не Калмыцкая АССР
1935-1943 гг.; Чеченская и Ингушская автономные области, а не Чечено-Ингушская
АССР 1936-1944 гг. Точные контуры конца 1930-х требуют ручной оцифровки листов
БСАМ 1937-39 - задача записана в data/peoples/RESEARCH.md и не сделана.
У Кизлярского округа Дагестанской АССР машиночитаемого контура нет нигде, и
рисовать его от руки мы не будем: строка в реестре есть, фичи нет.

Вход:  data/peoples/abolished.csv (7 строк, курируется руками)
Выход: data/peoples/abolished.geojson, data/peoples/abolished_report.md

Запуск:  .venv/bin/python tools/build_autonomies.py
Проверка: .venv/bin/python tools/check_resistance.py
"""
import csv
import json
import os
import sys

import geoclean as gc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_uprisings import _dump, _norm, resolve_geo   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
REG = os.path.join(DATA, 'peoples', 'abolished.csv')
OUT = os.path.join(DATA, 'peoples', 'abolished.geojson')
REPORT = os.path.join(DATA, 'peoples', 'abolished_report.md')
SIMPLIFY = 0.005


def main():
    if not os.path.exists(REG):
        raise SystemExit(f'нет таблицы {REG}')
    with open(REG, encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f)
                if r.get('slug') and not r['slug'].startswith('#')]
    feats, report, bad, nogeo = [], [], [], []
    for i, r in enumerate(rows, 2):
        slug = r['slug'].strip()
        if not r.get('abolished', '').strip():
            bad.append(f'строка {i} ({slug}): пустая дата упразднения')
            continue
        if not r.get('decree_abolished', '').strip():
            bad.append(f'строка {i} ({slug}): упразднение без акта в реестр '
                       f'не заводится')
        if not r.get('source', '').strip():
            bad.append(f'строка {i} ({slug}): пустой источник')
        ab = _norm(r['abolished'])
        re_ = _norm(r['restored']) if r.get('restored', '').strip() else ''
        if re_ and re_ < ab:
            bad.append(f'строка {i} ({slug}): восстановление раньше упразднения')
        props = {
            'slug': slug, 'name_ru': r['name_ru'].strip(),
            'people': r.get('people', '').strip(),
            'abolished': ab,
            'decree_abolished': r.get('decree_abolished', '').strip(),
            'restored': re_,
            'decree_restored': r.get('decree_restored', '').strip(),
            'source': r.get('source', '').strip(),
            'confidence': r.get('confidence', '').strip(),
            'note': r.get('note', '').strip(),
            'geometry_source': r.get('geo', '').strip(),
            'approximate': True,
        }
        geom = resolve_geo(r.get('geo'), f'строка {i} ({slug})')
        if geom is None:
            nogeo.append(slug)
        else:
            feats.append({'type': 'Feature', 'properties': props,
                          'geometry': _dump(geom.simplify(
                              SIMPLIFY, preserve_topology=True))})
        report.append((ab, re_ or '—', r['name_ru'].strip(),
                       r.get('people', '').strip(),
                       r.get('decree_abolished', '').strip()))
    if bad:
        print('ОШИБКИ ТАБЛИЦЫ:')
        for b in bad:
            print(' ', b)
        sys.exit(1)
    feats.sort(key=lambda f: f['properties']['abolished'])
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj({'type': 'FeatureCollection',
                   'note': 'ликвидированные автономии 1938-1945 и '
                           'восстановленные в 1957, tools/build_autonomies.py; '
                           'слой-переключатель, по умолчанию выключен',
                   'features': feats}), f, ensure_ascii=False,
                  separators=(',', ':'))
    report.sort()
    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write('# Ликвидированные автономии: что показывает карта\n\n')
        f.write('Собрано `tools/build_autonomies.py` из '
                '`data/peoples/abolished.csv`. В основную заливку слой не идёт: '
                'упразднение автономии не меняет того, кто контролирует землю. '
                'Контуры - heiDATA-1926, то есть предшественники республик '
                '1940-х годов; оговорки - в `data/peoples/RESEARCH.md`.\n\n')
        f.write('| упразднена | восстановлена | образование | народ | акт |\n')
        f.write('|---|---|---|---|---|\n')
        for row in report:
            f.write('| ' + ' | '.join(x.replace('|', '/') for x in row) + ' |\n')
    print(f'{OUT}: {len(feats)} контуров из {len(rows)} строк реестра')
    if nogeo:
        print(f'  БЕЗ ГЕОМЕТРИИ (машиночитаемого контура нет): {nogeo}')
    print(f'{REPORT}: таблица для куратора')


if __name__ == '__main__':
    main()
