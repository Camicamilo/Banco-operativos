# Banco concurrente

Simula un banco que procesa transacciones (depósitos, retiros, transferencias y consultas) con **procesos e hilos**, y muestra problemas clásicos de sistemas operativos: condición de carrera, productor-consumidor, interbloqueo, memoria compartida entre procesos y el costo en CPU y memoria de cada enfoque. Solo usa Python 3 (sin instalar nada) y está pensado para una VM Linux.

## Ejecutar (todo dentro de la VM)

1. Copiar la carpeta `banco/` a la VM (por ejemplo con `git clone`, `scp -r banco usuario@IP_VM:~/` o carpeta compartida).
2. Dentro de la VM:

```sh
sudo apt install -y python3 psmisc procps   # solo si faltan (psmisc trae pstree)
cd banco
python3 servidor.py                         # puerto 8000 (cambiar con PORT=9000)
```

3. Abrir `http://localhost:8000` en el navegador de la VM (o `http://IP_DE_LA_VM:8000` desde otra máquina).
4. Las evidencias se toman en otra terminal de la VM: `sh observar.sh nombre`.
5. Pruebas automáticas con 2, 4, 8 y 16 hilos (no necesitan el servidor):

```sh
python3 pruebas.py            # carga normal (~30 s en 4 núcleos)
python3 pruebas.py --rapido   # solo para comprobar que todo funciona
```

## Estructura

| Archivo | Qué hace |
|---|---|
| `banco.py` | `Cuenta`, `CuentaCompartida` y las operaciones (depósito, retiro, transferencia, consulta), con y sin protección |
| `experimentos.py` | Los 5 experimentos, el `Monitor` que mide cada proceso y el registro de estadísticas |
| `servidor.py` | Servidor web + API JSON + vista de procesos |
| `static/index.html` | La página (parámetros, botones y tablas) |
| `pruebas.py` | Corre todo con 2, 4, 8 y 16 hilos, verifica y arma la tabla comparativa |
| `observar.sh` | Guarda en `evidencias/` la salida de `pstree`, `ps`, `/proc` y `top` |
| `resultados/` | Se crea solo: `estadisticas.csv`, `ejecuciones.jsonl` y las comparativas |
| `docs/` | Diagrama de arquitectura y borrador del documento técnico |

## Procesos e hilos

```
banco-servidor (python3 servidor.py, PID X)
├── {banco-servidor}        hilo por cada petición HTTP (+ hilo alimentador de la cola entre procesos)
├── python3                 resource_tracker de multiprocessing (limpia semáforos y memoria compartida)
├── carrera-0 / cola-0 / interbloqueo-0 / auditoria-0     (un proceso por experimento)
│   ├── {hilo-0} ... {hilo-N}          o {productor-i} y {consumidor-i}, o {auditor-i}
│   └── {monitor}                      mide VmRSS, hilos y CPU cada 0,1 s
├── trabajador-0 ... trabajador-P      (experimento multiproceso: P procesos a la vez)
│   ├── {hilo-0} ... {hilo-N}
│   └── {monitor}
└── auditor-0 ... auditor-N            (auditoría con procesos: un proceso por trabajador)
```

Los procesos se crean con `multiprocessing` en modo `spawn` (cada hijo es un intérprete nuevo) y aparecen como hijos del servidor en `pstree -pt <PID>`. Los nombres (`cola-0`, `{consumidor-2}`...) se ponen en el kernel con `prctl(PR_SET_NAME)` (vía `ctypes`), así se ven en `pstree -t`, `ps -eLf` y `top -H` en lugar de `python3`.

## Experimentos

1. **Carrera** (5 cuentas): N hilos depositan $1 repartiéndose las cuentas, primero sin lock y luego con lock. Sin lock, `saldo = saldo + 1` son dos pasos (leer, escribir); si dos hilos leen el mismo valor, uno pisa al otro y se pierde dinero. El resultado muestra lo esperado, lo obtenido y lo perdido **por cuenta**. Con `Lock`, el par leer+escribir es una sección crítica: un solo hilo a la vez, y el resultado es exacto.
2. **Cola productor-consumidor**: los productores ponen transacciones de los 4 tipos en una `queue.Queue` (limitada a 100) y los consumidores las procesan. Si la cola se llena, los productores esperan; si está vacía, los consumidores esperan. Los retiros y transferencias sin saldo suficiente se **rechazan** y se cuentan por tipo. Se verifica que `inicial + depositado − retirado = final` (`cuadra: true`).
3. **Interbloqueo**: A→B y B→A al mismo tiempo. Con locks ingenuos cada hilo toma su cuenta de origen y espera la otra: se cumplen exclusión mutua, retención y espera, no expropiación y **espera circular**, así que ninguno avanza hasta que el timeout lo detecta y lo reporta como `bloqueo`. Con locks **ordenados por id** ambos hilos piden primero la cuenta menor, se rompe la espera circular y no puede ocurrir. Los parámetros *espera* y *timeout* (en la página) alargan la ventana: con 5 y 10 s hay tiempo de sobra para correr `observar.sh`.
4. **Multiproceso**: el servidor (productor) pone transacciones en una `multiprocessing.Queue`; P procesos hijo, cada uno con N hilos, las consumen. Los saldos están en **memoria compartida** (`multiprocessing.Array`) con un `multiprocessing.Lock` por cuenta. Sin lock, hilos de **distintos procesos** leen y escriben el mismo saldo a la vez en núcleos distintos y el total no cuadra (`diferencia ≠ 0`). Incluso `esperado` puede salir negativo: se aprueban retiros mirando un saldo viejo, así que se "retira" más dinero del que existía. Con lock cuadra siempre.
5. **Auditoría (CPU y memoria)**: cada trabajador firma transacciones con un cálculo en Python puro (CPU) y guarda un libro que crece (~9 KB por transacción, memoria). La misma carga se corre con N **hilos** en un proceso y con N **procesos**. El monitor toma muestras de `VmRSS` y `os.times()` durante la ejecución, y se calcula `nucleos_usados = CPU / tiempo real`.

