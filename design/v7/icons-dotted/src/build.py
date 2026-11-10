import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import importlib  # noqa: E402

import icondefs  # noqa: E402

importlib.reload(icondefs)
from icondefs import CATS, all_icons, symbols  # noqa: E402

OUT = os.path.dirname(HERE) + os.sep
SCR = HERE + os.sep


def use(name, size):
    return f'<svg class="i s{size}" aria-hidden="true" focusable="false"><use href="#b-{name}"/></svg>'


# icons.svg
sprite_file = (
    '<svg xmlns="http://www.w3.org/2000/svg" style="display:none">\n'
    + symbols("  ")
    + "\n</svg>\n"
)
with open(OUT + "icons.svg", "w", encoding="utf-8", newline="\n") as f:
    f.write(sprite_file)

# grid
grid = []
for cat, items in CATS:
    grid.append(f'    <h3 class="cat">{cat}</h3>')
    grid.append('    <div class="grid">')
    for nm, _ in items:
        grid.append(
            f'      <div class="tile" title="b-{nm}"><div class="row">{use(nm, 16)}{use(nm, 20)}{use(nm, 24)}</div><code>b-{nm}</code></div>'
        )
    grid.append("    </div>")
grid_html = "\n".join(grid)

# states rows
state_rows = []
for nm in ["star", "pin", "audio-on", "protection", "reader", "split-view", "download"]:
    state_rows.append(
        f'      <div class="nm">b-{nm}</div>'
        f'<div class="c"><span class="chip">{use(nm, 20)}</span></div>'
        f'<div class="c"><span class="chip hov">{use(nm, 20)}</span></div>'
        f'<div class="c"><span class="chip sel">{use(nm, 20)}</span></div>'
        f'<div class="c"><span class="chip dis">{use(nm, 20)}</span></div>'
    )
states_html = "\n".join(state_rows)

with open(SCR + "template.html", encoding="utf-8") as f:
    tpl = f.read()
tpl = tpl.replace("@@SPRITE@@", symbols("  "))
tpl = tpl.replace("@@GRID@@", grid_html)
tpl = tpl.replace("@@STATES@@", states_html)
tpl = tpl.replace("@@COUNT@@", str(len(all_icons())))
tpl = re.sub(
    r"\[\[([a-z\-]+) (\d+)\]\]", lambda m: use(m.group(1), int(m.group(2))), tpl
)
assert "\u2014" not in tpl and "\u2013" not in tpl
with open(OUT + "index.html", "w", encoding="utf-8", newline="\n") as f:
    f.write(tpl)
print("icons", len(all_icons()), "html bytes", len(tpl))
