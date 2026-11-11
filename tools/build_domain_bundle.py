#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Пакет встраиваемой карты: один файл на народ (задача куратора 31.08.2026).

«Жёстко режь количество шагов для встраиваемых карт, чтобы оно было легко и
быстро загружаемо. И саму карту обрежь если надо, всё в пользу скорости.
Чтобы с телефона мгновенно открывалось.»

Полная карта на каждой дате СЧИТАЕТ картинку в браузере: тянет годовой срез
мира (по полмегабайта), вычитает из него потери контроля и постсоветские
вырезы, докладывает занятое фронтом, подрезает швы. Для телефона это долго и
тяжело. Здесь всё то же самое считается ЗАРАНЕЕ и только внутри рамки народа:

- шагов остаётся не больше MAX_STEPS - берутся самые весомые (вес проставлен
  в <народ>_stops.json: у изменений контура это изменившаяся площадь, у
  событий - постоянная), первый и последний шаг остаются всегда;
- на каждом шаге геометрия уже СОБРАНА: контур империи минус вырезы, плюс
  занятое фронтом и постсоветские приобретения; отдельно остроги, Беларусь и
  сфера влияния;
- всё обрезано рамкой домена и упрощено под её масштаб, координаты округлены.

На выходе data/domains/<народ>_bundle.json - карта в браузере грузит ЕГО
ОДНОГО и больше ничего. Побочная выгода: геометрия готова к отрисовке без
WebGL (у куратора на телефоне включён режим блокировки iOS, который WebGL
запрещает, - 31.08.2026 карта на его айфоне не открывалась вовсе).

Запуск:

    cd ~/tmp/imperium-map && .venv/bin/python3 tools/build_domain_bundle.py
    ... --domain nokhchi --max-steps 12
