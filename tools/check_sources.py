#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тождество источника: тот ли это файл, что записан в реестре.

ЗАЧЕМ (01.09.2026, идея архивного чата). У карты девять чекеров на геометрию и
даты и ни одного на источники. А ошибка «файл открывается, читается, выглядит
как источник - и это НЕ ТОТ источник» проверкой «файл на месте и непустой» не
ловится вовсе.

Повод из своей же работы: том, подписанный на archive.org как «Т. 11 : 1891»,
внутри оказался томом XIX за 1899 год. Я искал в нём рескрипт 17.03.1891, не
нашёл и записал в разбор «в своде законов его нет». Написал бы и в витрину, если
бы не наткнулся на настоящий текст в другом издании. В тот же день того же
класса ошибка нашлась в датах кубанских крепостей: 1794 год оказался годом
казачьих станиц, а не постройки укреплений.

ЧТО ДЕЛАЕТ. У записей реестра `data/sources/registry.json`, где есть поле
`local` (путь к распознанному тексту относительно ~/tmp), читает первые 3 КБ -
титульный лист - и проверяет, что там встречаются все признаки из поля `expect`.

СРАВНЕНИЕ УСТОЙЧИВО К OCR. Титулы XIX века распознаются грязно: «т о м ъ IX»,
«РОСС1ЙСКОЙ ИМПЕР 1 И», «Оть № 46610—47557» (последняя цифра переврана).
Поэтому обе стороны нормализуются: убираются пробелы и знаки, ять и «i»
сводятся к «е» и «i», единица и «l» - туда же (OCR путает 1, i и l постоянно:
1830 в титулах читается как «i830»).

Запуск: .venv/bin/python tools/check_sources.py
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, 'data', 'sources', 'registry.json')
BASE = os.path.expanduser('~/tmp')
HEAD = 3000                      # титульный лист укладывается в три килобайта

_SUB = [('ѣ', 'е'), ('ё', 'е'), ('і', 'i'), ('1', 'i'), ('l', 'i'),
        ('|', 'i'), ('ъ', ''), ('ь', '')]


def norm(s):
    s = s.lower()
    for a, b in _SUB:
        s = s.replace(a, b)
    return re.sub(r'[^0-9a-zа-я]', '', s)


def main():
    with open(REG, encoding='utf-8') as f:
        items = json.load(f)['items']
    checked = bad = skipped = 0
    lines = []
    for it in items:
        loc = it.get('local')
        if not loc:
            skipped += 1
            continue
        path = os.path.join(BASE, loc)
        if not os.path.exists(path):
            bad += 1
            lines.append('!! %s: ФАЙЛА НЕТ - %s' % (it['slug'], loc))
            continue
        with open(path, encoding='utf-8', errors='replace') as f:
            head = norm(f.read(HEAD))
        miss = [e for e in it.get('expect', []) if norm(e) not in head]
        checked += 1
        if miss:
            bad += 1
            lines.append('!! %s: на титуле НЕ НАЙДЕНО %s (файл %s)'
                         % (it['slug'], ', '.join('«%s»' % m for m in miss),
                            loc))
    for l in lines:
        print(l)
    if bad:
        print('итог: НЕ СХОДИТСЯ %d из %d — файл не тот, что записан в реестре, '
              'либо признак задан неверно' % (bad, checked))
        return 1
    print('итог: ok - тождество источника сошлось у всех %d томов с локальным '
          'файлом (без файла %d записей)' % (checked, skipped))
    return 0


if __name__ == '__main__':
    sys.exit(main())
