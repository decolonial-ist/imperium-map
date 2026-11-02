#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сколько рабочих процессов можно поднять, чтобы машина не легла.

ЗАЧЕМ (01.11.2026). Пересборка 423 срезов шла на восьми процессах, рядом
работали чекер геометрии и сборка пакетов, а 32 ГБ из 48 держала модель в
ollama (qwen3.6:35b). Память кончилась, своп забился, машина встала. Куратор:
«не надо по одному. комп мощный пользуся этим. только как-то сделай так чтобы
он не падал». Поэтому число процессов считается от свободной памяти, а не от
числа ядер: мерка - пик одного рабочего процесса на самом большом срезе
(1918-08-15, 79 МБ: build_lite - 1,5 ГБ, union среза - 0,5 ГБ).

Что делает: читает vm_stat (свободные, неактивные, очищаемые страницы),
оставляет запас системе и делит остаток на пик процесса. Верхняя планка -
ядра минус два. Печатает одну строку: сколько свободно, сколько держит ollama,
сколько процессов взято. Больше памяти освобождается командой
`ollama stop <модель>` - её имя строка печатает, решение за человеком.

Использование в сборщиках:
    import memguard
    ap.add_argument('--workers', type=int, default=memguard.default_workers())
"""
import os
import re
import subprocess

PER_WORKER_MB = 1600      # пик build_lite на срезе 1918-08-15 (1,51 ГБ), с запасом
RESERVE_MB = 4096         # системе и остальным сборщикам рядом
PAGE = 16384
_printed = set()


def _vm_stat():
    try:
        out = subprocess.run(['vm_stat'], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    pages = {}
    for line in out.splitlines():
        m = re.match(r'\s*Pages ([a-z ]+?):\s+(\d+)', line)
        if m:
            pages[m.group(1).strip()] = int(m.group(2))
    if not pages:
        return None
    free = sum(pages.get(k, 0) for k in ('free', 'inactive', 'purgeable', 'speculative'))
    return free * PAGE // (1024 * 1024)


def available_mb():
    """Свободная память в МБ: free + inactive + purgeable + speculative. None - не узнать."""
    return _vm_stat()


def ollama_resident():
    """[(модель, ГБ)] по `ollama ps`; пусто, если ollama нет или модель не загружена."""
    try:
        out = subprocess.run(['ollama', 'ps'], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    res = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 4:
            m = re.match(r'([\d.]+)\s*(GB|MB)', ' '.join(parts[2:4]))
            if m:
                gb = float(m.group(1)) / (1024 if m.group(2) == 'MB' else 1)
                res.append((parts[0], gb))
    return res


def default_workers(per_worker_mb=PER_WORKER_MB, reserve_mb=RESERVE_MB, hard_max=None, tag=''):
    cpu = os.cpu_count() or 4
    cap = hard_max or max(1, cpu - 2)
    avail = available_mb()
    if avail is None:
        n = min(cap, 8)
        note = 'память не измерена, взято %d' % n
    else:
        n = max(1, min(cap, (avail - reserve_mb) // per_worker_mb))
        note = 'свободно %.1f ГБ' % (avail / 1024)
    oll = ollama_resident()
    if oll:
        note += ', ollama держит ' + ', '.join('%s %.0f ГБ' % (m, g) for m, g in oll)
    line = '### память: %s; рабочих процессов %d (пик ~%.1f ГБ на процесс, запас %.0f ГБ)' % (
        note, n, per_worker_mb / 1024, reserve_mb / 1024)
    if oll and avail is not None and n < cap:
        line += '; освободить память - ollama stop %s' % oll[0][0]
    key = (tag, line)
    if key not in _printed:
        _printed.add(key)
        print(line, flush=True)
    return n


if __name__ == '__main__':
    default_workers()
