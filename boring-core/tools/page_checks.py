"""Small helpers for the page smokes (newtab, warning page).

Not a test itself. Two jobs:

  Static look at a page written inside a C++ file: pull a raw string
  constant out of the source and ask node whether its script parses. A
  missing brace in a page script kills the whole page, and the C++
  compile never sees it.

  Photographs beside the compiled design: put our capture next to the
  picture of the screen it is built from (design/v12-compiled/shots-final),
  as one image when PIL is there, else as two files side by side in the
  same folder.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "design" / "v12-compiled" / "shots-final"

# Screen and light or dark, to the picture in shots-final. C01 and C02 are
# the new tab page in light and dark; C12 is the scam warning, with a dark
# copy in dark/.
REFERENCES = {
    ("C01", False): "c01-newtab.png",
    ("C02", True): "c02-newtabdark.png",
    ("C12", False): "c12-scamwarning.png",
    ("C12", True): "dark/c12-scamwarning.png",
}


def raw_string(cc_text, name):
    """The text of constexpr char name[] = R"TAG( ... )TAG"; or None."""
    m = re.search(
        r"constexpr\s+char\s+" + re.escape(name) + r'\[\]\s*=\s*R"(\w*)\((.*?)\)\1";',
        cc_text,
        re.DOTALL,
    )
    return m.group(2) if m else None


def script_blocks(html):
    """The bodies of the inline <script> elements in a page."""
    return re.findall(r"<script>(.*?)</script>", html, re.DOTALL)


def have_node():
    return shutil.which("node") is not None


def js_syntax_error(js):
    """None when node parses the script, else its complaint.

    Raises FileNotFoundError when node is not installed; see have_node.
    """
    with tempfile.TemporaryDirectory(prefix="page-js-") as folder:
        path = Path(folder) / "page.js"
        path.write_text(js, encoding="utf-8")
        run = subprocess.run(
            ["node", "--check", str(path)],
            capture_output=True,
            text=True,
            cwd=folder,
            timeout=60,
        )
    if run.returncode == 0:
        return None
    lines = [line for line in run.stderr.splitlines() if line.strip()]
    return " | ".join(lines[:6]) or "node refused the script"


def reference(screen, dark=False):
    """The compiled design's picture of this screen, or None when absent."""
    name = REFERENCES.get((screen, dark))
    path = SHOTS / name if name else None
    return path if path and path.is_file() else None


def beside(ours, screen, out_dir, dark=False):
    """Put our capture next to the design's picture of the screen.

    Returns the file written, or None when there is no picture of the
    screen to put beside. With PIL it is one image, ours on the left and
    the design on the right, both as tall as ours. Without PIL the
    design's picture is copied next to ours as <ours>-design.png.
    """
    ours = Path(ours)
    ref = reference(screen, dark)
    if ref is None or not ours.is_file():
        return None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image
    except ImportError:
        dest = out_dir / f"{ours.stem}-design.png"
        shutil.copyfile(ref, dest)
        return dest
    with Image.open(ours) as a, Image.open(ref) as b:
        a, b = a.convert("RGB"), b.convert("RGB")
        width = max(1, round(b.width * a.height / b.height))
        b = b.resize((width, a.height))
        sheet = Image.new("RGB", (a.width + 24 + b.width, a.height), (128, 128, 128))
        sheet.paste(a, (0, 0))
        sheet.paste(b, (a.width + 24, 0))
        dest = out_dir / f"{ours.stem}-beside-{screen.lower()}.png"
        sheet.save(dest)
    return dest
