# -*- coding: utf-8 -*-
"""
Tablero semántico (tableaux) a partir de reglas en español.

Uso:
    pip install streamlit plotly pandas
    streamlit run tablero_semantico.py

Flujo:
    texto en español -> proposiciones simples (p, q, r...) -> fórmulas (¬ ∧ ∨ → ↔)
    -> tablero semántico (se supone que TODAS las reglas son verdaderas)
    -> ramas abiertas (mundos posibles) / ramas cerradas (✕)

Novedades:
    * Persistencia en SQLite (archivo tablero_semantico.db junto a este script):
      bases de conocimiento, su resultado y el historial de consultas.
    * Panel de preguntas: se dan hechos (síntomas, por ejemplo) y/o una pregunta,
      y el sistema responde qué SE DEDUCE, qué se DESCARTA y qué queda INDETERMINADO.
      Una pregunta φ se deduce si (reglas + hechos + ¬φ) cierra todas las ramas;
      se refuta si (reglas + hechos + φ) cierra todas las ramas.
"""

import copy
import json
import os
import re
import sqlite3
import sys
import unicodedata
from contextlib import closing
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ----------------------------------------------------------------------------
# 1. FÓRMULAS (árbol sintáctico con tuplas)
#    ('atomo', 'p') | ('no', f) | ('y', a, b) | ('o', a, b) | ('si', a, b) | ('sii', a, b)
# ----------------------------------------------------------------------------
SIMBOLOS = {"y": "∧", "o": "∨", "si": "→", "sii": "↔"}
PRIORIDAD = {"sii": 1, "si": 2, "o": 3, "y": 4, "no": 5, "atomo": 6}


def a_texto(f):
    """Convierte una fórmula a texto, con paréntesis solo cuando hacen falta."""
    tipo = f[0]
    if tipo == "atomo":
        return f[1]
    if tipo == "no":
        hijo = f[1]
        if hijo[0] in ("atomo", "no"):
            return "¬" + a_texto(hijo)
        return "¬(" + a_texto(hijo) + ")"

    def envolver(h):
        if h[0] in ("atomo", "no"):
            return a_texto(h)
        if h[0] == tipo and tipo in ("y", "o"):  # asociativos: p ∧ q ∧ r
            return a_texto(h)
        return "(" + a_texto(h) + ")"  # cualquier otra combinación: paréntesis explícitos

    return f"{envolver(f[1])} {SIMBOLOS[tipo]} {envolver(f[2])}"


def evaluar(f, asignacion):
    tipo = f[0]
    if tipo == "atomo":
        return asignacion.get(f[1], False)
    if tipo == "no":
        return not evaluar(f[1], asignacion)
    a, b = evaluar(f[1], asignacion), evaluar(f[2], asignacion)
    return {"y": a and b, "o": a or b, "si": (not a) or b, "sii": a == b}[tipo]


# ----------------------------------------------------------------------------
# 2. ANALIZADOR DE LENGUAJE NATURAL (español)
# ----------------------------------------------------------------------------
LETRAS = list("pqrstuvwxyzabcdefghijklmno")


def sin_acentos(texto):
    """Quita acentos carácter por carácter (conserva la longitud)."""
    salida = []
    for c in texto:
        base = "".join(x for x in unicodedata.normalize("NFD", c) if not unicodedata.combining(x))
        salida.append(base[0] if base else c)
    return "".join(salida)


def limpiar(texto):
    texto = texto.strip().strip(".,;:!¡?¿").strip()
    return re.sub(r"\s+", " ", texto)


class TablaAtomos:
    """Misma idea escrita igual -> mismo átomo (se ignoran mayúsculas, acentos y puntuación)."""

    def __init__(self):
        self.por_clave = {}  # clave -> letra
        self.significado = {}  # letra -> texto original

    def obtener(self, texto):
        texto = limpiar(texto)
        if not texto:
            raise ValueError("Hay una proposición vacía (revisa conectores sobrantes).")
        clave = sin_acentos(texto).lower()
        if clave not in self.por_clave:
            n = len(self.por_clave)
            letra = LETRAS[n] if n < len(LETRAS) else f"p{n - len(LETRAS) + 1}"
            self.por_clave[clave] = letra
            self.significado[letra] = texto[0].upper() + texto[1:]
        return self.por_clave[clave]


PAT_SII = r"\s+(?:si\s+y\s+(?:solo|solamente)\s+si|sii)\s+"
PAT_SI = r"^(?:si\s+)?(.+?)\s*,?\s+entonces\s+(.+)$"
PAT_NO_CIERTO = r"^no\s+es\s+(?:cierto|verdad|el\s+caso)\s+que\s+(.+)$"


def _dividir(texto, plano, patron):
    """Divide `texto` en las posiciones donde `patron` coincide en `plano`."""
    partes, inicio = [], 0
    for m in re.finditer(patron, plano):
        partes.append(texto[inicio:m.start()])
        inicio = m.end()
    partes.append(texto[inicio:])
    return partes


def _unir(tipo, formulas):
    resultado = formulas[0]
    for f in formulas[1:]:
        resultado = (tipo, resultado, f)
    return resultado


