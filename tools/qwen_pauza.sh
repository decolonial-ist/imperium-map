#!/bin/bash
# Очередь Qwen перед тяжёлой сборкой карты (договор с Архивариусом 01.11.2026,
# WORK/archive/NOTICE_OT_KARTA_QWEN_OCHERED_2026-11-01.md; слово куратора: карта выше АКАК).
#   tools/qwen_pauza.sh start "что собираем, сколько ждать"  - ставит флаг PAUZA, через минуту выгружает модель
#   tools/qwen_pauza.sh done                                  - дописывает «готово» (флаг переносит Архивариус)
#   tools/qwen_pauza.sh done-sam                              - Архивариус молчит: флаг переносит карта (mv -n в pauza_snyaty/)
# Сообщение Архивариусу в сессию шлёт чат карты сам (SendMessage), скрипт этого не делает.
set -e
P=~/tmp/WORKFILES/poisk/PAUZA
N=~/tmp/WORK/archive/NOTICE_OT_KARTA_QWEN_OCHERED_2026-11-01.md
MODEL=qwen3.6:35b-a3b-nvfp4
case "$1" in
  start)
    if [ -e "$P" ]; then echo "PAUZA уже стоит:"; cat "$P"; exit 1; fi
    echo "карта (imperium-map) $(date '+%d.%m.%Y %H:%M'): ${2:-тяжёлая сборка}" > "$P"
    echo "- $(date '+%d.%m %H:%M'): PAUZA поставлена картой: ${2:-тяжёлая сборка}" >> "$N"
    echo "флаг поставлен, жду минуту, пока akak_ia.py допишет страницу"; sleep 60
    ollama stop "$MODEL" && echo "модель $MODEL выгружена"
    ollama ps
    ;;
  done)
    echo "- $(date '+%d.%m %H:%M'): карта закончила, Qwen свободен; флаг переносит Архивариус" >> "$N"
    echo "записано в NOTICE; напиши Архивариусу «готово»"
    ;;
  done-sam)
    # Архивариус 01.11: если «готово» некому принять, флаг переносит карта сама, без удаления
    [ -e "$P" ] || { echo "флага нет"; exit 0; }
    mv -n "$P" ~/tmp/WORKFILES/poisk/pauza_snyaty/PAUZA_karta_$(date '+%Y%m%d_%H%M%S')
    echo "- $(date '+%d.%m %H:%M'): карта закончила; Архивариус молчал, флаг перенесён картой в pauza_snyaty/" >> "$N"
    echo "флаг перенесён"
    ;;
  *) echo "usage: $0 start \"текст\" | done"; exit 2;;
esac
