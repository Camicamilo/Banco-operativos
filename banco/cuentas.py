"""Modelo del banco: cuentas, transacciones y contadores.

Aquí no hay ninguna decisión de concurrencia. Las operaciones sobre las cuentas
están en dos módulos con las mismas funciones:
  - banco_con_problema.py: sin sincronización (demuestra los problemas).
  - banco_corregido.py:    con sincronización (la solución).
"""

import random
import threading

TIPOS = ("deposito", "retiro", "transferencia", "consulta")


class Cuenta:
    def __init__(self, id, saldo):
        self.id = id
        self.saldo = saldo              # el dato compartido entre hilos
        self.lock = threading.Lock()    # lo usa solo la versión corregida


class CuentaCompartida:
    """Igual que Cuenta, pero el saldo vive en memoria compartida entre procesos.

    `saldos` es un multiprocessing.Array y `lock` un multiprocessing.Lock,
    así las operaciones de los dos módulos sirven sin cambios para varios procesos.
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


def nueva_transaccion(cantidad_cuentas):
    """Transacción al azar: (tipo, índice origen, índice destino, monto)."""
    tipo = random.choices(TIPOS, weights=(3, 3, 3, 1))[0]
    origen, destino = random.sample(range(cantidad_cuentas), 2)
    monto = random.randint(1, 100) if tipo == "deposito" else random.randint(1, 400)
    return tipo, origen, destino, monto


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
