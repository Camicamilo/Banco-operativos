"""Los experimentos. Cada uno corre en uno o varios procesos hijo con varios hilos.

Cada ejecución queda registrada en resultados/estadisticas.csv (una fila por
variante) y en resultados/ejecuciones.jsonl (el resultado completo).
"""

import csv
import ctypes
import datetime
import json
import multiprocessing
import os
import queue
import random
import threading
import time

from banco import (Contador, Cuenta, CuentaCompartida, depositar_con_lock,
                   depositar_sin_lock, nueva_transaccion, procesar,
                   transferir_ingenuo, transferir_ordenado)

CARPETA_RESULTADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")
CONTEXTO = multiprocessing.get_context("spawn")  # cada hijo arranca un intérprete nuevo


# --- Medición del proceso (lee /proc, solo Linux) --------------------------

def nombrar_en_so(nombre):
    """Pone el nombre al hilo actual en el kernel (prctl PR_SET_NAME, máx. 15 letras).

    Así pstree, ps y top -H muestran "consumidor-2" en vez de "python3".
    Si se llama desde el hilo principal, cambia el nombre del proceso.
    """
    try:
        ctypes.CDLL(None).prctl(15, nombre.encode()[:15], 0, 0, 0)
    except (OSError, AttributeError):
        pass  # no es Linux: se ignora


def _con_nombre(funcion):
    """Envuelve el trabajo de un hilo para que primero se nombre en el SO."""
    def envoltura(*args):
        nombrar_en_so(threading.current_thread().name)
        return funcion(*args)
    return envoltura


def _leer_status(campo):
    """Un campo numérico de /proc/self/status (VmRSS en kB, Threads, ...)."""
    try:
        with open("/proc/self/status") as f:
            for linea in f:
                if linea.startswith(campo + ":"):
                    return int(linea.split()[1])
    except OSError:
        pass
    return None


