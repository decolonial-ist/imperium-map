#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Акт против контроля: разбор расхождений и данные для попапа истории точки.

ЗАЧЕМ. Карта красила территорию имперской по дате ПРАВОВОГО АКТА: Дагестан
краснел с Гюлистанского трактата 12.10.1813, хотя империя воевала в тех горах
до 1859 года, а горная Чечня и вовсе краснела с 1783 года - за тридцать четыре
года до основания крепости Грозной. Куратор 19.08.2026: показ бинарный,
красное - империя тут была, чёрное - не была; пока идёт война за контроль,
территория не красная. Правка ядра живёт в `tools/build_expansion.py` (список
RESIST -> вычитания SUBS), а этот скрипт делает из того же списка две вещи:

  * `data/crosscheck/control_vs_act.csv` - таблица расхождений «акт против
    контроля»: что красило карту и с какой даты, чем империя объявила
    территорию своей, когда получила контроль на самом деле и какими
    кампаниями нашей базы это подтверждено. Плюс случаи, которые мы НЕ стали
    править на карте, с причиной - их решает куратор;
  * `data/campaigns/resistance.geojson` - те же территории с геометрией и
    списком кампаний, чтобы попап истории точки писал не «вне империи», а
    «до 19.08.1859 - война сопротивления, империя контроля не имела
    (кампании: ...)».

Даты и названия кампаний берутся из выгрузки нашей базы
(`data/campaigns/<домен>.json`, tools/build_campaigns.py) - не из головы. Если
кампании в выгрузке нет, скрипт падает: значит ID в RESIST опечатан или строку
из таблицы убрали.

Запуск (из корня репозитория, нужен shapely; ПОСЛЕ build_campaigns.py):

    cd ~/tmp/imperium-map && .venv/bin/python tools/build_campaigns.py
    cd ~/tmp/imperium-map && .venv/bin/python tools/build_resistance.py
