#!/usr/bin/env python3
"""Authenticode sign the files we ship, or say what would be signed.

The certificate is never named on the command line and never lives in
the repository. It is referenced through environment variables, and the
preferred form is a thumbprint of a certificate already in a Windows
store, because that form has no password to leak into a log.

Usage:
  python sign_windows.py --dry-run out\\Default\\chrome.exe
  python sign_windows.py --from-manifest E:\\tmp\\sign-list.txt
  python sign_windows.py --verify dist\\boring-installer.exe
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

# Windows SDK puts a versioned folder under here, newest last.
SDK_BIN = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")

# Timestamping is what keeps a signature valid after the certificate
# expires, so a release signed today still installs in three years.
DEFAULT_TIMESTAMP_URL = "http://timestamp.digicert.com"

# Microsoft's signing service insists on its own timestamp authority.
ARTIFACT_SIGNING_TIMESTAMP_URL = "http://timestamp.acs.microsoft.com"

# Timestamp servers rate limit, and a whole release should not fail
# because one request was turned away.
TIMESTAMP_RETRIES = 4
TIMESTAMP_RETRY_DELAY = 15.0

# What each credential source needs. Only one of these may be set.
CREDENTIAL_SOURCES = ("BORING_SIGN_THUMBPRINT", "BORING_SIGN_PFX", "BORING_SIGN_DLIB")

CONFIG_ERROR = 2


class CredentialError(RuntimeError):
    """The signing credentials are missing or contradict each other."""


class Credential(NamedTuple):
    """How signtool is told which certificate to use."""

    kind: str
    args: list[str]
    # Values that must never reach a log, redacted when we print.
    secrets: tuple[str, ...]


# Only ever used by --dry-run, so the shape of the real command is
# visible on a machine that has no certificate on it.
PLACEHOLDER_CREDENTIAL = Credential(
    "no certificate configured", ["/sha1", "<BORING_SIGN_THUMBPRINT>", "/s", "My"], ()
)


def find_signtool() -> Path | None:
    """The newest signtool.exe in the installed SDK, or None."""
    candidates = sorted(SDK_BIN.glob("*/x64/signtool.exe"))
    return candidates[-1] if candidates else None


def credential_from_env(env: dict[str, str] | None = None) -> Credential | None:
    """Read the one credential source that is set, or None if none is.

    Two sources set at once is always a mistake, and picking one for the
    caller would sign a release with a certificate nobody chose.
    """
    env = os.environ if env is None else env
    present = [name for name in CREDENTIAL_SOURCES if env.get(name)]
    if len(present) > 1:
        raise CredentialError(
            "set only one signing credential source, found " + " and ".join(present)
        )
    if not present:
        return None

    if present[0] == "BORING_SIGN_THUMBPRINT":
        thumbprint = env["BORING_SIGN_THUMBPRINT"].replace(" ", "")
        args = ["/sha1", thumbprint, "/s", env.get("BORING_SIGN_STORE", "My")]
        if env.get("BORING_SIGN_MACHINE_STORE"):
            args.append("/sm")
        return Credential("certificate store thumbprint", args, ())

    if present[0] == "BORING_SIGN_PFX":
        args = ["/f", env["BORING_SIGN_PFX"]]
        password = env.get("BORING_SIGN_PFX_PASSWORD", "")
        if password:
            args += ["/p", password]
        return Credential("pfx file", args, (password,) if password else ())

    dmdf = env.get("BORING_SIGN_DMDF")
    if not dmdf:
        raise CredentialError("BORING_SIGN_DLIB also needs BORING_SIGN_DMDF")
    return Credential(
        "signing service dlib", ["/dlib", env["BORING_SIGN_DLIB"], "/dmdf", dmdf], ()
    )


def timestamp_url_for(
    credential: Credential | None,
    override: str | None,
    env: dict[str, str] | None = None,
) -> str:
    env = os.environ if env is None else env
    if override:
        return override
    if env.get("BORING_SIGN_TIMESTAMP_URL"):
        return env["BORING_SIGN_TIMESTAMP_URL"]
    if credential and credential.kind == "signing service dlib":
        return ARTIFACT_SIGNING_TIMESTAMP_URL
    return DEFAULT_TIMESTAMP_URL


def build_sign_command(
    signtool: str,
    files: list[str],
    credential: Credential | None,
    timestamp_url: str,
) -> list[str]:
    """The exact argv signtool is run with."""
    command = [signtool, "sign", "/fd", "sha256", "/tr", timestamp_url, "/td", "sha256"]
    command += (credential or PLACEHOLDER_CREDENTIAL).args
    return command + files


def build_verify_command(signtool: str, files: list[str]) -> list[str]:
    """Check the whole chain, including the timestamp countersignature."""
    return [signtool, "verify", "/pa", "/all", *files]


def redact(command: list[str], secrets: tuple[str, ...]) -> list[str]:
    """Hide anything that must not be printed, such as a pfx password."""
    hidden = [s for s in secrets if s]
    return ["***" if arg in hidden else arg for arg in command]


def show(command: list[str], secrets: tuple[str, ...] = ()) -> str:
    return subprocess.list2cmdline(redact(command, secrets))


def read_manifest(path: Path) -> list[str]:
    """One path per line. Blank lines and # comments are ignored."""
    files = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            files.append(line)
    return files


