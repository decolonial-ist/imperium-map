#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ручные шаги встройки народа: data/domains/<id>_steps.json из TSV «дата <таб> подпись».

ЗАЧЕМ. Куратор 01.11.2026: шаги для Украины и Ичкерии отобрать вручную, как для
империи (tools/build_empire_embed.py), каждый со своей подписью. Автоматические
остановки <id>_stops.json остаются: на них собираются пакеты плотных периодов.
Файл шагов читает tools/build_domain_bundle.py, только для общего пакета народа.

Запуск:
    .venv/bin/python tools/build_steps_embed.py ukrainians steps.tsv
    .venv/bin/python3 tools/build_domain_bundle.py --domain ukrainians
"""
import json
import os
import sys
from datetime import date, timedelta

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
DATA = os.path.join(ROOT, 'data')


def main():
    dom, tsv = sys.argv[1], sys.argv[2]
    keys = set(map(str, json.load(open(os.path.join(DATA, 'manifest.json')))['years']))
    auto = {s['d'] for s in json.load(open(os.path.join(DATA, 'domains', dom + '_stops.json')))['stops']}
    # шаг может стоять и на вырезе удержания: у него своя дата, среза на неё нет
    cuts = json.load(open(os.path.join(DATA, 'resistance', 'cuts.geojson')))['features']
    for f in cuts:
        end = date.fromisoformat(f['properties']['hold_to']) + timedelta(days=1)
        auto |= {f['properties']['hold_from'], end.isoformat()}
    stops = []
    for line in open(tsv, encoding='utf-8'):
        line = line.rstrip('\n')
        if not line.strip() or line.startswith('#'):
            continue
        d, why = line.split('\t')
        if d not in keys and d not in auto:
            sys.exit('нет такой даты ни в срезах, ни в остановках: ' + d)
        stops.append({'d': d, 'why': why, 'w': 1.0})
    if [s['d'] for s in stops] != sorted((s['d'] for s in stops), key=lambda x: x if len(x) > 4 else x + '-01-01'):
        sys.exit('шаги не по порядку дат')
    with open(os.path.join(DATA, 'domains', dom + '_steps.json'), 'w', encoding='utf-8') as f:
        json.dump({'domain': dom, 'note': 'шаги подобраны руками (tools/build_steps_embed.py)', 'stops': stops},
                  f, ensure_ascii=False, indent=1)
    print(dom, 'шагов', len(stops))


if __name__ == '__main__':
    main()
