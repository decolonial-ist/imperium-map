#!/usr/bin/env python3
"""Регрессия слоя потерь контроля ДО XX века.

Зачем. Слой data/losses до 26.08.2026 покрывал только 2022-2026, и на вопрос
куратора «где война с наполеоном, где крымские войны» карта молчала. Эпизоды
заведены (tools/build_losses.py, список PRE20), и теперь их надо держать
проверенными тем же способом, каким проверяются расползание и фронты:
point-in-polygon по нашим же файлам.

Что проверяется.
1. ТАБЛИЦА ОЖИДАНИЙ data/crosscheck/losses_pre20.csv - «место, дата, ждём ли
   точку внутри империи». Статус считается ровно так же, как его рисует карта:
   берём последний срез ядра не позже даты, а из него вычитаем вырезающие
   эпизоды слоя потерь, действующие на дату. Колонка row - какой эпизод обязан
   быть виден в попапе на этой точке и дате (для raid и contested это
   единственный след эпизода: красное они не вырезают).
2. СТРУКТУРА ЭПИЗОДОВ - у каждой фичи есть источник, оценка достоверности,
   стиль дат и пояснение; вид (kind) известен; окно не вывернуто.
3. ВЫРЕЗ ВООБЩЕ ПОЛУЧИТСЯ - геометрия вырезающей фичи лежит внутри полигона
   среза ядра. Механизм cutCore в index.html вставляет вырез ВНУТРЕННИМ
   КОЛЬЦОМ того полигона ядра, который его содержит: кусок, торчащий наружу,
   дырки не даст. Фичи, у которых участка в обзорном контуре нет вовсе
   (Кинбурнская коса, Аланды), помечены в данных как outside_core и
   проверяются на эту пометку.

Запуск: .venv/bin/python tools/check_losses_pre20.py
Отчёт:  data/crosscheck/losses_pre20_report.md
Падает с кодом 1, если карта врёт.
"""
import csv
import json
import os
import sys
from datetime import date

from shapely.geometry import Point, shape
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_losses as B  # noqa: E402  (KIND_RU, NO_CUT, срезы ядра)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOSSES = os.path.join(ROOT, 'data', 'losses')
TABLE = os.path.join(ROOT, 'data', 'crosscheck', 'losses_pre20.csv')
REPORT = os.path.join(ROOT, 'data', 'crosscheck', 'losses_pre20_report.md')


def dt(s):
    return date(*map(int, s.split('-')))


def load_pre20():
    """Фичи курируемых эпизодов до XX века + строки манифеста."""
    with open(os.path.join(LOSSES, 'manifest.json'), encoding='utf-8') as f:
        man = json.load(f)
    eps = [e for e in man.get('episodes', []) if e.get('kind') == B.PRE20_KIND]
    feats = []
    for e in eps:
        path = os.path.join(LOSSES, e['slug'] + '.geojson')
        with open(path, encoding='utf-8') as f:
            fc = json.load(f)
        for ft in fc['features']:
            p = ft['properties']
            feats.append({'p': p, 'g': shape(ft['geometry']),
                          't0': dt(p['from']), 't1': dt(p['to'])})
    return man, eps, feats


def status(x, y, d, feats):
    """В империи или нет - тем же правилом, каким это рисует карта."""
    key = B.slice_key_at(d)
    if not B.core_slice(key).contains(Point(x, y)):
        return 'not_empire', key
    for f in feats:
        if f['p']['kind'] in B.NO_CUT:
            continue                      # raid и contested красное не режут
        if f['t0'] <= d <= f['t1'] and f['g'].contains(Point(x, y)):
            return 'not_empire', key
    return 'empire', key


def main():
    man, eps, feats = load_pre20()
    rows, ok, bad = [], 0, 0

    def check(name, cond, got=''):
        nonlocal ok, bad
        rows.append((name, 'ok' if cond else 'БРАК', got))
        if cond:
            ok += 1
        else:
            bad += 1

    # ---- 1. таблица ожиданий ----
    with open(TABLE, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            d = dt(r['date'])
            got, key = status(float(r['lon']), float(r['lat']), d, feats)
            check(f"{r['place']} на {r['date']}: ждём {r['expect']}",
                  got == r['expect'], f'получили {got} (срез {key})')
            if r.get('row'):
                seen = [f for f in feats
                        if f['p']['episode'] == r['row']
                        and f['t0'] <= d <= f['t1']
                        and f['g'].contains(Point(float(r['lon']),
                                                  float(r['lat'])))]
                check(f"{r['place']} на {r['date']}: в попапе эпизод "
                      f"{r['row']}", bool(seen),
                      'эпизод на точке не найден' if not seen else
                      seen[0]['p']['name'])

    # ---- 2. структура эпизодов ----
    for e in eps:
        path = os.path.join(LOSSES, e['slug'] + '.geojson')
        check(f"эпизод {e['slug']}: файл на месте", os.path.exists(path))
    for f in feats:
        p = f['p']
        tag = f"{p['episode']} / {p['name'][:40]}"
        check(f'{tag}: вид известен', p['kind'] in B.KIND_RU, p['kind'])
        check(f'{tag}: есть источник и достоверность',
              bool(p.get('source')) and p.get('confidence')
              in ('high', 'medium', 'low'), str(p.get('confidence')))
        check(f'{tag}: помечен стиль дат', bool(p.get('style')))
        check(f'{tag}: окно не вывернуто', f['t0'] <= f['t1'],
              f"{p['from']}..{p['to']}")
        check(f'{tag}: есть пояснение', len(p.get('note', '')) > 40)

    # ---- 3. вырез вообще получится ----
    for f in feats:
        p = f['p']
        if p['kind'] in B.NO_CUT:
            continue
        tag = f"{p['episode']} / {p['name'][:40]}"
        if p.get('outside_core'):
            check(f'{tag}: помечен как лежащий вне контура среза',
                  bool(p.get('geometry_note')))
            continue
        key = B.slice_key_at(f['t0'])
        core = B.core_slice(key)
        # упрощение линии на 500 м могло вынести кромку наружу - допуск в
        # 1 % площади куска, иначе кольцо выреза считаем торчащим
        outside = f['g'].difference(core).area
        check(f'{tag}: вырез лежит внутри среза {key}',
              outside <= 0.01 * f['g'].area,
              f'снаружи {outside:.4f} град² из {f["g"].area:.3f}')

    # ---- 4. слой не потерял эпизоды 2022+ ----
    later = [e for e in man['episodes'] if e.get('kind') != B.PRE20_KIND]
    check('эпизоды 2022+ на месте (их 11)', len(later) == 11, str(len(later)))
    check('эпизодов до XX века заведено не меньше десяти', len(eps) >= 10,
          str(len(eps)))

    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write('# Регрессия слоя потерь до XX века\n\n'
                f'Прогон `tools/check_losses_pre20.py`, проверок {ok + bad}, '
                f'брака {bad}.\n\nТаблица ожиданий — '
                '`data/crosscheck/losses_pre20.csv`.\n\n'
                '| проверка | итог | получили |\n| --- | --- | --- |\n')
        for n, res, got in rows:
            f.write(f'| {n} | {res} | {got} |\n')

    for n, res, got in rows:
        if res != 'ok':
            print(f'БРАК: {n} — {got}')
    print(f'проверок {ok + bad}, зелёных {ok}, брака {bad}')
    print(f'отчёт: {os.path.relpath(REPORT, ROOT)}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
