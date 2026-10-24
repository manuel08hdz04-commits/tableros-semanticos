import sys, os, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logica.parser_es import Traductor
from logica.formulas import a_texto
from logica.tableau import Tablero


def kb(*textos):
    tr = Traductor()
    return tr, [(f"R{i}", tr.traducir(t)) for i, t in enumerate(textos, 1)]


class Pruebas(unittest.TestCase):
    def test_video(self):
        tr, reglas = kb("Si es de día, entonces voy a trabajar",
                        "Si llueve, entonces no voy a trabajar", "Es de día")
        self.assertEqual([a_texto(f) for _, f in reglas], ["p → q", "r → ¬q", "p"])
        t = Tablero(reglas)
        r = t.ramas()
        self.assertEqual((len(r), sum(c for _, c in r)), (3, 2))
        self.assertEqual(t.modelos(), [{"p": True, "q": True, "r": False}])

    def test_inconsistente(self):
        _, reglas = kb("Si es de día, entonces voy a trabajar",
                       "Si llueve, entonces no voy a trabajar", "Es de día", "Llueve")
        self.assertEqual(Tablero(reglas).modelos(), [])

    def test_conectivos(self):
        for texto, esperado in [
            ("Voy a trabajar y estudio", "p ∧ q"),
            ("Voy a trabajar o estudio", "p ∨ q"),
            ("No voy a trabajar", "¬p"),
            ("Voy a trabajar si y solo si estudio", "p ↔ q"),
            ("Si voy a trabajar entonces estudio", "p → q"),
            ("Voy a trabajar si estudio", "q → p"),
        ]:
            self.assertEqual(a_texto(Traductor().traducir(texto)), esperado, texto)

    def test_mismo_atomo_y_parentesis(self):
        f = Traductor().traducir("Si llueve o hace frío, entonces no voy a trabajar y no estudio")
        self.assertEqual(a_texto(f), "p ∨ q → ¬r ∧ ¬s")
        self.assertEqual(a_texto(Traductor().traducir("Si no voy a trabajar entonces voy a trabajar")), "¬p → p")

    def test_negacion_compuesta(self):
        _, reglas = kb("no es verdad que llueve y hace frío", "llueve", "hace frío")
        self.assertEqual(Tablero(reglas).modelos(), [])

    def test_sii_y_xor(self):
        # p ↔ q  con  ¬p  -> modelo p=F, q=F
        _, reglas = kb("llueve si y solo si hay nubes", "no llueve")
        self.assertEqual(Tablero(reglas).modelos(), [{"q": False, "p": False}])


if __name__ == "__main__":
    unittest.main()
