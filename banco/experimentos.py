"""Los tres experimentos. Cada uno corre en un proceso hijo con varios hilos."""

import multiprocessing
import os
import queue
import random
import threading
import time

from banco import (Cuenta, depositar_con_lock, depositar_sin_lock,
                   transferir_ingenuo, transferir_ordenado)


def _memoria_kb():
    """Memoria residente del proceso (solo Linux, se lee de /proc)."""
    try:
        with open("/proc/self/status") as f:
            for linea in f:
                if linea.startswith("VmRSS"):
                    return int(linea.split()[1])
    except OSError:
        pass
    return None


def _correr_hilos(funcion, cantidad):
    hilos = [threading.Thread(target=funcion, args=(i,), name=f"hilo-{i}")
             for i in range(cantidad)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()


def _en_proceso(tarea, *args):
    """Lanza `tarea` en un proceso hijo y devuelve su resultado."""
    contexto = multiprocessing.get_context("spawn")
    buzon = contexto.Queue()
    proceso = contexto.Process(target=_trabajador, args=(tarea, args, buzon))
    proceso.start()
    resultado = buzon.get()
    proceso.join()
    return resultado


def _trabajador(tarea, args, buzon):
    inicio = time.time()
    resultado = tarea(*args)
    resultado["segundos"] = round(time.time() - inicio, 2)
    resultado["pid_trabajador"] = os.getpid()
    resultado["memoria_kb"] = _memoria_kb()
    buzon.put(resultado)


# --- 1. Condición de carrera --------------------------------------------

def _carrera(hilos, operaciones, con_lock):
    cuenta = Cuenta("A", 0)
    depositar = depositar_con_lock if con_lock else depositar_sin_lock

    def trabajo(_):
        for _ in range(operaciones):
            depositar(cuenta, 1)

    _correr_hilos(trabajo, hilos)
    esperado = hilos * operaciones
    return {"hilos": hilos, "esperado": esperado, "obtenido": cuenta.saldo,
            "dinero_perdido": esperado - cuenta.saldo}


def carrera(hilos=8, operaciones=5000):
    return {"sin_lock": _en_proceso(_carrera, hilos, operaciones, False),
            "con_lock": _en_proceso(_carrera, hilos, operaciones, True)}


# --- 2. Cola productor-consumidor ---------------------------------------

def _cola(hilos, operaciones):
    cuentas = [Cuenta(f"C{i}", 1000) for i in range(5)]
    total_inicial = sum(c.saldo for c in cuentas)
    pendientes = queue.Queue(maxsize=100)  # si se llena, los productores esperan
    procesadas = {}

    def productor(_):
        for _ in range(operaciones):
            origen, destino = random.sample(cuentas, 2)
            pendientes.put((origen, destino, random.randint(1, 50)))

    def consumidor(i):
        procesadas[i] = 0
        while True:
            tarea = pendientes.get()
            if tarea is None:       # señal de fin
                return
            transferir_ordenado(*tarea, espera=0)
            procesadas[i] += 1

    consumidores = [threading.Thread(target=consumidor, args=(i,), name=f"consumidor-{i}")
                    for i in range(hilos)]
    for h in consumidores:
        h.start()
    _correr_hilos(productor, hilos)          # los productores terminan primero
    for _ in consumidores:
        pendientes.put(None)                 # un "fin" por consumidor
    for h in consumidores:
        h.join()

    return {"productores": hilos, "consumidores": hilos,
            "transacciones": hilos * operaciones,
            "procesadas_por_consumidor": procesadas,
            "total_inicial": total_inicial,
            "total_final": sum(c.saldo for c in cuentas)}


def cola(hilos=4, operaciones=500):
    return _en_proceso(_cola, hilos, operaciones)


# --- 3. Interbloqueo -----------------------------------------------------

def _interbloqueo(ordenado):
    a, b = Cuenta("A", 1000), Cuenta("B", 1000)
    resultados = {}

    def trabajo(i):
        if i == 0:
            origen, destino = a, b
        else:
            origen, destino = b, a
        if ordenado:
            resultados[f"{origen.id}->{destino.id}"] = transferir_ordenado(origen, destino, 100)
        else:
            resultados[f"{origen.id}->{destino.id}"] = transferir_ingenuo(origen, destino, 100)

    _correr_hilos(trabajo, 2)
    return {"resultados": resultados, "total_final": a.saldo + b.saldo}


def interbloqueo():
    return {"ingenuo": _en_proceso(_interbloqueo, False),
            "ordenado": _en_proceso(_interbloqueo, True)}
