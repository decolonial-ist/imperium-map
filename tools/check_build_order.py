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
# 'lite' почти в конце: облегчённые срезы для телефона (tools/build_lite.py)
# производны от готовых срезов и пересобираются после них. 'start' - самый
# последний (tools/build_start_bundle.py, 15.09.2026): пакет старта склеивает
# манифесты и мелкие файлы, а метка версии данных сбрасывает кэш в браузере
# читателя - оба обязаны собираться после всего остального. 'mid' - средний
# уровень точных срезов (tools/build_lite.py --level mid, этап 4 плана
# 15.09.2026): тоже производный от готовых срезов, его опись едет в пакете
# старта - значит после 'lite' и перед 'start'
# 'clip_foreign' (18.09.2026) - обрезка красного по чужой земле
# (tools/clip_foreign.py). До 18.09 жила вне канона: её прогнали руками 07.09,
# и каждая полная пересборка её смывала - на 1878 году возвращалось 17 509 км²
# красного в Хэйлунцзяне, Норрботтене и Расоне. Идёт последней из тех, кто
# пишет срезы (после позднего окна), и ДО 'ostrogs': точки считают «вокруг
# покраснело» по срезам, и на необрезанных срезах уходили с карты
CANON = ['expansion', 'zones_1917_1921', 'pact_1939', 'ww2',
         'expansion-late', 'clip_foreign', 'losses', 'ostrogs', 'lite', 'mid',
         'start']


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
