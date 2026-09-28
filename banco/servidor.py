"""Servidor web: sirve la página y expone los experimentos como API JSON."""

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import experimentos

PUERTO = int(os.environ.get("PORT", 8000))
CARPETA = os.path.dirname(os.path.abspath(__file__))


def ver_procesos():
    """Procesos e hilos del servicio, tal como los ve el sistema operativo."""
    pid = os.getpid()
    filtro = f"$1=={pid} || $2=={pid} || NR==1"   # el servidor, sus hijos y el encabezado
    comandos = {
        "pstree": ["pstree", "-pt", str(pid)],
        "ps -eLf": ["sh", "-c", f"ps -eLf | awk '{filtro}'"],
    }
    salida = {}
    for nombre, comando in comandos.items():
        try:
            salida[nombre] = subprocess.run(comando, capture_output=True, text=True).stdout
        except OSError:
            salida[nombre] = "comando no disponible (¿estás en Linux?)"
    salida["pid_servidor"] = pid
    return salida


class Manejador(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            with open(os.path.join(CARPETA, "static", "index.html"), "rb") as f:
                self.responder(200, f.read(), "text/html; charset=utf-8")
        elif self.path == "/api/procesos":
            self.responder_json(ver_procesos())
        elif self.path == "/api/estadisticas":
            self.responder_json(experimentos.ultimas_estadisticas())
        else:
            self.responder_json({"error": "no encontrado"}, 404)

    def do_POST(self):
        url = urlparse(self.path)
        p = {k: float(v[0]) for k, v in parse_qs(url.query).items()}
        hilos, operaciones = int(p.get("hilos", 8)), int(p.get("operaciones", 5000))
        procesos = int(p.get("procesos", 3))
        if url.path == "/api/carrera":
            self.responder_json(experimentos.carrera(hilos, operaciones))
        elif url.path == "/api/cola":
            self.responder_json(experimentos.cola(hilos, operaciones // 10))
        elif url.path == "/api/interbloqueo":
            self.responder_json(experimentos.interbloqueo(p.get("espera", 0.1),
                                                          p.get("timeout", 1)))
        elif url.path == "/api/multiproceso":
            self.responder_json(experimentos.multiproceso(procesos, hilos, operaciones // 10))
        elif url.path == "/api/auditoria":
            self.responder_json(experimentos.auditoria(hilos, operaciones // 2))
        else:
            self.responder_json({"error": "no encontrado"}, 404)

    def responder_json(self, datos, codigo=200):
        self.responder(codigo, json.dumps(datos).encode(), "application/json")

    def responder(self, codigo, cuerpo, tipo):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)


if __name__ == "__main__":  # necesario: los procesos hijos (spawn) reimportan este módulo
    experimentos.nombrar_en_so("banco-servidor")
    print(f"Servidor PID {os.getpid()} en http://0.0.0.0:{PUERTO}")
    ThreadingHTTPServer(("0.0.0.0", PUERTO), Manejador).serve_forever()
