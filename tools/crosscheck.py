#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Кросс-чек карты по контрольным точкам: что говорит НАША карта на дату.

Каркас сверки (18.08.2026). Читает data/crosscheck/checkpoints.csv
(place,lat,lon,date,expected_controller,source,note), для каждой точки берёт
слой, действующий у нас на эту дату, и определяет попаданием точки в полигон,
кто по нашей карте контролирует место. Вердикты:

  match           - совпало с ожиданием источника;
  more-detailed   - расходится, но наш слой подробнее даты источника
                    (у нас дневной срез, у источника только год);
  hard-divergence - противоречие: обе стороны говорят про один момент разное;
  no-data         - наша карта в этом месте на эту дату молчит: слой есть, но
                    он де-юре (CShapes) и про фактический контроль не говорит.

Срезы реконструкции 1917-1921 (`reconstruction: true`) отвечают активно, но с
26.08.2026 на другой оси: не «советская власть / нет», а «в империи / вне
империи». Белые (Комуч, Колчак, ВСЮР, Врангель, Северная область, Краснов,
Семёнов, ДВР, интервенция с русской белой администрацией) - фракция той же
империи, поэтому ожидание `whites` совпадает с ответом `in_empire`, а не
противоречит ему. Ось задаёт множество EMPIRE_SIDE.

Точки контроля заводит куратор (в т.ч. по GeaCron). Скрипт ничего не чинит -
он показывает, где карта врёт или молчит.