"""
import argparse
import glob
import json
import math
import os

import shapely
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import unary_union

import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.normpath(os.path.join(HERE, '..'))
import geoclean as gc  # noqa: E402
DATA = os.path.join(ROOT, 'data')
DOM = os.path.join(DATA, 'domains')
CACHE = os.path.join(ROOT, 'cache')

MAX_STEPS = 12
# Резать геометрию РОВНО по рамке камеры нельзя: обрез виден - красное
# кончается прямой линией по краю кадра, да ещё и с обводкой. Режем с запасом,
# чтобы шов ушёл за экран даже когда читатель отвёл камеру в мягкую зону.
# Запас считается по ФОРМЕ ОКНА, а не только по доле рамки: карта садится на
# рамку целиком, и если окно шире рамки (16:10 у встройки, широкий монитор),
# по бокам видно землю ЗА рамкой. Первый заход 31.08.2026 резал ровно по
# рамке с запасом в 40%, и у Нохчи по краям кадра стояли две прямые красные
# стены - край обрезки. Считаем на диапазон пропорций окна от 0,55 (телефон
# в столбик) до 1,9 (широкая встройка).
# 08.11.2026, куратор по встройке Украины на 1853 («а это что за прямые линии?»):
# пружина камеры пускает территорию до края экрана, то есть в кадр попадает
# земля на целый экран за рамкой, а резка шла в 40% с потолком 3° - и с востока
# стоял прямой меридиан 44,6°. Запас - 1,2 размера рамки, потолок 30°.
CLIP_PAD = 1.2
ASPECT_MAX = 1.9
ASPECT_MIN = 0.55
CLIP_MAX_DEG = 30.0
# «Рейд не вырезает» - то же правило, что в index.html (NO_CUT) и build_losses
NO_CUT = {'contested'}


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def ms(iso, end=False):
    p = [int(x) for x in str(iso).split('-')[:3]]
    while len(p) < 3:
        p.append(1)
    import datetime
    d = datetime.date(p[0], p[1], p[2])
    return d.toordinal() * 86400000 + (86399999 if end else 0)


def geom_of(f):
    g = f.get('geometry')
    if not g:
        return None
    try:
        s = shape(g).buffer(0)
    except Exception:
        return None
    return None if s.is_empty else s


def drop_slivers(g, min_area):
    """Выбросить осколки: куски и дырки мельче порога.

    31.08.2026: у Украинцев весь слой империи не рисовался вовсе, хотя
    геометрия была валидной. Причина - те же грабли, что 30.08 с Куршской
    косой: в мультиполигоне лежали обрезки в четыре-шесть точек (следы
    обрезки рамкой), и триангулятор MapLibre ронял на них ВЕСЬ слой. Порядок
    полигонов от крупного к мелкому эту породу дефектов лечит не всегда -
    осколки надо просто убирать, на показе они и так невидимы.
    """
    from shapely.geometry import MultiPolygon, Polygon
    polys = ([g] if g.geom_type == 'Polygon'
             else list(g.geoms) if g.geom_type == 'MultiPolygon' else [])
    out = []
    for p in polys:
        if p.area < min_area or len(p.exterior.coords) < 5:
            continue
        holes = [r for r in p.interiors
                 if Polygon(r).area >= min_area / 2 and len(r.coords) >= 5]
        out.append(Polygon(p.exterior, holes))
    if not out:
        return None
    return out[0] if len(out) == 1 else MultiPolygon(out)


def clean(g, frame, tol, nd):
    """Обрезать рамкой, упростить под её масштаб, выбросить осколки, округлить."""
    if g is None or g.is_empty:
        return None
    g = g.intersection(frame)
    if g.is_empty:
        return None
    g = g.simplify(tol, preserve_topology=True).buffer(0)
    if g.is_empty:
        return None
    # 08.11.2026, куратор («вздрочь»): ободки толщиной в пиксель вдоль чужих границ
    # (Дунай у Валахии 1853, 20-100 км²) и косы-ниточки снимаем: тонкие (4A/L < 0,06°)
    # и мелкие (< 0,02 град², около 150 км²) куски
    parts = list(g.geoms) if g.geom_type == 'MultiPolygon' else [g]
    parts = [p for p in parts if not (p.area < 0.02 and p.length > 0 and 4 * p.area / p.length < 0.06)]
    if not parts:
        return None
    g = unary_union(parts) if len(parts) > 1 else parts[0]
    # Округление координат делаем СЕТКОЙ ТОЧНОСТИ, а не round() по месту.
    # 31.08.2026: у Украинцев слой империи не рисовался целиком, и виноват был
    # обычный round до четвёртого знака - он сводил соседние вершины в одну и
    # рождал самопересекающиеся осколки (бабочки) у Очакова. Такой кусок
    # роняет триангулятор MapLibre вместе со всем слоем. set_precision снимает
    # вершины по сетке и возвращает ВАЛИДНУЮ геометрию.
    try:
        g = shapely.set_precision(g, 10.0 ** -nd)
    except Exception:
        g = g.buffer(0)
    if g.is_empty:
        return None
    if not g.is_valid:
        g = g.buffer(0)
    g = drop_slivers(g, tol * tol * 4)
    if g is None or g.is_empty:
        return None
    # Полигоны от крупного к мелкому - иначе MapLibre ломает заливку целиком
    # (разбор 30.08.2026 в README: первой в списке стояла Куршская коса, и
    # половину карты закрывал чёрный прямоугольник). Тот же порядок пишут
    # сборщики срезов через geoclean.sort_polygons.
    obj = gc.sort_polygons(gc.sanitize_geom(mapping(g)))

    def rnd(c):
        if isinstance(c[0], (int, float)):
            return [round(c[0], nd), round(c[1], nd)]
        return [rnd(x) for x in c]
    obj['coordinates'] = rnd(obj['coordinates'])
    return obj


def pack_topology(steps):
    """10.11.2026: красное шагов - одной топологией (как data/years_lite.topo.json).

    Соседние шаги делят почти все границы, а пакет хранил полную геометрию
    каждого шага: у Украины 294 шага давали 11,9 МБ (3,8 МБ в сжатии). В
    топологии общая дуга лежит один раз: 2,9 МБ (0,85 МБ в сжатии). Без
    квантования (-q нет): координаты байт в байт те же, сетка точности clean()
    не трогается. Шаг держит в red имя объекта топологии, карта собирает
    геометрию при показе (index.html, redOf). Нет geo2topo - пакет остаётся
    прежним, карта читает оба вида.
    """
    import hashlib
    import subprocess
    import tempfile
    geo2topo = os.path.join(ROOT, 'node_modules', '.bin', 'geo2topo')
    if not os.path.exists(geo2topo):
        print('geo2topo не найден (%s): пакет без топологии; `cd %s && npm ci`'
              % (geo2topo, ROOT), file=sys.stderr)
        return None
    names, order = {}, []
    for st in steps:
        g = st.get('red')
        if not g:
            continue
        h = hashlib.md5(json.dumps(g, sort_keys=True).encode()).hexdigest()
        if h not in names:
            names[h] = 'r%d' % len(names)
            order.append((names[h], g))
        st['_red'] = names[h]
    if not order:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for name, g in order:
            fp = os.path.join(tmp, name + '.json')
            with open(fp, 'w', encoding='utf-8') as f:
                json.dump({'type': 'Feature', 'properties': {}, 'geometry': g}, f)
            files.append(name + '=' + fp)
        res = subprocess.run([geo2topo] + files, capture_output=True, text=True)
    if res.returncode != 0:
        print('geo2topo упал: %s' % res.stderr[:300], file=sys.stderr)
        for st in steps:
            st.pop('_red', None)
        return None
    topo = json.loads(res.stdout)
    for st in steps:
        if '_red' in st:
            st['red'] = st.pop('_red')
    return topo


def pick(stops, n):
    """Оставить n остановок: по весу, но с разгоном по времени.

    Один вес не годится. Первый заход 31.08.2026 отобрал у Нохчи четыре шага
    подряд на 1918-1920 (площадь там гуляла сильнее всего) и не оставил ни
    одного между 1783 и 1859 - крепость Грозная, взятие Ведено и обе войны
    девяностых вылетели. Поэтому вес делится на близость к уже выбранному:
    сосед через год почти ничего не стоит, событие в пустом столетии идёт
    вперёд. Первый и последний шаг остаются всегда.
    """
    if len(stops) <= n:
        return list(stops)
    ts = [ms(s['d']) / (365.2425 * 86400000.0) for s in stops]  # годы
    span = max(ts) - min(ts) or 1.0
    gap = span / n / 2.0                     # ближе этого шаги душат друг друга
    keep = {0, len(stops) - 1}
    while len(keep) < n:
        best, bestv = None, -1.0
        for i, s in enumerate(stops):
            if i in keep:
                continue
            near = min(abs(ts[i] - ts[j]) for j in keep)
            v = s.get('w', 0) * min(1.0, near / gap)
            if v > bestv:
                best, bestv = i, v
        if best is None:
            break
        keep.add(best)
    return [stops[i] for i in sorted(keep)]


# Плотные периоды, на которые собирается СВОЙ пакет. Карта кампании получает
# окно датами и берёт самый узкий пакет, который её окно накрывает: без этого
# у нынешней войны на общем пакете народа оставалось два шага на четыре года.
# Список курируемый: добавить период - добавить сюда строку и пересобрать.
WINDOWS = {
    'ukrainians': [('1917_1921', '1917-11-07', '1921-11-18'),
                   ('1939_1945', '1939-09-17', '1945-06-29'),
                   ('2014_2026', '2014-02-20', None)],
    'nokhchi': [('1785_1864', '1785-01-01', '1864-06-02'),   # 21.05.1864 ст. ст.; до 30.09.2026 стояла старостильная
                ('1990_2009', '1990-11-27', '2009-04-16')],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--domain')
    ap.add_argument('--max-steps', type=int, default=MAX_STEPS)
    a = ap.parse_args()
    ids = ([a.domain] if a.domain else
           sorted(os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(DOM, '*.json'))
                  if not p.endswith(('_stops.json', '_bundle.json',
                                     '_bundles.json', '_base.json'))))
    for i in ids:
        index = [build(i, a.max_steps)]
        for name, w0, w1 in WINDOWS.get(i, []):
            index.append(build(i, a.max_steps, name, w0, w1))
        path = os.path.join(DOM, i + '_bundles.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'domain': i, 'bundles': index}, f, ensure_ascii=False,
                      separators=(',', ':'))
        print('%-11s индекс пакетов: %d' % (i, len(index)))


def build(domain_id, max_steps, window=None, w_from=None, w_to=None):
    dom = load(os.path.join(DOM, domain_id + '.json'))
    b = dom['bbox']
    w, h = b[2] - b[0], b[3] - b[1]
    cl = math.cos(math.radians((b[1] + b[3]) / 2)) or 1.0
    h_lng = h / cl                        # высота рамки в «долготных» градусах
    need_w = max(w, ASPECT_MAX * h_lng)
    need_h = max(h, (w / ASPECT_MIN) * cl)
    pw = min(max((need_w - w) / 2, w * CLIP_PAD), CLIP_MAX_DEG)
    ph = min(max((need_h - h) / 2, h * CLIP_PAD), CLIP_MAX_DEG)
    frame = box(b[0] - pw, b[1] - ph, b[2] + pw, b[3] + ph)
    if b[2] + pw > 180:
        # рамка через 180-й меридиан (empire: Чукотка): восточный хвост
        # рамки - по ту сторону шва, в долготах от -180
        frame = unary_union([box(b[0] - pw, b[1] - ph, 180, b[3] + ph),
                             box(-180, b[1] - ph, b[2] + pw - 360, b[3] + ph)])
    fw = dom['bbox'][2] - dom['bbox'][0]
    tol = fw / 1500.0                     # около пикселя на обзорном кадре
    nd = max(3, min(5, int(round(math.log10(1500.0 / fw))) + 2))
    allstops = load(os.path.join(DOM, domain_id + '_stops.json'))['stops']
    # 07.11.2026: шаги раньше начала времени домена (build_domains.py, 'time') в пакет
    # не идут: встройка Украины открывалась 1500 годом с красной Чернигово-Северщиной,
    # куратор: «с самого начала нашего исчисления россия владела частью украины. ты
    # понимаешь как это звучит?». Шаг несёт полное состояние, «шаг до» не нужен.
    t_dom = (dom.get('time') or [None])[0]
    if t_dom and not (w_from or w_to):
        allstops = [s for s in allstops if ms(s['d']) >= ms(t_dom)]
    if w_from or w_to:
        t0 = ms(w_from) if w_from else -8.64e15
        t1 = ms(w_to, True) if w_to else 8.64e15
        inside = [s for s in allstops if t0 <= ms(s['d']) <= t1]
        # шаг ПЕРЕД окном нужен: иначе первая половина окна рисуется пустой
        before = [s for s in allstops if ms(s['d']) < t0]
        allstops = (before[-1:] if before else []) + inside
    # куратор 01.11.2026: у народа все известные шаги, а не выборка. Подписи - только
    # у шагов, написанных руками (data/domains/<id>_steps.json, tools/build_steps_embed.py);
    # служебное «контур изменился на N км²» читателю не показываем
    manual_path = os.path.join(DOM, domain_id + '_steps.json')
    manual = load(manual_path)['stops'] if os.path.exists(manual_path) else None
    if manual:
        t0 = ms(w_from) if w_from else -8.64e15
        t1 = ms(w_to, True) if w_to else 8.64e15
        byd = {s['d']: dict(s, why='') for s in allstops}
        byd.update({s['d']: s for s in manual if t0 <= ms(s['d']) <= t1})
        steps = sorted(byd.values(), key=lambda s: ms(s['d']))
    else:
        steps = pick(allstops, max_steps)

    # ---- сырьё -------------------------------------------------------------
    years = [(str(k), ms(str(k))) for k in load(os.path.join(DATA, 'manifest.json'))['years']]
    years.sort(key=lambda x: x[1])

    loss = []
    lman = os.path.join(DATA, 'losses', 'manifest.json')
    if os.path.exists(lman):
        for e in load(lman).get('episodes', []):
            p = os.path.join(DATA, 'losses', e['slug'] + '.geojson')
            if not os.path.exists(p):
                continue
            for f in load(p).get('features', []):
                pr = f['properties']
                g = geom_of(f)
                if g is None or not g.intersects(frame):
                    continue
                loss.append((ms(pr['from']), ms(pr['to'], True) if pr.get('to')
                             else 8.64e15, pr.get('kind'), g))

    # вырезы удержания (build_uprisings): на полной карте их режет RCUT в index.html
    rcp = os.path.join(DATA, 'resistance', 'cuts.geojson')
    if os.path.exists(rcp):
        for f in load(rcp).get('features', []):
            pr = f['properties']
            g = geom_of(f)
            if g is None or not g.intersects(frame):
                continue
            loss.append((ms(pr['hold_from']), ms(pr['hold_to'], True), 'hold', g))

    ps = []
    psp = os.path.join(DATA, 'postsoviet.geojson')
    if os.path.exists(psp):
        for f in load(psp).get('features', []):
            pr = f['properties']
            g = geom_of(f)
            if g is None or not g.intersects(frame):
                continue
            ps.append((ms(pr['from']), ms(pr['to'], True) if pr.get('to')
                       else 8.64e15, pr.get('paint'), g))

    ost = []
    op = os.path.join(DATA, 'ostrogs', 'ostrogs.geojson')
    if os.path.exists(op):
        for f in load(op).get('features', []):
            pr = f['properties']
            g = geom_of(f)
            if g is None or not g.intersects(frame):
                continue
            # 07.11.2026: во встройку идут ТОЧКИ (центр острога из свойств), как в полной
            # карте (ostrogDot): слой ostrog-dot типа circle полигон-кружок не рисует,
            # и куратор не увидел гарнизоны на шаге 1650 («почему гарнизонов не отмечено?»)
            pt = Point(pr['lon'], pr['lat']) if 'lon' in pr and 'lat' in pr else g.centroid
            ost.append((ms(pr['from']),
                        ms(pr['to'], True) if pr.get('to') else 8.64e15,
                        ms(pr['red_from']) if pr.get('red_from') else 8.64e15, pt))

    sph = []
    sp = os.path.join(DATA, 'sphere.geojson')
    if os.path.exists(sp):
        for f in load(sp).get('features', []):
            pr = f['properties']
            g = geom_of(f)
            if g is None or not g.intersects(frame):
                continue
            sph.append((ms(pr.get('gfrom') or pr['from']),
                        ms(pr.get('gto') or pr['to'], True)
                        if (pr.get('gto') or pr.get('to')) else 8.64e15, g))

    bel = None
    bp = os.path.join(DATA, 'belarus.geojson')
    if os.path.exists(bp):
        gs = [g for g in (geom_of(f) for f in load(bp).get('features', []))
              if g is not None and g.intersects(frame)]
        if gs:
            bel = unary_union(gs)
    BEL_FROM = ms('1991-12-26')

    dsmf = {}
    dsp = os.path.join(DATA, 'deepstate', 'manifest.json')
    if os.path.exists(dsp):
        m = load(dsp)
        for day in (m.get('months') or m.get('days') or []):
            dsmf[ms(day)] = day
    front_days = sorted(dsmf)

    out_steps = []
    for st in steps:
        t = ms(st['d'])
        key = None
        for k, kt in years:
            if kt <= t:
                key = k
        red = None
        if key:
            p = os.path.join(DATA, 'years', key + '.geojson')
            gs = [g for g in (geom_of(f) for f in load(p).get('features', []))
                  if g is not None and g.intersects(frame)]
            if gs:
                red = unary_union([g.intersection(frame) for g in gs])
        # вырезы: потери контроля (кроме удержанных) и постсоветские дырки
        cuts = [g for (t0, t1, kind, g) in loss
                if t0 <= t <= t1 and kind not in NO_CUT]
        cuts += [g for (t0, t1, paint, g) in ps if t0 <= t <= t1 and paint == 'cut']
        if red is not None and cuts:
            red = red.difference(unary_union(cuts))
        # приобретения постсоветских эпизодов (Крым, ОРДЛО) и занятое фронтом
        adds = [g for (t0, t1, paint, g) in ps if t0 <= t <= t1 and paint == 'red']
        fd = None
        for d in front_days:
            if d <= t:
                fd = dsmf[d]
        if fd:
            fp = os.path.join(DATA, 'deepstate', 'days', fd + '.geojson')
            if os.path.exists(fp):
                gs = [geom_of(f) for f in load(fp).get('features', [])
                      if f.get('properties', {}).get('s') == 'occupied']
                gs = [g for g in gs if g is not None and g.intersects(frame)]
                if gs:
                    adds.append(unary_union([g.intersection(frame) for g in gs]))
        if adds:
            red = unary_union(([red] if red is not None else []) + adds)

        step = {'d': st['d'], 'why': st['why']}
        g = clean(red, frame, tol, nd)
        if g:
            step['red'] = g
        og = [g for (t0, t1, tred, g) in ost if t0 <= t <= t1 and t < tred]
        if og:
            step['ostrog'] = {'type': 'MultiPoint',
                              'coordinates': [[round(q.x, nd), round(q.y, nd)] for q in og]}
        sg = [g for (t0, t1, g) in sph if t0 <= t <= t1]
        if sg:
            g = clean(unary_union(sg), frame, tol, nd)
            if g:
                step['sphere'] = g
        if bel is not None and t >= BEL_FROM:
            g = clean(bel, frame, tol, nd)
            if g:
                step['by'] = g
        out_steps.append(step)

    out = {
        'domain': domain_id,
        'title': dom['title'],
        'bbox': dom['bbox'],
        'bbox_geom': dom['bbox_geom'],
        'soft': dom['soft'],
        'center': dom['center'],
        'zoom': dom['zoom'],
        'matrix': dom['matrix'],
        'note': ('пакет встраиваемой карты: геометрия уже собрана, обрезана '
                 'рамкой домена и упрощена (tools/build_domain_bundle.py); '
                 'карта грузит только этот файл'),
        'simplify_deg': round(tol, 5),
        'steps': out_steps,
    }
    out['clip'] = list(frame.bounds)
    # 01.11.2026 куратор о подписях шагов народа: «убирай пока. нахуй они не нужны» -
    # подпись под картой у встройки народа выключена; ручные шаги остаются остановками.
    # 07.11.2026: у главной (empire, шаги подобраны руками) подпись остаётся - 01.11 её
    # выключило заодно, встройка главной шла без текста шагов.
    out['captions'] = bool(dom.get('manual_stops'))
    out['window'] = [w_from, w_to] if (w_from or w_to) else None
    topo = pack_topology(out_steps)
    if topo:
        out['topo'] = topo
    name = domain_id + ('_' + window if window else '') + '_bundle.json'
    path = os.path.join(DOM, name)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    kb = os.path.getsize(path) / 1024.0
    print('%-11s %-10s шагов %2d, %5.0f КБ -> %s'
          % (domain_id, window or 'весь домен', len(out_steps), kb,
             os.path.relpath(path, ROOT)))
    return {'file': name, 'from': w_from, 'to': w_to,
            'first': out_steps[0]['d'] if out_steps else None,
            'last': out_steps[-1]['d'] if out_steps else None,
            'steps': len(out_steps), 'kb': round(kb)}


if __name__ == '__main__':
    main()
