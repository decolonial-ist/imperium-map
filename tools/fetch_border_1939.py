#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Качалка исходных данных для линии раздела 04.10.1939 (OpenStreetMap).

Кладёт в cache/osm_border1939/ восемь файлов ответов Overpass API:

    rivers.json        русла по польским именам (Czarna Hańcza, Wołkuszanka,
                       Blizna, Pisa, Narew, Orz, Brok, Bug, Sołokija, Łówcza,
                       Gnojnik, Przykopa, Lubaczówka, San, Tanew)
    rivers_east.json   те же реки под белорусскими и украинскими именами
                       (Заходні Буг, Західний Буг, Солокія, Сян) - без них
                       Западный Буг обрывается на польском участке
    places_north.json, places_north2.json, places_mazovia.json,
    places_bug.json, places_south.json, places_south2.json
                       населённые пункты, названные в протоколе: они задают
                       концы прямых «условных линий» (Примечание 2 протокола:
                       эти участки уточняются при демаркации)

Natural Earth 10m rivers для этой задачи не годится: в нём нет ни Волкушанки,
ни Близны, ни Ожа, ни Солокии, а Нарев и Сан даны одной генерализованной
ниткой без меандров - линия по такому руслу уходит от документа на километры.
HydroRIVERS даёт нужную детализацию, но это гигабайтный слой на всю Европу
ради 700 км русла; OSM отдаёт ровно нужные реки по именам.

Данные OSM - ODbL, © участники OpenStreetMap. Дата выгрузки - см. mtime
файлов кэша. Кэш переиспользуется: файл на месте - запрос не шлётся.

Запуск (из корня репозитория):

    .venv/bin/python tools/fetch_border_1939.py
    .venv/bin/python tools/build_border_1939.py
"""
import json
import os
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'cache', 'osm_border1939')
EP = 'https://overpass-api.de/api/interpreter'
UA = 'imperium-map/1.0 (historical border research; decolonial.ist)'

RIVERS = ('Czarna Hańcza|Marycha|Wołkuszanka|Blizna|Pisa|Narew|Orz|Brok|'
          'Broczysko|Bug|Zachodni Bug|Західний Буг|Sołokija|Солокія|Łówcza|'
          'Lubaczówka|Przykopa|San|Сян|Krynica|Gnojnik|Igorka|Tanew')
NORTH = ('Rządowy|Rządowe|Żegary|Kapčiamiestis|Kopciowo|Jędrzejowo|Wołkusz|'
         'Ostrynskie|Ostryńskie|Czarny Bród|Szczebra|Topiłówka|Pruska Mała|'
         'Raczki|Suwałki|Augustów|Sejny|Giby|Berżniki|Sopoćkinie|Nowy Dwór')
MAZOVIA = ('Ostrołęka|Ostrowy|Ławy|Susk|Susk Nowy|Susk Stary|Troszyn|Rabędy|'
           'Stylągi|Buczyn|Zaorze|Sokołowo|Rogówek|Malinowo-Stare|'
           'Malinowo Stare|Ostrów Mazowiecka|Żabikowo|Nowa Złotoria|Pecki|'
           'Nadbużne|Nowogród|Brok')
SOUTH = ('Uhnów|Угнів|Chodywańce|Myślatyn|Мислятин|Przednie|Przeorsk|'
         'Nowosiółki|Новосілки|Żurawce|Żyłka|Жилка|Brzezina|Pizuny|Garby|'
         'Sigły|Gorajec|Cieszanów|Dachnów|Futory|Zabiała|Łatoszyn|Uszkowce|'
         'Dobcza|Miłków|Dziegielnia|Lubaczów|Bełżec|Lubycza Królewska|Krowica')

QUERIES = {
    'rivers': f'''[out:json][timeout:280];
( way["waterway"~"^(river|stream|canal|ditch)$"]["name"~"^({RIVERS})$"]
     (48.5,17.8,54.6,23.6); );
out geom;''',
    'rivers_east': '''[out:json][timeout:280];
( way["waterway"~"^(river|stream)$"]["name"~"Буг|Bug|Сян|San|Солокія|Солокия"]
     (48.5,22.0,53.0,25.5); );
out geom;''',
    'places_north': f'''[out:json][timeout:280];
( node["place"]["name"~"^({NORTH})$"](53.6,22.5,54.4,24.0);
  way ["place"]["name"~"^({NORTH})$"](53.6,22.5,54.4,24.0); );
out center tags;''',
    'places_north2': '''[out:json][timeout:280];
( nwr["name"~"^(Igorka|Igarka|Jedryno|Jędrzejowo|Ostryńskie|Rządowy|Rządowe|Przetok|Pszetok|Wołkusz|Kalety)$"]
     (53.7,23.0,54.2,23.9); );
out center tags;''',
    'places_mazovia': f'''[out:json][timeout:280];
( node["place"]["name"~"^({MAZOVIA})$"](52.4,20.8,53.4,22.8);
  way ["place"]["name"~"^({MAZOVIA})$"](52.4,20.8,53.4,22.8); );
out center tags;''',
    'places_bug': '''[out:json][timeout:280];
( nwr["name"~"^(Nadbużne|Pecki|Żabikowo|Nowa Złotoria|Nur|Małkinia Górna)$"]
     (52.5,21.7,52.95,22.6); );
out center tags;''',
    'places_south': f'''[out:json][timeout:280];
( node["place"]["name"~"^({SOUTH})$"](49.9,22.4,50.7,24.4);
  way ["place"]["name"~"^({SOUTH})$"](49.9,22.4,50.7,24.4); );
out center tags;''',
    'places_south2': '''[out:json][timeout:280];
( nwr["name"~"^(Brzezina|Sigły|Dziegielnia|Przednie|Nowosiółki|Krynica|Łówcza|Gnojnik|Przykopa|Huta Lubycka|Ruda Żurawiecka)$"]
     (50.05,22.7,50.55,23.85); );
out center tags;''',
}


def fetch(name, query):
    path = os.path.join(CACHE, name + '.json')
    if os.path.exists(path) and os.path.getsize(path) > 200:
        print(f'кэш {name}.json ({os.path.getsize(path) // 1024} КБ)')
        return
    for attempt in range(5):
        try:
            req = urllib.request.Request(
                EP, data=urllib.parse.urlencode({'data': query}).encode(),
                headers={'User-Agent': UA})
            raw = urllib.request.urlopen(req, timeout=300).read()
            n = len(json.loads(raw)['elements'])
            with open(path, 'wb') as f:
                f.write(raw)
            print(f'OK {name}.json: объектов {n}, {len(raw) // 1024} КБ')
            return
        except Exception as exc:                       # noqa: BLE001
            print(f'   повтор {name} ({attempt + 1}/5): {exc}')
            time.sleep(15)
    raise SystemExit(f'Overpass не отдал {name}')


def main():
    os.makedirs(CACHE, exist_ok=True)
    for name, q in QUERIES.items():
        fetch(name, q)
    print('дальше: .venv/bin/python tools/build_border_1939.py')


if __name__ == '__main__':
    main()
