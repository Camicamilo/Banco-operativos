"""Cuentas compartidas y operaciones sobre ellas.

Cada operación existe en una versión sin protección y otra con locks,
para poder comparar el resultado antes y después de sincronizar.
"""

import threading
import time


class Cuenta:
    def __init__(self, id, saldo):
        self.id = id
        self.saldo = saldo
        self.lock = threading.Lock()


def depositar_sin_lock(cuenta, monto):
    actual = cuenta.saldo           # 1. leer
    time.sleep(0)                   # cede la CPU: otro hilo puede leer el mismo saldo
    cuenta.saldo = actual + monto   # 2. escribir (pisa lo que escribió el otro hilo)


def depositar_con_lock(cuenta, monto):
    with cuenta.lock:               # solo un hilo a la vez ejecuta leer + escribir
        depositar_sin_lock(cuenta, monto)


def _mover(origen, destino, monto):
    if origen.saldo >= monto:
        origen.saldo -= monto
        destino.saldo += monto


def transferir_ingenuo(origen, destino, monto, espera=0.1, timeout=1):
    """Toma primero el lock del origen y luego el del destino.

    Si A->B y B->A ocurren a la vez, cada hilo tiene un lock y espera el otro:
    interbloqueo. El timeout permite detectarlo en vez de quedarse colgado.
    """
    if not origen.lock.acquire(timeout=timeout):
        return "bloqueo"
    try:
        time.sleep(espera)  # da tiempo a que el otro hilo tome su primer lock
        if not destino.lock.acquire(timeout=timeout):
            return "bloqueo"
        try:
            _mover(origen, destino, monto)
            return "ok"
        finally:
            destino.lock.release()
    finally:
        origen.lock.release()


def transferir_ordenado(origen, destino, monto, espera=0.1):
    """Toma los locks siempre en el mismo orden (por id): sin espera circular."""
    primero, segundo = sorted((origen, destino), key=lambda c: c.id)
    with primero.lock:
        time.sleep(espera)
        with segundo.lock:
            _mover(origen, destino, monto)
    return "ok"
