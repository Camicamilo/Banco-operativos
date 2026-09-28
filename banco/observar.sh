#!/bin/sh
# Guarda en evidencias/ lo que el sistema operativo ve del servicio.
# Uso: ./observar.sh <etiqueta>     (ej: ./observar.sh carrera_sin_lock)
# Ejecutarlo mientras corre un experimento (desde la página o con pruebas.py).
# Se puede forzar el PID a observar: PID=1234 ./observar.sh etiqueta

ETIQUETA=${1:-captura}
# El patrón exige que el comando empiece por python (evita atrapar editores o shells)
PID=${PID:-$(pgrep -f '^[^ ]*python[0-9.]* ([^ ]*/)?(servidor|pruebas)\.py' | head -n 1)}
[ -z "$PID" ] && { echo "Ni servidor.py ni pruebas.py están corriendo"; exit 1; }

mkdir -p evidencias
ARCHIVO="evidencias/${ETIQUETA}_$(date +%H%M%S).txt"

{
  echo "== $(date) | proceso principal PID $PID =="
  echo; echo "== pstree -pt (procesos e hilos: {nombre} = hilo) =="; pstree -pt "$PID"
  echo; echo "== ps -eLf (principal y sus hijos, una línea por hilo) =="
  ps -eLf | awk -v pid="$PID" 'NR==1 || $2==pid || $3==pid'
  echo; echo "== ps: CPU, memoria y estado por proceso =="
  ps -o pid,ppid,nlwp,%cpu,%mem,rss,stat,etime,cmd --pid "$PID" --ppid "$PID"
  for P in $PID $(pgrep -P "$PID"); do
    echo; echo "== /proc/$P/status (hilos, memoria, cambios de contexto) =="
    grep -E "^(Name|Pid|PPid|State|Threads|VmRSS|voluntary_ctxt_switches|nonvoluntary_ctxt_switches)" /proc/$P/status
  done
  echo; echo "== top (una foto, por hilo) =="
  top -H -b -n 1 -p "$(echo $PID $(pgrep -P "$PID") | tr ' ' ',')" | head -n 40
} > "$ARCHIVO" 2>&1

echo "Guardado en $ARCHIVO"
