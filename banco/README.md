# Banco concurrente

Simula un banco que procesa transacciones con procesos e hilos y muestra tres problemas clásicos de sistemas operativos: condición de carrera, productor-consumidor e interbloqueo. Solo usa Python 3 (sin instalar nada) y está pensado para una VM Linux.

## Ejecutar (todo dentro de la VM)

1. Copiar la carpeta `banco/` a la VM (por ejemplo con `scp -r banco usuario@IP_VM:~/` o carpeta compartida).
2. Dentro de la VM:

```sh
sudo apt install -y python3 psmisc procps   # solo si faltan (psmisc trae pstree)
cd banco
python3 servidor.py                         # puerto 8000 (cambiar con PORT=9000)
```

3. Abrir `http://localhost:8000` en el navegador de la VM (o `http://IP_DE_LA_VM:8000` desde otra máquina).
4. Las evidencias se toman en otra terminal de la VM: `sh observar.sh nombre`.

## Estructura

| Archivo | Qué hace |
|---|---|
| `banco.py` | `Cuenta` y las operaciones, con y sin protección |
| `experimentos.py` | Los 3 experimentos; cada uno corre en un **proceso hijo** con varios **hilos** |
| `servidor.py` | Servidor web + API JSON + vista de procesos |
| `static/index.html` | La página (botones y tablas) |
| `observar.sh` | Guarda en `evidencias/` la salida de `pstree`, `ps -eLf`, `/proc` y `top` |

## Procesos e hilos

```
servidor.py (proceso principal, PID X)
├── hilo por cada petición HTTP
└── proceso trabajador (uno por experimento)
    └── hilos: hilo-0 ... hilo-N  (o productores/consumidores)
```

Cada experimento se lanza con `multiprocessing` en modo `spawn`, así que aparece como proceso hijo del servidor en `pstree -p`.

## Experimentos

1. **Carrera**: N hilos suman $1 a la misma cuenta, primero sin lock y luego con lock. Sin lock, `saldo = saldo + 1` son dos pasos (leer, escribir); si dos hilos leen el mismo valor, uno pisa al otro y se pierde dinero. Con `Lock`, el par leer+escribir es una sección crítica: un solo hilo a la vez, y el resultado es exacto.
2. **Cola**: los productores ponen transferencias en una `queue.Queue` (limitada a 100) y los consumidores las sacan y procesan. Si la cola se llena, los productores esperan; si está vacía, los consumidores esperan. El total de dinero se conserva.
3. **Interbloqueo**: A→B y B→A al mismo tiempo. Con locks ingenuos cada hilo toma su cuenta de origen y espera la otra: se cumplen exclusión mutua, retención y espera, no expropiación y **espera circular**, así que ninguno avanza (un timeout de 1 s lo detecta y lo reporta como `bloqueo`). Con locks **ordenados por id** ambos hilos piden primero la cuenta menor, se rompe la espera circular y el interbloqueo no puede ocurrir.

## Recoger evidencias en la VM

Para alcanzar a verlos, subir las operaciones (ej. 200000) y, mientras corre el experimento:

```sh
./observar.sh carrera_sin_lock     # guarda evidencias/carrera_sin_lock_HHMMSS.txt
```

Comandos útiles a mano: `pstree -p <PID>`, `ps -eLf`, `top -H -p <PID>`, `cat /proc/<PID>/status` (campos `Threads` y `VmRSS`). El botón "Ver procesos" de la página muestra `pstree` y `ps -eLf` del servicio.

Comparar antes/después: ejecutar la carrera y anotar `dinero_perdido` (sin lock) contra `0` (con lock); el con-lock tarda más porque los hilos se turnan.
