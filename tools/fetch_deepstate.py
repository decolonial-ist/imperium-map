#!/usr/bin/env python3
"""Слой войны 2022+: история DeepStateMAP -> дневные срезы фронта.

Источник: https://deepstatemap.live/api/history/public (список снапшотов,
~ежедневно с 03.04.2022) и /api/history/<id>/geojson (снапшот целиком).

На выходе:
- cache/deepstate/<id>.json.gz — сырые снапшоты (кэш, в git не идёт);
- data/deepstate/days/<YYYY-MM-DD>.geojson — статусные полигоны на день
  (occupied / liberated / unknown), 2D-координаты, 4 знака;
- data/deepstate/territories.geojson — статичные оккупированные территории
  (Крым, ОРДЛО, Тузла — 2014; Абхазия, Цхинвали — 2008; Приднестровье — 1992)
  из свежайшего снапшота, с полем from (год начала показа);
- data/deepstate/manifest.json — список дней.

Дата дня — по Киеву. Несколько снапшотов в день -> берём последний.
Запуск повторный безопасен: скачанное не перекачивается.
"""
import gzip
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "cache" / "deepstate"
DAYS = ROOT / "data" / "deepstate" / "days"
OUT = ROOT / "data" / "deepstate"

API = "https://deepstatemap.live/api/history"
UA = {"User-Agent": "Mozilla/5.0 (imperium-map; decolonial.ist research)"}

try:
    from zoneinfo import ZoneInfo
    try:
        KYIV = ZoneInfo("Europe/Kyiv")
    except Exception:
        KYIV = ZoneInfo("Europe/Kiev")
except Exception:
    KYIV = timezone(timedelta(hours=3))

# статусы по заливке: ранние снапшоты подписаны вольно, цвета стабильны
#
# 19.08.2026: #01579b и #ce93d8 раньше не разбирались, и всё, что ими залито,
# молча выпадало из дневных файлов (`FILL_STATUS.get(...)` -> None -> continue).
# Выпадал ровно тот сюжет, ради которого карту и смотрят: Курская операция.
# DeepState красит украинский контроль ВНУТРИ РФ отдельным синим #01579b (в
# подписи то же «Звільнено /// Liberated», что и у зелёного #0f9d58 внутри
# Украины) — с 08.08.2024, 1264 полигона по всей истории. Даём этому свой
# статус `lost`: внутри Украины «освобождено» и потеря контроля империей над
# СВОЕЙ территорией — разные вещи, и рисуются на карте по-разному (см.
# tools/build_losses.py и слой `loss` в index.html).
# #ce93d8 — «Під контролем бойовиків-повстанців ПВК "Вагнер"», единственный
# снапшот 24.06.2023: тоже потеря контроля империей у себя дома, статус
# `mutiny`. #757575 — вариант серой зоны («Contested»/«Contensed»).
FILL_STATUS = {
    "#a52714": "occupied",
    "#0f9d58": "liberated",
    "#0288d1": "liberated",   # ранняя палитра (весна 2022)
    "#bcaaa4": "unknown",
    "#bdbdbd": "unknown",
    "#757575": "unknown",     # «Contested» / «Contensed»
    "#01579b": "lost",        # контроль Украины на территории РФ (Курск, 2024+)
    "#ce93d8": "mutiny",      # мятеж «Вагнера», 24.06.2023
}
# статичные территории: ключ в name -> год, с которого показывать
TERRITORIES = {
    "territories.crimea": 2014,
    "territories.ordlo": 2014,
    "territories.tuzla": 2014,
    "territories.abkhazia": 2008,
    "territories.tskhinvali": 2008,
    "territories.transnistria": 1992,
}


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))
            print(f"  retry {url}: {e}", file=sys.stderr)


def round2d(coords):
    if isinstance(coords, (int, float)):
        return round(coords, 4)
    if (len(coords) in (2, 3)
            and all(isinstance(x, (int, float)) for x in coords)):
        return [round(coords[0], 4), round(coords[1], 4)]
    return [round2d(c) for c in coords]