def analizar(texto, atomos):
    """Convierte una oración en español a fórmula. Precedencia (de menor a mayor):
    «si y solo si» < «si… entonces» < «o» < «y» < «no»."""
    texto = limpiar(texto)
    plano = sin_acentos(texto).lower()

    # «si y solo si»  ->  ↔
    partes = _dividir(texto, plano, PAT_SII)
    if len(partes) == 2:
        return ("sii", analizar(partes[0], atomos), analizar(partes[1], atomos))
    if len(partes) > 2:
        raise ValueError(f"Demasiados «si y solo si» en una misma regla: «{texto}»")

    # «si A entonces B»  ->  →
    m = re.match(PAT_SI, plano)
    if m:
        a = texto[m.start(1):m.end(1)]
        b = texto[m.start(2):m.end(2)]
        return ("si", analizar(a, atomos), analizar(b, atomos))
    if re.match(r"^si\s", plano) and "entonces" not in plano:
        raise ValueError(f"Falta «entonces» en: «{texto}»")

    # «no es cierto que ...»  ->  ¬ de toda la oración
    m = re.match(PAT_NO_CIERTO, plano)
    if m:
        return ("no", analizar(texto[m.start(1):m.end(1)], atomos))

    # «o»  ->  ∨
    partes = _dividir(texto, plano, r"\s+o\s+")
    if len(partes) > 1:
        return _unir("o", [analizar(p, atomos) for p in partes])

    # «y»  ->  ∧
    partes = _dividir(texto, plano, r"\s+y\s+")
    if len(partes) > 1:
        return _unir("y", [analizar(p, atomos) for p in partes])

    # «no ...»  ->  ¬
    if re.match(r"^no\s+\S", plano):
        return ("no", analizar(texto[3:], atomos))

    return ("atomo", atomos.obtener(texto))


def separar_reglas(texto):
    """Una regla por línea (también se aceptan ';' o '.' como separador)."""
    reglas = []
    for linea in re.split(r"[\n;]+", texto):
        for trozo in re.split(r"\.(?:\s+|$)", linea):
            if trozo.strip():
                reglas.append(trozo.strip())
    return reglas


def analizar_existentes(textos, atomos):
    """Analiza textos SIN crear átomos nuevos en `atomos`.
    Devuelve (fórmulas, [significados de proposiciones que no aparecen en las reglas])."""
    copia = copy.deepcopy(atomos)
    formulas = [analizar(t, copia) for t in textos]
    nuevos = [copia.significado[l] for l in copia.significado if l not in atomos.significado]
    return formulas, nuevos


# ----------------------------------------------------------------------------
# 3. TABLERO SEMÁNTICO
# ----------------------------------------------------------------------------
class Nodo:
    def __init__(self, idx, formula, padre=None, etiqueta=""):
        self.idx = idx
        self.formula = formula
        self.padre = padre
        self.hijos = []
        self.etiqueta = etiqueta  # "R1", "R2"... solo en la base de conocimiento
        self.aplicada = None  # número de paso en el que se desarrolló (✓)
        self.cerrada = False  # hoja cerrada (✕)
        self.contradiccion = None


def es_literal(f):
    return f[0] == "atomo" or (f[0] == "no" and f[1][0] == "atomo")


def neg(f):
    return ("no", f)


def clasificar(f):
    """Devuelve (tipo, nombre_regla, ramas). Cada rama es una lista de fórmulas en cadena.
    alfa: una sola rama | beta: varias ramas. None si es literal."""
    if es_literal(f):
        return None
    if f[0] == "y":
        return "alfa", "∧", [[f[1], f[2]]]
    if f[0] == "o":
        return "beta", "∨", [[f[1]], [f[2]]]
    if f[0] == "si":
        return "beta", "→", [[neg(f[1])], [f[2]]]
    if f[0] == "sii":
        return "beta", "↔", [[("y", f[1], f[2])], [("y", neg(f[1]), neg(f[2]))]]
    # f = ¬g con g compuesta
    g = f[1]
    if g[0] == "no":
        return "alfa", "¬¬", [[g[1]]]
    if g[0] == "o":
        return "alfa", "¬∨", [[neg(g[1]), neg(g[2])]]
    if g[0] == "si":
        return "alfa", "¬→", [[g[1], neg(g[2])]]
    if g[0] == "y":
        return "beta", "¬∧", [[neg(g[1])], [neg(g[2])]]
    if g[0] == "sii":
        return "beta", "¬↔", [[("y", g[1], neg(g[2]))], [("y", neg(g[1]), g[2])]]
    raise ValueError("Fórmula desconocida")


