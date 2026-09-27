#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Общее для таблиц в CSV (27.09.2026): чтение с проверкой колонок, запись
CRLF, перенос литералов Python в CSV с комментариями из кода.

Пользуются tools/zones_tables.py, tools/losses_tables.py, tools/ww2_tables.py
(tools/core_tables.py старше и держит свою копию). Правила файлов: CRLF,
UTF-8, даты ISO, пустая ячейка в колонках из nullable = None, колонка comment -
комментарии, стоявшие в коде над строкой и внутри неё (сборка её не читает).
"""
import ast
import csv
import importlib.util
import io
import os
import sys
import tokenize

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)


def read_rows(path, cols, nullable=()):
    fn = os.path.basename(path)
    with open(path, encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    for i, r in enumerate(rows, 2):
        if list(r) != list(cols):
            sys.exit(f'{fn}: колонки {list(r)}, ожидались {list(cols)}')
        for c in cols:
            if r[c] is None:
                sys.exit(f'{fn}, строка {i}: не хватает ячеек')
            if c in nullable and r[c] == '':
                r[c] = None
    return rows


def write_rows(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, lineterminator='\r\n')
        w.writerow(cols)
        for r in rows:
            w.writerow(['' if r.get(c) is None else r[c] for c in cols])


def lit(s):
    return ast.literal_eval(s)


# ---- перенос литералов ------------------------------------------------------
def comments(src):
    out = {}
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            out[tok.start[0]] = tok.string[1:].strip()
    return out


def import_file(py, name='_lit'):
    d = os.path.dirname(os.path.abspath(py))
    if d not in sys.path:
        sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location(name, py)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def elts_of(value):
    """Элементы литерала-контейнера: список/кортеж - elts, словарь - значения."""
    if isinstance(value, ast.Dict):
        return value.values
    return value.elts


def spans(tree, names):
    """имя таблицы -> (узел присваивания, конечные строки его элементов)."""
    out = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) \
                and n.targets[0].id in names:
            out[n.targets[0].id] = (n, [e.end_lineno for e in elts_of(n.value)])
    return out


def notes(span, com):
    """Комментарии на каждый элемент: над ним и внутри него (до конца)."""
    n, ends = span
    res, prev = [], n.lineno
    for i, end in enumerate(ends):
        hi = n.end_lineno if i == len(ends) - 1 else end
        res.append('\n'.join(com[ln] for ln in range(prev + 1, hi + 1) if ln in com))
        prev = end
    return res


def keyword_list(call, kw):
    """Узел списка в именованном аргументе kw вызова dict(...) - для вложенных
    таблиц (parts=[dict(...), ...])."""
    for k in call.keywords:
        if k.arg == kw:
            return k.value
    return None


# ---- простые словари: ключ -> значение ------------------------------------
def load_dict(path, cols):
    """CSV из колонок (ключ, значение, comment) -> dict."""
    return {r[cols[0]]: r[cols[1]] for r in read_rows(path, cols)}


def export_dict(py, var, path, cols, name='_dict_lit'):
    """Словарь-литерал var файла py -> CSV path с комментариями строк."""
    src = open(py, encoding='utf-8').read()
    com = comments(src)
    sp = spans(ast.parse(src), {var})
    mod = import_file(py, name)
    d = getattr(mod, var)
    c = notes(sp[var], com)
    rows = [{cols[0]: k, cols[1]: v, 'comment': c[i]} for i, (k, v) in enumerate(d.items())]
    write_rows(path, cols, rows)
    return len(rows), load_dict(path, cols) == d