## Por qué los hilos no aceleran la auditoría: el GIL

CPython tiene un *Global Interpreter Lock*: solo un hilo por proceso ejecuta bytecode de Python a la vez. Los hilos sí son hilos reales del kernel (se ven en `ps -eLf` y `top -H`), pero se turnan el GIL, por eso con carga de CPU pura `nucleos_usados` queda en ~1 sin importar cuántos hilos haya. Con procesos cada uno tiene su propio intérprete y su propio GIL, y el planificador del SO los reparte en todos los núcleos (en 4 núcleos, ~3 núcleos usados y la tercera parte del tiempo). El precio es la memoria: cada proceso carga su propio intérprete (~14 MB) y sus datos no se comparten.

Ejemplo real (4 núcleos, `pruebas.py`, 16 trabajadores × 1000 transacciones):

| Variante | Tiempo | CPU | Núcleos usados | Memoria máx. |
|---|---|---|---|---|
| 16 hilos, 1 proceso | 3,81 s | 3,92 s | 1,03 | 58 MB |
| 16 procesos | 1,43 s | 4,28 s | 2,99 | 308 MB (suma) |

El GIL **no** evita la condición de carrera: el cambio de hilo puede ocurrir entre leer y escribir el saldo. Y los locks siguen siendo necesarios entre procesos, donde no hay GIL compartido.

## Qué hace `time.sleep(0)`

No duerme: le dice al planificador "puedes pasar a otro hilo ahora". Está entre la lectura y la escritura del saldo en las versiones sin lock para que el cambio de contexto caiga justo en la sección crítica y la carrera aparezca en casi todas las corridas (sin él también ocurre, pero es más raro). Es la forma de hacer visible un error que en un sistema real aparecería "a veces".

## Estadísticas

Cada ejecución (desde la página o desde `pruebas.py`) agrega una fila por variante a `resultados/estadisticas.csv`:

`fecha, experimento, variante, procesos, hilos, operaciones, segundos, pid, ppid, hilos_max, cpu_usuario_s, cpu_sistema_s, memoria_max_kb, esperado, obtenido, rechazadas`

y el resultado completo (con detalle por cuenta, por tipo, por proceso y las muestras del monitor) a `resultados/ejecuciones.jsonl`. `hilos_max` incluye el hilo principal y el monitor; la CPU se cuenta desde que arranca el monitor. La página muestra las últimas filas con el botón "Ver estadísticas". El archivo se escribe con un lock porque el servidor atiende peticiones en varios hilos.

## Recoger evidencias en la VM

Subir las operaciones (ej. 200000) para alcanzar a verlos y, mientras corre el experimento:

```sh
sh observar.sh carrera_sin_lock     # guarda evidencias/carrera_sin_lock_HHMMSS.txt
PID=1234 sh observar.sh algo        # observar un PID concreto
```

Captura `pstree -pt`, `ps -eLf` (una línea por hilo), `ps` con CPU/memoria/estado por proceso, `/proc/<PID>/status` del servidor y de cada hijo (`Threads`, `VmRSS`, cambios de contexto) y `top -H`. Sugerencias:

| Evidencia | Cómo |
|---|---|
| Árbol de procesos e hilos | Multiproceso con 3 procesos × 4 hilos y 100000 operaciones, luego `observar.sh multiproceso` |
| Interbloqueo | Espera 5 y timeout 10, ejecutar, y a los 2 s `observar.sh interbloqueo`: dos hilos en estado `S` esperando un lock y 0 % de CPU |
| CPU y GIL | Auditoría con 8 hilos y 20000 operaciones; `top -H` muestra los hilos repartiéndose ~100 %, los procesos ~100 % cada uno |
| Memoria | `watch -n 0.5 'grep VmRSS /proc/<PID_HIJO>/status'` durante la auditoría |
| Comparativa | `python3 pruebas.py` → `resultados/comparativa_*.md` |

Comandos útiles a mano: `pstree -pt <PID>`, `ps -eLf`, `top -H -p <PID>`, `cat /proc/<PID>/status`, `htop` (tecla `H` muestra hilos).
