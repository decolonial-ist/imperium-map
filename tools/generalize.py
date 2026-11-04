"""Картографическое обобщение ярусов показа (03.11.2026, куратор: «вздрочь это капли,
всякие маленькие хуйнюшки на карте»).

Срезы data/years держат берег OSM как есть: дельты Лены, Яны, Волги, финские шхеры -
тысячи островков в 1-5 км². На масштабе показа они меньше пикселя и рисуются каплями.
Здесь: 1) закрытие береговой части (buffer +d, -d): островки, разделённые протокой уже
d, сливаются в одну сушу - считается один раз на срез и кэшируется (cache/gen_union);
2) части и дырки меньше min_km2 снимаются везде, порог свой у каждого яруса (и крошки
швов внутри суши). Данные (data/years) не трогаются - только ярусы показа.
"""
import hashlib
import math
import os

from shapely import wkb
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'cache', 'gen_union')
CLOSE = 0.006          # протока уже 0,006° (~0,5 км) сливается - одна для всех ярусов
V = 1


def km2(p):
    return p.area * 111.32 ** 2 * math.cos(math.radians(p.centroid.y))


def _polys(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == 'Polygon':
        return [g]
    if g.geom_type == 'MultiPolygon':
        return list(g.geoms)
    return [p for p in getattr(g, 'geoms', []) if p.geom_type == 'Polygon']


def close_coast(g, band, close_deg=CLOSE):
    """Закрытие береговой части среза (в полосе band = coast_osm.coast_band())."""
    if g is None or g.is_empty:
        return g
    coast = g.intersection(band)
    inland = g.difference(band)
    closed = coast.buffer(close_deg).buffer(-close_deg).buffer(0).intersection(band)
    return unary_union([closed, inland]).buffer(0)


def closed(key, g, band, close_deg=CLOSE):
    """То же с кэшем на диске: ключ - срез и отпечаток его геометрии."""
    if g is None or g.is_empty:
        return g
    os.makedirs(CACHE, exist_ok=True)
    raw = g.wkb
    h = hashlib.md5(raw).hexdigest()[:12]
    path = os.path.join(CACHE, f'{key}_{close_deg}_{V}_{h}.wkb')
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return wkb.loads(f.read())
    out = close_coast(g, band, close_deg)
    for old in os.listdir(CACHE):              # прежние отпечатки этого среза - вон
        if old.startswith(f'{key}_{close_deg}_{V}_') and old != os.path.basename(path):
            os.remove(os.path.join(CACHE, old))
    with open(path, 'wb') as f:
        f.write(out.wkb)
    return out


def drop_small(g, min_km2):
    """Снять части и дырки меньше min_km2."""
    out = []
    for p in _polys(g):
        if km2(p) < min_km2:
            continue
        holes = [i for i in p.interiors if km2(Polygon(i)) >= min_km2]
        out.append(Polygon(p.exterior, holes) if len(holes) != len(p.interiors) else p)
    if not out:
        return None
    return out[0] if len(out) == 1 else MultiPolygon(out)


def generalize(key, g, min_km2, band, close_deg=CLOSE):
    return drop_small(closed(key, g, band, close_deg), min_km2)
