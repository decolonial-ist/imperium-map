#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Свои подписи для мобильной карты: города и области на МЕСТНОМ языке.

Растровые подписи Esri локализовать нельзя - служба отдаёт готовые тайлы, и
поля языка у неё нет (проверено 31.08.2026 по её же описанию). На нашей карте
это означает «Kiev» вместо «Київ», то есть имперскую транслитерацию столицы
там, где мы рассказываем о колонизации.

Свой слой берёт имена оттуда, где они уже лежат местными:
- города - Natural Earth 10m populated places (`NAME_UK`, `NAME_RU`, ...,
  запасной вариант `NAME`, который у Киева уже «Kyiv»);
- области и республики - Natural Earth admin-1 (`name_uk`, `name_ru`, ...);
- страны - словарь NAME0 из build_domain_bundle.

Города режутся по населению: в кадре домена оставляем столько, чтобы карта не
зарастала - порог считается от размера рамки.

Запуск:

    cd ~/tmp/imperium-map && .venv/bin/python3 tools/build_domain_labels.py
"""
import glob
import json
import os
import sys

from shapely.geometry import box, shape

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import geoclean as gc  # noqa: E402
from build_domain_bundle import CLIP_PAD, CLIP_MAX_DEG  # noqa: E402

# Язык подписи - язык места, а не империи: у украинских областей `name_uk`,
# у российских `name_ru` и так далее. Названия стран Natural Earth хранит
# только по-английски, поэтому для них словарь.
LANG = {'Ukraine': 'name_uk', 'Russia': 'name_ru', 'Belarus': 'name_ru',
        'Poland': 'name_pl', 'Romania': 'name_ro', 'Moldova': 'name_ro',
        'Hungary': 'name_hu', 'Slovakia': 'name_sk', 'Turkey': 'name_tr',
        'Bulgaria': 'name_bg', 'Georgia': 'name_ka', 'Azerbaijan': 'name_az',
        'Kazakhstan': 'name_ru', 'Armenia': 'name_hy'}
NAME0 = {
    'Ukraine': 'Україна', 'Russia': 'Россия', 'Belarus': 'Беларусь',
    'Poland': 'Polska', 'Romania': 'România', 'Moldova': 'Moldova',
    'Hungary': 'Magyarország', 'Slovakia': 'Slovensko',
    'Bulgaria': 'България', 'Turkey': 'Türkiye', 'Georgia': 'საქართველო',
    'Azerbaijan': 'Azərbaycan', 'Armenia': 'Հայաստան',
    'Kazakhstan': 'Қазақстан', 'Serbia': 'Србија',
    'Republic of Serbia': 'Србија', 'Czechia': 'Česko',
    'Lithuania': 'Lietuva', 'Latvia': 'Latvija', 'Estonia': 'Eesti',
    'Finland': 'Suomi', 'Sweden': 'Sverige', 'Germany': 'Deutschland',
    'Austria': 'Österreich', 'Croatia': 'Hrvatska', 'Greece': 'Ελλάδα',
    'Slovenia': 'Slovenija', 'Mongolia': 'Монгол улс', 'China': '中国',
    'Iran': 'ایران', 'Turkmenistan': 'Türkmenistan',
    'Uzbekistan': 'Oʻzbekiston', 'Kyrgyzstan': 'Кыргызстан',
    'Tajikistan': 'Тоҷикистон', 'Norway': 'Norge',
}

DATA = os.path.join(ROOT, 'data')
DOM = os.path.join(DATA, 'domains')
CACHE = os.path.join(ROOT, 'cache')
CITY_LANG = {'Ukraine': 'NAME_UK', 'Russia': 'NAME_RU', 'Belarus': 'NAME_RU',
             'Poland': 'NAME_PL', 'Romania': 'NAME_RO', 'Moldova': 'NAME_RO',
             'Turkey': 'NAME_TR', 'Georgia': 'NAME_KA', 'Bulgaria': 'NAME_BG',
             'Hungary': 'NAME_HU', 'Kazakhstan': 'NAME_RU'}


def build(domain_id):
    dom = json.load(open(os.path.join(DOM, domain_id + '.json'), encoding='utf-8'))
    b = dom['bbox']
    pw = min((b[2] - b[0]) * CLIP_PAD, CLIP_MAX_DEG)
    ph = min((b[3] - b[1]) * CLIP_PAD, CLIP_MAX_DEG)
    frame = box(b[0] - pw, b[1] - ph, b[2] + pw, b[3] + ph)
    fa = frame.area
    out = []

    # ---- области и страны ---------------------------------------------------
    seen0, geo0 = {}, {}
    for f in gc.admin1_features(CACHE):
        g = None
        try:
            g = shape(f['geometry']).buffer(0)
        except Exception:
            continue
        if g.is_empty or not g.intersects(frame):
            continue
        g = g.intersection(frame)
        if g.is_empty:
            continue
        p = f['properties']
        admin = p.get('admin')
        seen0[admin] = seen0.get(admin, 0) + g.area
        if admin not in geo0 or g.area > geo0[admin].area:
            geo0[admin] = g
        if g.area < fa * 0.004:
            continue
        nm = (p.get(LANG.get(admin)) if LANG.get(admin) else None) or p.get('name')
        if not nm:
            continue
        pt = g.representative_point()
        out.append({'x': round(pt.x, 3), 'y': round(pt.y, 3), 't': nm, 'k': 'adm1'})
    for admin, area in sorted(seen0.items(), key=lambda kv: -kv[1]):
        if area < fa * 0.02:
            continue
        pt = geo0[admin].representative_point()
        out.append({'x': round(pt.x, 3), 'y': round(pt.y, 3),
                    't': NAME0.get(admin, admin), 'k': 'adm0'})

    # ---- города -------------------------------------------------------------
    path = os.path.join(CACHE, 'ne_10m_populated_places.geojson')
    cities = []
    with open(path, encoding='utf-8') as f:
        for feat in json.load(f)['features']:
            p = feat['properties']
            x, y = feat['geometry']['coordinates'][:2]
            if not (frame.bounds[0] <= x <= frame.bounds[2]
                    and frame.bounds[1] <= y <= frame.bounds[3]):
                continue
            admin = p.get('ADM0NAME')
            nm = (p.get(CITY_LANG.get(admin)) if CITY_LANG.get(admin) else None) \
                or p.get('NAME')
            if not nm:
                continue
            cities.append((p.get('POP_MAX') or 0, {
                'x': round(x, 3), 'y': round(y, 3), 't': nm, 'k': 'city',
                'p': p.get('POP_MAX') or 0}))
    cities.sort(key=lambda c: -c[0])
    # чем шире рамка, тем крупнее должны быть города, чтобы карта не заросла
    keep = 45 if (b[2] - b[0]) > 8 else 30
    out.extend(c[1] for c in cities[:keep])

    res = {'domain': domain_id, 'labels': out,
           'note': ('подписи на местном языке: города и области Natural Earth '
                    '(tools/build_domain_labels.py); растровые подписи Esri '
                    'локализовать нельзя')}
    p = os.path.join(DOM, domain_id + '_labels.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, separators=(',', ':'))
    print('%-11s подписей %d (городов %d), %.0f КБ -> %s'
          % (domain_id, len(out), min(keep, len(cities)),
             os.path.getsize(p) / 1024.0, os.path.relpath(p, ROOT)))


def main():
    ids = sorted(os.path.splitext(os.path.basename(p))[0]
                 for p in glob.glob(os.path.join(DOM, '*.json'))
                 if not p.endswith(('_stops.json', '_bundle.json',
                                    '_bundles.json', '_base.json',
                                    '_labels.json')))
    for i in ids:
        build(i)


if __name__ == '__main__':
    main()
