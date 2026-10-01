"""VERSIÓN CON PROBLEMA: operaciones bancarias sin sincronización.

Se conserva a propósito para demostrar los problemas de concurrencia
("versión en la que pueda demostrarse al menos un problema", pautas).
banco_corregido.py tiene las mismas funciones, con los mismos nombres,
ya corregidas: comparar ambos archivos muestra exactamente la corrección.

Todas siguen el patrón leer -> ceder la CPU -> escribir. time.sleep(0) no
espera nada: le dice al planificador "puedes pasar a otro hilo ahora", lo que
hace que la condición de carrera aparezca en casi todas las ejecuciones.
"""

import time


def depositar(cuenta, monto):
    """PROBLEMA: actualización perdida. Leer y escribir son dos pasos separados."""
    actual = cuenta.saldo           # 1. leer
    time.sleep(0)                   # cede la CPU: otro hilo puede leer el mismo saldo
    cuenta.saldo = actual + monto   # 2. escribir (pisa lo que escribió el otro hilo)
    return True


def retirar(cuenta, monto):
    """PROBLEMA: verificar y luego actuar. El saldo puede cambiar entre ambos pasos."""
    actual = cuenta.saldo
    if actual < monto:              # saldo insuficiente: se rechaza
        return False
    time.sleep(0)                   # otro hilo puede retirar con el mismo saldo "viejo"
    cuenta.saldo = actual - monto
    return True


def transferir(origen, destino, monto):
    """PROBLEMA: toca dos cuentas sin proteger ninguna."""
    if origen.saldo < monto:
        return False
    actual = origen.saldo
    time.sleep(0)
    origen.saldo = actual - monto
    destino.saldo += monto
    return True


def consultar(cuenta):
    """PROBLEMA: puede leer un saldo que otro hilo está a medio actualizar."""
    return cuenta.saldo


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


def transferir_ingenuo(origen, destino, monto, espera=0.1, timeout=1):
    """PROBLEMA: interbloqueo. Usa locks, pero los toma en el orden de la transferencia.

    Si A->B y B->A ocurren a la vez, cada hilo tiene un lock y espera el otro:
    se cumplen las cuatro condiciones de Coffman. El timeout solo permite
    detectarlo en vez de quedarse colgado para siempre.
    """
    if not origen.lock.acquire(timeout=timeout):        # toma el recurso 1
        return "bloqueo"
    try:
        time.sleep(espera)          # lo retiene: da tiempo a que el otro tome el suyo
        if not destino.lock.acquire(timeout=timeout):   # pide el recurso 2: ciclo
            return "bloqueo"
        try:
            return "ok" if transferir(origen, destino, monto) else "rechazada"
        finally:
            destino.lock.release()
    finally:
        origen.lock.release()