class Tablero:
    MAX_NODOS = 1000000

    def __init__(self, formulas, limite_pasos=None):
        self.nodos = []
        self.pasos = []
        self.truncado = False
        self.completo = False
        self.raiz = None

        ultimo = None
        for i, f in enumerate(formulas):
            ultimo = self._nuevo(f, ultimo, etiqueta=f"R{i + 1}")
        self._revisar_cierre(ultimo)

        while True:
            if limite_pasos is not None and len(self.pasos) >= limite_pasos:
                break
            if len(self.nodos) > self.MAX_NODOS:
                self.truncado = True
                break
            elegido = self._elegir()
            if elegido is None:
                self.completo = True
                break
            self._aplicar(elegido)

    # --- construcción ---------------------------------------------------
    def _nuevo(self, formula, padre, etiqueta=""):
        nodo = Nodo(len(self.nodos) + 1, formula, padre, etiqueta)
        self.nodos.append(nodo)
        if padre is None:
            self.raiz = nodo
        else:
            padre.hijos.append(nodo)
        return nodo

    def _hojas_abiertas(self, nodo):
        if not nodo.hijos:
            return [] if nodo.cerrada else [nodo]
        hojas = []
        for h in nodo.hijos:
            hojas += self._hojas_abiertas(h)
        return hojas

    def _revisar_cierre(self, hoja):
        positivos, negativos = set(), set()
        n = hoja
        while n is not None:
            f = n.formula
            if f[0] == "atomo":
                positivos.add(f[1])
            elif f[0] == "no" and f[1][0] == "atomo":
                negativos.add(f[1][1])
            n = n.padre
        comunes = positivos & negativos
        if comunes:
            hoja.cerrada = True
            hoja.contradiccion = sorted(comunes)[0]

    def _elegir(self):
        """Primero reglas α (no ramifican), luego β; dentro de cada tipo, de arriba hacia abajo."""
        mejor = None
        for nodo in self.nodos:
            if nodo.aplicada is not None or es_literal(nodo.formula):
                continue
            if not self._hojas_abiertas(nodo):
                continue
            tipo = clasificar(nodo.formula)[0]
            if tipo == "alfa":
                return nodo
            if mejor is None:
                mejor = nodo
        return mejor

    def _aplicar(self, nodo):
        tipo, regla, ramas = clasificar(nodo.formula)
        paso = len(self.pasos) + 1
        hojas = self._hojas_abiertas(nodo)
        for hoja in hojas:
            for cadena in ramas:
                actual = hoja
                for f in cadena:
                    actual = self._nuevo(f, actual)
                self._revisar_cierre(actual)
        nodo.aplicada = paso
        self.pasos.append({
            "paso": paso,
            "fórmula": (nodo.etiqueta + ": " if nodo.etiqueta else "") + a_texto(nodo.formula),
            "regla": regla,
            "tipo": "α (no ramifica)" if tipo == "alfa" else "β (ramifica)",
            "ramas afectadas": len(hojas),
        })

    # --- resultados -------------------------------------------------------
    def hojas(self):
        """Hojas de izquierda a derecha (mismo orden que el dibujo)."""
        resultado = []

        def recorrer(n):
            if not n.hijos:
                resultado.append(n)
            for h in n.hijos:
                recorrer(h)

        recorrer(self.raiz)
        return resultado

    def ramas_abiertas(self):
        return [h for h in self.hojas() if not h.cerrada]

    def ramas_cerradas(self):
        return [h for h in self.hojas() if h.cerrada]

    @staticmethod
    def literales(hoja):
        valores = {}
        n = hoja
        while n is not None:
            f = n.formula
            if f[0] == "atomo":
                valores[f[1]] = True
            elif f[0] == "no" and f[1][0] == "atomo":
                valores[f[1][1]] = False
            n = n.padre
        return valores


# ----------------------------------------------------------------------------
# 3b. SALIDA EN TEXTO
# ----------------------------------------------------------------------------
def modelo_texto(letras, valores):
    return ", ".join(f"{l} = {'V' if valores[l] else 'F'}" if l in valores else f"{l} = libre"
                     for l in letras)


def frase_modelo(significado, letras, valores):
    partes = []
    for l in letras:
        if l in valores:
            t = significado[l]
            t = t[0].lower() + t[1:]
            partes.append(t if valores[l] else "no " + t)
    return "; ".join(partes) if partes else "sin restricciones"


def _etiqueta_texto(n):
    t = (n.etiqueta + ": " if n.etiqueta else "") + a_texto(n.formula)
    return t + (" ✓" if n.aplicada is not None else "")


def _emitir(nodo, p1, p2):
    salida, actual, primero = [], nodo, True
    while True:
        salida.append((p1 if primero else p2) + _etiqueta_texto(actual))
        primero = False
        if len(actual.hijos) == 1:
            actual = actual.hijos[0]
            continue
        break
    if not actual.hijos:
        if actual.cerrada:
            c = actual.contradiccion
            salida.append(p2 + f"✕ rama cerrada ({c} y ¬{c})")
        else:
            salida.append(p2 + "● rama abierta")
    else:
        for i, h in enumerate(actual.hijos):
            ultimo = i == len(actual.hijos) - 1
            salida += _emitir(h, p2 + ("└── " if ultimo else "├── "), p2 + ("    " if ultimo else "│   "))
    return salida


def informe_texto(atomos, tablero):
    letras = list(atomos.significado)
    lineas = ["=== ÁRBOL SEMÁNTICO ===", "(✓ fórmula aplicada, ✕ rama cerrada, ● rama abierta)", ""]
    lineas += _emitir(tablero.raiz, "", "")
    abiertas, cerradas = tablero.ramas_abiertas(), tablero.ramas_cerradas()
    lineas += ["", "=== RESULTADO ==="]
    if not abiertas:
        lineas.append(f"La base es INCONSISTENTE: las {len(cerradas)} rama(s) se cierran. "
                      "Ninguna asignación hace verdaderas todas las reglas.")
    else:
        lineas.append(f"La base es CONSISTENTE: {len(abiertas)} rama(s) abierta(s) y {len(cerradas)} cerrada(s).")
        for i, hoja in enumerate(abiertas, 1):
            v = Tablero.literales(hoja)
            lineas += ["", f"Rama abierta {i}: {modelo_texto(letras, v)}",
                       f"Todas las reglas se cumplen cuando: {frase_modelo(atomos.significado, letras, v)}."]
    return "\n".join(lineas)


def resumen_resultado(atomos, tablero):
    """Resumen serializable (JSON) del tablero completo, para guardarlo en la base de datos."""
    letras = list(atomos.significado)
    abiertas = tablero.ramas_abiertas()
    modelos = []
    for hoja in abiertas:
        v = Tablero.literales(hoja)
        modelos.append({"asignacion": modelo_texto(letras, v),
                        "se_cumple_cuando": frase_modelo(atomos.significado, letras, v)})
    return {
        "consistente": bool(abiertas),
        "completo": tablero.completo,
        "ramas_abiertas": len(abiertas),
        "ramas_cerradas": len(tablero.ramas_cerradas()),
        "atomos": atomos.significado,
        "modelos": modelos,
    }


