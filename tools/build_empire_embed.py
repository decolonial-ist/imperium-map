#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Встраиваемая карта «яркие шаги империи» для главной страницы базы знаний.

ЗАЧЕМ. Задача куратора 28.09.2026: на главной базы знаний - 4-10 моментов
истории империи, самые малые и самые большие её состояния, с железным
фактажом («лучше 5 хороших, чем 10 притянутых»). Розыск и выбор шагов -
~/tmp/MAP-MATERIALS/KB_STEPS_2026-09-28.md; площади всех срезов -
~/tmp/WORKFILES/kb-steps/areas_1010/.

Встройка - тот же режим, что у народов (index.html?embed=empire): домен
data/domains/empire.json, шаги ползунка data/domains/empire_stops.json,
пакет data/domains/empire_bundle.json (tools/build_domain_bundle.py). Отличия
от народа:
- шаги подобраны руками (STEPS ниже), а не собраны из изменений внутри рамки:
  build_domain_stops.py и build_domain_labels.py этот домен пропускают
  (manual_stops);
- рамка - вся империя на всех шагах, через 180-й меридиан (Чукотка);
- к подписи шага дописывается площадь красного на срезе этой даты (мера
  Ламберта, R=6371.0072 км, как в розыске).

Запуск (после пересборки срезов):
    .venv/bin/python tools/build_empire_embed.py
