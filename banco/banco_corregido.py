"""VERSIÓN CORREGIDA: las mismas operaciones de banco_con_problema.py, sincronizadas.

Correcciones de la condición de carrera:
  1. Lock por cuenta (depositar, retirar, consultar, transferir).
  2. Lock global (depositar_lock_global): también corrige, pero serializa todo.
  3. Dueño por cuenta (DuenoDeCuenta): un solo hilo modifica cada cuenta, sin locks.

Correcciones del interbloqueo:
  4. Orden global de locks (transferir): rompe la espera circular.
  5. Intentar y soltar (transferir_reintentando): rompe la retención y espera.
"""

import queue
import random
import threading
import time


# --- 1. Lock por cuenta ------------------------------------------------------
# El mismo código de la versión con problema, dentro de una sección crítica:
# mientras un hilo tiene el lock de la cuenta, ningún otro puede leerla ni
# escribirla, así que nadie puede pisar una escritura ni usar un saldo viejo.

def depositar(cuenta, monto):
    with cuenta.lock:               # solo un hilo a la vez ejecuta leer + escribir
        actual = cuenta.saldo
        time.sleep(0)               # aunque ceda la CPU, nadie más puede entrar
        cuenta.saldo = actual + monto
        return True


def retirar(cuenta, monto):
    with cuenta.lock:               # verificar saldo + descontar es una sola sección crítica
        actual = cuenta.saldo
        if actual < monto:
            return False
        time.sleep(0)
        cuenta.saldo = actual - monto
        return True


def consultar(cuenta):
    with cuenta.lock:               # no ve un saldo a medio actualizar
        return cuenta.saldo


def _mover(origen, destino, monto):
    """Mueve el dinero. Quien la llama ya tiene los locks de las dos cuentas."""
    if origen.saldo < monto:
        return False
    actual = origen.saldo
    time.sleep(0)
    origen.saldo = actual - monto
    destino.saldo += monto
    return True


# --- 4. Orden global de locks ----------------------------------------------

def transferir(origen, destino, monto, espera=0):
    """Toma los dos locks siempre en el mismo orden (por id de cuenta).

    A->B y B->A piden primero la cuenta menor: el que llega segundo espera sin
    tener nada tomado, así que no puede formarse la espera circular.
    El orden de los locks cambia; la dirección del dinero no.
    """
    primero, segundo = sorted((origen, destino), key=lambda c: c.id)
    with primero.lock:
        time.sleep(espera)
        with segundo.lock:
            return _mover(origen, destino, monto)


def procesar(tipo, origen, destino, monto):
    """Aplica una transacción. Devuelve True si se hizo y False si se rechazó."""
    if tipo == "deposito":
        return depositar(origen, monto)
    if tipo == "retiro":
        return retirar(origen, monto)
    if tipo == "transferencia":
        return transferir(origen, destino, monto)
    consultar(origen)
    return True


# --- 2. Lock global ----------------------------------------------------------

LOCK_GLOBAL = threading.Lock()


def depositar_lock_global(cuenta, monto):
    """Un solo lock para todo el banco. Corrige la carrera, pero dos hilos no
    pueden trabajar a la vez ni siquiera en cuentas distintas (granularidad gruesa)."""
    with LOCK_GLOBAL:
        actual = cuenta.saldo
        time.sleep(0)
        cuenta.saldo = actual + monto
        return True


# --- 3. Dueño por cuenta ---------------------------------------------------

class DuenoDeCuenta:
    """Un único hilo modifica la cuenta; los demás le envían mensajes.

    Como solo un hilo toca el saldo, el código de actualización es el mismo de
    la versión con problema (sin lock) y aun así es correcto: no hay dato
    compartido entre hilos. La sincronización se traslada a la cola de
    mensajes (queue.Queue), que ya es segura entre hilos.
    """

    def __init__(self, cuenta):
        self.cuenta = cuenta
        self.buzon = queue.Queue()

    def depositar(self, monto):     # lo llaman los demás hilos
        self.buzon.put(monto)
        return True

    def atender(self):              # lo ejecuta el hilo dueño
        while True:
            monto = self.buzon.get()
            if monto is None:       # señal de fin
                return
            actual = self.cuenta.saldo
            time.sleep(0)           # aunque ceda la CPU, ningún otro hilo escribe aquí
            self.cuenta.saldo = actual + monto

    def cerrar(self):
        self.buzon.put(None)


# --- 5. Intentar y soltar ----------------------------------------------------

def transferir_reintentando(origen, destino, monto, espera=0.1, max_intentos=1000):
    """Si no consigue el segundo lock, suelta el primero y vuelve a intentar.

    Nunca retiene un recurso mientras espera otro: rompe la condición de
    retención y espera. La pausa al azar entre intentos evita que los dos hilos
    vuelvan a chocar siempre igual (livelock).
    Devuelve (resultado, intentos).
    """
    for intento in range(1, max_intentos + 1):
        with origen.lock:
            time.sleep(espera)
            if destino.lock.acquire(blocking=False):   # no espera: intenta y sigue
                try:
                    return ("ok" if _mover(origen, destino, monto) else "rechazada"), intento
                finally:
                    destino.lock.release()
        # aquí ya soltó el origen: el otro hilo puede completar su transferencia
        time.sleep(random.uniform(0, max(espera, 0.001)))
    return "agotado", max_intentos
