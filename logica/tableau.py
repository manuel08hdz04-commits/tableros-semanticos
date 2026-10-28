"""Tablero semántico (árboles de verdad) para una base de conocimiento."""
from .formulas import Atomo, No, Y, O, Implica, Sii, es_literal, complemento, a_texto


def expandir(f):
    """Devuelve (tipo, ramas, nombre_regla) o None si f es un literal.
    tipo 'α' = no ramifica (una sola rama); 'β' = ramifica."""
    if isinstance(f, No):
        g = f.f
        if isinstance(g, No):
            return "α", [[g.f]], "¬¬"
        if isinstance(g, O):
            return "α", [[No(g.izq), No(g.der)]], "¬∨"
        if isinstance(g, Implica):
            return "α", [[g.izq, No(g.der)]], "¬→"
        if isinstance(g, Y):
            return "β", [[No(g.izq)], [No(g.der)]], "¬∧"
        if isinstance(g, Sii):
            return "β", [[g.izq, No(g.der)], [No(g.izq), g.der]], "¬↔"
        return None
    if isinstance(f, Y):
        return "α", [[f.izq, f.der]], "∧"
    if isinstance(f, O):
        return "β", [[f.izq], [f.der]], "∨"
    if isinstance(f, Implica):
        return "β", [[No(f.izq)], [f.der]], "→"
    if isinstance(f, Sii):
        return "β", [[f.izq, f.der], [No(f.izq), No(f.der)]], "↔"
    return None


class Nodo:
    def __init__(self, num, formula, padre, origen):
        self.num = num
        self.formula = formula
        self.padre = padre
        self.hijos = []
        self.origen = origen      # "R1" o "∧ de 4"
        self.aplicada = None      # nº de orden en que se expandió (None = pendiente)
        self.cierre = None        # nº del nodo con el que forma contradicción


class Tablero:
    def __init__(self, reglas):
        """reglas: lista de (etiqueta, formula). Se suponen todas verdaderas."""
        self.nodos = []
        self.raiz = None
        self._orden = 0
        ultimo = None
        for etiqueta, f in reglas:
            ultimo = self._nuevo(f, ultimo, etiqueta)
        self._resolver()

    # ---------- construcción ----------
    def _nuevo(self, formula, padre, origen):
        n = Nodo(len(self.nodos) + 1, formula, padre, origen)
        self.nodos.append(n)
        if padre is None:
            self.raiz = n
        else:
            padre.hijos.append(n)
        if es_literal(formula):  # ¿átomo y su negación en la misma rama?
            comp, a = complemento(formula), padre
            while a is not None:
                if a.formula == comp:
                    n.cierre = a.num
                    break
                a = a.padre
        return n

    def hojas_abiertas(self, desde):
        a = desde
        while a is not None:
            if a.cierre is not None:
                return []
            a = a.padre
        res, pila = [], [desde]
        while pila:
            x = pila.pop()
            if x.cierre is not None:
                continue
            if not x.hijos:
                res.append(x)
            else:
                pila.extend(reversed(x.hijos))
        return res

    def _resolver(self):
        while True:
            cand = [n for n in self.nodos
                    if n.aplicada is None and expandir(n.formula) and self.hojas_abiertas(n)]
            if not cand:
                break
            alfa = [n for n in cand if expandir(n.formula)[0] == "α"]
            n = (alfa or cand)[0]          # primero las que no ramifican
            _, ramas, regla = expandir(n.formula)
            for hoja in self.hojas_abiertas(n):
                for rama in ramas:
                    padre = hoja
                    for f in rama:
                        padre = self._nuevo(f, padre, f"{regla} de {n.num}")
            self._orden += 1
            n.aplicada = self._orden

    # ---------- consultas ----------
    def ramas(self):
        """Lista de (hoja, cerrada)."""
        res, pila = [], [(self.raiz, False)]
        while pila:
            n, cerrada = pila.pop()
            cerrada = cerrada or n.cierre is not None
            if n.hijos:
                pila.extend((h, cerrada) for h in reversed(n.hijos))
            else:
                res.append((n, cerrada))
        return res

    def nodos_abiertos(self):
        """Números de nodos que tienen al menos una rama abierta por debajo."""
        abiertos = set()
        for hoja, cerrada in self.ramas():
            if not cerrada:
                a = hoja
                while a is not None:
                    abiertos.add(a.num)
                    a = a.padre
        return abiertos

    def modelos(self):
        """Una asignación {letra: True/False} por cada rama abierta."""
        res = []
        for hoja, cerrada in self.ramas():
            if cerrada:
                continue
            asign, a = {}, hoja
            while a is not None:
                if isinstance(a.formula, Atomo):
                    asign[a.formula.nombre] = True
                elif es_literal(a.formula):
                    asign[a.formula.f.nombre] = False
                a = a.padre
            res.append(asign)
        return res

    def cierre_de(self, hoja):
        a = hoja
        while a is not None:
            if a.cierre is not None:
                return a
            a = a.padre
        return None


# ---------- presentación en texto ----------
def etiqueta_nodo(n):
    marca = "  ✓" if n.aplicada is not None else ""
    return f"{n.num}. {a_texto(n.formula)}{marca}   [{n.origen}]"


def render_texto(tab):
    lineas = []

    def sufijo(n):
        if n.hijos:
            return ""
        c = tab.cierre_de(n)
        if c is None:
            return "   ○ RAMA ABIERTA"
        return f"   ✕ RAMA CERRADA (contradicción {c.cierre} y {c.num})"

    def rec(n, cab, resto):
        extra = f"   ✕ (contradice {n.cierre})" if n.cierre is not None and n.hijos else ""
        lineas.append(cab + etiqueta_nodo(n) + extra + sufijo(n))
        if len(n.hijos) == 1:
            rec(n.hijos[0], resto, resto)
        else:
            for i, h in enumerate(n.hijos):
                ultimo = i == len(n.hijos) - 1
                rec(h, resto + ("└─ " if ultimo else "├─ "),
                    resto + ("   " if ultimo else "│  "))

    rec(tab.raiz, "", "")
    return "\n".join(lineas)
