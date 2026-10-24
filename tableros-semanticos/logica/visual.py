"""Dibujo gráfico del tablero con matplotlib (verde = abierta, rojo = cerrada)."""
from .formulas import a_texto


def dibujar(tab, titulo="Tablero semántico", ruta_png=None, mostrar=True):
    import matplotlib
    if not mostrar:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    abiertos = tab.nodos_abiertos()
    hojas_cerradas = {h.num: c for h, c in tab.ramas()}

    def etiqueta(n):
        marca = " ✓" if n.aplicada is not None else ""
        return f"{n.num}. {a_texto(n.formula)}{marca}\n[{n.origen}]"

    maxlen = max(len(a_texto(n.formula)) + 6 for n in tab.nodos)
    ancho_slot = max(2.8, maxlen * 0.09 + 0.5)

    pos, cont, prof = {}, [0], [0]

    def layout(n, d):
        prof[0] = max(prof[0], d)
        if not n.hijos:
            x = cont[0] * ancho_slot + ancho_slot / 2
            cont[0] += 1
        else:
            xs = [layout(h, d + 1) for h in n.hijos]
            x = sum(xs) / len(xs)
        pos[n.num] = (x, -d * 1.3)
        return x

    layout(tab.raiz, 0)
    w = max(7.0, cont[0] * ancho_slot)
    h = max(4.0, (prof[0] + 2) * 0.95)
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, w)
    ax.set_ylim(-(prof[0] + 1.4) * 1.3, 1.0)
    ax.axis("off")

    for n in tab.nodos:
        x, y = pos[n.num]
        for hijo in n.hijos:
            cx, cy = pos[hijo.num]
            ax.plot([x, cx], [y - 0.32, cy + 0.32], color="#888", lw=1, zorder=1)

    for n in tab.nodos:
        x, y = pos[n.num]
        abierto = n.num in abiertos
        ax.text(x, y, etiqueta(n), ha="center", va="center", fontsize=9, zorder=2,
                bbox=dict(boxstyle="round,pad=0.35",
                          fc="#e6f4e6" if abierto else "#fde4e4",
                          ec="#2e7d32" if abierto else "#c0392b", lw=1.4))
        if not n.hijos:
            if hojas_cerradas[n.num]:
                ax.text(x, y - 0.62, "✕", ha="center", va="center",
                        fontsize=18, color="#c0392b", fontweight="bold")
            else:
                ax.text(x, y - 0.62, "○ abierta", ha="center", va="center",
                        fontsize=10, color="#2e7d32", fontweight="bold")

    ax.set_title(titulo, fontsize=13, fontweight="bold")
    fig.text(0.5, 0.01, "Verde: rama abierta   ·   Rojo/✕: rama cerrada   ·   ✓: fórmula ya aplicada   ·   "
             "[regla de n]: origen de la fórmula", ha="center", fontsize=8, color="#555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    if ruta_png:
        fig.savefig(ruta_png, dpi=150)
    if mostrar:
        plt.show()
    plt.close(fig)
