# Borrador del documento técnico — Proyecto 4: Banco concurrente

> Borrador para completar. Los números salen de una corrida de `pruebas.py` en un equipo Linux de 4 núcleos; **reemplazarlos por los de la VM** (`resultados/comparativa_*.md`) y ajustar los títulos a los que pidan exactamente las pautas. Las partes entre `[ ]` las debe llenar el grupo.

## 1. Portada
[Universidad, curso Sistemas Operativos, Proyecto 4, integrantes, docente, fecha]

## 2. Resumen
Se construyó un servicio bancario en Python 3 que procesa depósitos, retiros, transferencias y consultas usando procesos (`multiprocessing`) e hilos (`threading`). Sobre él se ejecutan cinco experimentos: condición de carrera, productor-consumidor, interbloqueo, procesos con memoria compartida y carga de CPU/memoria. Cada ejecución registra PID, PPID, hilos, CPU y memoria. Se comprobó que sin sincronización se pierde dinero (con 16 hilos se obtuvo 19 485 de 80 000), que los locks lo corrigen, que ordenar los locks elimina el interbloqueo y que, por el GIL de CPython, los hilos no aprovechan varios núcleos en tareas de CPU mientras que los procesos sí (2,99 núcleos contra 1,03), a costa de más memoria.

## 3. Introducción
[Contexto: un banco atiende muchas transacciones a la vez; el SO ofrece procesos e hilos para esa concurrencia, y con ella aparecen problemas de acceso a datos compartidos.]

## 4. Objetivos
- General: diseñar y analizar un servicio bancario concurrente que use procesos e hilos del SO.
- Específicos:
  - Evidenciar una condición de carrera y corregirla con exclusión mutua.
  - Implementar productor-consumidor con una cola acotada.
  - Provocar un interbloqueo y prevenirlo rompiendo la espera circular.
  - Coordinar varios procesos sobre memoria compartida.
  - Medir y comparar CPU, memoria y tiempo con distintas cantidades de hilos y procesos.

## 5. Marco teórico
- **Proceso**: programa en ejecución con su propio espacio de memoria; PID, PPID, estados.
- **Hilo**: flujo de ejecución dentro de un proceso que comparte su memoria. En Linux cada hilo es una tarea del kernel (LWP), visible en `ps -eLf`.
- **Sección crítica y condición de carrera**: operación leer-modificar-escribir no atómica.
- **Exclusión mutua**: `Lock` / mutex, semáforos.
- **Productor-consumidor**: búfer acotado, bloqueo cuando está lleno o vacío.
- **Interbloqueo**: las cuatro condiciones de Coffman (exclusión mutua, retención y espera, no expropiación, espera circular) y estrategias de prevención.
- **IPC**: colas (`multiprocessing.Queue`, implementada con tuberías) y memoria compartida (`multiprocessing.Array`).
- **GIL de CPython**: un solo hilo ejecuta bytecode a la vez por proceso.
- **Planificación y cambio de contexto**: `time.sleep(0)` cede la CPU; cambios de contexto voluntarios y no voluntarios en `/proc/<PID>/status`.

## 6. Descripción del problema
[Un banco con varias cuentas recibe transacciones simultáneas. Requisitos: el dinero total debe conservarse, un retiro no puede dejar saldo negativo, las transferencias cruzadas no deben bloquear el sistema, y se debe poder observar y medir el comportamiento desde el SO.]

## 7. Arquitectura
Ver `docs/arquitectura.md` (diagrama de componentes y de flujo). Resumen:
- `servidor.py`: proceso principal, servidor HTTP con un hilo por petición.
- Cada experimento corre en uno o varios **procesos hijo** creados con `spawn`, con varios **hilos** y un hilo **monitor**.
- Comunicación: `multiprocessing.Queue` (resultados y transacciones), `multiprocessing.Array` (saldos compartidos).
- Persistencia de métricas: `resultados/estadisticas.csv` y `ejecuciones.jsonl`.

## 8. Diseño e implementación
- `banco.py`: `Cuenta` (saldo + `threading.Lock`), `CuentaCompartida` (misma interfaz, saldo en memoria compartida), operaciones con y sin lock, `procesar()` y `Contador`.
- `experimentos.py`: los cinco experimentos, `Monitor` (lee `/proc/self/status` y `os.times()` cada 0,1 s), `registrar()`.
- `pruebas.py`: ejecución con 2, 4, 8 y 16 hilos, verificación automática y tabla comparativa.
- `observar.sh`: captura `pstree -pt`, `ps -eLf`, `ps -o ...`, `/proc/<PID>/status` y `top -H`.
- Hilos y procesos se nombran en el kernel con `prctl(PR_SET_NAME)` para identificarlos en las herramientas del SO.