# ----------------------------------------------------------------------------
# 3c. INFERENCIA: PREGUNTAS SOBRE LA BASE DE CONOCIMIENTO
# ----------------------------------------------------------------------------
def cierra(tablero):
    """True si el tablero terminó y TODAS sus ramas se cerraron (contradicción)."""
    return tablero.completo and not tablero.ramas_abiertas()


def hechos_literales(formulas):
    """Átomos dados directamente como hechos (p -> True, ¬p -> False)."""
    dados = {}
    for f in formulas:
        if f[0] == "atomo":
            dados[f[1]] = True
        elif f[0] == "no" and f[1][0] == "atomo":
            dados[f[1][1]] = False
    return dados


def estado_atomos(tablero, letras):
    """Para cada átomo: 'V' si es verdadero en TODOS los mundos posibles, 'F' si es falso en todos,
    '?' si depende del mundo (o queda libre en alguna rama abierta)."""
    modelos = [Tablero.literales(h) for h in tablero.ramas_abiertas()]
    estado = {}
    for l in letras:
        vals = [m.get(l) for m in modelos]
        if vals and all(v is True for v in vals):
            estado[l] = "V"
        elif vals and all(v is False for v in vals):
            estado[l] = "F"
        else:
            estado[l] = "?"
    return estado


def consultar(formulas_kb, hechos, pregunta=None):
    """Reglas + hechos (+ pregunta opcional).
    estado: 'ok' | 'inconsistente' | 'truncado'
    veredicto (si hay pregunta): 'se_deduce' | 'se_refuta' | 'indeterminada' | 'no_concluyente'"""
    premisas = list(formulas_kb) + list(hechos)
    base = Tablero(premisas)
    r = {"base": base, "premisas": premisas, "veredicto": None}
    if not base.completo:
        r["estado"] = "truncado"
        return r
    if not base.ramas_abiertas():
        r["estado"] = "inconsistente"
        return r
    r["estado"] = "ok"
    if pregunta is not None:
        t_neg = Tablero(premisas + [neg(pregunta)])  # ¿existe un mundo donde la pregunta sea falsa?
        t_pos = Tablero(premisas + [pregunta])  # ¿existe un mundo donde sea verdadera?
        if not (t_neg.completo and t_pos.completo):
            r["veredicto"] = "no_concluyente"
        elif cierra(t_neg):
            r["veredicto"] = "se_deduce"
        elif cierra(t_pos):
            r["veredicto"] = "se_refuta"
        else:
            r["veredicto"] = "indeterminada"
            r["ej_verdadero"] = Tablero.literales(t_pos.ramas_abiertas()[0])
            r["ej_falso"] = Tablero.literales(t_neg.ramas_abiertas()[0])
    return r


def resumen_lineas(significado, estado, dados, letras):
    """Frases en español sobre lo que se deduce, se descarta o queda indeterminado."""
    def minus(t):
        return t[0].lower() + t[1:]

    ver = [minus(significado[l]) for l in letras if estado[l] == "V" and l not in dados]
    fal = [minus(significado[l]) for l in letras if estado[l] == "F" and l not in dados]
    ind = [minus(significado[l]) for l in letras if estado[l] == "?"]
    lineas = []
    if ver:
        lineas.append("✅ Se deduce que: " + "; ".join(ver) + ".")
    if fal:
        lineas.append("🚫 Se descarta que: " + "; ".join(fal) + ".")
    if ind:
        lineas.append("❓ No se puede determinar: " + "; ".join(ind) + ".")
    if not ver and not fal:
        lineas.insert(0, "Con esta información no se deduce nada nuevo.")
    return lineas


ETIQUETA_VEREDICTO = {
    "se_deduce": "Se deduce (verdadera)",
    "se_refuta": "Se refuta (falsa)",
    "indeterminada": "Indeterminada",
    "no_concluyente": "No concluyente",
}


# ----------------------------------------------------------------------------
# 3d. PERSISTENCIA (SQLite)
# ----------------------------------------------------------------------------
RUTA_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tablero_semantico.db")