class Monitor(threading.Thread):
    """Hilo que mide su propio proceso cada `intervalo` segundos.

    Toma memoria residente (VmRSS), número de hilos y tiempo de CPU (os.times).
    Ojo: el conteo de hilos incluye el hilo principal y este mismo monitor.
    La CPU se cuenta desde que arranca el monitor (sin el arranque del intérprete).
    """

    actual = None  # el monitor del proceso actual, para medir al lanzar hilos

    def __init__(self, intervalo=0.1):
        super().__init__(name="monitor", daemon=True)
        self.intervalo = intervalo
        self.inicio = time.time()
        self.cpu_inicial = os.times()
        self.muestras = []
        self._parar = threading.Event()
        Monitor.actual = self

    def run(self):
        nombrar_en_so("monitor")
        self.medir()
        while not self._parar.wait(self.intervalo):
            self.medir()

    def medir(self):
        cpu = os.times()
        self.muestras.append({
            "t": round(time.time() - self.inicio, 2),
            "memoria_kb": _leer_status("VmRSS"),
            "hilos": _leer_status("Threads"),
            "cpu_s": round(cpu.user + cpu.system
                           - self.cpu_inicial.user - self.cpu_inicial.system, 2),
        })

    def detener(self):
        self._parar.set()
        self.join()
        self.medir()

    def resumen(self, max_muestras=None):
        cpu = os.times()
        datos = {
            "segundos": round(time.time() - self.inicio, 2),
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "hilos_max": max((m["hilos"] or 0) for m in self.muestras),
            "cpu_usuario_s": round(cpu.user - self.cpu_inicial.user, 2),
            "cpu_sistema_s": round(cpu.system - self.cpu_inicial.system, 2),
            "memoria_max_kb": max((m["memoria_kb"] or 0) for m in self.muestras),
        }
        if max_muestras:  # recorta la serie para que se pueda leer en pantalla
            paso = max(1, len(self.muestras) // max_muestras)
            datos["muestras"] = self.muestras[::paso]
            if datos["muestras"][-1] is not self.muestras[-1]:
                datos["muestras"].append(self.muestras[-1])
        return datos


# --- Lanzar procesos -------------------------------------------------------

def _trabajador(tarea, args, buzon, max_muestras):
    nombrar_en_so(multiprocessing.current_process().name)
    monitor = Monitor()
    monitor.start()
    resultado = tarea(*args)
    monitor.detener()
    resultado.update(monitor.resumen(max_muestras))
    buzon.put(resultado)


def _en_procesos(tarea, lista_args, max_muestras=None, nombre=None):
    """Lanza un proceso hijo por cada elemento de `lista_args`, todos a la vez."""
    nombre = nombre or tarea.__name__.strip("_")  # así se ve en pstree: carrera-0, cola-0...
    buzon = CONTEXTO.Queue()
    procesos = [CONTEXTO.Process(target=_trabajador, name=f"{nombre}-{i}",
                                 args=(tarea, args, buzon, max_muestras))
                for i, args in enumerate(lista_args)]
    for p in procesos:
        p.start()
    resultados = [buzon.get() for _ in procesos]  # leer antes de join (evita bloqueo)
    for p in procesos:
        p.join()
    return resultados


def _en_proceso(tarea, *args):
    """Lanza `tarea` en un proceso hijo y devuelve su resultado."""
    return _en_procesos(tarea, [args])[0]


def _correr_hilos(funcion, cantidad, nombre="hilo"):
    hilos = [threading.Thread(target=_con_nombre(funcion), args=(i,), name=f"{nombre}-{i}")
             for i in range(cantidad)]
    for h in hilos:
        h.start()
    if Monitor.actual:           # una medición con todos los hilos vivos
        Monitor.actual.medir()
    for h in hilos:
        h.join()


# --- Estadísticas ------------------------------------------------------------

COLUMNAS = ["fecha", "experimento", "variante", "procesos", "hilos", "operaciones",
            "segundos", "pid", "ppid", "hilos_max", "cpu_usuario_s", "cpu_sistema_s",
            "memoria_max_kb", "esperado", "obtenido", "rechazadas"]
_lock_archivo = threading.Lock()  # el servidor atiende peticiones en varios hilos


def registrar(experimento, variantes):
    """Agrega una fila por variante al CSV y el resultado completo al JSONL."""
    fecha = datetime.datetime.now().isoformat(timespec="seconds")
    os.makedirs(CARPETA_RESULTADOS, exist_ok=True)
    ruta_csv = os.path.join(CARPETA_RESULTADOS, "estadisticas.csv")
    with _lock_archivo:
        nuevo = not os.path.exists(ruta_csv)
        with open(ruta_csv, "a", newline="") as f:
            escritor = csv.DictWriter(f, COLUMNAS, extrasaction="ignore")
            if nuevo:
                escritor.writeheader()
            for variante, r in variantes.items():
                fila = {k: r.get(k, "") for k in COLUMNAS}
                fila.update(fecha=fecha, experimento=experimento, variante=variante)
                escritor.writerow(fila)
        with open(os.path.join(CARPETA_RESULTADOS, "ejecuciones.jsonl"), "a") as f:
            f.write(json.dumps({"fecha": fecha, "experimento": experimento,
                                "resultado": variantes}) + "\n")
    return variantes


def ultimas_estadisticas(cantidad=30):
    ruta_csv = os.path.join(CARPETA_RESULTADOS, "estadisticas.csv")
    if not os.path.exists(ruta_csv):
        return []
    with _lock_archivo, open(ruta_csv, newline="") as f:
        return list(csv.DictReader(f))[-cantidad:]


# --- 1. Condición de carrera (varias cuentas) ------------------------------

def _carrera(hilos, operaciones, con_lock, cantidad_cuentas):
    cuentas = [Cuenta(f"C{i}", 0) for i in range(cantidad_cuentas)]
    depositar = depositar_con_lock if con_lock else depositar_sin_lock
    esperado = [[0] * cantidad_cuentas for _ in range(hilos)]  # cada hilo anota lo suyo

    def trabajo(i):
        for j in range(operaciones):
            k = (i + j) % cantidad_cuentas   # los hilos se reparten las cuentas
            depositar(cuentas[k], 1)
            esperado[i][k] += 1

    _correr_hilos(trabajo, hilos)
    por_cuenta = {}
    for k, c in enumerate(cuentas):
        debia = sum(e[k] for e in esperado)
        por_cuenta[c.id] = {"esperado": debia, "obtenido": c.saldo, "perdido": debia - c.saldo}
    obtenido = sum(c.saldo for c in cuentas)
    return {"hilos": hilos, "procesos": 1, "operaciones": hilos * operaciones,
            "cuentas": cantidad_cuentas, "esperado": hilos * operaciones,
            "obtenido": obtenido, "dinero_perdido": hilos * operaciones - obtenido,
            "por_cuenta": por_cuenta}


def carrera(hilos=8, operaciones=5000, cuentas=5):
    return registrar("carrera", {
        "sin_lock": _en_proceso(_carrera, hilos, operaciones, False, cuentas),
        "con_lock": _en_proceso(_carrera, hilos, operaciones, True, cuentas)})


# --- 2. Cola productor-consumidor (todos los tipos de transacción) ---------

SALDO_INICIAL = 500


def _cola(hilos, operaciones, cantidad_cuentas=5):
    cuentas = [Cuenta(f"C{i}", SALDO_INICIAL) for i in range(cantidad_cuentas)]
    total_inicial = sum(c.saldo for c in cuentas)
    pendientes = queue.Queue(maxsize=100)  # si se llena, los productores esperan
    contadores = [Contador() for _ in range(hilos)]
    procesadas = {}

    def productor(_):
        for _ in range(operaciones):
            pendientes.put(nueva_transaccion(cantidad_cuentas))

    def consumidor(i):
        procesadas[f"consumidor-{i}"] = 0
        while True:
            tarea = pendientes.get()
            if tarea is None:       # señal de fin
                return
            tipo, origen, destino, monto = tarea
            hecha = procesar(tipo, cuentas[origen], cuentas[destino], monto)
            contadores[i].anotar(tipo, monto, hecha)
            procesadas[f"consumidor-{i}"] += 1

    consumidores = [threading.Thread(target=_con_nombre(consumidor), args=(i,),
                                     name=f"consumidor-{i}")
                    for i in range(hilos)]
    for h in consumidores:
        h.start()
    _correr_hilos(productor, hilos, "productor")  # los productores terminan primero
    for _ in consumidores:
        pendientes.put(None)                       # un "fin" por consumidor
    for h in consumidores:
        h.join()

    total = Contador()
    for c in contadores:
        total.sumar(c)
    esperado = total_inicial + total.depositado - total.retirado
    obtenido = sum(c.saldo for c in cuentas)
    return {"hilos": hilos * 2, "procesos": 1, "productores": hilos, "consumidores": hilos,
            "operaciones": hilos * operaciones, "rechazadas": total.rechazadas,
            "por_tipo": total.por_tipo, "procesadas_por_consumidor": procesadas,
            "total_inicial": total_inicial, "depositado": total.depositado,
            "retirado": total.retirado, "esperado": esperado, "obtenido": obtenido,
            "cuadra": esperado == obtenido}


def cola(hilos=4, operaciones=500):
    return registrar("cola", {"con_lock": _en_proceso(_cola, hilos, operaciones)})


# --- 3. Interbloqueo -------------------------------------------------------

def _interbloqueo(ordenado, espera, timeout):
    a, b = Cuenta("A", 1000), Cuenta("B", 1000)
    resultados = {}

    def trabajo(i):
        origen, destino = (a, b) if i == 0 else (b, a)
        if ordenado:
            r = transferir_ordenado(origen, destino, 100, espera)
        else:
            r = transferir_ingenuo(origen, destino, 100, espera, timeout)
        resultados[f"{origen.id}->{destino.id}"] = r

    _correr_hilos(trabajo, 2)
    return {"hilos": 2, "procesos": 1, "operaciones": 2, "resultados": resultados,
            "esperado": 2000, "obtenido": a.saldo + b.saldo,
            "rechazadas": sum(r != "ok" for r in resultados.values())}


def interbloqueo(espera=0.1, timeout=1):
    """`espera` y `timeout` largos (ej. 5 y 10 s) dejan tiempo de capturarlo con observar.sh."""
    return registrar("interbloqueo", {
        "ingenuo": _en_proceso(_interbloqueo, False, espera, timeout),
        "ordenado": _en_proceso(_interbloqueo, True, espera, timeout)})


# --- 4. Varios procesos trabajadores con memoria compartida ----------------

def _proceso_trabajador(hilos, tareas, saldos, locks, con_lock):
    """Un proceso hijo: `hilos` hilos sacan transacciones de la cola entre procesos."""
    cuentas = [CuentaCompartida(i, saldos, lock) for i, lock in enumerate(locks)]
    contadores = [Contador() for _ in range(hilos)]

    def trabajo(i):
        while True:
            tarea = tareas.get()
            if tarea is None:
                return
            tipo, origen, destino, monto = tarea
            hecha = procesar(tipo, cuentas[origen], cuentas[destino], monto, con_lock)
            contadores[i].anotar(tipo, monto, hecha)

    _correr_hilos(trabajo, hilos)
    total = Contador()
    for c in contadores:
        total.sumar(c)
    return {"hilos": hilos, "procesadas": sum(v["ok"] + v["rechazadas"]
                                             for v in total.por_tipo.values()),
            "contador": total.como_dict()}


def _multiproceso(procesos, hilos, operaciones, con_lock, cantidad_cuentas=5):
    # Los saldos viven en memoria compartida; lock=False porque sincronizamos a mano
    saldos = CONTEXTO.Array("q", [SALDO_INICIAL] * cantidad_cuentas, lock=False)
    locks = [CONTEXTO.Lock() for _ in range(cantidad_cuentas)]  # un lock por cuenta
    tareas = CONTEXTO.Queue(maxsize=1000)  # cola entre procesos
    total_operaciones = procesos * hilos * operaciones
    inicio = time.time()

    buzon = CONTEXTO.Queue()
    hijos = [CONTEXTO.Process(target=_trabajador, name=f"trabajador-{p}",
                              args=(_proceso_trabajador, (hilos, tareas, saldos, locks, con_lock),
                                    buzon, None))
             for p in range(procesos)]
    for h in hijos:
        h.start()
    for _ in range(total_operaciones):          # el padre es el productor
        tareas.put(nueva_transaccion(cantidad_cuentas))
    for _ in range(procesos * hilos):
        tareas.put(None)
    por_proceso = [buzon.get() for _ in hijos]
    for h in hijos:
        h.join()

    total = Contador()
    for r in por_proceso:
        total.sumar(r.pop("contador"))
    esperado = SALDO_INICIAL * cantidad_cuentas + total.depositado - total.retirado
    obtenido = sum(saldos)
    return {"procesos": procesos, "hilos": procesos * hilos, "operaciones": total_operaciones,
            "segundos": round(time.time() - inicio, 2),
            "pid": "|".join(str(r["pid"]) for r in por_proceso), "ppid": os.getpid(),
            "hilos_max": sum(r["hilos_max"] for r in por_proceso),
            "cpu_usuario_s": round(sum(r["cpu_usuario_s"] for r in por_proceso), 2),
            "cpu_sistema_s": round(sum(r["cpu_sistema_s"] for r in por_proceso), 2),
            "memoria_max_kb": sum(r["memoria_max_kb"] for r in por_proceso),
            "rechazadas": total.rechazadas, "por_tipo": total.por_tipo,
            "depositado": total.depositado, "retirado": total.retirado,
            "esperado": esperado, "obtenido": obtenido, "diferencia": obtenido - esperado,
            "cuadra": esperado == obtenido, "por_proceso": por_proceso}


def multiproceso(procesos=3, hilos=4, operaciones=500):
    return registrar("multiproceso", {
        "sin_lock": _multiproceso(procesos, hilos, operaciones, False),
        "con_lock": _multiproceso(procesos, hilos, operaciones, True)})


# --- 5. Auditoría: carga de CPU y memoria (hilos vs procesos) --------------

def _firmar(texto, rondas=150):
    """Firma de juguete hecha en Python puro: solo gasta CPU (no suelta el GIL)."""
    h = 0
    for _ in range(rondas):
        for letra in texto:
            h = (h * 31 + ord(letra)) % 1_000_000_007
    return h


def _auditar(operaciones, semilla):
    """Arma un libro de transacciones y firma cada una.

    El libro se guarda completo, así la memoria crece mientras avanza.
    """
    azar = random.Random(semilla)
    libro = []
    for n in range(operaciones):
        registro = f"{n};C{azar.randrange(100)};C{azar.randrange(100)};{azar.randint(1, 10**6)}"
        comprobante = registro.encode() * 300   # ~9 KB por transacción
        libro.append((registro, _firmar(registro), comprobante))
    return len(libro)


def _auditoria_hilos(hilos, operaciones):
    auditadas = [0] * hilos

    def trabajo(i):
        auditadas[i] = _auditar(operaciones, i)

    _correr_hilos(trabajo, hilos, "auditor")
    return {"hilos": hilos, "procesos": 1, "operaciones": sum(auditadas)}


def _auditoria_un_proceso(operaciones, semilla):
    return {"hilos": 1, "operaciones": _auditar(operaciones, semilla)}


def auditoria(hilos=4, operaciones=2000):
    """La misma carga repartida en `hilos` hilos de un proceso o en `hilos` procesos."""
    con_hilos = _en_procesos(_auditoria_hilos, [(hilos, operaciones)], 15, "auditoria")[0]

    inicio = time.time()
    por_proceso = _en_procesos(_auditoria_un_proceso,
                               [(operaciones, i) for i in range(hilos)], 15, "auditor")
    con_procesos = {
        "procesos": hilos, "hilos": hilos, "operaciones": hilos * operaciones,
        "segundos": round(time.time() - inicio, 2),
        "pid": "|".join(str(r["pid"]) for r in por_proceso), "ppid": os.getpid(),
        "hilos_max": sum(r["hilos_max"] for r in por_proceso),
        "cpu_usuario_s": round(sum(r["cpu_usuario_s"] for r in por_proceso), 2),
        "cpu_sistema_s": round(sum(r["cpu_sistema_s"] for r in por_proceso), 2),
        "memoria_max_kb": sum(r["memoria_max_kb"] for r in por_proceso),
        "muestras": por_proceso[0]["muestras"],   # la serie de uno de ellos
    }
    for r in (con_hilos, con_procesos):
        cpu = r["cpu_usuario_s"] + r["cpu_sistema_s"]
        # CPU / tiempo real: ~1 = un solo núcleo trabajando; ~N = N núcleos en paralelo
        r["nucleos_usados"] = round(cpu / r["segundos"], 2) if r["segundos"] else None
    return registrar("auditoria", {"hilos": con_hilos, "procesos": con_procesos})