def polygons(feature):
    """Полигоны фичи, разворачивая GeometryCollection."""
    g = feature.get("geometry") or {}
    if g.get("type") in ("Polygon", "MultiPolygon"):
        yield g
    elif g.get("type") == "GeometryCollection":
        for sub in g.get("geometries", []):
            if sub.get("type") in ("Polygon", "MultiPolygon"):
                yield sub


def day_features(snapshot):
    feats = []
    for f in snapshot.get("features", []):
        name = (f.get("properties") or {}).get("name", "") or ""
        if "territories" in name or name.strip() == "ОРДЛО":
            continue  # статичные территории идут отдельным файлом
        status = FILL_STATUS.get((f.get("properties") or {}).get("fill"))
        if not status:
            continue
        for g in polygons(f):
            feats.append({
                "type": "Feature",
                "properties": {"s": status},
                "geometry": {"type": g["type"],
                             "coordinates": round2d(g["coordinates"])},
            })
    return feats


def build_territories(snapshot):
    feats = []
    for f in snapshot.get("features", []):
        name = (f.get("properties") or {}).get("name", "") or ""
        for key, year in TERRITORIES.items():
            if key in name:
                for g in polygons(f):
                    feats.append({
                        "type": "Feature",
                        "properties": {"s": "occupied", "from": year,
                                       "name": name.split("///")[0].strip()},
                        "geometry": {"type": g["type"],
                                     "coordinates": round2d(g["coordinates"])},
                    })
    return {"type": "FeatureCollection", "features": feats}


def month_picks(days):
    """Помесячная выборка: последний доступный день каждого месяца.

    Решение куратора 19.08.2026: карта показывает фронт 2022+ ПОМЕСЯЧНО,
    обзорно («широкими мазками»), подневная динамика остаётся у самого
    DeepStateMAP. Дневные файлы с диска не удаляются и продолжают собираться —
    это задел; в показ и в историю точки идёт только этот список.
    """
    last = {}
    for day in sorted(days):
        last[day[:7]] = day
    return [last[m] for m in sorted(last)]


def write_manifest():
    have = sorted(p.stem for p in DAYS.glob("*.geojson"))
    months = month_picks(have)
    (OUT / "manifest.json").write_text(json.dumps({
        "source": "DeepStateMAP (deepstatemap.live), история с 03.04.2022",
        "note_months": ("в показ и в историю точки идёт помесячная выборка "
                        "months (последний доступный день месяца) — решение "
                        "куратора 19.08.2026; days остаются на диске как задел"),
        "months": months,
        "days": have,
    }, ensure_ascii=False, indent=1))
    print(f"манифест: дней {len(have)}, месяцев {len(months)}"
          + (f" ({months[0]} … {months[-1]})" if months else ""))
    return have, months


def cached_days():
    """day -> путь к сырому снапшоту, по одному кэшу, без сети.

    id снапшота у DeepState — unix-время его создания, поэтому день (по Киеву)
    и «последний снапшот дня» восстанавливаются из имён файлов кэша ровно так
    же, как их выбирает main() по ответу /api/history/public.
    """
    by_day = {}
    for p in RAW.glob("*.json.gz"):
        try:
            sid = int(p.name.split(".")[0])   # «1727771655.json.gz» -> id
        except ValueError:
            continue
        day = datetime.fromtimestamp(sid, timezone.utc).astimezone(KYIV).date()
        cur = by_day.get(day.isoformat())
        if cur is None or sid > cur[0]:
            by_day[day.isoformat()] = (sid, p)
    return {d: v[1] for d, v in sorted(by_day.items())}