def _conectar():
    conn = sqlite3.connect(RUTA_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def iniciar_db():
    with closing(_conectar()) as c, c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS bases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT UNIQUE NOT NULL,
                reglas TEXT NOT NULL,
                resultado TEXT,
                creado TEXT NOT NULL,
                actualizado TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS consultas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                base_id INTEGER NOT NULL REFERENCES bases(id) ON DELETE CASCADE,
                hechos TEXT,
                pregunta TEXT,
                veredicto TEXT,
                respuesta TEXT,
                fecha TEXT NOT NULL
            );
        """)


def guardar_base(nombre, reglas, resultado):
    """Crea la base o la actualiza si ya existe una con ese nombre. Devuelve su id."""
    ahora = _ahora()
    with closing(_conectar()) as c, c:
        c.execute(
            "INSERT INTO bases (nombre, reglas, resultado, creado, actualizado) VALUES (?,?,?,?,?) "
            "ON CONFLICT(nombre) DO UPDATE SET reglas=excluded.reglas, resultado=excluded.resultado, "
            "actualizado=excluded.actualizado",
            (nombre, reglas, json.dumps(resultado, ensure_ascii=False), ahora, ahora))
        return c.execute("SELECT id FROM bases WHERE nombre=?", (nombre,)).fetchone()["id"]


def listar_bases():
    with closing(_conectar()) as c:
        return c.execute("SELECT id, nombre, actualizado FROM bases ORDER BY actualizado DESC").fetchall()


def cargar_base(base_id):
    with closing(_conectar()) as c:
        return c.execute("SELECT * FROM bases WHERE id=?", (base_id,)).fetchone()


def borrar_base(base_id):
    with closing(_conectar()) as c, c:
        c.execute("DELETE FROM bases WHERE id=?", (base_id,))


def guardar_consulta(base_id, hechos, pregunta, veredicto, respuesta):
    with closing(_conectar()) as c, c:
        c.execute("INSERT INTO consultas (base_id, hechos, pregunta, veredicto, respuesta, fecha) "
                  "VALUES (?,?,?,?,?,?)", (base_id, hechos, pregunta, veredicto, respuesta, _ahora()))


def listar_consultas(base_id):
    with closing(_conectar()) as c:
        return c.execute("SELECT fecha, hechos, pregunta, veredicto, respuesta FROM consultas "
                         "WHERE base_id=? ORDER BY id DESC", (base_id,)).fetchall()


# ----------------------------------------------------------------------------
# 4. VISUALIZACIÓN CON PLOTLY
# ----------------------------------------------------------------------------
VERDE, ROJO, GRIS, AZUL = "#2e7d32", "#c62828", "#78909c", "#1565c0"


def figura_arbol(tablero, ancho_rama=190, alto_nivel=62):
    raiz = tablero.raiz
    pos = {}
    contador = [0]

    def colocar(nodo, nivel):
        if not nodo.hijos:
            x = contador[0]
            contador[0] += 1
        else:
            xs = [colocar(h, nivel + 1) for h in nodo.hijos]
            x = sum(xs) / len(xs)
        pos[nodo.idx] = (x, -nivel)
        return x

    sys.setrecursionlimit(max(sys.getrecursionlimit(), 5000))
    colocar(raiz, 0)

    n_hojas = max(contador[0], 1)
    nivel_max = max(-y for _, y in pos.values())

    # aristas
    ex, ey = [], []
    for n in tablero.nodos:
        for h in n.hijos:
            ex += [pos[n.idx][0], pos[h.idx][0], None]
            ey += [pos[n.idx][1], pos[h.idx][1], None]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ex, y=ey, mode="lines", line=dict(color=GRIS, width=1.5),
                             hoverinfo="skip", showlegend=False))

    anotaciones = []
    for n in tablero.nodos:
        x, y = pos[n.idx]
        texto = (n.etiqueta + ": " if n.etiqueta else "") + a_texto(n.formula)
        if n.aplicada is not None:
            texto += f"  ✓{n.aplicada}"
        if n.hijos:
            fondo, borde = ("#e3f2fd" if n.etiqueta else "#f5f5f5"), (AZUL if n.etiqueta else GRIS)
        elif n.cerrada:
            fondo, borde = "#ffebee", ROJO
        else:
            fondo, borde = "#e8f5e9", VERDE
        anotaciones.append(dict(x=x, y=y, text=texto, showarrow=False, bgcolor=fondo,
                                bordercolor=borde, borderwidth=1.5, borderpad=4,
                                font=dict(size=12, color="#111111")))
        if not n.hijos:
            if n.cerrada:
                marca, color = f"✕ ({n.contradiccion} y ¬{n.contradiccion})", ROJO
            else:
                marca, color = "● abierta", VERDE
            anotaciones.append(dict(x=x, y=y - 0.62, text=f"<b>{marca}</b>", showarrow=False,
                                    font=dict(size=12, color=color)))

    # leyenda
    for nombre, color in (("fórmula / regla", AZUL), ("rama abierta", VERDE), ("rama cerrada ✕", ROJO)):
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=nombre,
                                 marker=dict(size=11, color=color, symbol="square")))

    fig.update_layout(
        annotations=anotaciones,
        width=max(900, int(n_hojas * ancho_rama + 120)),
        height=int((nivel_max + 2.4) * alto_nivel),
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(visible=False, range=[-0.7, n_hojas - 0.3]),
        yaxis=dict(visible=False, range=[-(nivel_max + 1.5), 0.6]),
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", y=1.0, x=0),
    )
    return fig


def mostrar_figura(fig):
    """Compatible con versiones antiguas y nuevas de Streamlit."""
    try:
        st.plotly_chart(fig,width="content",key=f"grafica_{id(fig)}")
    except TypeError:
        st.plotly_chart(fig, use_container_width=False)


# ----------------------------------------------------------------------------
# 5. INTERFAZ STREAMLIT
# ----------------------------------------------------------------------------
SIN_EJEMPLO = "(escribir el mío)"

EJEMPLOS = {
    "Día / lluvia / trabajo": (
        "Si es de día, entonces voy a trabajar\n"
        "Si llueve, entonces no voy a trabajar\n"
        "Es de día"
    ),
    "Inconsistente": (
        "Si llueve, entonces me mojo\n"
        "Llueve\n"
        "No me mojo"
    ),
    "Todos los conectivos": (
        "Si estudio entonces apruebo\n"
        "Apruebo si y solo si no repruebo\n"
        "Estudio o juego\n"
        "No es cierto que juego y estudio"
    ),
    "Diagnóstico (enfermedades)": (
        "Si tiene gripe entonces tiene fiebre y tiene tos\n"
        "Si tiene alergia entonces tiene estornudos y no tiene fiebre\n"
        "Si tiene covid entonces tiene fiebre y pierde el olfato\n"
        "Si tiene gripe entonces no pierde el olfato\n"
        "Tiene gripe o tiene alergia o tiene covid"
    ),
}


# --- callbacks ---------------------------------------------------------------
def _cargar_ejemplo():
    sel = st.session_state.get("ejemplo_sel")
    if sel in EJEMPLOS:
        st.session_state["texto_reglas"] = EJEMPLOS[sel]
        st.session_state["base_id_actual"] = None
        st.session_state["nombre_base"] = ""


def _cargar_guardada():
    fila = cargar_base(st.session_state.get("base_sel"))
    if fila:
        st.session_state["texto_reglas"] = fila["reglas"]
        st.session_state["nombre_base"] = fila["nombre"]
        st.session_state["base_id_actual"] = fila["id"]
        st.session_state["ejemplo_sel"] = SIN_EJEMPLO
        st.session_state["aviso"] = f"Base «{fila['nombre']}» cargada."


def _eliminar_guardada():
    base_id = st.session_state.get("base_sel")
    fila = cargar_base(base_id)
    if fila:
        borrar_base(base_id)
        if st.session_state.get("base_id_actual") == base_id:
            st.session_state["base_id_actual"] = None
        st.session_state["aviso"] = f"Base «{fila['nombre']}» eliminada."
    st.session_state.pop("base_sel", None)
    st.session_state["confirmar_borrado"] = False


# --- vistas ------------------------------------------------------------------
def vista_tablero(formulas, completo, atomos, ancho_rama, alto_nivel):
    st.subheader("Tablero semántico")
    total = len(completo.pasos)
    if total > 0:
        mostrar_pasos = st.slider("Pasos del desarrollo a mostrar", 0, total, total,
                                  help="0 = solo la base de conocimiento; el máximo es el tablero terminado.")
    else:
        mostrar_pasos = 0
    tablero = Tablero(formulas, limite_pasos=mostrar_pasos)

    if completo.truncado:
        st.warning("El tablero es demasiado grande y se detuvo antes de terminar.")

    fig = figura_arbol(tablero, ancho_rama, alto_nivel)
    mostrar_figura(fig)
    st.download_button("Descargar árbol (HTML interactivo)",
                       fig.to_html(include_plotlyjs="cdn"), file_name="tablero.html", mime="text/html")
    st.caption("✓n = fórmula ya desarrollada en el paso n · ✕ = rama cerrada (átomo y su negación) "
               "· ● = rama abierta")

    with st.expander("Ver pasos de expansión"):
        if tablero.pasos:
            st.dataframe(pd.DataFrame(tablero.pasos), hide_index=True)
        else:
            st.write("Todavía no se aplica ninguna regla.")

    st.subheader("Resultado")
    if mostrar_pasos < total:
        st.info(f"Mostrando {mostrar_pasos} de {total} pasos. Mueve el control al máximo para ver el resultado final.")
        return

    abiertas = completo.ramas_abiertas()
    cerradas = completo.ramas_cerradas()
    letras = list(atomos.significado)
    st.write(f"Ramas cerradas: **{len(cerradas)}** · Ramas abiertas: **{len(abiertas)}**")

    if not abiertas:
        st.error("Todas las ramas se cierran: la base de conocimiento es **inconsistente** "
                 "(contradictoria). No existe ninguna asignación de valores que haga verdaderas todas las reglas.")
    else:
        st.success("La base de conocimiento es **consistente**. Condiciones en las que todas las reglas se cumplen:")
        filas = []
        for i, hoja in enumerate(abiertas, 1):
            valores = Tablero.literales(hoja)
            asign = {l: valores.get(l, False) for l in letras}
            ok = all(evaluar(f, asign) for f in formulas)
            filas.append({
                "Rama abierta": i,
                "Asignación": modelo_texto(letras, valores),
                "Se cumple cuando": frase_modelo(atomos.significado, letras, valores),
                "Verificación": "✔ todas las reglas son V" if ok else "✘ revisar",
            })
        st.dataframe(pd.DataFrame(filas), hide_index=True)
        st.caption("«libre» = el átomo no aparece en la rama: puede valer V o F sin afectar a las reglas.")

    with st.expander("Salida en texto (para copiar)"):
        st.code(informe_texto(atomos, completo), language=None)


def vista_preguntas(atomos, formulas, texto_reglas, ancho_rama, alto_nivel):
    sig = atomos.significado
    letras = list(sig)
    firma = "".join(letras)  # cambia si cambia el número de átomos -> reinicia las selecciones

    st.subheader("Preguntas sobre las reglas")
    st.caption("Indica lo que **sabes** (por ejemplo, síntomas o la enfermedad) y/o haz una **pregunta**. "
               "El sistema usa el tablero para decir qué se deduce, qué se descarta y qué queda indeterminado.")

    def fmt(l):
        return f"{l} · {sig[l]}"

    c1, c2 = st.columns(2)
    with c1:
        sel_v = st.multiselect("Hechos VERDADEROS", letras, format_func=fmt, key=f"hv_{firma}")
    with c2:
        sel_f = st.multiselect("Hechos FALSOS", letras, format_func=fmt, key=f"hf_{firma}")
    otros = st.text_area("Otros hechos (opcional, uno por línea, escritos igual que en las reglas)",
                         key=f"ho_{firma}", height=80)
    c3, c4 = st.columns(2)
    with c3:
        pregunta_txt = st.text_input("Pregunta (opcional): una proposición o fórmula en español",
                                     key=f"pt_{firma}",
                                     help="Ej.: «Tiene covid», «Tiene gripe o tiene covid», "
                                          "«Si tiene fiebre entonces tiene tos».")
    with c4:
        rapida = st.selectbox("…o elige una proposición", [""] + letras, key=f"pr_{firma}",
                              format_func=lambda l: "(ninguna)" if l == "" else f"¿{sig[l]}?")

    choque = sorted(set(sel_v) & set(sel_f))
    if choque:
        st.error("Marcaste como verdadero y falso a la vez: " + ", ".join(fmt(l) for l in choque))
        return

    try:
        extra, nuevos = analizar_existentes(separar_reglas(otros), atomos)
        pregunta = None
        if pregunta_txt.strip():
            lista, nuevos_p = analizar_existentes([pregunta_txt], atomos)
            pregunta, nuevos = lista[0], nuevos + nuevos_p
        elif rapida:
            pregunta = ("atomo", rapida)
    except ValueError as e:
        st.error(str(e))
        return
    if nuevos:
        st.warning("Estas proposiciones no aparecen en las reglas (¿están escritas igual?): "
                   + "; ".join(f"«{n}»" for n in nuevos) + ". Sin ellas no se puede deducir nada.")
        return

    hechos = ([("atomo", l) for l in sel_v] + [("no", ("atomo", l)) for l in sel_f] + extra)
    texto_preg = pregunta_txt.strip() or (sig[rapida] if rapida else "")

    r = consultar(formulas, hechos, pregunta)

    st.markdown("---")
    st.subheader("Respuesta")

    if r["estado"] == "truncado":
        st.warning("El tablero es demasiado grande y se detuvo antes de terminar; no hay conclusión fiable.")
        return
    if r["estado"] == "inconsistente":
        st.error("Los hechos **contradicen las reglas**: no existe ningún mundo posible en el que todo sea "
                 "verdadero a la vez. Revisa los hechos marcados.")
        return

    veredicto = r["veredicto"]
    if pregunta is not None:
        etiqueta = f"«{texto_preg}»"
        if veredicto == "se_deduce":
            st.success(f"✅ **Sí, se deduce.** {etiqueta} es verdadera en todos los mundos posibles "
                       "que cumplen las reglas y los hechos.")
        elif veredicto == "se_refuta":
            st.error(f"🚫 **No.** {etiqueta} es falsa en todos los mundos posibles "
                     "que cumplen las reglas y los hechos.")
        elif veredicto == "indeterminada":
            st.info(f"❓ **No se puede determinar.** {etiqueta} es verdadera en algunos mundos y falsa en otros; "
                    "faltan hechos para decidir.")
            letras_ej = list(sig)
            st.caption("Ejemplo donde es verdadera: " + frase_modelo(sig, letras_ej, r["ej_verdadero"]) + ".")
            st.caption("Ejemplo donde es falsa: " + frase_modelo(sig, letras_ej, r["ej_falso"]) + ".")
        else:
            st.warning("Consulta demasiado grande: no se pudo concluir.")

    estado = estado_atomos(r["base"], letras)
    dados = hechos_literales(hechos)
    lineas = resumen_lineas(sig, estado, dados, letras)
    st.markdown("**Con las reglas y los hechos indicados:**")
    st.markdown("\n\n".join(lineas))

    iconos = {"V": "✅ Verdadero", "F": "🚫 Falso", "?": "❓ Indeterminado"}
    st.dataframe(pd.DataFrame({
        "Letra": letras,
        "Proposición": [sig[l] for l in letras],
        "Estado": [iconos[estado[l]] + (" (dato)" if l in dados else "") for l in letras],
    }), hide_index=True)

    abiertas = r["base"].ramas_abiertas()
    with st.expander(f"Mundos posibles compatibles ({len(abiertas)})"):
        for i, hoja in enumerate(abiertas, 1):
            st.write(f"**Mundo {i}:** " + frase_modelo(sig, letras, Tablero.literales(hoja)) + ".")
    with st.expander("Ver el tablero de esta consulta (reglas + hechos)"):
        if len(r["base"].nodos) > 400:
            st.info("El tablero es muy grande para dibujarlo aquí.")
        else:
            mostrar_figura(figura_arbol(r["base"], ancho_rama, alto_nivel))

    # --- guardar la consulta ------------------------------------------------
    base_id = st.session_state.get("base_id_actual")
    fila = cargar_base(base_id) if base_id else None
    puede = bool(fila) and fila["reglas"] == texto_reglas
    if st.button("💾 Guardar esta consulta", disabled=not puede, key="guardar_consulta"):
        partes = ([f"{sig[l]} (V)" for l in sel_v] + [f"{sig[l]} (F)" for l in sel_f]
                  + separar_reglas(otros))
        guardar_consulta(base_id, "; ".join(partes), texto_preg,
                         ETIQUETA_VEREDICTO.get(veredicto, "—"), "\n".join(lineas))
        st.toast("Consulta guardada en el historial.")
    if not puede:
        st.caption("Para guardar consultas, guarda primero la base actual en la pestaña «Guardado» "
                   "(y no la modifiques después sin volver a guardarla).")


def vista_guardado(atomos, completo, texto_reglas):
    base_id = st.session_state.get("base_id_actual")

    st.subheader("Guardar la base actual")
    nombre = st.text_input("Nombre de la base", key="nombre_base", placeholder="Ej.: Diagnóstico de enfermedades")
    if st.button("💾 Guardar / actualizar", disabled=not nombre.strip()):
        nuevo_id = guardar_base(nombre.strip(), texto_reglas, resumen_resultado(atomos, completo))
        st.session_state["base_id_actual"] = nuevo_id
        st.session_state["aviso"] = f"Base «{nombre.strip()}» guardada."
        st.rerun()
    st.caption("Si ya existe una base con ese nombre, se actualiza (su historial de consultas se conserva).")

    st.subheader("Bases guardadas")
    bases = listar_bases()
    if not bases:
        st.caption("Aún no hay bases guardadas.")
    else:
        etiquetas = {b["id"]: f"{b['nombre']} · {b['actualizado']}" for b in bases}
        st.selectbox("Elige una base", list(etiquetas), format_func=lambda i: etiquetas[i], key="base_sel")
        c1, c2 = st.columns(2)
        with c1:
            st.button("📂 Cargar", on_click=_cargar_guardada)
        with c2:
            conf = st.checkbox("Confirmo que quiero eliminarla", key="confirmar_borrado")
            st.button("🗑️ Eliminar", disabled=not conf, on_click=_eliminar_guardada)

    fila = cargar_base(base_id) if base_id else None
    if fila:
        st.markdown("---")
        st.subheader(f"Historial de «{fila['nombre']}»")
        st.caption(f"Creada: {fila['creado']} · Última actualización: {fila['actualizado']}")
        if fila["reglas"] != texto_reglas:
            st.warning("Las reglas del editor son distintas a las guardadas. Guarda para actualizar la base.")
        if fila["resultado"]:
            res = json.loads(fila["resultado"])
            if res.get("consistente"):
                st.success(f"Resultado guardado: consistente · {res['ramas_abiertas']} mundo(s) posible(s) · "
                           f"{res['ramas_cerradas']} rama(s) cerrada(s).")
                st.dataframe(pd.DataFrame(res["modelos"]).rename(columns={
                    "asignacion": "Asignación", "se_cumple_cuando": "Se cumple cuando"}), hide_index=True)
            else:
                st.error("Resultado guardado: base inconsistente (todas las ramas se cierran).")
        consultas = listar_consultas(fila["id"])
        st.markdown(f"**Consultas guardadas: {len(consultas)}**")
        if consultas:
            st.dataframe(pd.DataFrame([dict(c) for c in consultas]).rename(columns={
                "fecha": "Fecha", "hechos": "Hechos", "pregunta": "Pregunta",
                "veredicto": "Veredicto", "respuesta": "Respuesta"}), hide_index=True)


def main():
    st.set_page_config(page_title="Tablero semántico", page_icon="🌳", layout="wide")
    iniciar_db()
    st.session_state.setdefault("texto_reglas", EJEMPLOS["Día / lluvia / trabajo"])
    st.session_state.setdefault("base_id_actual", None)
    aviso = st.session_state.pop("aviso", None)
    if aviso:
        st.toast(aviso)

    st.title("🌳 Tablero semántico a partir de reglas en español")
    st.caption("Escribe una regla o hecho por línea. Se supone que **todas** son verdaderas "
               "y se buscan las condiciones en las que se cumplen.")

    with st.sidebar:
        st.header("Opciones")
        st.selectbox("Cargar ejemplo", [SIN_EJEMPLO] + list(EJEMPLOS), key="ejemplo_sel",
                     on_change=_cargar_ejemplo)
        ancho_rama = st.slider("Ancho por rama (px)", 120, 400, 190, 10)
        alto_nivel = st.slider("Alto por nivel (px)", 40, 120, 62, 2)
        st.markdown(
            "**Conectores reconocidos**\n\n"
            "- «y» → ∧\n- «o» → ∨\n- «no» → ¬\n- «si … entonces …» → →\n- «si y solo si» ↔\n\n"
            "También: «no es cierto que …» → ¬ de toda la oración."
        )
        fila_actual = cargar_base(st.session_state["base_id_actual"]) if st.session_state["base_id_actual"] else None
        st.markdown("---")
        st.caption(f"💾 Base actual: **{fila_actual['nombre']}**" if fila_actual
                   else "💾 Base actual: sin guardar")

    texto = st.text_area("Base de conocimiento (una regla por línea)", height=170, key="texto_reglas")

    reglas_texto = separar_reglas(texto)
    if not reglas_texto:
        st.info("Escribe al menos una regla.")
        return

    # --- análisis -----------------------------------------------------------
    atomos = TablaAtomos()
    try:
        formulas = [analizar(r, atomos) for r in reglas_texto]
    except ValueError as e:
        st.error(str(e))
        return

    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("1. Átomos")
        st.dataframe(pd.DataFrame({"Letra": list(atomos.significado),
                                   "Significado": list(atomos.significado.values())}),
                     hide_index=True)
    with col2:
        st.subheader("2. Reglas y fórmulas")
        st.dataframe(pd.DataFrame({
            "Regla": [f"R{i + 1}" for i in range(len(formulas))],
            "Texto": reglas_texto,
            "Fórmula": [f"R{i + 1}: {a_texto(f)}" for i, f in enumerate(formulas)],
        }), hide_index=True)

    completo = Tablero(formulas)

    tab1, tab2, tab3 = st.tabs(["🌳 Tablero", "💬 Preguntas", "💾 Guardado"])
    with tab1:
        vista_tablero(formulas, completo, atomos, ancho_rama, alto_nivel)
    with tab2:
        vista_preguntas(atomos, formulas, texto, ancho_rama, alto_nivel)
    with tab3:
        vista_guardado(atomos, completo, texto)


if __name__ == "__main__":
    main()
