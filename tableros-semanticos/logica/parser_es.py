"""
Traductor de reglas en español a fórmulas proposicionales.

Gramática reconocida (de menor a mayor precedencia):
    «si A entonces B»  /  «A si B»  /  «A solo si B»     ->  →
    «A si y solo si B»                                  ->  ↔
    «A o B»                                             ->  ∨
    «A y B»                                             ->  ∧
    «no A» / «no es verdad que A»                       ->  ¬
Lo que queda es una proposición simple (átomo).
"""
import re
import unicodedata

from .formulas import Atomo, No, Y, O, Implica, Sii


class ErrorTraduccion(ValueError):
    pass


def quitar_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


SI_Y_SOLO_SI = ["si", "y", "solo", "si"]
PREFIJOS_NEGACION = (["no", "es", "verdad", "que"], ["no", "es", "cierto", "que"],
                     ["no", "es", "el", "caso", "que"])


class Traductor:
    LETRAS = list("pqrstuvwxyz")

    def __init__(self):
        self.atomos = {}  # clave normalizada -> (letra, texto original)

    # ---------- átomos ----------
    def _nueva_letra(self):
        n = len(self.atomos)
        if n < len(self.LETRAS):
            return self.LETRAS[n]
        return f"p{n - len(self.LETRAS) + 1}"

    def _atomo(self, pal, cl):
        clave = " ".join(cl)
        if clave not in self.atomos:  # misma idea escrita igual => mismo átomo
            self.atomos[clave] = (self._nueva_letra(), " ".join(pal))
        return Atomo(self.atomos[clave][0])

    def tabla_atomos(self):
        return [(letra, texto[:1].upper() + texto[1:]) for letra, texto in self.atomos.values()]

    # ---------- traducción ----------
    def traducir(self, texto):
        pal = re.findall(r"\w+", texto.lower())
        if not pal:
            raise ErrorTraduccion("la regla está vacía")
        return self._parse(pal, [quitar_acentos(p) for p in pal])

    @staticmethod
    def _buscar(cl, secuencia, desde=1):
        k = len(secuencia)
        for i in range(desde, len(cl) - k + 1):
            if cl[i:i + k] == secuencia:
                return i
        return -1

    def _parse(self, pal, cl):
        if not cl:
            raise ErrorTraduccion("falta una proposición (¿conector sin operandos?)")

        # 1) «si A entonces B» (respeta condicionales anidados)
        if cl[0] == "si" and cl[:4] != SI_Y_SOLO_SI:
            prof = 0
            for i, t in enumerate(cl):
                if t == "si" and cl[i:i + 4] != SI_Y_SOLO_SI and not (i > 0 and cl[i - 1] == "solo"):
                    prof += 1
                elif t == "entonces":
                    prof -= 1
                    if prof == 0:
                        return Implica(self._parse(pal[1:i], cl[1:i]),
                                       self._parse(pal[i + 1:], cl[i + 1:]))
            raise ErrorTraduccion("falta «entonces» en: «" + " ".join(pal) + "»")

        # 2) «A si y solo si B»
        i = self._buscar(cl, SI_Y_SOLO_SI)
        if i > 0:
            return Sii(self._parse(pal[:i], cl[:i]), self._parse(pal[i + 4:], cl[i + 4:]))

        # 3) «A solo si B»  ==  A → B
        i = self._buscar(cl, ["solo", "si"])
        if i > 0:
            return Implica(self._parse(pal[:i], cl[:i]), self._parse(pal[i + 2:], cl[i + 2:]))

        # 4) «A si B»  ==  B → A
        i = self._buscar(cl, ["si"])
        if i > 0:
            consecuente = self._parse(pal[:i], cl[:i])   # primero A: las letras siguen el orden del texto
            return Implica(self._parse(pal[i + 1:], cl[i + 1:]), consecuente)

        # 5) «o»  y  6) «y»  (izquierda a derecha)
        for conector, clase in (("o", O), ("y", Y)):
            if conector in cl:
                partes, ini = [], 0
                for j, t in enumerate(cl):
                    if t == conector:
                        partes.append((pal[ini:j], cl[ini:j]))
                        ini = j + 1
                partes.append((pal[ini:], cl[ini:]))
                f = self._parse(*partes[0])
                for p, c in partes[1:]:
                    f = clase(f, self._parse(p, c))
                return f

        # 7) negación
        for pref in PREFIJOS_NEGACION:
            if cl[:len(pref)] == pref:
                return No(self._parse(pal[len(pref):], cl[len(pref):]))
        if cl[0] == "no":
            return No(self._parse(pal[1:], cl[1:]))

        # 8) proposición simple
        return self._atomo(pal, cl)
