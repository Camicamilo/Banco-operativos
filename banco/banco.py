"""Cuentas compartidas y operaciones sobre ellas.

Cada operación existe en una versión sin protección y otra con locks,
para poder comparar el resultado antes y después de sincronizar.
"""

import random
import threading
import time

TIPOS = ("deposito", "retiro", "transferencia", "consulta")


class Cuenta:
    def __init__(self, id, saldo):
        self.id = id
        self.saldo = saldo
        self.lock = threading.Lock()


class CuentaCompartida:
    """Igual que Cuenta, pero el saldo vive en memoria compartida entre procesos.

    `saldos` es un multiprocessing.Array y `lock` un multiprocessing.Lock,
    así todas las operaciones de abajo sirven sin cambios para varios procesos.
    """

    def __init__(self, indice, saldos, lock):
        self.id = indice
        self._saldos = saldos
        self.lock = lock

    @property
    def saldo(self):
        return self._saldos[self.id]

    @saldo.setter
    def saldo(self, valor):
        self._saldos[self.id] = valor


# --- Operaciones sin protección -------------------------------------------
# Todas siguen el patrón leer -> ceder la CPU -> escribir. time.sleep(0) no
# espera nada: solo le dice al planificador "puedes pasar a otro hilo ahora",
# lo que hace que la condición de carrera aparezca casi siempre.

def depositar_sin_lock(cuenta, monto):
    actual = cuenta.saldo           # 1. leer
    time.sleep(0)                   # cede la CPU: otro hilo puede leer el mismo saldo
    cuenta.saldo = actual + monto   # 2. escribir (pisa lo que escribió el otro hilo)
    return True


def retirar_sin_lock(cuenta, monto):
    actual = cuenta.saldo
    if actual < monto:              # saldo insuficiente: se rechaza
        return False
    time.sleep(0)                   # otro hilo puede retirar con el mismo saldo "viejo"
    cuenta.saldo = actual - monto
    return True


def transferir_sin_lock(origen, destino, monto):
    if origen.saldo < monto:
        return False
    actual = origen.saldo
    time.sleep(0)
    origen.saldo = actual - monto
    destino.saldo += monto
    return True


def consultar_sin_lock(cuenta):
    return cuenta.saldo


# --- Operaciones con lock --------------------------------------------------

def depositar_con_lock(cuenta, monto):
    with cuenta.lock:               # solo un hilo a la vez ejecuta leer + escribir
        return depositar_sin_lock(cuenta, monto)


def retirar_con_lock(cuenta, monto):
    with cuenta.lock:               # verificar saldo + descontar es una sola sección crítica
        return retirar_sin_lock(cuenta, monto)


def consultar_con_lock(cuenta):
    with cuenta.lock:               # no ve un saldo a medio actualizar
        return cuenta.saldo


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
            return "ok" if transferir_sin_lock(origen, destino, monto) else "rechazada"
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
            return "ok" if transferir_sin_lock(origen, destino, monto) else "rechazada"


# --- Transacciones genéricas (usadas por la cola y los procesos) -----------

def nueva_transaccion(cantidad_cuentas):
    """Transacción al azar: (tipo, índice origen, índice destino, monto)."""
    tipo = random.choices(TIPOS, weights=(3, 3, 3, 1))[0]
    origen, destino = random.sample(range(cantidad_cuentas), 2)
    monto = random.randint(1, 100) if tipo == "deposito" else random.randint(1, 400)
    return tipo, origen, destino, monto


def procesar(tipo, origen, destino, monto, con_lock=True):
    """Aplica una transacción. Devuelve True si se hizo y False si se rechazó."""
    if tipo == "deposito":
        return (depositar_con_lock if con_lock else depositar_sin_lock)(origen, monto)
    if tipo == "retiro":
        return (retirar_con_lock if con_lock else retirar_sin_lock)(origen, monto)
    if tipo == "transferencia":
        if con_lock:
            return transferir_ordenado(origen, destino, monto, espera=0) == "ok"
        return transferir_sin_lock(origen, destino, monto)
    (consultar_con_lock if con_lock else consultar_sin_lock)(origen)
    return True


class Contador:
    """Cuenta transacciones hechas y rechazadas por tipo (uno por hilo: sin compartir)."""

    def __init__(self):
        self.por_tipo = {t: {"ok": 0, "rechazadas": 0} for t in TIPOS}
        self.depositado = 0
        self.retirado = 0

    def anotar(self, tipo, monto, hecha):
        self.por_tipo[tipo]["ok" if hecha else "rechazadas"] += 1
        if hecha and tipo == "deposito":
            self.depositado += monto
        if hecha and tipo == "retiro":
            self.retirado += monto

    def sumar(self, otro):
        """Acepta otro Contador o su versión en dict (la que viaja entre procesos)."""
        if isinstance(otro, Contador):
            otro = otro.como_dict()
        for t in TIPOS:
            for k in ("ok", "rechazadas"):
                self.por_tipo[t][k] += otro["por_tipo"][t][k]
        self.depositado += otro["depositado"]
        self.retirado += otro["retirado"]

    def como_dict(self):
        return {"por_tipo": self.por_tipo, "depositado": self.depositado,
                "retirado": self.retirado}

    @property
    def rechazadas(self):
        return sum(v["rechazadas"] for v in self.por_tipo.values())
