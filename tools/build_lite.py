#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Облегчённые срезы для телефона (задача A4, «го» куратора 01.09.2026).

Полная карта тянет мировые срезы по полмегабайта: на телефоне это минуты
белого экрана, а при включённом режиме блокировки iOS она не рисуется вовсе.
Здесь те же срезы пересобираются в лёгкие: упрощение до 0,02° (около двух
километров - на обзорном масштабе телефона невидимо), сортировка полигонов от
крупного к мелкому, сетка точности, выброс осколков. Замер на трёх срезах:
1783 - 215 КБ против 17 КБ по сети, 1900 - 166 против 15, 1992 - 1686 КБ
против 39.

Правила те же, что у пакетов доменов (build_domain_bundle.py), и по той же
причине: MapLibre и Leaflet роняют заливку из-за одной дефектной части
мультиполигона.

На выходе:
    data/years_lite/<ключ>.geojson       - облегчённые срезы ядра
    data/deepstate/months_lite/<день>.geojson - облегчённые снимки фронта
    data/years_lite.topo.json            - вся облегчённая линия времени одной
                                           топологией с общими дугами (0,6 МБ;
                                           карта берёт её с 15.09.2026, пакет
                                           years_lite_bundle.json снят в тот же
                                           день - этап 4, хвост T1)
    data/lite_manifest.json              - что собрано и с каким упрощением

С `--level mid` (этап 4 плана 15.09.2026) - средний уровень точных срезов:
    data/years_mid/<ключ>.geojson        - упрощение 0,002° (около 200 м),
                                           координаты до 5 знаков; карта берёт
                                           его вместо полного до масштаба 8
    data/mid_manifest.json               - опись: срезы, упрощение, байты
Пакет, топологию, снимки фронта, охваты и lite_manifest.json средний уровень
не пишет и не трогает.

Запуск:

    cd ~/tmp/imperium-map && .venv/bin/python3 tools/build_lite.py
    ... --tol 0.02 --only 1783   (для проверки одного среза)
    ... --level mid              (средний уровень, после облегчённого)
    ... --level mid --only 1991-04-09   (проба: опись и штамп не пишутся)
