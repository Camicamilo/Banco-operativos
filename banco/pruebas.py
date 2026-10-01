"""Pruebas automáticas: corre los experimentos con 2, 4, 8 y 16 hilos.

Uso:
    python3 pruebas.py            # carga normal
    python3 pruebas.py --rapido   # menos operaciones, para probar que todo funciona

Imprime una tabla comparativa, la guarda en resultados/comparativa_<fecha>.csv
y .md, y verifica que todas las variantes corregidas den el resultado correcto.
Cada ejecución también queda en resultados/estadisticas.csv.
"""

import csv
import datetime
import os
import sys

import experimentos

CARGAS = [2, 4, 8, 16]
COLUMNAS = ["experimento", "variante", "procesos", "hilos", "operaciones", "segundos",
            "cpu_s", "nucleos_usados", "memoria_max_kb", "hilos_max",
            "esperado", "obtenido", "rechazadas", "correcto"]


def fila(experimento, variante, r, correcto):
    cpu = r.get("cpu_usuario_s", 0) + r.get("cpu_sistema_s", 0)
    datos = {k: r.get(k, "") for k in COLUMNAS}
    datos.update(experimento=experimento, variante=variante, cpu_s=round(cpu, 2),
                 nucleos_usados=round(cpu / r["segundos"], 2) if r.get("segundos") else "",
                 correcto=correcto)
    return datos


def main():
    rapido = "--rapido" in sys.argv
    ops = 500 if rapido else 5000          # operaciones por hilo en la carrera
    filas, fallas = [], []

    def revisar(nombre, condicion):
        if not condicion:
            fallas.append(nombre)
        return "sí" if condicion else "NO"

    for h in CARGAS:
        print(f"--- {h} hilos ---", flush=True)
        r = experimentos.carrera(h, ops)
        filas.append(fila("carrera", "con_problema", r["con_problema"], "(se espera pérdida)"))
        for v in ("lock_por_cuenta", "lock_global", "dueno_por_cuenta"):
            ok = r[v]["obtenido"] == r[v]["esperado"]
            filas.append(fila("carrera", v, r[v], revisar(f"carrera {v} {h}", ok)))

        r = experimentos.cola(h, ops // 10)
        filas.append(fila("cola", "con_problema", r["con_problema"], "(puede no cuadrar)"))
        filas.append(fila("cola", "corregido", r["corregido"],
                          revisar(f"cola {h}", r["corregido"]["cuadra"])))

        r = experimentos.multiproceso(2, h, ops // 20)
        filas.append(fila("multiproceso", "con_problema", r["con_problema"], "(puede no cuadrar)"))
        filas.append(fila("multiproceso", "corregido", r["corregido"],
                          revisar(f"multiproceso {h}", r["corregido"]["cuadra"])))

        r = experimentos.auditoria(h, ops // 10 if rapido else ops // 5)
        filas.append(fila("auditoria", "hilos", r["hilos"], "-"))
        filas.append(fila("auditoria", "procesos", r["procesos"], "-"))

    r = experimentos.interbloqueo()
    filas.append(fila("interbloqueo", "con_problema", r["con_problema"], "(se espera bloqueo)"))
    for v in ("orden_global", "reintento"):
        ok = all(x == "ok" for x in r[v]["resultados"].values())
        filas.append(fila("interbloqueo", v, r[v], revisar(f"interbloqueo {v}", ok)))

    guardar(filas)
    print()
    print(como_markdown(filas))
    print()
    if fallas:
        print("FALLARON:", ", ".join(fallas))
        sys.exit(1)
    print("Todas las variantes corregidas dieron el resultado correcto.")


def como_markdown(filas):
    lineas = ["| " + " | ".join(COLUMNAS) + " |", "|" + "---|" * len(COLUMNAS)]
    for f in filas:
        lineas.append("| " + " | ".join(str(f[c]) for c in COLUMNAS) + " |")
    return "\n".join(lineas)


def guardar(filas):
    os.makedirs(experimentos.CARPETA_RESULTADOS, exist_ok=True)
    fecha = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(experimentos.CARPETA_RESULTADOS, f"comparativa_{fecha}")
    with open(base + ".csv", "w", newline="") as f:
        escritor = csv.DictWriter(f, COLUMNAS)
        escritor.writeheader()
        escritor.writerows(filas)
    with open(base + ".md", "w") as f:
        f.write(f"# Comparativa {fecha} ({os.cpu_count()} núcleos)\n\n{como_markdown(filas)}\n")
    print(f"\nGuardado en {base}.csv y {base}.md")


if __name__ == "__main__":  # necesario: los procesos hijos (spawn) reimportan este módulo
    main()
