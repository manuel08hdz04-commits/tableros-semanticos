"""Tableros semánticos desde reglas en español.

Uso:
    python main.py ejemplos/video.txt
    python main.py                       (escribes las reglas a mano)
    python main.py reglas.txt --png salida.png --no-mostrar
"""
import argparse
import sys

from logica.parser_es import Traductor, ErrorTraduccion
from logica.formulas import a_texto, es_literal
from logica.tableau import Tablero, render_texto


def leer_reglas(ruta):
    if ruta:
        with open(ruta, encoding="utf-8") as fh:
            lineas = fh.read().splitlines()
    else:
        print("Escribe una regla por línea (línea vacía para terminar):")
        lineas = []
        while True:
            try:
                linea = input("> ")
            except EOFError:
                break
            if not linea.strip():
                break
            lineas.append(linea)
    return [l.strip() for l in lineas if l.strip() and not l.strip().startswith("#")]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("archivo", nargs="?", help="archivo de texto con una regla por línea")
    ap.add_argument("--png", help="guardar el dibujo del tablero en este archivo PNG")
    ap.add_argument("--no-mostrar", action="store_true", help="no abrir la ventana gráfica")
    args = ap.parse_args()

    textos = leer_reglas(args.archivo)
    if not textos:
        sys.exit("No se ingresaron reglas.")

    tr = Traductor()
    reglas = []
    for i, t in enumerate(textos, 1):
        try:
            reglas.append((f"R{i}", tr.traducir(t)))
        except ErrorTraduccion as e:
            sys.exit(f"Error en la regla {i} («{t}»): {e}")

    print("\n=== TABLA DE ÁTOMOS ===")
    for letra, texto in tr.tabla_atomos():
        print(f"  {letra:<3} = {texto}")

    print("\n=== REGLAS Y FÓRMULAS ===")
    for (et, f), t in zip(reglas, textos):
        tipo = " (hecho)" if es_literal(f) else ""
        print(f"  {et}: {a_texto(f):<28} ←  {t}{tipo}")

    tab = Tablero(reglas)
    print("\n=== TABLERO SEMÁNTICO (se parte de que todas las reglas son verdaderas) ===")
    print(render_texto(tab))

    ramas = tab.ramas()
    cerradas = sum(1 for _, c in ramas if c)
    print(f"\n=== RESULTADO ===\n  Ramas: {len(ramas)}  |  cerradas: {cerradas}  |  abiertas: {len(ramas) - cerradas}")
    modelos = tab.modelos()
    if not modelos:
        print("  Todas las ramas se cierran: la base de conocimiento es INCONSISTENTE (insatisfacible).")
        titulo = "Base de conocimiento INCONSISTENTE: todas las ramas cerradas"
    else:
        print("  La base de conocimiento es CONSISTENTE (satisfacible). Condiciones en que todas las reglas se cumplen:")
        letras = [l for l, _ in tr.tabla_atomos()]
        for k, m in enumerate(modelos, 1):
            asign = ", ".join(f"{l} = {'V' if m[l] else 'F'}" for l in letras if l in m)
            libres = [l for l in letras if l not in m]
            extra = f"   (libres: {', '.join(libres)})" if libres else ""
            print(f"    Rama abierta {k}: {asign}{extra}")
        titulo = f"Base de conocimiento CONSISTENTE: {len(modelos)} rama(s) abierta(s)"

    try:
        from logica.visual import dibujar
        dibujar(tab, titulo, ruta_png=args.png, mostrar=not args.no_mostrar)
        if args.png:
            print(f"\nDibujo guardado en {args.png}")
    except ImportError:
        print("\n(Instala matplotlib para ver el dibujo: pip install -r requirements.txt)")


if __name__ == "__main__":
    main()