"""
import argparse
import json
import os
import subprocess
import sys

import shapely
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import geoclean as gc  # noqa: E402
from build_domain_bundle import drop_slivers  # noqa: E402

DATA = os.path.join(ROOT, 'data')
TOL = 0.02
ND = 3
# Квантование топологии (этап 2 плана 15.09.2026): сетка 1e5 на охват всех
# срезов - шаг около 200 м, мельче упрощения 0,02° в восемь раз, на кадре
# не видно. При 1e4 (около 2 км) файл 0,34 МБ вместо 0,61, но это уже грубее
# самих срезов.
TOPO_Q = '1e5'
# Средний уровень точных срезов (этап 4 плана 15.09.2026). Полный срез 1991
# года - 17 МБ сырыми, 6,6 МБ сжатыми и 440 тысяч вершин, и карта брала его на
# каждой остановке ползунка с масштаба 4,5; облегчённый 0,02° на масштабе 5 и
# выше уже виден (косы и лиманы Азова). Средний - 0,002° (около 200 м) и пять
# знаков: замер на срезе 1991 года - около 148 КБ сжатыми и 20 тысяч вершин.
TOL_MID = 0.002
ND_MID = 5


def lighten(fc, tol, nd):
    parts = []
    for f in fc.get('features', []):
        g = f.get('geometry')
        if not g:
            continue
        try:
            s = shape(g).buffer(0)
        except Exception:
            continue
        if not s.is_empty:
            parts.append(s)
    if not parts:
        return None
    g = unary_union(parts).simplify(tol, preserve_topology=True).buffer(0)
    if g.is_empty:
        return None
    try:
        g = shapely.set_precision(g, 10.0 ** -nd)
    except Exception:
        g = g.buffer(0)
    if not g.is_valid:
        g = g.buffer(0)
    g = drop_slivers(g, tol * tol * 4)
    if g is None or g.is_empty:
        return None
    return gc.sort_polygons(gc.sanitize_geom(mapping(g)))


def write(path, geom, src, level='lite'):
    # level - признак уровня в свойствах фичи ('lite' или 'mid'): по нему
    # index.html различает уровни в ключах кэшей подрезки фронта и вычитаний
    fc = {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {level: True, 'src': src},
         'geometry': geom}]}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(fc, f, ensure_ascii=False, separators=(',', ':'))
    return os.path.getsize(path)


def main_mid(a):
    """Средний уровень: только срезы data/years_mid и их опись.

    Правила чистки те же (lighten), меняются упрощение и сетка точности.
    Пакет линии времени, топология, снимки фронта, охваты и
    lite_manifest.json - дело облегчённого уровня, здесь не пишутся.
    """
    tol = TOL_MID if a.tol is None else a.tol
    out = os.path.join(DATA, 'years_mid')
    os.makedirs(out, exist_ok=True)
    mf = json.load(open(os.path.join(DATA, 'manifest.json'), encoding='utf-8'))
    keys = [str(k) for k in mf['years']]
    if a.only:
        keys = [k for k in keys if k == a.only]
    redo = set(a.keys.split(',')) if a.keys else None
    done, skipped, sizes = [], [], {}
    for k in keys:
        src = os.path.join(DATA, 'years', k + '.geojson')
        if not os.path.exists(src):
            continue
        dst = os.path.join(out, k + '.geojson')
        if redo is not None and k not in redo and os.path.exists(dst):
            sizes[k] = os.path.getsize(dst)
            done.append(k)
            continue
        g = lighten(json.load(open(src, encoding='utf-8')), tol, ND_MID)
        if g is None:
            skipped.append(k)
            continue
        sizes[k] = write(dst, g, 'data/years/%s.geojson' % k, level='mid')
        done.append(k)
    total = sum(sizes.values())
    if a.only:
        # проба на одном срезе: опись с одним ключом отправила бы карту за
        # полными срезами на всех остальных датах - опись и штамп не трогаем
        print('средний уровень, проба: срезов %d (%.2f МБ), пропущено %d; '
              'опись и штамп не тронуты' % (len(done), total / 1048576, len(skipped)))
        return
    man = {
        'note': ('средний уровень точных срезов: упрощение %.3f°, координаты '
                 'до %d знаков; сборка tools/build_lite.py --level mid'
                 % (tol, ND_MID)),
        'tol': tol, 'nd': ND_MID, 'years': done, 'skipped': skipped,
        'bytes': sizes,
    }
    with open(os.path.join(DATA, 'mid_manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(man, f, ensure_ascii=False, separators=(',', ':'))
    # штамп для check_build_order: после 'lite', перед 'start'
    gc.write_stamp('mid')
    print('средний уровень: срезов %d (%.1f МБ), пропущено %d'
          % (len(done), total / 1048576, len(skipped)))
    if skipped:
        print('пустые после упрощения:', ', '.join(skipped[:8]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--level', choices=('lite', 'mid'), default='lite')
    ap.add_argument('--tol', type=float, default=None)
    ap.add_argument('--only')
    # --keys k1,k2: пересобрать только эти срезы, остальные взять готовыми из
    # data/years_lite (years_mid); топология, опись и штамп - по всем
    # (tools/rebuild.py --changed, 24.09.2026)
    ap.add_argument('--keys')
    a = ap.parse_args()
    if a.level == 'mid':
        return main_mid(a)
    if a.tol is None:
        a.tol = TOL

    out_y = os.path.join(DATA, 'years_lite')
    out_m = os.path.join(DATA, 'deepstate', 'months_lite')
    os.makedirs(out_y, exist_ok=True)
    os.makedirs(out_m, exist_ok=True)

    mf = json.load(open(os.path.join(DATA, 'manifest.json'), encoding='utf-8'))
    keys = [str(k) for k in mf['years']]
    if a.only:
        keys = [k for k in keys if k == a.only]
    redo = set(a.keys.split(',')) if a.keys else None
    done_y, size_y, skipped = [], 0, []
    bounds = {}                     # охват среза [зап, юг, вост, сев] - стартовому виду
    for k in keys:
        src = os.path.join(DATA, 'years', k + '.geojson')
        if not os.path.exists(src):
            continue
        dst = os.path.join(out_y, k + '.geojson')
        if redo is not None and k not in redo and os.path.exists(dst):
            with open(dst, encoding='utf-8') as f:
                g = json.load(f)['features'][0]['geometry']
            size_y += os.path.getsize(dst)
        else:
            g = lighten(json.load(open(src, encoding='utf-8')), a.tol, ND)
            if g is None:
                skipped.append(k)
                continue
            size_y += write(dst, g, 'data/years/%s.geojson' % k)
        done_y.append(k)
        bounds[k] = [round(v, 3) for v in shape(g).bounds]

    dsp = os.path.join(DATA, 'deepstate', 'manifest.json')
    done_m, size_m = [], 0
    old_lm = os.path.join(DATA, 'lite_manifest.json')
    if a.keys and os.path.exists(old_lm):
        # снимки фронта от правки таблиц ядра не зависят - берём готовые
        with open(old_lm, encoding='utf-8') as f:
            done_m = json.load(f).get('months') or []
        size_m = sum(os.path.getsize(os.path.join(out_m, d + '.geojson'))
                     for d in done_m if os.path.exists(os.path.join(out_m, d + '.geojson')))
    elif os.path.exists(dsp) and not a.only:
        ds = json.load(open(dsp, encoding='utf-8'))
        for day in (ds.get('months') or []):
            src = os.path.join(DATA, 'deepstate', 'days', day + '.geojson')
            if not os.path.exists(src):
                continue
            fc = json.load(open(src, encoding='utf-8'))
            occ = {'features': [f for f in fc.get('features', [])
                                if f.get('properties', {}).get('s') == 'occupied']}
            g = lighten(occ, a.tol, ND)
            if g is None:
                continue
            size_m += write(os.path.join(out_m, day + '.geojson'), g,
                            'data/deepstate/days/%s.geojson' % day)
            done_m.append(day)

    # Пакет всей облегчённой линии времени одним файлом (years_lite_bundle.json,
    # 06.09.2026) снят 15.09.2026 - этап 4 плана загрузки, хвост T1: 17 МБ
    # сырыми и 5,6 МБ сжатыми, а карта берёт ту же линию времени топологией
    # (ниже, 0,65 МБ), запасной путь - срезы поштучно. Поле bundle в описи - null.

    # Вся облегчённая линия времени ОДНОЙ ТОПОЛОГИЕЙ (этап 2 плана 15.09.2026,
    # «го» куратора). Пакет из 233 копий срезов весил 5,6 МБ сжатыми, хотя
    # соседние срезы делят одни и те же границы: TopoJSON хранит каждую дугу
    # один раз, а срез - как список ссылок на дуги. Замер 15.09: 30 868 дуг,
    # 98 тысяч точек, 0,61 МБ сжатыми при квантовании 1e5. Карта берёт файл
    # одним запросом и собирает срез из дуг при первом обращении
    # (vendor/topojson-client.min.js). Сборка - geo2topo из topojson-server
    # (package.json, `npm ci`); без него топология не собирается, карта
    # греется срезами поштучно, и об этом говорится в конце вывода.
    tpath = os.path.join(DATA, 'years_lite.topo.json')
    tsize = 0
    geo2topo = os.path.join(ROOT, 'node_modules', '.bin', 'geo2topo')
    if a.only:
        pass                                   # один срез - топологию не трогаем
    elif os.path.exists(geo2topo) and done_y:
        cmd = [geo2topo, '-q', TOPO_Q] + [os.path.join(out_y, k + '.geojson') for k in done_y]
        with open(tpath, 'w', encoding='utf-8') as f:
            subprocess.run(cmd, stdout=f, check=True)
        topo = json.load(open(tpath, encoding='utf-8'))
        missing = [k for k in done_y if k not in topo.get('objects', {})]
        if missing:
            sys.exit('топология без срезов: %s' % ', '.join(missing[:8]))
        tsize = os.path.getsize(tpath)
    else:
        print('geo2topo не найден (%s): топология не собрана, поставьте node-инструменты '
              'командой `cd %s && npm ci`' % (geo2topo, ROOT), file=sys.stderr)

    man = {
        'note': ('облегчённые срезы для телефона: упрощение %.3f°, координаты '
                 'до %d знаков; сборка tools/build_lite.py' % (a.tol, ND)),
        'tol': a.tol, 'years': done_y, 'months': done_m,
        'skipped': skipped,
        'bundle': None,                        # пакет снят 15.09.2026 (T1)
        'topology': 'data/years_lite.topo.json' if tsize else None,
        'topology_q': TOPO_Q,
        # Охват каждого среза (15.09.2026, этап 3): index.html подгоняет
        # стартовый вид под срез даты ДО первого запроса тайлов подложки, а
        # не после первого рендера - иначе подложка успевала запросить полсотни
        # тайлов обзорного вида, которые тут же выбрасывались.
        'bounds': bounds,
    }
    with open(os.path.join(DATA, 'lite_manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(man, f, ensure_ascii=False, separators=(',', ':'))
    # штамп для check_build_order: облегчённые срезы производны от обычных и
    # обязаны пересобираться ПОСЛЕ всей цепочки, иначе телефон покажет
    # вчерашнюю карту
    gc.write_stamp('lite')
    print('срезов %d (%.1f МБ), снимков фронта %d (%.1f МБ), пропущено %d, '
          'топология %.1f МБ'
          % (len(done_y), size_y / 1048576, len(done_m), size_m / 1048576,
             len(skipped), tsize / 1048576))
    if skipped:
        print('пустые после упрощения:', ', '.join(skipped[:8]))


if __name__ == '__main__':
    main()
