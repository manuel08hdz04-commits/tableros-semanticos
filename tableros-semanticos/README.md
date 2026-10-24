# Tableros semánticos desde reglas en español

Escribes reglas en lenguaje natural; el programa detecta proposiciones simples (p, q, r…),
las convierte en fórmulas, construye el tablero semántico y lo muestra (texto + gráfico).

## Uso
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows   (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
python main.py ejemplos/video.txt
python main.py                  # modo interactivo
python main.py reglas.txt --png salida.png --no-mostrar
python tests/test_basico.py     # pruebas
```

## Cómo escribir las reglas (una por línea; `#` = comentario)
| Texto | Símbolo |
|---|---|
| «y» | ∧ |
| «o» | ∨ |
| «no», «no es verdad que» | ¬ |
| «si A entonces B», «A si B», «A solo si B» | → |
| «A si y solo si B» | ↔ |

Precedencia: ¬ > ∧ > ∨ > →/↔. Un hecho es una frase simple («Es de día»).
La misma frase escrita igual (sin importar mayúsculas, acentos o puntuación) es siempre el mismo átomo.
Limitación: no hay paréntesis en español; «A o B y C» se lee como A ∨ (B ∧ C). Si necesitas otra
agrupación, usa reglas separadas.

## Reglas de expansión
- Sin ramificar: ∧, ¬∨, ¬→, ¬¬
- Ramifican: ∨, →, ↔, ¬∧, ¬↔
Una rama se cierra (✕) al contener un átomo y su negación. Si todas se cierran, la base es inconsistente;
las ramas abiertas se listan como asignaciones (p = V, q = V, r = F).

## Estructura
```
main.py              interfaz de consola
logica/formulas.py   AST y escritura con paréntesis mínimos
logica/parser_es.py  español -> fórmulas, tabla de átomos
logica/tableau.py    motor del tablero + render en texto
logica/visual.py     dibujo con matplotlib
```
