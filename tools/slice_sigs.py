#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Подписи срезов слоёв войн (v4, 27.09.2026): срез слоя пересобирается, только
если изменилось то, из чего он собран.

До этого слой (зоны 1917-1921 - 100+ срезов, ПМВ - 42, ВМВ - 50) пересобирался
ЦЕЛИКОМ от любой правки своего входа: одна строка в таблице якорей или один
файл региона - и все срезы слоя писались заново, а за ними шёл берег OSM на
каждом (74 минуты полной сборки уходили на берег), lite, mid, ячейки.
Куратор 27.09.2026: «почему берега пересчитываются двадцатый раз».

Теперь сборщик слоя считает на каждый срез подпись - хеш ровно тех входов,
от которых зависит этот день: основа, состояние якорей НА ЭТОТ ДЕНЬ,
действующие окна и приобретения, геометрия задетых регионов, свой код.
Совпала со старой и файл среза на месте - срез не трогается, его mtime
не меняется, и tools/rebuild.py не ведёт его ни на берег, ни дальше.

Подписи лежат в build/state/sigs_<слой>.json вместе с тем, что нужно
переиспользовать без пересчёта (линия фронта среза). `--all` у сборщика
подписи не читает - собирает всё.
"""
import hashlib
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, 'build', 'state')
_FILE_SHA = {}


def sha_obj(obj):
    """Хеш любого JSON-представимого объекта (даты - строкой)."""
    s = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(s.encode('utf-8')).hexdigest()


def sha_file(path):
    """Хеш содержимого файла (по пути, кэш на процесс); нет файла - 'нет'."""
    if path not in _FILE_SHA:
        if not os.path.exists(path):
            _FILE_SHA[path] = 'нет'
        else:
            h = hashlib.sha1()
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(1 << 20), b''):
                    h.update(chunk)
            _FILE_SHA[path] = h.hexdigest()
    return _FILE_SHA[path]


_DATA_INDEX = {}


def _data_index():
    if not _DATA_INDEX:
        for top in ('data', 'cache'):
            for dp, dn, fns in os.walk(os.path.join(ROOT, top)):
                dn[:] = [x for x in dn if x not in ('years', 'years_lite', 'years_mid',
                                                    'mid_packs', 'fine_cells', 'preclipped',
                                                    'basetiles', 'deepstate')]
                for fn in fns:
                    if fn.endswith(('.csv', '.geojson', '.json', '.wkb')):
                        _DATA_INDEX.setdefault(fn, []).append(os.path.join(dp, fn))
    return _DATA_INDEX


def named_inputs(script, exclude=()):
    """Хеши файлов данных, названных в тексте скрипта (как layer_inputs в
    tools/rebuild.py), кроме exclude - тех, что учтены точнее (якоря по дню)."""
    text = open(script, encoding='utf-8').read()
    out = {}
    for fn in sorted(set(re.findall(r"'([A-Za-z0-9_./-]+\.(?:csv|geojson|json|wkb))'", text))):
        base = os.path.basename(fn)
        if base in exclude or fn in exclude or base == 'manifest.json':
            continue
        for p in _data_index().get(base, []):
            # имя с каталогом ('ww1/ohm_abroad_1914.geojson') - только этот путь
            if '/' in fn and not p.replace(os.sep, '/').endswith('/' + fn):
                continue
            out[os.path.relpath(p, ROOT)] = sha_file(p)
    return out


def reg_sig(BE, name):
    """Подпись региона таблицы regions.csv: спецификация плюс файлы в ней."""
    spec = BE.REG.get(name)
    files = []
    for p in (spec or []):
        if isinstance(p, tuple) and p and p[0] in ('file', 'and_file', 'minus_file',
                                                   'file_where'):
            files.append(sha_file(os.path.join(ROOT, 'data', p[1])))
    return [repr(spec), files]


class Sigs:
    """Подписи одного слоя: старые с диска, новые - по ходу сборки."""

    def __init__(self, name, use_old=True):
        self.path = os.path.join(STATE, f'sigs_{name}.json')
        self.old = {}
        if use_old and os.path.exists(self.path):
            try:
                with open(self.path, encoding='utf-8') as f:
                    self.old = json.load(f)
            except ValueError:
                self.old = {}
        self.new = {}
        self.kept = []

    def fresh(self, key, sig, path):
        """Срез с этой подписью уже на диске: помечаем его сохранённым."""
        rec = self.old.get(key)
        if rec and rec.get('sig') == sig and os.path.exists(path):
            self.new[key] = rec
            self.kept.append(key)
            return True
        return False

    def put(self, key, sig, **extra):
        self.new[key] = dict(sig=sig, **extra)

    def get(self, key):
        return self.new.get(key) or {}

    def save(self):
        os.makedirs(STATE, exist_ok=True)
        tmp = f'{self.path}.{os.getpid()}.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.new, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def report(self, label):
        n = len(self.new)
        print(f'{label}: без изменений {len(self.kept)} из {n} срезов'
              + (' (' + ', '.join(self.kept[:6]) + (', …' if len(self.kept) > 6 else '') + ')'
                 if self.kept else ''), flush=True)