## 9. Mecanismos de sincronización
| Problema | Mecanismo | Dónde |
|---|---|---|
| Actualización perdida de saldo | `threading.Lock` por cuenta | `depositar_con_lock`, `retirar_con_lock` |
| Retiro con saldo viejo (verificar-luego-actuar) | verificación y descuento en la misma sección crítica | `retirar_con_lock` |
| Búfer compartido | `queue.Queue(maxsize=100)` (lock + variables de condición internas) | experimento cola |
| Espera circular | adquisición de locks en orden global por id | `transferir_ordenado` |
| Detección de interbloqueo | `acquire(timeout=...)` | `transferir_ingenuo` |
| Datos entre procesos | `multiprocessing.Array` + `multiprocessing.Lock` por cuenta (semáforo del SO) | experimento multiproceso |
| Escritura del CSV desde varios hilos del servidor | `threading.Lock` | `registrar()` |

## 10. Experimentos
[Para cada uno: objetivo, parámetros, procedimiento, qué se espera. Ver README, sección "Experimentos".]

## 11. Resultados y análisis
Corrida de ejemplo (`python3 pruebas.py`, 4 núcleos):

**Condición de carrera (5 cuentas)**

| Hilos | Esperado | Sin lock | Perdido | Con lock | Tiempo sin / con lock |
|---|---|---|---|---|---|
| 2 | 10 000 | 8 247 | 17,5 % | 10 000 | 0,39 / 0,42 s |
| 4 | 20 000 | 11 792 | 41,0 % | 20 000 | 0,41 / 0,52 s |
| 8 | 40 000 | 15 859 | 60,4 % | 40 000 | 0,82 / 1,62 s |
| 16 | 80 000 | 19 485 | 75,6 % | 80 000 | 2,82 / 4,14 s |

Análisis: la pérdida crece con los hilos porque hay más lecturas simultáneas del mismo saldo. El lock garantiza el resultado exacto a cambio de más tiempo (los hilos se turnan la sección crítica).

**Cola productor-consumidor y multiproceso**: en todas las cargas la versión con lock cuadra (`inicial + depositado − retirado = final`), con cientos a miles de transacciones rechazadas por saldo insuficiente. La versión multiproceso sin lock nunca cuadró (diferencias de miles de pesos), porque procesos en núcleos distintos modifican el mismo saldo en memoria compartida.

**Interbloqueo**: la versión ingenua terminó con una transferencia en `bloqueo` (detectada por el timeout de 1 s, 1,1 s en total); la ordenada completó ambas en 0,2 s. En la captura con espera larga se ven los dos hilos en estado `S` sin consumir CPU.

**Auditoría: hilos vs procesos (GIL)**

| Trabajadores | Hilos: tiempo / núcleos | Procesos: tiempo / núcleos | Memoria hilos / procesos |
|---|---|---|---|
| 2 | 0,44 s / 0,98 | 0,27 s / 1,52 | 20 / 37 MB |
| 4 | 1,00 s / 1,00 | 0,30 s / 2,80 | 31 / 72 MB |
| 8 | 1,95 s / 1,02 | 0,61 s / 2,95 | 40 / 150 MB |
| 16 | 3,81 s / 1,03 | 1,43 s / 2,99 | 58 / 308 MB |

Análisis: con hilos el tiempo crece linealmente y nunca se usa más de un núcleo (GIL). Con procesos se usan casi todos los núcleos hasta saturarlos (4 núcleos, uno compartido con el sistema), pero cada proceso carga su propio intérprete: la memoria total crece mucho más rápido. [Agregar la serie de muestras de memoria (`muestras`) como gráfica del crecimiento durante la ejecución.]

## 12. Evidencias
[Capturas de `evidencias/*.txt` y de la página, cada una con una explicación: qué comando, qué se ve (PID/PPID, hilos, estado, CPU, memoria) y qué demuestra. Ver la tabla "Recoger evidencias en la VM" del README.]

## 13. Conclusiones
- Una operación de una sola línea (`saldo += monto`) no es atómica; sin exclusión mutua se pierde dinero y el error empeora con más hilos.
- Los locks corrigen el resultado pero serializan la sección crítica: la corrección cuesta rendimiento, por eso conviene un lock por cuenta y no uno global.
- Basta romper una de las cuatro condiciones de Coffman para prevenir el interbloqueo; ordenar los recursos es simple y no requiere timeouts.
- Una cola acotada regula productores y consumidores sin espera activa.
- En CPython los hilos sirven para concurrencia de E/S, no para paralelismo de CPU; los procesos sí paralelizan, a cambio de memoria y de necesitar IPC.
- La memoria compartida entre procesos reintroduce las condiciones de carrera: los procesos también necesitan sincronizarse, con primitivas del SO.
- Las herramientas del SO (`pstree`, `ps -eLf`, `top -H`, `/proc`) permiten verificar que lo que el programa dice hacer es lo que realmente ocurre.

## 14. Referencias
- Silberschatz, Galvin, Gagne. *Operating System Concepts*, 10.ª ed. Caps. 3–8.
- Tanenbaum, Bos. *Modern Operating Systems*, 4.ª ed. Caps. 2 y 6.
- Documentación de Python: `threading`, `multiprocessing`, `queue`.
- `man 5 proc`, `man 1 ps`, `man 1 pstree`, `man 2 prctl`.
