# Arquitectura

GitHub dibuja los bloques `mermaid` directamente. Para draw.io: *Organizar → Insertar → Avanzado → Mermaid* y pegar el bloque.

## Componentes y procesos

```mermaid
flowchart TB
    U[Navegador<br/>static/index.html] -- "HTTP POST /api/..." --> S

    subgraph S["Proceso banco-servidor (servidor.py)"]
        HTTP["Hilo por petición<br/>(ThreadingHTTPServer)"]
        REG["registrar()<br/>lock de archivo"]
        HTTP --> REG
    end

    REG --> CSV[("resultados/<br/>estadisticas.csv<br/>ejecuciones.jsonl")]

    subgraph P1["Proceso hijo por experimento (spawn)"]
        direction TB
        H1["hilo-0 ... hilo-N<br/>productores / consumidores<br/>auditores"]
        M1["monitor<br/>VmRSS, Threads, os.times()"]
        C1[("Cuentas en memoria del proceso<br/>threading.Lock por cuenta")]
        H1 --> C1
    end

    subgraph MP["Experimento multiproceso"]
        direction TB
        Q[["multiprocessing.Queue<br/>(maxsize 1000)"]]
        T0["trabajador-0<br/>N hilos + monitor"]
        T1["trabajador-1<br/>N hilos + monitor"]
        TP["trabajador-P<br/>N hilos + monitor"]
        SH[("multiprocessing.Array (saldos)<br/>+ multiprocessing.Lock por cuenta")]
        Q --> T0 & T1 & TP
        T0 & T1 & TP --> SH
    end

    HTTP -- "multiprocessing (spawn)" --> P1
    HTTP -- "productor: put()" --> Q
    P1 -- "resultado (Queue)" --> HTTP
    T0 & T1 & TP -- "resultado (Queue)" --> HTTP

    OBS["observar.sh<br/>pstree, ps -eLf, /proc, top -H"] -. observa .-> S
    PR["pruebas.py<br/>2, 4, 8, 16 hilos"] -- "mismas funciones" --> P1
```

## Flujo de una transacción (cola y multiproceso)

```mermaid
sequenceDiagram
    participant Prod as Productor
    participant Cola as Cola (acotada)
    participant Cons as Consumidor (hilo)
    participant Cta as Cuenta(s)
    Prod->>Cola: put((tipo, origen, destino, monto))
    Note over Prod,Cola: si está llena, el productor se bloquea
    Cons->>Cola: get()
    Note over Cons,Cola: si está vacía, el consumidor se bloquea
    alt depósito / retiro / consulta
        Cons->>Cta: with cuenta.lock
    else transferencia
        Cons->>Cta: locks en orden por id (evita espera circular)
    end
    Cta-->>Cons: hecha o rechazada (saldo insuficiente)
    Cons->>Cons: Contador.anotar(tipo, monto, hecha)
    Prod->>Cola: None (una señal de fin por consumidor)
```