"""
import csv
import json
import os
import sys

import geoclean as gc

from shapely.geometry import mapping

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_expansion as be   # noqa: E402  (RESIST, reg_geom - оттуда)

ROOT = be.ROOT
DATA = be.DATA
CAMP = os.path.join(DATA, 'campaigns')
CC = os.path.join(DATA, 'crosscheck')
SIMPLIFY = 0.01
DIGITS = 3

# ---- случаи, которые НА КАРТЕ НЕ ПРАВИМ ------------------------------------
# Разбор в таблицу нужен и по ним: куратор должен видеть, что мы их нашли и
# почему оставили. N(территория, чем покрашена, акт, что говорит наша база,
# кампании, домен, почему не правим)


def N(terr, painted, act, control, campaigns, domain, why):
    return dict(terr=terr, painted=painted, act=act, control=control,
                campaigns=campaigns, domain=domain, why=why)


NOT_MAPPED = [
    N('Левобережная Украина (Гетманщина)',
      'Переяславская рада 08.01.1654 (срез 1654-01-08)',
      'Переяславская рада 08.01.1654; Андрусовское перемирие 30.01.1667',
      'войны за контроль внутри уже покрашенного: Московско-украинская война '
      '(1658-1659), Батуринская резня и Лебединские казни (1708-1709), '
      'Полтава (1709), поход Пилипа Орлика на Правобережье (1711)',
      ['C0003', 'C0012', 'C0013', 'C0015', 'C0027'], 'ukraina',
      'окна войн короткие и разрозненные, между ними империя контроль имела - '
      'бинарный показ тут дал бы мигание красным. Нужно решение куратора: '
      'вычитать ли Гетманщину на 1658-1659 и 1708-1709'),
    N('Вольности Войска Запорожского',
      'Переяславская рада 08.01.1654 и Андрусовское перемирие 30.01.1667',
      'те же акты; ликвидация Сечи 04.05-14.08.1775',
      'Сечь империя разорила в 1709 году, с 1711 по 1734 год Запорожье ушло '
      'под османский протекторат, окончательно империя взяла его военной '
      'силой в 1775 году',
      ['C0014', 'C0033'], 'ukraina',
      'нет машиночитаемого контура Вольностей: в Natural Earth admin-1 такой '
      'единицы нет, приближать современными областями значит захватить '
      'полсотни тысяч км² чужой истории. Нужен курируемый контур'),
    N('Правобережная Украина',
      'второй раздел Речи Посполитой 12.01.1793 (срез 1793-01-12)',
      'конвенция о разделе 12.01.1793, ПСЗРИ т. 23 № 17108',
      'восстания внутри уже покрашенного: гайдамацкое движение Устима '
      'Кармалюка (1813-1835), Ноябрьское восстание (1830-1831), Январское '
      'восстание (1863-1864)',
      ['C0058', 'C0057', 'C0062'], 'ukraina',
      'восстание в несколько месяцев - не то же, что война за контроль: '
      'империя держала администрацию и войска всё это время. Красим красным'),
    N('Ингушетия',
      'контур источника 1783 г. (Назрань в империи с 1783)',
      'крепость Владикавказ 1784, Назрановское укрепление 1810',
      'отдельных кампаний про войну за контроль над Ингушетией в базе нет; '
      'единственное упоминание - вторжение отряда Розена «в горную Ингушетию '
      'и Чечню» в кампании про истребление 61 селения (C1155), 1832 год',
      ['C1155'], 'nohchi',
      'одного упоминания мало, чтобы вычитать целую республику. Ингушетию на '
      'карте не трогали - строка на вычитку куратором'),
]


def load_campaigns():
    out = {}
    for dom in ('nohchi', 'ukraina'):
        p = os.path.join(CAMP, dom + '.json')
        if not os.path.exists(p):
            raise SystemExit(f'нет {p} - сперва tools/build_campaigns.py')
        with open(p, encoding='utf-8') as f:
            doc = json.load(f)
        for c in doc['campaigns']:
            out[c['id']] = dict(c, domain=dom)
    return out


def pick(db, ids):
    miss = [i for i in ids if i not in db]
    if miss:
        raise SystemExit(f'в выгрузке базы нет кампаний {miss} - опечатка в '
                         'RESIST или строку убрали из таблицы')
    cs = [db[i] for i in ids]
    cs.sort(key=lambda c: c['first_seen_iso'] or '')
    return cs


def short(name, n=88):
    return name if len(name) <= n else name[:n - 1].rstrip(' ,;:-') + '…'


def _round(g):
    def walk(c):
        if isinstance(c[0], (int, float)):
            return [round(c[0], DIGITS), round(c[1], DIGITS)]
        return [walk(x) for x in c]
    return {'type': g['type'], 'coordinates': walk(g['coordinates'])}


def main():
    db = load_campaigns()
    feats, rows = [], []

    for r in be.RESIST:
        cs = pick(db, r['campaigns'])
        frm = cs[0]['first_seen_iso'] if cs else None
        geom = be.reg_geom(r['reg']).simplify(SIMPLIFY).buffer(0)
        feats.append({
            'type': 'Feature',
            'geometry': _round(mapping(geom)),
            'properties': {
                'id': r['reg'],
                'name': r['name'],
                'from': frm,
                'to': r['until'],
                'event': r['event'],
                'source': r['src'],
                'painted': r['painted'],
                'note': r['note'],
                'domain': r['domain'],
                'campaigns': [{'id': c['id'], 'name': c['name'],
                               'short': short(c['name']),
                               'from': c['first_seen_iso'],
                               'to': c['last_seen_iso']} for c in cs],
                'approximate': True,
                'geometry_source': be.NE + ' (рамки указаны в REG '
                                           'tools/build_expansion.py)',
            },
        })
        rows.append({
            'territory': r['name'],
            'on_map': 'вычтено из ядра до даты контроля',
            'painted_since': r['painted'],
            'act': r['event'],
            'control_since': r['until'],
            'control_source': r['src'],
            'resistance_from': frm or '-',
            'resistance_to': r['until'],
            'campaigns': '; '.join(f'{c["name"]} ({c["id"]})' for c in cs) or '-',
            'domain': r['domain'] or '-',
            'note': r['note'],
        })

    for n in NOT_MAPPED:
        cs = pick(db, n['campaigns'])
        rows.append({
            'territory': n['terr'],
            'on_map': 'НЕ ПРАВИЛИ',
            'painted_since': n['painted'],
            'act': n['act'],
            'control_since': '-',
            'control_source': n['control'],
            'resistance_from': cs[0]['first_seen_iso'] if cs else '-',
            'resistance_to': max((c['last_seen_iso'] or '') for c in cs) if cs else '-',
            'campaigns': '; '.join(f'{c["name"]} ({c["id"]})' for c in cs) or '-',
            'domain': n['domain'],
            'note': n['why'],
        })

    os.makedirs(CC, exist_ok=True)
    path = os.path.join(CC, 'control_vs_act.csv')
    cols = ['territory', 'on_map', 'painted_since', 'act', 'control_since',
            'control_source', 'resistance_from', 'resistance_to', 'campaigns',
            'domain', 'note']
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f'OK data/crosscheck/control_vs_act.csv: строк {len(rows)} '
          f'(правлено на карте {len(be.RESIST)}, оставлено {len(NOT_MAPPED)})')

    fc = {'type': 'FeatureCollection', 'features': feats,
          'source': 'территории, где империя объявила себя хозяйкой актом, но '
                    'контроля не имела: вычитаются из ядра до даты контроля '
                    '(tools/build_expansion.py, список RESIST). Даты и '
                    'кампании - из нашей базы (data/campaigns/*.json). '
                    'Геометрия приближена современными административными '
                    'единицами. Разбор - data/crosscheck/control_vs_act.csv'}
    path = os.path.join(CAMP, 'resistance.geojson')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(gc.sanitize_obj(fc), f, ensure_ascii=False)
    print(f'OK data/campaigns/resistance.geojson: территорий {len(feats)}, '
          f'{os.path.getsize(path) // 1024} КБ')
    for ft in feats:
        p = ft['properties']
        print(f'   {p["name"]}: до {p["to"]}, кампаний '
              f'{len(p["campaigns"])}, окно с {p["from"] or "-"}')


if __name__ == '__main__':
    main()
