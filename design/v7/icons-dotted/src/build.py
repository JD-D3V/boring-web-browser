import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import importlib, icondefs
importlib.reload(icondefs)
from icondefs import CATS, symbols, all_icons

OUT = os.path.dirname(HERE) + os.sep
SCR = HERE + os.sep

def use(name, size):
    return '<svg class="i s%d" aria-hidden="true" focusable="false"><use href="#b-%s"/></svg>' % (size, name)

# icons.svg
sprite_file = '<svg xmlns="http://www.w3.org/2000/svg" style="display:none">\n' + symbols("  ") + '\n</svg>\n'
open(OUT + "icons.svg", "w", encoding="utf-8", newline="\n").write(sprite_file)

# grid
grid = []
for cat, items in CATS:
    grid.append('    <h3 class="cat">%s</h3>' % cat)
    grid.append('    <div class="grid">')
    for nm, _ in items:
        grid.append('      <div class="tile" title="b-%s"><div class="row">%s%s%s</div><code>b-%s</code></div>' % (nm, use(nm, 16), use(nm, 20), use(nm, 24), nm))
    grid.append('    </div>')
grid_html = "\n".join(grid)

# states rows
state_rows = []
for nm in ["star", "pin", "audio-on", "protection", "reader", "split-view", "download"]:
    state_rows.append(
      '      <div class="nm">b-%s</div>'
      '<div class="c"><span class="chip">%s</span></div>'
      '<div class="c"><span class="chip hov">%s</span></div>'
      '<div class="c"><span class="chip sel">%s</span></div>'
      '<div class="c"><span class="chip dis">%s</span></div>' % (nm, use(nm, 20), use(nm, 20), use(nm, 20), use(nm, 20)))
states_html = "\n".join(state_rows)

tpl = open(SCR + "template.html", encoding="utf-8").read()
tpl = tpl.replace("@@SPRITE@@", symbols("  "))
tpl = tpl.replace("@@GRID@@", grid_html)
tpl = tpl.replace("@@STATES@@", states_html)
tpl = tpl.replace("@@COUNT@@", str(len(all_icons())))
tpl = re.sub(r"\[\[([a-z\-]+) (\d+)\]\]", lambda m: use(m.group(1), int(m.group(2))), tpl)
assert "\u2014" not in tpl and "\u2013" not in tpl
open(OUT + "index.html", "w", encoding="utf-8", newline="\n").write(tpl)
print("icons", len(all_icons()), "html bytes", len(tpl))
