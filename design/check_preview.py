"""Exercise the interface study in the actual Chromium build."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "boring-core/tools"))
from drive import Browser

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/ui-preview"
OUT.mkdir(parents=True, exist_ok=True)
checks = []


def check(name, ok):
    checks.append({"name": name, "passed": bool(ok)})


with Browser(args=["--window-size=1440,1000"]) as b:
    b.get((ROOT / "design/index.html").as_uri())
    check("home renders", "Room to breathe" in b.run("return document.body.innerText"))
    b.screenshot(str(OUT / "home-light.png"))
    for theme in ["light", "dark"]:
        for density in ["comfortable", "compact", "large"]:
            b.run(
                "state.theme=arguments[0];state.density=arguments[1];render()",
                [theme, density],
            )
            for view in ["home", "search", "reader", "settings", "warning", "summary"]:
                b.run("navigate(arguments[0])", [view])
                check(
                    f"{theme}/{density}/{view}: no page overflow",
                    b.run("return document.documentElement.scrollWidth<=innerWidth"),
                )
            b.screenshot(str(OUT / f"summary-{theme}-{density}.png"))
    b.run("state.theme='dark';state.density='comfortable';navigate('home')")
    b.screenshot(str(OUT / "home-dark.png"))
    for count in [1, 10, 30, 100]:
        b.run("state.tabs=arguments[0];state.activeTab=0;render()", [count])
        check(
            f"{count} tabs preserve minimum width",
            b.run(
                "return [...document.querySelectorAll('.tab')]"
                ".every(t=>t.getBoundingClientRect().width>=190)"
            ),
        )
        check(
            f"{count} tabs do not overflow window",
            b.run("return document.documentElement.scrollWidth<=innerWidth"),
        )
    b.run("document.querySelector('.tab').focus()")
    b._req(
        "POST",
        f"/session/{b.sid}/actions",
        {
            "actions": [
                {
                    "type": "key",
                    "id": "keyboard",
                    "actions": [
                        {"type": "keyDown", "value": "\ue014"},
                        {"type": "keyUp", "value": "\ue014"},
                    ],
                }
            ]
        },
    )
    check(
        "arrow key moves tab focus",
        b.run("return document.activeElement.dataset.tab==='1'"),
    )
    b.run(
        "state.tabs=3;state.activeTab=0;state.failed=true;render();document.getElementById('protection').click()"
    )
    check(
        "protection failure is explicit",
        b.run(
            "return document.getElementById('protection-panel').innerText"
            ".includes('Known scam sites are not being blocked')"
        ),
    )
    b.screenshot(str(OUT / "protection-unavailable.png"))
    b.run("state.senior=true;navigate('warning')")
    check(
        "senior mode has no bypass",
        b.run("return !document.getElementById('bypass-demo')"),
    )
    b.run("navigate('search')")
    check(
        "hidden sponsored fixture absent",
        b.run("return !document.querySelector('.sponsored')"),
    )
    b.run("state.senior=false;state.hideAds=false;render()")
    check(
        "label option shows sponsored fixture",
        b.run("return !!document.querySelector('.sponsored .ad-label')"),
    )
    b.run(
        "state.summary='consent';navigate('summary');document.getElementById('send-summary').click()"
    )
    check("summary result interaction", b.run("return state.summary==='done'"))
    b.run("document.getElementById('summary-error').click()")
    check("summary error interaction", b.run("return state.summary==='failed'"))
    b.run(
        "state.tabs=3;state.activeTab=0;render();document.getElementById('new-tab').click()"
    )
    check("new tab is selected", b.run("return state.tabs===4 && state.activeTab===3"))
    b.run("document.querySelector('[data-close-tab=\"3\"]').click()")
    check(
        "closing active tab keeps valid selection",
        b.run("return state.tabs===3 && state.activeTab===2"),
    )
    for width in [1440, 1152, 960, 720, 390]:
        b._req(
            "POST",
            f"/session/{b.sid}/goog/cdp/execute",
            {
                "cmd": "Emulation.setDeviceMetricsOverride",
                "params": {
                    "width": width,
                    "height": 900,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
            },
        )
        for view in ["home", "settings", "warning", "reader", "summary"]:
            b.run("navigate(arguments[0])", [view])
            check(
                f"width {width}/{view}: no page overflow",
                b.run("return document.documentElement.scrollWidth<=innerWidth"),
            )
    b._req(
        "POST",
        f"/session/{b.sid}/goog/cdp/execute",
        {
            "cmd": "Emulation.clearDeviceMetricsOverride",
            "params": {},
        },
    )
    b.run(
        "state.failed=false;state.theme='light';state.hideAds=true;state.section='protection';navigate('settings')"
    )
    b.screenshot(str(OUT / "settings-light.png"))
    b.run("navigate('reader')")
    b.screenshot(str(OUT / "reader-light.png"))
    b.run("navigate('warning')")
    b.screenshot(str(OUT / "warning-light.png"))

(OUT / "checks.json").write_text(json.dumps(checks, indent=2))
failed = [c for c in checks if not c["passed"]]
print(json.dumps({"passed": len(checks) - len(failed), "failed": failed}, indent=2))
sys.exit(bool(failed))
