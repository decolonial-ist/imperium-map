#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка: цепочка сборки прогнана в каноническом порядке.

ЗАЧЕМ (29.08.2026, вопрос ревью «как застраховать порядок дёшево»). Двадцать
сборщиков пишут в общий data/manifest.json и перезаписывают срезы друг друга:
build_ww2 переписывает 1941-1945, позднее окно build_expansion патчит их
следом. Порядок запуска записан в HANDOFF.md, но до сих пор ничем не
проверялся: запустишь не в том порядке - получишь тихо неверную карту.

Теперь каждый сборщик цепочки в конце main() пишет штамп
(geoclean.write_stamp) в data/build_stamps.json; эта проверка сверяет времена
штампов с каноном. Времена обязаны идти неубывающе в порядке канона.

Запуск: .venv/bin/python tools/check_build_order.py
Падает с кодом 1, если штампов нет, не хватает или порядок нарушен.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAMPS = os.path.join(ROOT, 'data', 'build_stamps.json')

# порядок = HANDOFF.md, раздел «Порядок пересборки - ОБЯЗАТЕЛЕН»
# 'lite' в конце: облегчённые срезы для телефона (tools/build_lite.py)
# производны от готовых срезов и пересобираются последними
CANON = ['expansion', 'zones_1917_1921', 'pact_1939', 'ww2',
         'expansion-late', 'losses', 'ostrogs', 'lite']


def main():
    if not os.path.exists(STAMPS):
        print('!! штампов нет (data/build_stamps.json): прогони пересборку '
              'по шагу в порядке из HANDOFF.md - каждый сборщик оставит штамп')
        return 1
    with open(STAMPS, encoding='utf-8') as f:
        stamps = json.load(f)
    missing = [n for n in CANON if n not in stamps]
    if missing:
        print(f'!! не хватает штампов: {", ".join(missing)} - эти шаги не '
              f'прогонялись (или прогонялись до появления штампов 29.08.2026)')
        return 1
    bad = []
    for a, b in zip(CANON, CANON[1:]):
        if stamps[a] > stamps[b]:
            bad.append(f'{b} ({stamps[b]}) прогнан РАНЬШЕ, чем {a} '
                       f'({stamps[a]})')
    for line in bad:
        print('!! ' + line)
    if bad:
        print('порядок канона: ' + ' -> '.join(CANON))
        return 1
    print(f'итог: ok - цепочка из {len(CANON)} шагов прогнана в каноне, '
          f'последний шаг {CANON[-1]} в {stamps[CANON[-1]]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
