#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Выгрузка кампаний доменов из мастер-таблицы DECOLONIAL.IST в data/campaigns.

ЗАЧЕМ. Карта красит территорию имперской по дате ПРАВОВОГО АКТА. Про то, когда
империя получила там реальный контроль, знает не карта, а наша собственная база
кампаний: домен nohchi описывает Кавказскую войну год за годом, домен ukraina -
войны за Гетманщину. Чтобы билдер срезов (tools/build_expansion.py) мог
опираться на эту базу, а не на выдумку, кампании выгружаются сюда как есть.

ЧТО ДЕЛАЕТ. Читает лист кампаний домена ЧИТАЮЩИМ ключом (reader-key.json в
~/tmp/colonial-sheet-automation, ничего не пишет) и складывает в
`data/campaigns/<домен>.json`: ID, название, окно (first seen / last seen),
описание, ссылка. Смысл не правится: тексты и даты кладутся байт-в-байт, только
даты дополнительно разбираются в ISO для машинного сравнения.

Колонки региона в листе НЕТ - привязка кампании к территории живёт не здесь, а
в курируемой таблице сопротивления (tools/build_expansion.py, список RESIST).

Запуск (из корня репозитория):

    python3 tools/build_campaigns.py                 # оба домена
    python3 tools/build_campaigns.py --domain nohchi

ЧИТАЕТ ТОЛЬКО. В таблицу этот скрипт не пишет и писать не может: у ключа
scope spreadsheets.readonly.
"""
import argparse
import json
import os
import re
import subprocess
import sys

import geoclean as gc
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'campaigns')
CSA = os.path.expanduser('~/tmp/colonial-sheet-automation')

SHEETS = {'nohchi': 'Кампании Нохчи', 'ukraina': 'Кампании Украина'}
TITLES = {'nohchi': 'Нохчи (чеченцы)', 'ukraina': 'Украинцы'}

MONTHS = {'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5,
          'june': 6, 'july': 7, 'august': 8, 'september': 9, 'october': 10,
          'november': 11, 'december': 12}


def iso(s):
    """«01 January 1550» -> «1550-01-01»; непонятное -> None (не выдумываем)."""
    m = re.match(r'^\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{3,4})\s*$', s or '')
    if not m:
        return None
    mon = MONTHS.get(m.group(2).lower())
    if not mon:
        return None
    return date(int(m.group(3)), mon, int(m.group(1))).isoformat()


def read_sheet(domain):
    """TSV листа кампаний читающим ключом (read_table.py --get)."""
    sheet = SHEETS[domain]
    py = os.path.join(CSA, '.venv', 'bin', 'python')
    if not os.path.exists(py):
        py = 'python3'
    cmd = [py, 'read_table.py', '--domain', domain,
           '--get', f'{sheet}!A1:X999']
    r = subprocess.run(cmd, cwd=CSA, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'read_table.py упал ({domain}):\n{r.stderr}')
    # read_table.py --get сам сплющивает переносы строк внутри ячеек, так что
    # строка TSV = строка листа
    return [ln.split('\t') for ln in r.stdout.splitlines()]


def col(header, name):
    norm = [h.strip().lower() for h in header]
    return norm.index(name) if name in norm else None


def build(domain):
    rows = read_sheet(domain)
    if not rows:
        raise SystemExit(f'пустой лист {SHEETS[domain]}')
    hdr = rows[0]
    idx = {k: col(hdr, k) for k in
           ('id', 'name (ru)', 'name (en)', 'description (ru)', 'url',
            'first seen', 'last seen', 'to be published')}
    missing = [k for k, v in idx.items() if v is None]
    if missing:
        raise SystemExit(f'в листе {SHEETS[domain]} нет колонок: {missing}; '
                         'заголовок листа менялся - посмотреть '
                         'read_table.py --inspect')

    def cell(row, key):
        i = idx[key]
        return row[i].strip() if i is not None and len(row) > i else ''

    out = []
    for row in rows[1:]:
        cid = cell(row, 'id')
        if not re.match(r'^C\d+$', cid):
            continue
        name = cell(row, 'name (ru)')
        if not name:
            continue                       # заготовка без названия - пропуск
        f, l = cell(row, 'first seen'), cell(row, 'last seen')
        out.append({
            'id': cid,
            'name': name,
            'name_en': cell(row, 'name (en)'),
            'first_seen': f,
            'last_seen': l,
            'first_seen_iso': iso(f),
            'last_seen_iso': iso(l),
            'to_be_published': cell(row, 'to be published'),
            'url': cell(row, 'url'),
            'description': cell(row, 'description (ru)'),
        })
    doc = {
        'domain': domain,
        'title': TITLES[domain],
        'sheet': SHEETS[domain],
        'exported': date.today().isoformat(),
        'count': len(out),
        'source': 'мастер-таблица DECOLONIAL.IST (лист кампаний домена), '
                  'выгрузка tools/build_campaigns.py читающим ключом '
                  'reader-key.json; тексты и даты не редактируются',
        'note_region': 'колонки региона в листе нет: привязка кампании к '
                       'территории задаётся курируемым списком RESIST в '
                       'tools/build_expansion.py',
        'campaigns': out,
    }
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, domain + '.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(gc.sanitize_obj(doc), fh, ensure_ascii=False, indent=1)
    bad = [c['id'] for c in out if not c['first_seen_iso'] or not c['last_seen_iso']]
    print(f'OK data/campaigns/{domain}.json: кампаний {len(out)}, '
          f'{os.path.getsize(path) // 1024} КБ'
          + (f', без разобранных дат: {", ".join(bad)}' if bad else ''))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--domain', choices=sorted(SHEETS), action='append')
    a = ap.parse_args()
    for dom in (a.domain or sorted(SHEETS)):
        build(dom)
    print('дальше: python3 tools/build_resistance.py')


if __name__ == '__main__':
    main()