Запуск:  python3 tools/crosscheck.py   (из корня репозитория)
"""
import argparse
import csv
import json
import os
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CC = os.path.join(DATA, 'crosscheck')

# наши слои отвечают одним из этих токенов
SOVRUS = 'sovrus'          # ядро: Россия / РСФСР / СССР / РФ и оккупация 2022+
BELSAT = 'belarus_sat'     # Беларусь как несуверенный сателлит
UKR = 'ukraine'            # освобождённая территория по DeepStateMAP
UNKNOWN = 'unknown'        # серая зона DeepStateMAP
NOTSOV = 'not_sovrus'      # (историческое) не советская зона
INEMP = 'in_empire'        # реконструкция 1917-1921: точка внутри империи
NOTEMP = 'not_empire'      # реконструкция 1917-1921: точка вне империи

# ожидания куратора приводим к тем же семьям
FAMILY = {
    'bolsheviks': SOVRUS, 'soviets': SOVRUS, 'ussr': SOVRUS, 'russia': SOVRUS,
    'ukraine': UKR, 'unr': 'unr', 'directory': 'directory',
    'germans': 'germans', 'hetmanate': 'germans', 'whites': 'whites',
    'wrangel': 'whites', 'entente': 'entente', 'poles': 'poles',
    'makhno': 'makhno', 'belarus': BELSAT,
    'kolchak': 'whites', 'komuch': 'whites', 'dutov': 'whites',
    'krasnov': 'whites', 'semenov': 'whites', 'dvr': 'whites',
    'north_region': 'whites', 'transcaspia': 'whites',
}

# кто в окне 1917-1921 считается ИМПЕРИЕЙ (решение куратора 18.08.2026,
# память empire-not-factions): красные и белые - две фракции одной империи,
# междоусобицы имперцев карта не различает. Всё остальное - вне империи.
EMPIRE_SIDE = {SOVRUS, 'whites', 'entente'}

BELARUS_FROM = date(1991, 12, 26)


def parse_date(s):
    """'1919-06-12' | '1919-06' | '1919' -> (date, точность)."""
    p = [int(x) for x in s.strip().split('-')]
    if len(p) == 3:
        return date(*p), 'day'
    if len(p) == 2:
        return date(p[0], p[1], 1), 'month'
    return date(p[0], 1, 1), 'year'


def slice_date(key):
    """Ключ среза -> дата, с которой он показывается (как в build_data.py)."""
    p = [int(x) for x in str(key).split('-')]
    return date(p[0], p[1] if len(p) > 1 else 1, p[2] if len(p) > 2 else 1)


def in_ring(x, y, ring):
    """Луч вправо: нечётное число пересечений — точка внутри кольца."""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > y) != (y2 > y):
            xx = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xx > x:
                inside = not inside
    return inside


def in_polygon(x, y, poly):
    """poly — список колец: первое внешнее, остальные дырки."""
    if not poly or not in_ring(x, y, poly[0]):
        return False
    return not any(in_ring(x, y, hole) for hole in poly[1:])


def in_geom(x, y, g):
    if not g:
        return False
    if g['type'] == 'Polygon':
        return in_polygon(x, y, g['coordinates'])
    if g['type'] == 'MultiPolygon':
        return any(in_polygon(x, y, p) for p in g['coordinates'])
    return False


def hits(x, y, fc):
    return [f for f in fc.get('features', []) if in_geom(x, y, f.get('geometry'))]


def load(path):
    if not os.path.exists(path):
        return {'features': []}
    with open(path, encoding='utf-8') as f:
        return json.load(f)


class Map:
    """Наша карта: годовые/датированные срезы ядра, дни фронта, Беларусь."""

    def __init__(self):
        mf = json.load(open(os.path.join(DATA, 'manifest.json'), encoding='utf-8'))
        self.slices = sorted(((slice_date(k), str(k)) for k in mf['years']))
        dsmf = load(os.path.join(DATA, 'deepstate', 'manifest.json'))
        self.days = sorted(dsmf.get('days', []))
        self.belarus = load(os.path.join(DATA, 'belarus.geojson'))
        self.cache = {}

    def core_slice(self, d):
        cur = None
        for sd, key in self.slices:
            if sd <= d:
                cur = key
        return cur

    def day_slice(self, d):
        cur = None
        for k in self.days:
            if parse_date(k)[0] <= d:
                cur = k
        return cur

    def geo(self, path):
        if path not in self.cache:
            self.cache[path] = load(os.path.join(DATA, path))
        return self.cache[path]

    def ask(self, lon, lat, d):
        """-> (ответ или None, чем ответили, дробность слоя: 'day'|'year')."""
        day = self.day_slice(d)
        if day:
            fc = self.geo(os.path.join('deepstate', 'days', day + '.geojson'))
            got = hits(lon, lat, fc)
            if got:
                st = got[0]['properties'].get('s')
                ans = {'occupied': SOVRUS, 'liberated': UKR}.get(st, UNKNOWN)
                return ans, f'DeepStateMAP {day}', 'day'
        if d >= BELARUS_FROM and hits(lon, lat, self.belarus):
            return BELSAT, 'слой «Беларусь несуверенна»', 'day'
        key = self.core_slice(d)
        if key:
            fc = self.geo(os.path.join('years', key + '.geojson'))
            prec = 'day' if '-' in key else 'year'
            # `reconstruction` стоит и у срезов расползания 1552-1914
            # (tools/build_expansion.py), но они про ПРИОБРЕТЕНИЯ по актам, а
            # не про фактический контроль: отвечать ими «здесь не было
            # советской власти» нельзя. Активно отвечает только реконструкция
            # зоны контроля 1917-1921.
            recon = any(f['properties'].get('reconstruction')
                        and not f['properties'].get('expansion')
                        for f in fc.get('features', []))
            tag = 'реконструкция' if recon else 'срез ядра'
            if recon:      # ось «в империи / вне империи», а не «советы / нет»
                return ((INEMP, f'{tag} {key}', prec) if hits(lon, lat, fc)
                        else (NOTEMP, f'{tag} {key}: вне империи', prec))
            if hits(lon, lat, fc):
                return SOVRUS, f'{tag} {key}', prec
            return None, f'срез ядра {key}: точка вне контура', prec
        return None, 'слоёв на эту дату нет', 'year'


def verdict(expected, got, layer_prec, cp_prec):
    if got is None:
        return 'no-data'
    exp = FAMILY.get(expected, expected)
    if got in (INEMP, NOTEMP):
        # реконструкция 1917-1921 отвечает про империю, а не про фракцию:
        # `whites` внутри красного - совпадение, а не противоречие
        return 'match' if (exp in EMPIRE_SIDE) == (got == INEMP) \
            else 'hard-divergence'
    if got == NOTSOV:
        return 'hard-divergence' if exp == SOVRUS else 'match'
    if exp == got:
        return 'match'
    if layer_prec == 'day' and cp_prec != 'day':
        return 'more-detailed'
    return 'hard-divergence'


def run(rows, mp):
    out = []
    for r in rows:
        d, prec = parse_date(r['date'])
        got, layer, layer_prec = mp.ask(float(r['lon']), float(r['lat']), d)
        out.append({
            'place': r['place'], 'date': r['date'],
            'expected': r['expected_controller'],
            'got': got or '-', 'layer': layer,
            'verdict': verdict(r['expected_controller'], got, layer_prec, prec),
            'source': r['source'], 'note': r['note'],
        })
    return out


def report(res, path):
    counts = {}
    for r in res:
        counts[r['verdict']] = counts.get(r['verdict'], 0) + 1
    w = max(len(r['place']) for r in res)
    print(f'{"место".ljust(w)}  {"дата".ljust(10)}  {"ожидание".ljust(12)}  '
          f'{"наша карта".ljust(12)}  вердикт / слой')
    for r in res:
        print(f'{r["place"].ljust(w)}  {r["date"].ljust(10)}  '
              f'{r["expected"].ljust(12)}  {r["got"].ljust(12)}  '
              f'{r["verdict"]} / {r["layer"]}')
    print('итог: ' + ', '.join(f'{k} - {v}' for k, v in sorted(counts.items())))

    lines = ['# Кросс-чек карты по контрольным точкам', '',
             'Собрано `tools/crosscheck.py` из `data/crosscheck/checkpoints.csv`.',
             'Файл перезаписывается при каждом прогоне - правки вносить в CSV.', '',
             'Вердикты: **match** - совпало; **more-detailed** - расходится, но наш',
             'слой подробнее даты источника; **hard-divergence** - противоречие;',
             '**no-data** - наша карта в этом месте на эту дату молчит (слой',
             'де-юре, про фактический контроль не говорит). Срезы реконструкции',
             '1917-1921 отвечают активно и на своей оси: `in_empire` /',
             '`not_empire`. Белые - фракция той же империи, поэтому ожидание',
             '`whites` совпадает с `in_empire` (смена рамки 26.08.2026).', '',
             'Итог: ' + ', '.join(f'{k} - {v}' for k, v in sorted(counts.items())), '',
             '| место | дата | ожидание источника | наша карта | вердикт | чем ответили | источник ожидания |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for r in res:
        src = r['source'].replace('|', '/')
        lines.append(f'| {r["place"]} | {r["date"]} | {r["expected"]} | {r["got"]} | '
                     f'{r["verdict"]} | {r["layer"]} | {src} |')
    lines += ['', '## Примечания к точкам', '']
    for r in res:
        if r['note']:
            lines.append(f'- **{r["place"]}, {r["date"]}** - {r["note"].replace("|", "/")}')
    lines.append('')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'OK {os.path.relpath(path, ROOT)}')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--checkpoints', default=os.path.join(CC, 'checkpoints.csv'))
    ap.add_argument('--out', default=os.path.join(CC, 'report.md'))
    args = ap.parse_args()

    with open(args.checkpoints, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    report(run(rows, Map()), args.out)


if __name__ == '__main__':
    main()
