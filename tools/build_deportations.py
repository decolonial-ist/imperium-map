#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Слой массовых советских депортаций, 1935-1951: 28 позиций атласа УІФ.

ЗАЧЕМ. Атлас отдаёт депортациям отдельный раздел (48) с 28 датированными
позициями, у нашей карты этого сюжета не было вовсе
(data/crosscheck/atlas_sync.md, «Что делать дальше», п. 6).

ФОРМА ПОКАЗА (задача куратора 26.08.2026). Депортация - это НЕ про контроль
территории: земля остаётся за империей, с неё убирают людей. Значит, в основную
заливку сюжет не идёт ни в каком виде - иначе показ перестанет быть бинарным.
Депортации живут:
  * отдельным слоем-переключателем (кнопка рядом со спутником), по умолчанию
    ВЫКЛЮЧЕННЫМ;
  * строкой в попапе истории точки - «с этой земли в такой-то день вывезли
    такой-то народ, по такому-то постановлению».

ГЕОМЕТРИЯ - откуда вывозили, а не куда. Только машиночитаемые контуры:
  * heiDATA-1926 (Transcultural Empire, CC-BY 4.0) - там, где у народа была
    своя автономия: Крымская АССР, АССР немцев Поволжья, Калмыцкая,
    Карачаевская, Кабардино-Балкарская, Чеченская и Ингушская автономные
    области;
  * Natural Earth admin-1 - для всего остального (Западная Украина, Западная
    Беларусь, Прибалтика, Молдавия, Мурманская область, Дальний Восток,
    Самцхе-Джавахети, Калининградская область).
Всё помечено approximate: контур автономии 1926 года и современная область -
это «примерно эта земля», а не граница операции.

Вход:  data/deportations/registry.csv (курируется руками; 30 строк на 28
       позиций атласа - у двух позиций по две волны)
Выход: data/deportations/deportations.geojson, data/deportations/report.md

Запуск:  .venv/bin/python tools/build_deportations.py
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
REG = os.path.join(DATA, 'deportations', 'registry.csv')
OUT = os.path.join(DATA, 'deportations', 'deportations.geojson')
REPORT = os.path.join(DATA, 'deportations', 'report.md')
SIMPLIFY = 0.01

WEST_UA = ("ne:Ukraine:L'viv|Ternopil'|Ivano-Frankivs'k|Volyn|Rivne")
WEST_BY = 'ne:Belarus:Brest|Grodno'
BALTICS = 'ne:Estonia:*;ne:Latvia:*;ne:Lithuania:*'
MOLDOVA = 'ne:Moldova:*;ne:Ukraine:Chernivtsi|Odessa'

# ключ from_territory -> спецификация геометрии (разбирается resolve_geo)
TERRITORIES = {
    'ingermanland': 'ne:Russia:Leningrad|City of St. Petersburg',
    'west_ukraine': WEST_UA,
    'west_belarus': WEST_BY,
    'west_ukraine_belarus': WEST_UA + ';' + WEST_BY,
    'far_east': "ne:Russia:Primor'ye|Khabarovsk",
    'murmansk': 'ne:Russia:Murmansk',
    'moldova': MOLDOVA,
    'estonia': 'ne:Estonia:*',
    'latvia': 'ne:Latvia:*',
    'lithuania': 'ne:Lithuania:*',
    'baltics': BALTICS,
    'baltics_west_ussr': BALTICS + ';' + WEST_UA + ';' + WEST_BY + ';' + MOLDOVA,
    'volga_germans': 'heidata:Volga German ASSR',
    'crimea': 'heidata:Crimean ASSR',
    'karachay': 'heidata:Karachai AR',
    'kalmyk': 'heidata:Kalmyk AR',
    'chechen_ingush': 'heidata:Chechen AR|Ingush AR|AC Grozny',
    'balkar': 'heidata:Kabardino-Balkar AR',
    'meskheti': 'ne:Georgia:Samtskhe-Javakheti',
    'caucasus_coast': ('ne:Russia:Krasnodar;'
                       'ne:Georgia:Abkhazia|Samegrelo-Zemo Svaneti|Ajaria'),
    'east_prussia': 'ne:Russia:Kaliningrad',
}


def main():
    if not os.path.exists(REG):
        raise SystemExit(f'нет таблицы {REG}')
    with open(REG, encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f)
                if r.get('people') and not r['people'].startswith('#')]
    feats, report, bad = [], [], []
    for i, r in enumerate(rows, 2):
        key = r['from_territory'].strip()
        if key not in TERRITORIES:
            bad.append(f'строка {i}: неизвестная территория «{key}», есть '
                       f'{sorted(TERRITORIES)}')
            continue
        if not r.get('source', '').strip():
            bad.append(f'строка {i}: пустой источник')
        if not r.get('decree', '').strip():
            bad.append(f'строка {i}: пустой акт - депортация без постановления '
                       f'в реестр не заводится')
        if not r.get('date', '').strip():
            bad.append(f'строка {i}: пустая дата')
            continue
        geom = resolve_geo(TERRITORIES[key], f'строка {i} ({key})')
        feats.append({'type': 'Feature', 'properties': {
            'people': r['people'].strip(),
            'people_ru': r['people_ru'].strip(),
            'date': _norm(r['date']),
            'from_territory': key,
            'to_territory': r.get('to_territory', '').strip(),
            'decree': r.get('decree', '').strip(),
            'people_count': r.get('people_count', '').strip(),
            'source': r.get('source', '').strip(),
            'confidence': r.get('confidence', '').strip(),
            'note': r.get('note', '').strip(),
            'geometry_source': TERRITORIES[key],
            'approximate': True,
        }, 'geometry': _dump(geom.simplify(SIMPLIFY, preserve_topology=True))})
        report.append((_norm(r['date']), r['people_ru'].strip(),
                       r.get('people_count', '').strip(),
                       r.get('decree', '').strip(),
                       r.get('to_territory', '').strip()))
    if bad:
        print('ОШИБКИ ТАБЛИЦЫ:')
        for b in bad:
            print(' ', b)
        sys.exit(1)
    feats.sort(key=lambda f: f['properties']['date'])
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj({'type': 'FeatureCollection',
                   'note': 'массовые советские депортации 1935-1951, '
                           'tools/build_deportations.py; слой-переключатель, '
                           'по умолчанию выключен',
                   'features': feats}), f, ensure_ascii=False,
                  separators=(',', ':'))
    report.sort()
    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write('# Массовые советские депортации: что показывает карта\n\n')
        f.write('Собрано `tools/build_deportations.py` из '
                '`data/deportations/registry.csv`. Геометрия - откуда вывозили; '
                'в основную заливку слой не идёт (депортация не меняет того, '
                'кто контролирует землю), показ - отдельным переключателем и '
                'строкой в попапе истории точки.\n\n')
        f.write('| дата | кого | сколько | акт | куда |\n|---|---|---|---|---|\n')
        for row in report:
            f.write('| ' + ' | '.join(x.replace('|', '/') for x in row) + ' |\n')
    print(f'{OUT}: {len(feats)} депортаций, '
          f'{len({f["properties"]["from_territory"] for f in feats})} территорий')
    print(f'{REPORT}: таблица для куратора')


if __name__ == '__main__':
    main()
