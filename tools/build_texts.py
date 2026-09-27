#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тексты витрины: data/text/TEXTS.md -> data/text.js (27.09.2026).

Куратор 27.09.2026: «весь наш кастомный текст - в отдельный документ, чтобы
можно было править». Все слова, которые видит человек на карте, лежат в
data/text/TEXTS.md - один документ, ключ заголовком, текст под ним. Страница
(index.html, ee-shim.js) слов не держит: она читает window.TEXT из data/text.js
и подставляет значения через T('ключ', {имя: значение}).

Формат документа - в его шапке. Тут: заголовок `## ключ - пояснение`; текст
до следующего заголовка, переносы строк склеиваются пробелом; подстановки
`{имя}`; склонения и перечни через `|`.

Проверки: ключ не пустой, не повторяется, все подстановки из кода (SLOTS)
в тексте есть, лишних нет. Список ключей и подстановок, которых ждёт код,
ниже - при новой строке в index.html её ключ добавляется сюда же.

Запуск: python tools/build_texts.py [--check]
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'data', 'text', 'TEXTS.md')
OUT = os.path.join(ROOT, 'data', 'text.js')
OUT_JSON = os.path.join(ROOT, 'data', 'text.json')

# ключ -> подстановки, которые код обязан найти в тексте
SLOTS = {
    'splash.tiles': {'done', 'all'},
    'entity.slice': {'key'}, 'entity.slice_year': {'year'},
    'embed.slice_title': {'d', 'why'},
    'err.script': {'msg'}, 'err.data': {'msg'}, 'err.show': {'msg'},
    'err.embed': {'id', 'msg'}, 'err.build': {'msg'},
    'holder.under': {'who'}, 'holder.slice': {'year'},
    'prec.month': {'a', 'b'}, 'prec.exact': {'date', 'why'},
    'prec.dated': {'a', 'b'}, 'prec.slices': {'a', 'b'},
    'state.sub': {'when'},
    'hist.wait_front': {'i', 'n'},
    'hist.since': {'when'}, 'hist.till': {'when'}, 'hist.already': {'dur'},
    'hist.remains': {'when', 'dur'},
    'ostrog.land': {'land'},
    'note.black': {'name'}, 'note.red_comes': {'when'},
    'resist.camps_now': {'camps'}, 'resist.camps': {'camps'}, 'resist.more': {'n'},
    'resist.no_control': {'name'}, 'resist.until': {'when', 'event'},
    'resist.note': {'name', 'when', 'event', 'proof', 'painted'},
    'pact.in_since_until': {'a', 'b'}, 'pact.was_since_until': {'a', 'b'},
    'pact.in_since': {'a'}, 'pact.row': {'name', 'win', 'act'}, 'pact.geom': {'src'},
    'sphere.row': {'name', 'kind'}, 'conf': {'source', 'conf'},
    'sphere.note_head': {'name'}, 'ep.end': {'event'}, 'sphere.table': {'geom'},
    'ps.series': {'n', 'series'}, 'ps.table': {'geom'},
    'upr.held': {'windows'}, 'upr.note_head': {'n'}, 'upr.more': {'n'},
    'dep.row': {'people', 'when'}, 'dep.where': {'where'},
    'aut.restored': {'when'}, 'loss.source': {'src'},
}
# ключи без подстановок, которые код тоже ждёт
KEYS = [
    'page.title', 'splash.title', 'splash.loading', 'splash.libs', 'splash.start_ok', 'splash.start_each',
    'splash.first', 'hdr.title', 'hdr.sub', 'hdr.fold', 'hdr.unfold',
    'legend.empire', 'legend.sphere', 'legend.points',
    'btn.play', 'btn.prev', 'btn.next', 'btn.year', 'btn.month', 'btn.day',
    'sat.ctl', 'sat.cap_off', 'sat.cap_on', 'sat.title_off', 'sat.title_on', 'sat.attrib',
    'base.attrib', 'base.attrib_short', 'popup.close', 'core.attrib',
    'entity.moscow', 'entity.tsardom', 'entity.empire', 'entity.rsfsr', 'entity.ussr',
    'entity.rf', 'entity.front', 'entity.front_days',
    'months', 'coord.ns', 'coord.ew', 'dur.days', 'dur.years', 'dur.months', 'dur.less',
    'embed.full', 'embed.full_title', 'err.unknown', 'err.tiles', 'holder.window',
    'prec.start', 'prec.loss', 'prec.ps', 'state.in', 'state.out', 'state.occ_front',
    'state.occ', 'state.later', 'state.unknown', 'hist.head', 'hist.km', 'hist.wait',
    'row.before', 'row.now', 'row.after', 'row.same', 'row.whose', 'row.resist', 'row.act',
    'row.sphere', 'row.episode', 'row.uprising', 'row.deport', 'row.autonomy',
    'hist.no_before', 'hist.no_after', 'hist.no_more',
    'ostrog.left_f', 'ostrog.left_n', 'ostrog.left_m', 'until_today',
    'ps.note_head', 'upr.elsewhere', 'upr.note_foot', 'dep.note_head', 'dep.table',
    'aut.abolished', 'aut.was_abolished', 'aut.not_restored', 'aut.note_head', 'aut.table',
    'note.loss_days', 'note.deepstate', 'note.ww1', 'note.recon', 'note.cshapes',
    'ticks.front', 'ticks.recon', 'ticks.ww2', 'ticks.ww1',
] + list(SLOTS)
LISTS = {'months': 12, 'coord.ns': 2, 'coord.ew': 2, 'dur.days': 3, 'dur.years': 3,
         'dur.months': 3}


