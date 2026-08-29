import geoclean as gc
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборка слоя событий советско-украинской войны 1917-1921 из черновика CSV.

Читает data/events/<набор>/draft_events.csv (колонки date, date_precision,
place, lat, lon, event, actor_gained, actor_lost, source, confidence, note)
и пишет рядом events.geojson — точки с окном показа на ползунке карты:

  точность day    -> [дата - 3 дня, дата + 11 дней]
  точность month  -> весь месяц
  точность year   -> весь год

Окно лежит в свойствах t0/t1 (миллисекунды UTC) — index.html фильтрует по ним
дату ползунка. Конвертация повторяемая: запуск перезаписывает events.geojson.

Запуск:  python3 tools/build_events.py            (из корня репозитория)
         python3 tools/build_events.py --set ukraina_1917_1921
"""
import argparse
import calendar
import csv
import json
import os
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# окно показа события с точностью до дня: сколько дней до и после даты
DAYS_BEFORE, DAYS_AFTER = 3, 11

ACTORS_RU = {
    'bolsheviks': 'большевики',
    'unr': 'УНР (Центральная рада)',
    'directory': 'УНР (Директория)',
    'germans': 'германские войска',
    'hetmanate': 'гетманат Скоропадского',
    'whites': 'белые',
    'wrangel': 'Врангель',
    'entente': 'Антанта',
    'poles': 'поляки',
    'makhno': 'махновцы',
}

EVENTS_RU = {
    'took_city': 'взятие города',
    'left_city': 'оставление города',
    'evacuation': 'эвакуация',
    'operation_start': 'начало операции',
    'operation_end': 'конец операции',
    'declared_war': 'объявление войны',
    'treaty': 'договор',
}

CONF_RU = {'high': 'высокая', 'medium': 'средняя', 'low': 'низкая'}

MONTHS_RU = ['янв', 'фев', 'мар', 'апр', 'май', 'июн',
             'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']


def parse_date(s):
    """'1919-06-12' | '1919-06' | '1919' -> (date, точность по формату)."""
    parts = [int(p) for p in s.strip().split('-')]
    if len(parts) == 3:
        return date(*parts), 'day'
    if len(parts) == 2:
        return date(parts[0], parts[1], 1), 'month'
    return date(parts[0], 1, 1), 'year'


def window(d, prec):
    """Окно показа события -> (дата с, дата по) включительно."""
    if prec == 'year':
        return date(d.year, 1, 1), date(d.year, 12, 31)
    if prec == 'month':
        last = calendar.monthrange(d.year, d.month)[1]
        return date(d.year, d.month, 1), date(d.year, d.month, last)
    return d - timedelta(days=DAYS_BEFORE), d + timedelta(days=DAYS_AFTER)


def ms(d, end=False):
    """Дата -> миллисекунды UTC (для end — конец суток)."""
    t = calendar.timegm((d.year, d.month, d.day, 0, 0, 0)) * 1000
    return t + (86400000 - 1 if end else 0)


def date_ru(d, prec):
    if prec == 'year':
        return str(d.year)
    if prec == 'month':
        return f'{MONTHS_RU[d.month - 1]} {d.year}'
    return f'{d.day} {MONTHS_RU[d.month - 1]} {d.year}'


def build(csv_path, out_path):
    feats, warn = [], []
    with open(csv_path, encoding='utf-8') as f:
        for n, r in enumerate(csv.DictReader(f), 2):
            d, fmt_prec = parse_date(r['date'])
            prec = (r.get('date_precision') or fmt_prec).strip()
            if prec == 'day' and fmt_prec != 'day':
                prec = fmt_prec           # '1918-04' + day -> точнее месяца нет
            w0, w1 = window(d, prec)
            lat, lon = float(r['lat']), float(r['lon'])
            if not (40 <= lat <= 60 and 20 <= lon <= 45):
                warn.append(f'строка {n}: {r["place"]} вне Украины ({lat},{lon})')
            gained, lost = r['actor_gained'].strip(), r['actor_lost'].strip()
            for a in (gained, lost):
                if a and a not in ACTORS_RU:
                    warn.append(f'строка {n}: неизвестный актор {a!r}')
            if r['event'].strip() not in EVENTS_RU:
                warn.append(f'строка {n}: неизвестный тип {r["event"]!r}')
            feats.append({
                'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
                'properties': {
                    'date': r['date'].strip(),
                    'prec': prec,
                    'date_ru': date_ru(d, prec),
                    'place': r['place'].strip(),
                    'ev': r['event'].strip(),
                    'ev_ru': EVENTS_RU.get(r['event'].strip(), r['event'].strip()),
                    'gained': gained,
                    'lost': lost,
                    'gained_ru': ACTORS_RU.get(gained, ''),
                    'lost_ru': ACTORS_RU.get(lost, ''),
                    'source': r['source'].strip(),
                    'conf': r['confidence'].strip(),
                    'conf_ru': CONF_RU.get(r['confidence'].strip(), r['confidence'].strip()),
                    'note': r['note'].strip(),
                    't0': ms(w0),
                    't1': ms(w1, end=True),
                    'win': f'{w0.isoformat()}..{w1.isoformat()}',
                },
            })
    feats.sort(key=lambda f: (f['properties']['t0'], f['properties']['place']))
    fc = {'type': 'FeatureCollection',
          'note': ('События советско-украинской войны 1917-1921. ЧЕРНОВИК НА '
                   'ВЫЧИТКЕ У КУРАТОРА. Собрано tools/build_events.py из '
                   'draft_events.csv; окно показа t0..t1 (мс UTC).'),
          'features': feats}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj(fc), f, ensure_ascii=False)
    return feats, warn


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--set', default='ukraina_1917_1921',
                    help='каталог набора в data/events/ (по умолчанию ukraina_1917_1921)')
    ap.add_argument('--csv', default='draft_events.csv', help='имя входного CSV в наборе')
    ap.add_argument('--out', default='events.geojson', help='имя выходного geojson в наборе')
    args = ap.parse_args()

    base = os.path.join(ROOT, 'data', 'events', args.set)
    feats, warn = build(os.path.join(base, args.csv), os.path.join(base, args.out))

    years = {}
    for f in feats:
        years[f['properties']['date'][:4]] = years.get(f['properties']['date'][:4], 0) + 1
    conf = {}
    for f in feats:
        conf[f['properties']['conf']] = conf.get(f['properties']['conf'], 0) + 1
    print(f'OK data/events/{args.set}/{args.out}: событий {len(feats)}')
    print('  по годам: ' + ', '.join(f'{k} - {v}' for k, v in sorted(years.items())))
    print('  confidence: ' + ', '.join(f'{k} - {v}' for k, v in sorted(conf.items())))
    for w in warn:
        print('  ВНИМАНИЕ ' + w)


if __name__ == '__main__':
    main()
