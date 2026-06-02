from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for

from secure_log import anadir_al_log, inicializar_log, monitor1
from access_control import access_control, set_active_user

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = DATA_DIR / "aula_secmlgbyte.sqlite3"
LOG_PATH      = str(DATA_DIR / "AulaSecMLGbyte.log")

# ── Constantes ────────────────────────────────────────────────────────────────
INITIAL_BALANCE = 3.0
TRANSACTION_FEE = 0.05   # 5% va al fondo de dividendos
MAX_BALANCE     = 100.0

SUBJECTS = [
    "Matemáticas", "Programación", "Sistemas Operativos",
    "Bases de Datos", "Software Seguro", "Otra",
]

SUBJECT_META: dict[str, dict] = {
    "Matemáticas":         {"code": "mat", "icon": "∑"},
    "Programación":        {"code": "pro", "icon": "</>"},
    "Sistemas Operativos": {"code": "sis", "icon": "⚙"},
    "Bases de Datos":      {"code": "bda", "icon": "▦"},
    "Software Seguro":     {"code": "swg", "icon": "⚿"},
    "Otra":                {"code": "otr", "icon": "◎"},
}

# ── Estado en memoria ─────────────────────────────────────────────────────────
wallets:          dict[int, float]      = {}
wallet_addresses: dict[int, str]        = {}
notes_db:         dict[int, dict]       = {}
transactions:     list[dict]            = []
purchases:        set[tuple[int, int]]  = set()
ratings_db:       dict[int, list[dict]] = {}
_note_id_counter = 0
_dividend_pool:   list[float]           = [0.0]


def get_pool() -> float:
    return round(_dividend_pool[0], 4)


@monitor1("info")
def add_to_pool(amount: float) -> float:
    _dividend_pool[0] = round(_dividend_pool[0] + amount, 4)
    return _dividend_pool[0]


# ── App ───────────────────────────────────────────────────────────────────────
app = Flask(
    __name__,
    template_folder=str(FRONTEND_DIR / "templates"),
    static_folder=str(FRONTEND_DIR / "static"),
    static_url_path="/static",
)
app.config["SECRET_KEY"] = "notecoin-aula-secret-key"


