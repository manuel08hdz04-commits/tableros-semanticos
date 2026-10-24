"""Representación de fórmulas proposicionales y su impresión con paréntesis mínimos."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Atomo:
    nombre: str


@dataclass(frozen=True)
class No:
    f: object


@dataclass(frozen=True)
class Y:
    izq: object
    der: object


@dataclass(frozen=True)
class O:
    izq: object
    der: object


@dataclass(frozen=True)
class Implica:
    izq: object
    der: object


@dataclass(frozen=True)
class Sii:
    izq: object
    der: object


SIMBOLO = {Y: "∧", O: "∨", Implica: "→", Sii: "↔"}
# Precedencia: mayor = se une con más fuerza
PREC = {Sii: 1, Implica: 2, O: 3, Y: 4, No: 5, Atomo: 6}


def es_literal(f):
    return isinstance(f, Atomo) or (isinstance(f, No) and isinstance(f.f, Atomo))


def complemento(literal):
    """Complemento de un literal: p <-> ¬p."""
    return No(literal) if isinstance(literal, Atomo) else literal.f


def _envolver(hijo, padre, es_derecho):
    texto = a_texto(hijo)
    ph, pp = PREC[type(hijo)], PREC[type(padre)]
    # →, ↔ no son asociativos para nosotros: siempre se parentiza el mismo nivel
    necesita = ph < pp or (ph == pp and (type(padre) in (Implica, Sii) or es_derecho))
    return f"({texto})" if necesita else texto


def a_texto(f):
    if isinstance(f, Atomo):
        return f.nombre
    if isinstance(f, No):
        interno = a_texto(f.f)
        return "¬" + (interno if isinstance(f.f, (Atomo, No)) else f"({interno})")
    op = SIMBOLO[type(f)]
    return f"{_envolver(f.izq, f, False)} {op} {_envolver(f.der, f, True)}"