def rebuild_from_cache(dry=False):
    """Пересборка дневных файлов из кэша, без сети.

    Нужна, когда меняется разбор снапшота (например, добавился цвет в
    FILL_STATUS): сырые снапшоты уже лежат в cache/deepstate, перекачивать
    полторы тысячи дней незачем. Пишем только те файлы, содержимое которых
    изменилось, и печатаем, что именно прибавилось по статусам.
    """
    days = cached_days()
    print(f"снапшотов в кэше: {len(days)} дней "
          + (f"({min(days)} … {max(days)})" if days else ""))
    changed = added = 0
    delta = {}
    for day, raw_path in days.items():
        snap = json.loads(gzip.decompress(raw_path.read_bytes()))
        fc = {"type": "FeatureCollection", "features": day_features(snap)}
        body = json.dumps(fc, separators=(",", ":"))
        day_path = DAYS / f"{day}.geojson"
        old = day_path.read_text() if day_path.exists() else None
        if old == body:
            continue
        changed += 1
        was = len(json.loads(old)["features"]) if old else 0
        added += len(fc["features"]) - was
        for f in fc["features"]:
            s = f["properties"]["s"]
            if s in ("lost", "mutiny") or not old:
                delta[s] = delta.get(s, 0) + 1
        if not dry:
            day_path.write_text(body)
    print(f"{'СВЕРКА' if dry else 'записано'}: изменилось файлов {changed}, "
          f"полигонов прибавилось {added}, из них {delta}")
    if not dry:
        write_manifest()
    return changed


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    DAYS.mkdir(parents=True, exist_ok=True)
    if "--manifest-only" in sys.argv:      # пересборка выборки без сети
        write_manifest()
        return
    if "--rebuild" in sys.argv:            # пересборка дней из кэша, без сети
        rebuild_from_cache(dry="--dry-run" in sys.argv)
        return

    history = json.loads(get(f"{API}/public"))
    print(f"снапшотов в истории: {len(history)}")

    by_day = {}  # kyiv date -> последняя запись дня
    for h in history:
        dt = datetime.fromisoformat(h["createdAt"].replace("Z", "+00:00"))
        day = dt.astimezone(KYIV).date().isoformat()
        cur = by_day.get(day)
        if cur is None or h["createdAt"] > cur["createdAt"]:
            by_day[day] = h
    days = sorted(by_day)
    print(f"дней с данными: {len(days)} ({days[0]} … {days[-1]})")

    done = errors = 0
    for i, day in enumerate(days):
        h = by_day[day]
        raw_path = RAW / f"{h['id']}.json.gz"
        day_path = DAYS / f"{day}.geojson"
        if day_path.exists() and raw_path.exists():
            done += 1
            continue
        try:
            if raw_path.exists():
                snap = json.loads(gzip.decompress(raw_path.read_bytes()))
            else:
                body = get(f"{API}/{h['id']}/geojson")
                snap = json.loads(body)
                raw_path.write_bytes(gzip.compress(body))
                time.sleep(0.25)
        except Exception as e:
            errors += 1
            print(f"  ПРОПУСК {day} (id {h['id']}): {e}", file=sys.stderr)
            continue
        fc = {"type": "FeatureCollection", "features": day_features(snap)}
        day_path.write_text(json.dumps(fc, separators=(",", ":")))
        done += 1
        if done % 50 == 0:
            print(f"  {done}/{len(days)} … {day}")

    # территории — из свежайшего успешно скачанного снапшота
    for day in reversed(days):
        raw_path = RAW / f"{by_day[day]['id']}.json.gz"
        if raw_path.exists():
            snap = json.loads(gzip.decompress(raw_path.read_bytes()))
            terr = build_territories(snap)
            (OUT / "territories.geojson").write_text(
                json.dumps(terr, separators=(",", ":"), ensure_ascii=False))
            print(f"территорий: {len(terr['features'])} (срез {day})")
            break

    have, _ = write_manifest()
    print(f"готово: {len(have)} дневных файлов, ошибок: {errors}")


if __name__ == "__main__":
    main()