def parse(path=SRC):
    """Документ -> {ключ: текст}, ошибки списком."""
    texts, err, key, buf = {}, [], None, []
    order = []

    def flush():
        if key is None:
            return
        body = ' '.join(ln.strip() for ln in buf if ln.strip())
        if key in texts:
            err.append(f'ключ {key} дважды')
        texts[key] = body
        order.append(key)

    with open(path, encoding='utf-8') as f:
        for ln in f.read().split('\n'):
            if ln.startswith('## '):
                flush()
                head = ln[3:].strip()
                key = re.split(r'\s+-\s+', head, maxsplit=1)[0].strip()
                buf = []
                if not re.fullmatch(r'[a-z0-9_.]+', key):
                    err.append(f'ключ «{key}»: только латиница, цифры, точка и _')
            elif key is not None:
                buf.append(ln)
    flush()
    for k in KEYS:
        if k not in texts:
            err.append(f'нет ключа {k}')
        elif not texts[k]:
            err.append(f'ключ {k} пустой')
    for k in texts:
        if k not in KEYS:
            err.append(f'ключ {k} коду не нужен (лишний или опечатка)')
    for k, need in SLOTS.items():
        if k in texts:
            have = set(re.findall(r'\{([a-z_]+)\}', texts[k]))
            if have != need:
                err.append(f'{k}: подстановки {sorted(have)}, код ждёт {sorted(need)}')
    for k, n in LISTS.items():
        if k in texts and len(texts[k].split('|')) != n:
            err.append(f'{k}: частей через | должно быть {n}')
    return texts, err


def build():
    texts, err = parse()
    if err:
        for e in err:
            print('  ' + e)
        sys.exit(f'тексты: ошибок {len(err)} ({os.path.relpath(SRC, ROOT)})')
    js = ('// Собрано tools/build_texts.py из data/text/TEXTS.md - править ТАМ.\n'
          'window.TEXT = ' + json.dumps(texts, ensure_ascii=False, indent=0, sort_keys=True)
          + ';\n')
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(js)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(texts, f, ensure_ascii=False, indent=0, sort_keys=True)
        f.write('\n')
    print(f'OK тексты: ключей {len(texts)} -> {os.path.relpath(OUT, ROOT)}')


if __name__ == '__main__':
    if '--check' in sys.argv:
        _, err = parse()
        for e in err:
            print('  ' + e)
        print(f'тексты: ошибок {len(err)}')
        sys.exit(1 if err else 0)
    build()