# ── DB helpers ────────────────────────────────────────────────────────────────
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    inicializar_log(LOG_PATH)
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                email    TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                name     TEXT NOT NULL,
                role     TEXT NOT NULL DEFAULT 'student'
            );
            CREATE TABLE IF NOT EXISTS profiles (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id  INTEGER NOT NULL UNIQUE,
                email    TEXT NOT NULL,
                address  TEXT NOT NULL,
                phone    TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
        """)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO users (email, password, name, role) VALUES (?,?,?,?)",
                [
                    ("ana@example.test",    "ana123",    "Ana García",      "student"),
                    ("bruno@example.test",  "bruno123",  "Bruno López",     "student"),
                    ("admin@example.test",  "admin123",  "Admin",           "admin"),
                    ("carlos@example.test", "carlos123", "Carlos Martínez", "student"),
                    ("laura@example.test",  "laura123",  "Laura Sánchez",   "student"),
                    ("pedro@example.test",  "pedro123",  "Pedro García",    "student"),
                    ("sofia@example.test",  "sofia123",  "Sofía Ruiz",      "student"),
                ],
            )
            conn.executemany(
                "INSERT INTO profiles (user_id, email, address, phone) VALUES (?,?,?,?)",
                [
                    (1, "ana@example.test",    "Ingeniería Informática", "600111222"),
                    (2, "bruno@example.test",  "Ingeniería Informática", "600333444"),
                    (3, "admin@example.test",  "Administración",         "600999888"),
                    (4, "carlos@example.test", "Ingeniería Informática", "600444555"),
                    (5, "laura@example.test",  "Ingeniería Informática", "600555666"),
                    (6, "pedro@example.test",  "Ingeniería Informática", "600666777"),
                    (7, "sofia@example.test",  "Ingeniería Informática", "600777888"),
                ],
            )
    _seed_notes()


# ── Crypto helpers ────────────────────────────────────────────────────────────
def _gen_address() -> str:
    raw = secrets.token_bytes(20)
    return "NC" + hashlib.sha256(raw).hexdigest()[:38].upper()


def _gen_tx_hash(from_w: str, to_w: str, amount: float) -> str:
    payload = f"{from_w}{to_w}{amount}{time.time()}{secrets.token_hex(8)}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _note_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _record_tx(
    from_wallet: str, to_wallet: str, amount: float, fee: float,
    tx_type: str, description: str, note_id: int | None = None,
) -> str:
    tx_hash = _gen_tx_hash(from_wallet, to_wallet, amount)
    transactions.append({
        "tx_hash":     tx_hash,
        "from_wallet": from_wallet,
        "to_wallet":   to_wallet,
        "amount":      amount,
        "fee":         fee,
        "tx_type":     tx_type,
        "note_id":     note_id,
        "description": description,
        "created_at":  datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    })
    return tx_hash


def ensure_wallet(user_id: int, user_name: str) -> None:
    if user_id not in wallets:
        wallets[user_id] = INITIAL_BALANCE
        wallet_addresses[user_id] = _gen_address()
        _record_tx(
            from_wallet="SISTEMA",
            to_wallet=wallet_addresses[user_id],
            amount=INITIAL_BALANCE,
            fee=0,
            tx_type="coinbase",
            description=f"Saldo inicial — {user_name}",
        )


def get_wallet(user_id: int) -> float:
    return wallets.get(user_id, 0.0)


# ── Seed ──────────────────────────────────────────────────────────────────────
def _seed_notes() -> None:
    global _note_id_counter
    if notes_db:
        return

    seed_users = [
        (1, "Ana García"),
        (2, "Bruno López"),
        (3, "Admin"),
        (4, "Carlos Martínez"),
        (5, "Laura Sánchez"),
        (6, "Pedro García"),
        (7, "Sofía Ruiz"),
    ]
    for uid, name in seed_users:
        ensure_wallet(uid, name)

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    demo = [
        # ── Ana García (id=1) ──────────────────────────────────────
        {
            "owner_id": 1, "owner_name": "Ana García",
            "title": "Resumen de criptografía simétrica",
            "subject": "Software Seguro",
            "description": "AES, DES y modos de operación con ejemplos.",
            "content": (
                "Criptografía simétrica\n======================\n\n"
                "Usa la misma clave para cifrar y descifrar.\n\n"
                "AES\n---\n- Bloques de 128 bits\n- Claves de 128, 192 o 256 bits\n"
                "- Modos: ECB, CBC, GCM\n\nDES (obsoleto)\n--------------\n"
                "- Clave de 56 bits, inseguro.\n\nModos de operación\n------------------\n"
                "- ECB: sin encadenamiento, inseguro.\n"
                "- CBC: cada bloque depende del anterior.\n"
                "- GCM: autenticado, recomendado."
            ),
            "price": 1.0, "views": 12, "grade": "9.0",
        },
        {
            "owner_id": 1, "owner_name": "Ana García",
            "title": "Álgebra lineal: matrices y determinantes",
            "subject": "Matemáticas",
            "description": "Operaciones básicas, inversa y rango con ejemplos.",
            "content": (
                "Matrices\n========\n\nOperaciones\n-----------\n"
                "- Suma: misma dimensión\n- Producto: columnas de A = filas de B\n- Transpuesta\n\n"
                "Determinante\n------------\n- Solo para matrices cuadradas\n"
                "- det(AB) = det(A)·det(B)\n\nInversa\n-------\n"
                "- Existe si det != 0\n- A·A^(-1) = I"
            ),
            "price": 1.5, "views": 8, "grade": "8.0",
        },
        # ── Bruno López (id=2) ─────────────────────────────────────
        {
            "owner_id": 2, "owner_name": "Bruno López",
            "title": "Apuntes de TCP/IP",
            "subject": "Otra",
            "description": "Modelo de capas, protocolos y ejercicios resueltos.",
            "content": (
                "TCP/IP\n======\n\nModelo de capas\n---------------\n"
                "1. Enlace\n2. Internet (IP)\n3. Transporte (TCP/UDP)\n4. Aplicación\n\n"
                "TCP\n---\n- Orientado a conexión (three-way handshake)\n"
                "- Control de flujo y congestión\n- Fiable\n\n"
                "UDP\n---\n- Sin conexión\n- Más rápido, sin garantías de entrega"
            ),
            "price": 0.8, "views": 15, "grade": "8.5",
        },
        {
            "owner_id": 2, "owner_name": "Bruno López",
            "title": "Direccionamiento IPv4 y subredes",
            "subject": "Otra",
            "description": "Clases, CIDR, máscaras de subred y ejercicios.",
            "content": (
                "IPv4\n====\n\nClases de red\n-------------\n"
                "- Clase A: 0.0.0.0 - 127.255.255.255\n"
                "- Clase B: 128.0.0.0 - 191.255.255.255\n"
                "- Clase C: 192.0.0.0 - 223.255.255.255\n\n"
                "CIDR\n----\nNotacion: 192.168.1.0/24\n"
                "Hosts utiles = 2^(32-prefijo) - 2\n\n"
                "Ejemplo: /24 -> 254 hosts, /25 -> 126 hosts"
            ),
            "price": 1.0, "views": 9, "grade": "8.0",
        },
        # ── Carlos Martínez (id=4) ─────────────────────────────────
        {
            "owner_id": 4, "owner_name": "Carlos Martínez",
            "title": "Introducción a Python",
            "subject": "Programación",
            "description": "Variables, tipos de datos, bucles y funciones básicas.",
            "content": (
                "Python Basico\n=============\n\nVariables\n---------\n"
                "x = 5\nnombre = 'hola'\nlista = [1, 2, 3]\n\n"
                "Bucles\n------\nfor i in range(10):\n    print(i)\n\n"
                "Funciones\n---------\ndef suma(a, b):\n    return a + b\n\n"
                "print(suma(3, 4))  # 7"
            ),
            "price": 0.8, "views": 20, "grade": "9.5",
        },
        {
            "owner_id": 4, "owner_name": "Carlos Martínez",
            "title": "Listas, tuplas y diccionarios en Python",
            "subject": "Programación",
            "description": "Estructuras de datos básicas con ejemplos prácticos.",
            "content": (
                "Estructuras de datos\n====================\n\n"
                "Lista\n-----\nlista = [1, 2, 3]\nlista.append(4)\nlista.pop()\n\n"
                "Tupla\n-----\ntupla = (1, 2, 3)  # inmutable\n\n"
                "Diccionario\n-----------\nd = {'clave': 'valor'}\nd['nueva'] = 42\n"
                "for k, v in d.items():\n    print(k, v)"
            ),
            "price": 1.0, "views": 11, "grade": "9.0",
        },
        {
            "owner_id": 4, "owner_name": "Carlos Martínez",
            "title": "SQL basico: SELECT, JOIN y subconsultas",
            "subject": "Bases de Datos",
            "description": "Consultas SQL desde cero con ejemplos reales.",
            "content": (
                "SQL\n===\n\nSELECT basico\n-------------\n"
                "SELECT nombre, edad FROM usuarios WHERE edad > 18;\n\n"
                "JOIN\n----\nSELECT u.nombre, p.producto\n"
                "FROM usuarios u\nINNER JOIN pedidos p ON u.id = p.usuario_id;\n\n"
                "Subconsulta\n-----------\n"
                "SELECT nombre FROM usuarios\nWHERE id IN (SELECT usuario_id FROM pedidos);"
            ),
            "price": 1.2, "views": 14, "grade": "8.5",
        },
        {
            "owner_id": 4, "owner_name": "Carlos Martínez",
            "title": "Normalizacion de bases de datos",
            "subject": "Bases de Datos",
            "description": "1FN, 2FN, 3FN y FNBC explicadas con ejemplos.",
            "content": (
                "Normalizacion\n=============\n\n1FN\n---\n"
                "- Atributos atomicos, sin grupos repetidos\n\n"
                "2FN\n---\n- Cumple 1FN + sin dependencias parciales\n\n"
                "3FN\n---\n- Cumple 2FN + sin dependencias transitivas\n\n"
                "FNBC\n----\n- Todo determinante es clave candidata"
            ),
            "price": 1.5, "views": 6, "grade": "9.0",
        },
        {
            "owner_id": 4, "owner_name": "Carlos Martínez",
            "title": "Algoritmos de ordenacion",
            "subject": "Programación",
            "description": "BubbleSort, MergeSort y QuickSort con complejidades.",
            "content": (
                "Algoritmos de ordenacion\n========================\n\n"
                "BubbleSort\n----------\nO(n^2) en todos los casos. Simple, ineficiente.\n\n"
                "MergeSort\n---------\nO(n log n) siempre. Divide y venceras.\n\n"
                "QuickSort\n---------\nO(n log n) media, O(n^2) peor caso.\n"
                "Elige un pivote, particiona.\n\nResumen\n-------\n"
                "Pocos datos: InsertionSort\nMuchos: MergeSort o QuickSort"
            ),
            "price": 1.0, "views": 18, "grade": "8.0",
        },
        # ── Laura Sánchez (id=5) ───────────────────────────────────
        {
            "owner_id": 5, "owner_name": "Laura Sánchez",
            "title": "Calculo diferencial: derivadas",
            "subject": "Matemáticas",
            "description": "Reglas de derivacion, cadena y derivadas implicitas.",
            "content": (
                "Derivadas\n=========\n\nReglas basicas\n--------------\n"
                "- d/dx(x^n) = n*x^(n-1)\n- d/dx(sin x) = cos x\n"
                "- d/dx(e^x) = e^x\n- d/dx(ln x) = 1/x\n\n"
                "Regla de la cadena\n------------------\n"
                "d/dx f(g(x)) = f'(g(x)) * g'(x)\n\n"
                "Ejemplo: d/dx(sin(x^2)) = cos(x^2) * 2x"
            ),
            "price": 1.2, "views": 22, "grade": "9.5",
        },
        {
            "owner_id": 5, "owner_name": "Laura Sánchez",
            "title": "Integrales indefinidas y metodos",
            "subject": "Matemáticas",
            "description": "Integracion por sustitucion, partes y fracciones parciales.",
            "content": (
                "Integrales\n==========\n\nReglas basicas\n--------------\n"
                "int x^n dx = x^(n+1)/(n+1) + C\nint e^x dx = e^x + C\nint 1/x dx = ln|x| + C\n\n"
                "Sustitucion\n-----------\nSi u = g(x), entonces du = g'(x)dx\n\n"
                "Integracion por partes\n-----------------------\nint u dv = uv - int v du"
            ),
            "price": 1.5, "views": 17, "grade": "9.0",
        },
        {
            "owner_id": 5, "owner_name": "Laura Sánchez",
            "title": "Probabilidad y estadistica basica",
            "subject": "Matemáticas",
            "description": "Media, varianza, distribuciones y probabilidad condicionada.",
            "content": (
                "Estadistica\n===========\n\nMedidas de centralizacion\n-------------------------\n"
                "- Media: x = sum(xi)/n\n- Mediana: valor central\n- Moda: valor mas frecuente\n\n"
                "Varianza\n--------\nVar = sum((xi-x)^2)/n\nDE = sqrt(Var)\n\n"
                "Probabilidad condicionada\n--------------------------\n"
                "P(A|B) = P(A int B)/P(B)\n"
                "Bayes: P(A|B) = P(B|A)*P(A)/P(B)"
            ),
            "price": 1.0, "views": 13, "grade": "8.5",
        },
        {
            "owner_id": 5, "owner_name": "Laura Sánchez",
            "title": "DNS, HTTP y HTTPS explicados",
            "subject": "Otra",
            "description": "Como funciona la web: DNS, peticiones HTTP y HTTPS.",
            "content": (
                "DNS\n===\nTraduce nombres a IPs.\n"
                "Ejemplo: www.google.com -> 142.250.200.46\n\n"
                "HTTP\n====\nMetodos: GET, POST, PUT, DELETE\n"
                "Cabeceras: Content-Type, Authorization, Cookie\n\n"
                "HTTPS\n=====\n= HTTP + TLS\n"
                "ClientHello -> ServerHello -> Certificado -> Clave de sesion\n"
                "Todo el trafico queda cifrado."
            ),
            "price": 0.8, "views": 25, "grade": "9.0",
        },
        {
            "owner_id": 5, "owner_name": "Laura Sánchez",
            "title": "Vocabulario ingles tecnico para ingenieria",
            "subject": "Otra",
            "description": "Terminos frecuentes en documentacion tecnica y entrevistas.",
            "content": (
                "Technical English\n=================\n\nCommon verbs\n------------\n"
                "- to implement -> implementar\n- to deploy -> desplegar\n"
                "- to parse -> analizar/procesar\n- to fetch -> obtener\n"
                "- to override -> sobreescribir\n\nUseful phrases\n--------------\n"
                "- 'It is deprecated' -> Esta obsoleto\n"
                "- 'Pull request' -> Solicitud de cambio en Git\n"
                "- 'Edge case' -> Caso limite"
            ),
            "price": 0.5, "views": 30, "grade": "8.0",
        },
        # ── Pedro García (id=6) ────────────────────────────────────
        {
            "owner_id": 6, "owner_name": "Pedro García",
            "title": "Procesos e hilos en Linux",
            "subject": "Sistemas Operativos",
            "description": "fork(), exec(), pthreads y senales.",
            "content": (
                "Procesos\n========\nfork() -> crea proceso hijo\n"
                "exec() -> reemplaza imagen del proceso\nwait() -> espera al hijo\n\n"
                "Hilos (pthreads)\n----------------\n"
                "pthread_create() -> crea hilo\npthread_join() -> espera al hilo\n"
                "pthread_mutex_lock/unlock() -> exclusion mutua\n\n"
                "Senales\n-------\nSIGKILL -> matar (no se puede capturar)\n"
                "SIGTERM -> terminar con gracia\nSIGINT -> Ctrl+C"
            ),
            "price": 1.2, "views": 10, "grade": "8.5",
        },
        {
            "owner_id": 6, "owner_name": "Pedro García",
            "title": "Gestion de memoria: paginacion y segmentacion",
            "subject": "Sistemas Operativos",
            "description": "Memoria virtual, TLB, fragmentacion y swap.",
            "content": (
                "Gestion de memoria\n==================\n\nPaginacion\n----------\n"
                "- Division en paginas de tamano fijo\n- Tabla de paginas: VP -> MP\n"
                "- TLB: cache de traducciones (rapida)\n\nSegmentacion\n------------\n"
                "- Division logica (codigo, datos, pila)\n- Segmentos de tamano variable\n\n"
                "Memoria virtual\n---------------\n- Swap: paginas en disco\n"
                "- Page fault: carga del disco\n- Thrashing: demasiados page faults"
            ),
            "price": 1.5, "views": 7, "grade": "9.0",
        },
        {
            "owner_id": 6, "owner_name": "Pedro García",
            "title": "Deadlocks: causas, deteccion y prevencion",
            "subject": "Sistemas Operativos",
            "description": "Condiciones de Coffman, grafo de recursos y algoritmos.",
            "content": (
                "Deadlock\n========\n\nCondiciones de Coffman\n----------------------\n"
                "1. Exclusion mutua\n2. Retencion y espera\n"
                "3. No apropiacion\n4. Espera circular\n\n"
                "Prevencion\n----------\n- Eliminar alguna condicion de Coffman\n\n"
                "Deteccion\n---------\n- Grafo de asignacion de recursos\n"
                "- Si tiene ciclo -> deadlock\n\nRecuperacion\n------------\n"
                "- Terminar proceso(s) involucrados"
            ),
            "price": 1.0, "views": 5, "grade": "8.0",
        },
        {
            "owner_id": 6, "owner_name": "Pedro García",
            "title": "RSA y criptografia asimetrica",
            "subject": "Software Seguro",
            "description": "Funcionamiento de RSA, claves publica/privada y firma digital.",
            "content": (
                "Criptografia asimetrica\n=======================\n\n"
                "Principio\n---------\n- Clave publica: cifrar\n- Clave privada: descifrar\n\n"
                "RSA\n---\n1. Elegir p, q primos grandes\n2. n = p*q\n"
                "3. phi(n) = (p-1)(q-1)\n4. e: coprimo con phi(n)\n"
                "5. d: inverso de e mod phi(n)\n\n"
                "Cifrar: C = M^e mod n\nDescifrar: M = C^d mod n\n\n"
                "Firma digital\n-------------\n"
                "Firmar con clave privada -> verificar con clave publica"
            ),
            "price": 1.5, "views": 19, "grade": "9.5",
        },
        {
            "owner_id": 6, "owner_name": "Pedro García",
            "title": "HTTPS y TLS: handshake y certificados",
            "subject": "Software Seguro",
            "description": "Como funciona TLS 1.3, PKI y certificados X.509.",
            "content": (
                "TLS 1.3 Handshake\n-----------------\n1. ClientHello (cipher suites)\n"
                "2. ServerHello + Certificate\n3. Verificacion del certificado\n"
                "4. Derivacion de claves de sesion\n5. Comunicacion cifrada\n\n"
                "Certificados X.509\n------------------\n"
                "- Contienen: clave publica + identidad + firma de CA\n"
                "- CA: entidad de confianza\n"
                "- Cadena: certificado -> CA intermedia -> CA raiz\n\n"
                "Perfect Forward Secrecy\n-----------------------\n"
                "Claves efimeras -> tráfico pasado seguro si roban la clave"
            ),
            "price": 1.2, "views": 16, "grade": "9.0",
        },
        # ── Sofía Ruiz (id=7) ──────────────────────────────────────
        {
            "owner_id": 7, "owner_name": "Sofía Ruiz",
            "title": "Grafos: BFS, DFS y caminos minimos",
            "subject": "Programación",
            "description": "Recorridos en grafos y algoritmo de Dijkstra.",
            "content": (
                "Grafos\n======\n\nBFS (Busqueda en anchura)\n-------------------------\n"
                "- Usa cola (queue)\n- Camino minimo en grafos no ponderados\n- O(V + E)\n\n"
                "DFS (Busqueda en profundidad)\n------------------------------\n"
                "- Usa pila (stack) o recursion\n- Detecta ciclos\n- O(V + E)\n\n"
                "Dijkstra\n--------\n- Camino minimo en grafos ponderados (pesos >= 0)\n"
                "- Usa cola de prioridad\n- O((V+E) log V)"
            ),
            "price": 1.0, "views": 21, "grade": "9.0",
        },
        {
            "owner_id": 7, "owner_name": "Sofía Ruiz",
            "title": "Arboles binarios y BST",
            "subject": "Programación",
            "description": "Insercion, busqueda, recorridos y balanceo.",
            "content": (
                "Arbol binario\n=============\n\nRecorridos\n----------\n"
                "- Inorden: izq -> raiz -> der\n- Preorden: raiz -> izq -> der\n"
                "- Postorden: izq -> der -> raiz\n\n"
                "BST\n---\n- nodo.izq < nodo < nodo.der\n- Busqueda: O(log n) si balanceado\n\n"
                "Arboles AVL\n-----------\n- BST autobalanceado\n"
                "- |altura(izq) - altura(der)| <= 1"
            ),
            "price": 1.2, "views": 9, "grade": "8.5",
        },
        {
            "owner_id": 7, "owner_name": "Sofía Ruiz",
            "title": "Programacion dinamica: memoizacion y tabulacion",
            "subject": "Programación",
            "description": "Fibonacci, mochila 0/1 y longest common subsequence.",
            "content": (
                "Programacion dinamica\n=====================\n\n"
                "Principio\n---------\nSubproblemas solapados. Guarda resultados para no recalcular.\n\n"
                "Top-down (memoizacion)\n-----------------------\ndef fib(n, memo={}):\n"
                "    if n in memo: return memo[n]\n"
                "    if n <= 1: return n\n    memo[n] = fib(n-1)+fib(n-2)\n"
                "    return memo[n]\n\nBottom-up (tabulacion)\n-----------------------\n"
                "dp = [0]*(n+1)\ndp[1] = 1\nfor i in range(2,n+1):\n"
                "    dp[i] = dp[i-1]+dp[i-2]"
            ),
            "price": 1.5, "views": 12, "grade": "9.0",
        },
        {
            "owner_id": 7, "owner_name": "Sofía Ruiz",
            "title": "Complejidad algoritmica: notacion Big-O",
            "subject": "Programación",
            "description": "O(1), O(log n), O(n), O(n^2) con ejemplos reales.",
            "content": (
                "Complejidad\n===========\n\nNotaciones\n----------\n"
                "O(1)       -> acceso a array por indice\n"
                "O(log n)   -> busqueda binaria\n"
                "O(n)       -> recorrer lista\n"
                "O(n log n) -> MergeSort\n"
                "O(n^2)     -> BubbleSort\n"
                "O(2^n)     -> backtracking\n\n"
                "Reglas\n------\n- Se descarta la constante: 3n -> O(n)\n"
                "- Termino dominante: n^2+n -> O(n^2)"
            ),
            "price": 0.8, "views": 28, "grade": "9.5",
        },
        {
            "owner_id": 7, "owner_name": "Sofía Ruiz",
            "title": "Present Perfect y tiempos verbales en ingles",
            "subject": "Otra",
            "description": "Uso del Present Perfect vs Past Simple con ejemplos.",
            "content": (
                "Present Perfect\n===============\n\nEstructura\n----------\n"
                "have/has + participio pasado\n\nUso\n---\n"
                "- Accion pasada con efecto en el presente\n"
                "  'I have finished the project'\n"
                "- Experiencia de vida: 'I have visited London'\n"
                "- Con: just, already, yet, ever, never\n\n"
                "vs Past Simple\n--------------\n"
                "Past Simple: tiempo definido ('I finished yesterday')\n"
                "Present Perfect: tiempo indefinido ('I have finished')"
            ),
            "price": 0.5, "views": 35, "grade": "8.5",
        },
    ]

    for note in demo:
        _note_id_counter += 1
        nid = _note_id_counter
        notes_db[nid] = {
            "id": nid, "created_at": now,
            "file_hash": _note_hash(note["content"]),
            **note,
        }

    ratings_db[1] = [
        {"user_id": 2, "user_name": "Bruno López", "score": 5,
         "comment": "Muy claros y bien organizados", "created_at": now},
        {"user_id": 4, "user_name": "Carlos Martínez", "score": 5,
         "comment": "Perfectos para el examen", "created_at": now},
    ]
    ratings_db[3] = [
        {"user_id": 1, "user_name": "Ana García", "score": 4,
         "comment": "Buena estructura", "created_at": now},
        {"user_id": 5, "user_name": "Laura Sánchez", "score": 5,
         "comment": "Muy completo", "created_at": now},
    ]
    ratings_db[5] = [
        {"user_id": 2, "user_name": "Bruno López", "score": 4,
         "comment": "Bien explicado con ejemplos", "created_at": now},
    ]
    ratings_db[16] = [
        {"user_id": 1, "user_name": "Ana García", "score": 5,
         "comment": "Explicacion muy clara del handshake TLS", "created_at": now},
    ]


# ── Auth helpers ──────────────────────────────────────────────────────────────
def current_user() -> sqlite3.Row | None:
    uid = session.get("user_id")
    if not uid:
        return None
    with get_connection() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


@app.before_request
def sync_active_user() -> None:
    set_active_user(
        session.get("user_id"),
        session.get("role"),
        session.get("email"),
    )


@app.errorhandler(PermissionError)
def handle_permission_error(e: PermissionError) -> Response:
    if request.path.startswith("/api/"):
        return jsonify({"error": str(e)}), 403
    return redirect(url_for("index"))


@app.context_processor
def inject_globals() -> dict[str, Any]:
    user = current_user()
    return {
        "current_user":   user,
        "wallet_balance": get_wallet(user["id"]) if user else None,
        "wallet_addr":    wallet_addresses.get(user["id"]) if user else None,
        "subjects":       SUBJECTS,
        "subject_meta":   SUBJECT_META,
        "pool_amount":    get_pool(),
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> Response:
    return jsonify({"service": "NoteCoin", "status": "ok"})


@app.get("/")
def index() -> str:
    subject_filter = request.args.get("subject", "")
    query = request.args.get("q", "").lower()

    notes = list(notes_db.values())
    if subject_filter:
        notes = [n for n in notes if n["subject"] == subject_filter]
    if query:
        notes = [n for n in notes if
                 query in n["title"].lower() or
                 query in n["description"].lower() or
                 query in n["subject"].lower()]
    notes.sort(key=lambda n: n["id"], reverse=True)

    enriched = []
    for n in notes:
        rs = ratings_db.get(n["id"], [])
        avg = round(sum(r["score"] for r in rs) / len(rs), 1) if rs else 0
        enriched.append({**n, "avg_rating": avg, "rating_count": len(rs)})

    return render_template("index.html",
                           notes=enriched,
                           subject_filter=subject_filter,
                           query=query)


@app.get("/notes/<int:note_id>")
def note_detail(note_id: int) -> str | Response:
    user = current_user()
    note = notes_db.get(note_id)
    if note is None:
        return render_template("not_found.html"), 404

    note_ratings = ratings_db.get(note_id, [])
    avg_rating = round(sum(r["score"] for r in note_ratings) / len(note_ratings), 1) if note_ratings else 0

    already_purchased = is_owner = False
    my_rating = buyer_balance = buyer_addr = None

    if user:
        is_owner = user["id"] == note["owner_id"]
        already_purchased = is_owner or (user["id"], note_id) in purchases
        buyer_balance = get_wallet(user["id"])
        buyer_addr = wallet_addresses.get(user["id"])
        for r in note_ratings:
            if r["user_id"] == user["id"]:
                my_rating = r
                break

    return render_template(
        "note_detail.html",
        note=note,
        ratings=note_ratings,
        avg_rating=avg_rating,
        already_purchased=already_purchased,
        is_owner=is_owner,
        my_rating=my_rating,
        buyer_balance=buyer_balance,
        buyer_addr=buyer_addr,
    )


@app.post("/notes/<int:note_id>/buy")
def buy_note(note_id: int) -> Response:
    user = current_user()
    if not user:
        return jsonify({"error": "Debes iniciar sesion"}), 401

    note = notes_db.get(note_id)
    if note is None:
        return jsonify({"error": "Apunte no encontrado"}), 404
    if note["owner_id"] == user["id"]:
        return jsonify({"error": "No puedes comprarte tus propios apuntes"}), 400
    if (user["id"], note_id) in purchases:
        return jsonify({"error": "Ya tienes este apunte"}), 400

    price = note["price"]
    fee = round(price * TRANSACTION_FEE, 4)
    seller_receives = round(price - fee, 4)
    buyer_bal = get_wallet(user["id"])

    if buyer_bal < price:
        return jsonify({"error": f"Saldo insuficiente. Necesitas {price:.2f} NC, tienes {buyer_bal:.2f} NC"}), 400

    wallets[user["id"]] = round(buyer_bal - price, 4)
    wallets[note["owner_id"]] = round(get_wallet(note["owner_id"]) + seller_receives, 4)
    add_to_pool(fee)
    purchases.add((user["id"], note_id))
    note["views"] += 1

    buyer_addr_str = wallet_addresses.get(user["id"], "SISTEMA")
    seller_addr_str = wallet_addresses.get(note["owner_id"], "SISTEMA")
    tx_hash = _record_tx(
        from_wallet=buyer_addr_str,
        to_wallet=seller_addr_str,
        amount=price,
        fee=fee,
        tx_type="purchase",
        note_id=note_id,
        description=f"Compra: {note['title'][:50]}",
    )

    anadir_al_log(
        "info",
        f"Compra: apunte #{note_id} '{note['title'][:40]}' — {price:.2f} NC "
        f"(comisión {fee:.4f} NC) — tx {tx_hash[:12]}...",
    )

    return jsonify({
        "success": True,
        "tx_hash": tx_hash,
        "buyer_new_balance": round(wallets[user["id"]], 4),
        "seller_new_balance": round(wallets[note["owner_id"]], 4),
        "seller_name": note["owner_name"],
        "price": price,
        "fee": fee,
        "seller_receives": seller_receives,
        "dividend_added": fee,
    })


@app.post("/notes/<int:note_id>/rate")
def rate_note(note_id: int) -> Response:
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    note = notes_db.get(note_id)
    if note is None:
        return render_template("not_found.html"), 404
    if (user["id"], note_id) not in purchases and note["owner_id"] != user["id"]:
        return redirect(url_for("note_detail", note_id=note_id))

    try:
        score = max(1, min(5, int(request.form.get("score", 5))))
    except ValueError:
        score = 5
    comment = request.form.get("comment", "").strip()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    if note_id not in ratings_db:
        ratings_db[note_id] = []
    idx = next((i for i, r in enumerate(ratings_db[note_id]) if r["user_id"] == user["id"]), None)
    entry = {"user_id": user["id"], "user_name": user["name"],
             "score": score, "comment": comment, "created_at": now}
    if idx is not None:
        ratings_db[note_id][idx] = entry
    else:
        ratings_db[note_id].append(entry)

    anadir_al_log("info", f"Valoración: apunte #{note_id} — puntuación {score}/5")
    return redirect(url_for("note_detail", note_id=note_id))


@app.route("/notes/upload", methods=["GET", "POST"])
def upload_note() -> str | Response:
    user = current_user()
    if user is None:
        return redirect(url_for("login", next=url_for("upload_note")))

    error = None
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        subject = request.form.get("subject", "").strip()
        description = request.form.get("description", "").strip()
        content = request.form.get("content", "").strip()
        try:
            price = round(float(request.form.get("price", "1.0")), 2)
            if price <= 0:
                raise ValueError
        except ValueError:
            price = None

        if not title or not subject or not content:
            error = "Titulo, asignatura y contenido son obligatorios."
        elif subject not in SUBJECTS:
            error = "Asignatura no valida."
        elif price is None:
            error = "El precio debe ser un numero positivo."
        else:
            global _note_id_counter
            _note_id_counter += 1
            nid = _note_id_counter
            notes_db[nid] = {
                "id": nid, "title": title, "subject": subject,
                "description": description, "content": content,
                "price": price, "file_hash": _note_hash(content),
                "owner_id": user["id"], "owner_name": user["name"],
                "views": 0, "grade": None,
                "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            }
            anadir_al_log("info", f"Apunte subido: '{title}' ({subject}) — precio {price:.2f} NC — id={nid}")
            return redirect(url_for("note_detail", note_id=nid))

    return render_template("upload_note.html", error=error)


# ── Wallet ────────────────────────────────────────────────────────────────────

@app.get("/wallet")
def wallet_page() -> str | Response:
    user = current_user()
    if user is None:
        return redirect(url_for("login", next=url_for("wallet_page")))

    uid = user["id"]
    addr = wallet_addresses.get(uid, "")
    balance = get_wallet(uid)

    my_txs = [t for t in transactions if t["from_wallet"] == addr or t["to_wallet"] == addr]
    my_txs = list(reversed(my_txs[-30:]))

    my_notes = [n for n in notes_db.values() if n["owner_id"] == uid]
    my_purchases_list = [notes_db[nid] for (bid, nid) in purchases if bid == uid and nid in notes_db]

    return render_template(
        "wallet.html",
        w_balance=balance,
        w_addr=addr,
        transactions=my_txs,
        my_notes=my_notes,
        my_purchases=my_purchases_list,
    )


@app.get("/api/wallet")
def api_wallet() -> Response:
    user = current_user()
    if not user:
        return jsonify({"error": "not logged in"}), 401
    return jsonify({
        "balance": round(get_wallet(user["id"]), 4),
        "address": wallet_addresses.get(user["id"], ""),
    })


@app.get("/api/pool")
def api_pool() -> Response:
    return jsonify({"pool": get_pool()})


@app.post("/api/distribute-dividend")
@access_control
def distribute_dividend() -> Response:
    pool = get_pool()
    if pool < 0.01:
        return jsonify({"error": "El fondo es demasiado pequeno para distribuir"}), 400

    active = list(wallets.keys())
    if not active:
        return jsonify({"error": "No hay wallets activas"}), 400

    share = round(pool / len(active), 4)
    for uid in active:
        wallets[uid] = round(min(wallets[uid] + share, MAX_BALANCE), 4)
        _record_tx(
            from_wallet="POOL",
            to_wallet=wallet_addresses.get(uid, "SISTEMA"),
            amount=share, fee=0,
            tx_type="dividend",
            description=f"Dividendo ({share:.4f} NC)",
        )
    _dividend_pool[0] = 0.0

    anadir_al_log(
        "info",
        f"Dividendos distribuidos: {share:.4f} NC a {len(active)} wallets (total pool: {pool:.4f} NC)",
    )
    return jsonify({"success": True, "share_per_wallet": share, "wallets": len(active)})


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.get("/admin")
@access_control
def admin() -> str | Response:
    user = current_user()
    with get_connection() as conn:
        users = conn.execute("SELECT * FROM users").fetchall()
    wallet_list = [{"name": u["name"], "email": u["email"],
                    "address": wallet_addresses.get(u["id"], "—"),
                    "balance": get_wallet(u["id"])} for u in users]

    return render_template("admin.html",
                           wallets=wallet_list,
                           transactions=list(reversed(transactions[-30:])),
                           pool_amount=get_pool())


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login() -> str | Response:
    error = None
    if request.method == "POST":
        email = request.form.get("email", "")
        password = request.form.get("password", "")
        with get_connection() as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE email = ? AND password = ?",
                (email, password),
            ).fetchone()
        if user:
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["role"] = user["role"]
            session["email"] = user["email"]
            ensure_wallet(user["id"], user["name"])
            anadir_al_log("info", f"Login exitoso — usuario '{user['email']}' (rol: {user['role']})")
            next_url = request.args.get("next")
            if next_url and next_url.startswith("/"):
                return redirect(next_url)
            return redirect(url_for("index"))
        anadir_al_log("warning", f"Intento de login fallido para '{email}'")
        error = "Credenciales incorrectas."
    return render_template("login.html", error=error)


@app.get("/logout")
def logout() -> Response:
    email = session.get("email", "desconocido")
    anadir_al_log("info", f"Sesión cerrada — usuario '{email}'")
    session.clear()
    return redirect(url_for("index"))


@app.route("/account", methods=["GET", "POST"])
def account() -> str | Response:
    user = current_user()
    if user is None:
        return redirect(url_for("login", next=url_for("account")))

    if request.method == "POST":
        email = request.form.get("email", "")
        address = request.form.get("address", "")
        phone = request.form.get("phone", "")
        with get_connection() as conn:
            conn.execute(
                "UPDATE profiles SET email=?, address=?, phone=? WHERE user_id=?",
                (email, address, phone, user["id"]),
            )

    with get_connection() as conn:
        profile = conn.execute(
            "SELECT * FROM profiles WHERE user_id=?", (user["id"],)
        ).fetchone()

    uid = user["id"]
    my_notes = sorted(
        [n for n in notes_db.values() if n["owner_id"] == uid],
        key=lambda n: n["created_at"], reverse=True,
    )
    purchased_note_ids = {nid for (bid, nid) in purchases if bid == uid}
    purchased_notes = sorted(
        [notes_db[nid] for nid in purchased_note_ids if nid in notes_db],
        key=lambda n: n["created_at"], reverse=True,
    )

    return render_template(
        "account.html",
        user=user,
        profile=profile,
        my_notes=my_notes,
        purchased_notes=purchased_notes,
    )


@app.get("/not-found")
def not_found_page() -> tuple[str, int]:
    return render_template("not_found.html"), 404


if __name__ == "__main__":
    print("NoteCoin en: http://127.0.0.1:5000")
    init_database()
    app.run(debug=True, host="0.0.0.0", port=5000)