"""
import json
import math
import os
import sys

import numpy as np
from shapely.geometry import box, mapping, shape
from shapely.ops import transform, unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.normpath(os.path.join(HERE, '..'))
DATA = os.path.join(ROOT, 'data')
DOM = os.path.join(DATA, 'domains')
import build_domains as bd          # noqa: E402
import build_domain_bundle as bb    # noqa: E402

R = 6371.0072

# Шаги главной. d - ключ среза (дата шага), why - подпись (без площади: её
# дописывает сборка). Редакция 2 (10.10.2026, после розыска пруфов
# WORKFILES/kb-steps/proofs_1010): «Ясно, понятно» и «Пиши, сокращай» трижды,
# журнал - WORKFILES/kb-steps/captions_journal_v2.md. Порядок - хронологический.
STEPS = [
    ('1462-04-05', 'Московский князь Василий II, умерший 5 апреля 1462 года, перечислил в завещании '
                   'свои земли. Младшие сыновья обязаны давать старшему, Ивану, дань для ханов Орды. '
                   'Рязанью правят московские наместники, Новгород и Тверь ещё не захвачены.'),
    ('1650', 'В 1639 году отряд томского казака Москвитина достиг Охотского моря на Тихом океане. '
             'Империя управляет землёй на западе Сибири до Енисея, на реке Ангаре и вокруг Якутска. '
             'Восточнее стоят отдельные крепости с гарнизонами.'),
    ('1900-12-15', 'Наибольшее состояние империи до 1917 года. Летом и осенью 1900 года российские '
                   'войска захватили Маньчжурию на северо-востоке Китая. В войне 1904-1905 годов '
                   'Япония отбила юг Маньчжурии. Россия вывела войска с севера к 15 апреля 1907 года, '
                   'но оставила охрану построенной ею железной дороги.'),
    ('1918-08-15', 'Империя меньше, чем в любой год после 1822-го. Войска Германии и Австро-Венгрии '
                   'держат Польшу, Украину, страны Балтии, большую часть Беларуси, запад Псковщины, Крым, '
                   'Ростов и Таганрог с округой. Румыния присоединила Бессарабию, почти всю нынешнюю '
                   'Молдову. Финляндия, Грузия, Армения и Азербайджан объявили независимость. На западе '
                   'нынешнего Казахстана правит Алаш-Орда, правительство Казахов. Империя ещё не управляет '
                   'землёй на Таймыре, Ямале, в землях Эвенков, на Чукотке, на севере Камчатки и на '
                   'Охотском берегу.'),
    ('1945-09-03', 'Наибольшее состояние империи за всю историю. Советские войска держат восток '
                   'Германии и Австрии, Польшу, Чехословакию без запада Чехии, Венгрию, Румынию и '
                   'Болгарию. В Скандинавии и Финляндии - датский остров Борнхольм, норвежский город '
                   'Киркенес с округой и полуостров Порккала у Хельсинки. В Азии - Монголию, север Ирана, '
                   'Маньчжурию, восток китайской Внутренней Монголии, север Кореи, Южный Сахалин и Курилы.'),
    ('1991-12-26', '6 сентября 1991 года чеченцы на митингах в Грозном заставили местный парламент, '
                   'подчинённый Москве, распустить себя. Этот день празднуют как День независимости '
                   'Ичкерии. 27 октября чеченцы избрали президентом Джохара Дудаева. 26 декабря СССР '
                   'прекратил существование. К этому дню о выходе из союза объявили 14 из 15 '
                   'республик, все, кроме России.'),
]


def km2(g):
    f = lambda x, y, z=None: (R * np.radians(np.asarray(x, float)),   # noqa: E731
                              R * np.sin(np.radians(np.asarray(y, float))))
    return transform(f, g).area


def slice_geom(key):
    fc = json.load(open(os.path.join(DATA, 'years', key + '.geojson'), encoding='utf-8'))
    return unary_union([shape(f['geometry']) for f in fc['features'] if f.get('geometry')])


def east_shift(g):
    """Куски западнее -100° (Чукотка за 180-м меридианом) - в долготы > 180."""
    parts = list(g.geoms) if g.geom_type == 'MultiPolygon' else [g]
    out = []
    for p in parts:
        if p.bounds[2] < -100:
            p = transform(lambda x, y, z=None: (np.asarray(x) + 360, y), p)
        out.append(p)
    return unary_union(out)


def main():
    keys = set(json.load(open(os.path.join(DATA, 'manifest.json')))['years'])
    miss = [d for d, _ in STEPS if d not in keys]
    if miss:
        sys.exit('нет срезов: ' + ', '.join(miss))
    stops, ext = [], []
    for d, why in STEPS:
        g = slice_geom(d)
        a = km2(g) / 1e6
        stops.append({'d': d, 'why': f'{why} Площадь - {a:.2f} млн км².'.replace(f'{a:.2f}', f'{a:.2f}'.replace('.', ',')),
                      'w': 1.0, 'km2': round(km2(g))})
        ext.append(east_shift(g))
        print(f'{d:12s} {a:6.3f} млн км²  {why}')
    whole = unary_union(ext)
    bbox = [round(v, 4) for v in whole.bounds]
    frame = bd.pad_bbox(bbox, 0.03)
    center, zoom = bd.camera(frame)
    dom = {
        'id': 'empire',
        'title': 'Российская империя',
        'matrix': '/',
        'campaigns': None,
        'frame_source': 'объединение красного на срезах шагов (tools/build_empire_embed.py)',
        'bbox_geom': bbox,
        'bbox': frame,
        'soft': 0.1,
        'stops_buffer_deg': bd.STOPS_BUF,
        'center': center,
        'zoom': zoom,
        'min_zoom': round(zoom - 0.7, 2),
        'time': [STEPS[0][0], STEPS[-1][0]],
        'manual_stops': True,
        'geometry': mapping(box(*bbox)),
    }
    with open(os.path.join(DOM, 'empire.json'), 'w', encoding='utf-8') as f:
        json.dump(dom, f, ensure_ascii=False, separators=(',', ':'))
    with open(os.path.join(DOM, 'empire_stops.json'), 'w', encoding='utf-8') as f:
        json.dump({'domain': 'empire', 'note': 'шаги главной базы знаний, подобраны руками '
                   '(tools/build_empire_embed.py)', 'stops': stops},
                  f, ensure_ascii=False, indent=1)
    info = bb.build('empire', len(STEPS))
    with open(os.path.join(DOM, 'empire_bundles.json'), 'w', encoding='utf-8') as f:
        json.dump({'domain': 'empire', 'bundles': [info]}, f, ensure_ascii=False,
                  separators=(',', ':'))
    print('рамка', frame, 'центр', center, 'зум', zoom)


if __name__ == '__main__':
    main()
