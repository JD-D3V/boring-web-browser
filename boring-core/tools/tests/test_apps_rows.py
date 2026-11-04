"""The helpers behind "Apps you added" on the Protection page: which
add-ons are password managers, and how the AI assistant row reads.

The real header is compiled into a small program (apps_probe.cc), the same
way test_lookalike.py does, so the test needs Visual Studio but not a
Chromium build."""

import os
import re
import shutil
import subprocess
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.dirname(os.path.dirname(TESTS))
HEADER = os.path.join(CORE, "components", "boring", "protection", "apps_data.h")
VCVARS = (
    r"C:\Program Files\Microsoft Visual Studio\2022\Community"
    r"\VC\Auxiliary\Build\vcvars64.bat"
)

PASSWORD_MANAGERS = [
    "nngceckbapebfimnlniiiahkandclblb",  # Bitwarden
    "aeblfdkhhhdcdjpifhhbdiojplfjncoa",  # 1Password
    "oboonakemofpalcgghocfoadofidjkkk",  # KeePassXC-Browser
    "ghmbeldphafepmbegfdlkpapadhbakde",  # Proton Pass
]
CLOUD = "gmbmikajjgmnabiglmofipeabaddhgne"  # Save to Google Drive
AI = "difoiogjjojoaoomphldepapgpbgkhkb"  # Sider


class KnownIds(unittest.TestCase):
    def test_ids_are_extension_ids(self):
        with open(HEADER, encoding="utf-8") as f:
            ids = re.findall(r'\{"([a-z]{32})", AddonGroup', f.read())
        self.assertEqual(sorted(ids), sorted([*PASSWORD_MANAGERS, CLOUD, AI]))
        for ext_id in ids:
            # Chromium ids use only a to p.
            self.assertRegex(ext_id, r"^[a-p]{32}$")

    def test_no_em_dashes(self):
        with open(HEADER, encoding="utf-8") as f:
            self.assertNotIn("\u2014", f.read())


class AppsProbe(unittest.TestCase):
    exe = None
    workdir = None

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(VCVARS):
            raise unittest.SkipTest("Visual Studio 2022 is not installed here")
        cls.workdir = tempfile.mkdtemp(prefix="apps-rows-", dir=os.environ.get("TMP"))
        exe = os.path.join(cls.workdir, "apps_probe.exe")
        bat = os.path.join(cls.workdir, "build.bat")
        with open(bat, "w") as f:
            f.write(
                "@echo off\n"
                f'call "{VCVARS}" >nul\n'
                f'cd /d "{cls.workdir}"\n'
                "cl /nologo /EHsc /std:c++20 /W3 /O1 "
                f'/I "{CORE}" /Fe"{exe}" '
                f'"{os.path.join(TESTS, "apps_probe.cc")}"\n'
            )
        done = subprocess.run(
            ["cmd", "/c", bat], capture_output=True, text=True, timeout=300
        )
        if done.returncode != 0 or not os.path.exists(exe):
            raise AssertionError("probe did not compile:\n" + done.stdout + done.stderr)
        cls.exe = exe

    @classmethod
    def tearDownClass(cls):
        if cls.workdir:
            shutil.rmtree(cls.workdir, ignore_errors=True)

    def ask(self, lines):
        done = subprocess.run(
            [self.exe], input="\n".join(lines) + "\n", capture_output=True,
            text=True, timeout=60,
        )  # fmt: skip
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.split("\n")[:-1]

    def test_known_password_managers_are_grouped(self):
        answers = self.ask([f"group {i}" for i in PASSWORD_MANAGERS])
        self.assertEqual(answers, ["password"] * len(PASSWORD_MANAGERS))

    def test_known_cloud_and_ai_addons_are_grouped(self):
        self.assertEqual(self.ask([f"group {CLOUD}", f"group {AI}"]), ["cloud", "ai"])

    def test_everything_else_is_other(self):
        answers = self.ask(
            [
                "group ocaahdebbfolfmndjeplogmgcagdmblk",  # the bundled store
                "group aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "group NNGCECKBAPEBFIMNLNIIIAHKANDCLBLB",  # ids are lower case
                "group nngceckbapebfimnlniiiahkandclbl",  # one short
            ]
        )
        self.assertEqual(answers, ["other"] * 4)

    def test_ai_row(self):
        answers = self.ask(
            [
                "ai off",
                "ai bogus",
                "ai ollama localhost local",
                "ai ollama 127.0.0.2 local",
                "ai ollama",
                "ai ollama box.example",
                "ai gemini",
                "ai openai",
                "ai openrouter",
                "ai groq",
            ]
        )
        self.assertEqual(
            answers,
            [
                "off|Off|",
                "off|Off|",
                "on|Ollama on this computer|",
                "on|Ollama on this computer|",
                "on|Ollama address needs to be set up|",
                "on|Ollama at box.example|",
                "on|Gemini, your key, on click only|generativelanguage.googleapis.com",
                "on|OpenAI, your key, on click only|api.openai.com",
                "on|OpenRouter, your key, on click only|openrouter.ai",
                "on|Groq, your key, on click only|api.groq.com",
            ],
        )


if __name__ == "__main__":
    unittest.main()
