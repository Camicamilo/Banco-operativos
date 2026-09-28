#!/bin/sh
# Guarda en evidencias/ lo que el sistema operativo ve del servicio.
# Uso: ./observar.sh <etiqueta>     (ej: ./observar.sh carrera_sin_lock)
# Ejecutarlo mientras corre un experimento.

ETIQUETA=${1:-captura}
PID=$(pgrep -f "servidor.py" | head -n 1)
[ -z "$PID" ] && { echo "El servidor no está corriendo"; exit 1; }

mkdir -p evidencias
ARCHIVO="evidencias/${ETIQUETA}_$(date +%H%M%S).txt"

{
  echo "== $(date) | servidor PID $PID =="
  echo; echo "== pstree -p =="; pstree -p "$PID"
  echo; echo "== ps -eLf (servidor y sus hijos) =="
  ps -eLf | awk -v pid="$PID" 'NR==1 || $2==pid || $3==pid'
  echo; echo "== /proc/$PID/status (hilos y memoria) =="
  grep -E "^(Name|Pid|Threads|VmRSS|voluntary_ctxt_switches|nonvoluntary_ctxt_switches)" /proc/$PID/status
  echo; echo "== top (una foto, por hilo) =="
  top -H -b -n 1 -p "$PID" | head -n 20
} > "$ARCHIVO"

echo "Guardado en $ARCHIVO"
