#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Пакет старта карты и метка версии данных (этап 3 плана 15.09.2026).

Зачем. До первого кадра карта делала около сорока мелких запросов: манифесты,
сфера влияния, постсоветские эпизоды, Беларусь, остроги, границы Украины и
Ичкерии, контур Крыма, сателлит, 23 мелких эпизода потерь. На 3G с задержкой
150 мс одни только обмены с сервером складывались в секунды. Здесь всё это
склеивается в ОДИН файл data/start.json (около 0,4 МБ сжатыми); карта берёт
его одним запросом, а поштучный путь остаётся запасным (нет пакета или он
старее манифеста - берёт файлы по одному, как раньше).

Заодно пишется data/version.json - метка версии данных для service worker
(sw.js): хеш всех манифестов и штампов сборки. Меняется при любой
пересборке, и кэш в браузере читателя сбрасывается сам.

Место в цепочке: ПОСЛЕДНИЙ шаг после build_lite.py (штамп «start» для
check_build_order.py).

Запуск:
    cd ~/tmp/imperium-map && .venv/bin/python tools/build_start_bundle.py
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import geoclean as gc  # noqa: E402

DATA = os.path.join(ROOT, 'data')
LOSS_EAGER_PARTS = 20      # как в index.html: эпизоды до стольких частей едут сразу

# Что кладём в пакет: ключ в пакете -> путь файла (относительно корня репо).
# Ключи совпадают с адресами, по которым index.html и ee-shim.js берут файлы
# поштучно, - чтобы запасной путь и пакет нельзя было перепутать.
FILES = [
    'data/manifest.json',
    'data/lite_manifest.json',
    # опись среднего уровня (этап 4, 15.09.2026): карте она нужна до первого
    # приближения, без неё срезы на масштабе 4,5-8 берутся полными
    'data/mid_manifest.json',
    'data/sphere.geojson',
    'data/deepstate/manifest.json',
    'data/postsoviet.geojson',
    'data/belarus.geojson',
    'data/attribution/manifest.json',
    'data/losses/manifest.json',
    'data/ostrogs/ostrogs.geojson',
    'data/satellite/chechnya_1993_1994.geojson',
    'data/borders/ichkeria_osm.geojson',
    'data/borders/ukraine_osm.geojson',
    'data/crimea_outline.geojson',
    'data/basetiles/manifest.json',
]
REQUIRED = {'data/manifest.json', 'data/sphere.geojson', 'data/losses/manifest.json'}

# Хеш версии: манифесты и штампы, а не сами данные (их сотни мегабайт).
VERSION_OF = [
    'data/manifest.json', 'data/lite_manifest.json', 'data/deepstate/manifest.json',
    'data/losses/manifest.json', 'data/attribution/manifest.json',
    'data/basetiles/manifest.json', 'data/postsoviet.geojson', 'data/sphere.geojson',
    'data/build_stamps.json',
]


def load(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        return None
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def main():
    files = {}
    missing = []
    for rel in FILES:
        d = load(rel)
        if d is None:
            missing.append(rel)
            continue
        files[rel] = d
    if REQUIRED & set(missing):
        sys.exit('нет обязательных файлов: %s' % ', '.join(sorted(REQUIRED & set(missing))))
    # мелкие эпизоды потерь - те же, что index.html грузит до первого кадра
    eps = (files['data/losses/manifest.json'] or {}).get('episodes', [])
    for e in eps:
        if (e.get('features') or 0) <= LOSS_EAGER_PARTS:
            rel = 'data/losses/%s.geojson' % e['slug']
            d = load(rel)
            if d is None:
                missing.append(rel)
            else:
                files[rel] = d

    # версия данных: хеш манифестов и штампов
    h = hashlib.sha256()
    for rel in VERSION_OF:
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            with open(p, 'rb') as f:
                h.update(rel.encode() + b'\0' + f.read() + b'\0')
    version = h.hexdigest()[:12]
    built = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    bundle = {'version': version, 'built': built, 'files': files,
              'note': 'пакет старта карты, tools/build_start_bundle.py; ключи = адреса файлов'}
    out = os.path.join(DATA, 'start.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(bundle, f, ensure_ascii=False, separators=(',', ':'))
    vout = os.path.join(DATA, 'version.json')
    with open(vout, 'w', encoding='utf-8') as f:
        json.dump({'version': version, 'built': built}, f, ensure_ascii=False)
    gc.write_stamp('start')
    print('пакет старта: %d файлов, %.2f МБ сырыми, версия %s; нет в пакете: %s'
          % (len(files), os.path.getsize(out) / 1048576, version,
             ', '.join(missing) if missing else 'ничего'))


if __name__ == '__main__':
    main()