def _looks_like_timestamp_trouble(output: str) -> bool:
    """Worth another try, as opposed to a certificate that is simply wrong."""
    lowered = output.lower()
    return "timestamp" in lowered or "0x80070002" in lowered


def run_with_timestamp_retries(
    command: list[str],
    secrets: tuple[str, ...],
    retries: int,
    delay: float,
) -> int:
    """Run signtool, retrying only when the timestamp server refused us."""
    for attempt in range(1, retries + 1):
        print(f"$ {show(command, secrets)}")
        done = subprocess.run(command, capture_output=True, text=True, check=False)
        output = done.stdout + done.stderr
        sys.stdout.write(output)
        if done.returncode == 0:
            return 0
        if attempt == retries or not _looks_like_timestamp_trouble(output):
            return done.returncode
        print(f"timestamping failed, retrying in {delay:.0f}s ({attempt}/{retries})")
        time.sleep(delay)
    return 1


def _gather_files(args: argparse.Namespace) -> list[str]:
    files = list(args.files)
    for manifest in args.from_manifest:
        files += read_manifest(Path(manifest))
    # Same file twice is harmless but confusing in a log, so drop repeats
    # while keeping the order the caller gave.
    return list(dict.fromkeys(files))


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Authenticode sign the files we ship.")
    ap.add_argument("files", nargs="*", help="files to sign or verify")
    ap.add_argument(
        "--from-manifest",
        action="append",
        default=[],
        metavar="FILE",
        help="text file of paths, one per line",
    )
    ap.add_argument("--verify", action="store_true", help="check signatures instead")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print the command that would run and stop, no certificate needed",
    )
    ap.add_argument("--signtool", default=None, help="override the signtool.exe path")
    ap.add_argument(
        "--timestamp-url", default=None, help="RFC 3161 timestamp authority"
    )
    ap.add_argument("--timestamp-retries", type=int, default=TIMESTAMP_RETRIES)
    ap.add_argument("--timestamp-delay", type=float, default=TIMESTAMP_RETRY_DELAY)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(sys.argv[1:] if argv is None else argv)

    try:
        files = _gather_files(args)
    except OSError as error:
        print(f"cannot read the manifest: {error}", file=sys.stderr)
        return CONFIG_ERROR
    if not files:
        print("give at least one file, or --from-manifest", file=sys.stderr)
        return CONFIG_ERROR

    found = Path(args.signtool) if args.signtool else find_signtool()
    if found is None and not args.dry_run:
        print(f"no signtool.exe under {SDK_BIN}", file=sys.stderr)
        return CONFIG_ERROR
    signtool = str(found) if found else "signtool.exe"

    try:
        credential = credential_from_env()
    except CredentialError as error:
        print(str(error), file=sys.stderr)
        return CONFIG_ERROR

    if args.verify:
        command = build_verify_command(signtool, files)
        if args.dry_run:
            print(show(command))
            return 0
        return subprocess.run(command, check=False).returncode

    if credential is None and not args.dry_run:
        print(
            "no signing credentials. Set one of "
            + ", ".join(CREDENTIAL_SOURCES)
            + ", or pass --dry-run. See docs/release/SIGNING.md.",
            file=sys.stderr,
        )
        return CONFIG_ERROR

    timestamp_url = timestamp_url_for(credential, args.timestamp_url)
    command = build_sign_command(signtool, files, credential, timestamp_url)
    secrets = credential.secrets if credential else ()

    if args.dry_run:
        where = "no certificate configured" if credential is None else credential.kind
        print(f"would sign {len(files)} file(s) using {where}")
        print(show(command, secrets))
        return 0

    missing = [f for f in files if not Path(f).is_file()]
    if missing:
        print("these files are not there: " + ", ".join(missing), file=sys.stderr)
        return CONFIG_ERROR

    print(f"signing {len(files)} file(s) with {credential.kind}")
    return run_with_timestamp_retries(
        command, secrets, max(1, args.timestamp_retries), args.timestamp_delay
    )


if __name__ == "__main__":
    sys.exit(main())
