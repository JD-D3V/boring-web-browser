#!/usr/bin/env python3
"""One writer at a time for the shared Chromium build tree.

Everything that writes into E:\\ung takes this lock first, including a
build JD starts by hand at a developer prompt. Two ninja runs against
one out\\Default corrupt each other quietly, and the damage only shows
up hours later in a half linked chrome.exe.

Usage:
  python joblock.py --job "manual build" -- ninja -C out\\Default chrome
  python joblock.py --claim --owner gh-1234 --lease 43200 --job release
  python joblock.py --release --owner gh-1234
  python joblock.py --status
"""

import argparse
import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

# Told apart from the exit code of whatever we ran, so a caller can see
# "someone else has the tree" rather than "the build failed".
BUSY_EXIT = 75

# Slow enough not to spin, quick enough that a queued build starts soon
# after the tree frees up.
POLL_SECONDS = 5.0


def default_lock_path() -> Path:
    """Where the lock lives, next to the tree it guards."""
    from_env = os.environ.get("BORING_JOBLOCK")
    if from_env:
        return Path(from_env)
    if os.name == "nt":
        return Path(r"E:\ung\boring-build.lock")
    return Path(tempfile.gettempdir()) / "boring-build.lock"


def _take(fd: int) -> bool:
    """Take the operating system lock, or return False if someone has it."""
    if os.name == "nt":
        import msvcrt

        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _drop(fd: int) -> None:
    """Give the operating system lock back. Closing the file does this too."""
    if os.name == "nt":
        import msvcrt

        with contextlib.suppress(OSError):
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    with contextlib.suppress(OSError):
        fcntl.flock(fd, fcntl.LOCK_UN)


def _holder_path(lock_path: Path) -> Path:
    """A separate file, because the locked one cannot be read by others."""
    return lock_path.with_name(lock_path.name + ".holder.json")


def read_holder(lock_path: Path) -> dict | None:
    """Whatever the last acquirer wrote about itself, or None."""
    try:
        holder = json.loads(_holder_path(lock_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return holder if isinstance(holder, dict) else None


def lease_is_live(holder: dict | None) -> bool:
    """True while a multi step claim still stands.

    A record with no expiry is not a claim, it is only a note about the
    command that was running. The operating system lock covers that one
    and it is gone the moment that process ends. Only an expiry makes a
    holder outlive its process, and an expiry always runs out, so a job
    killed part way through cannot block the tree for ever.
    """
    if not holder:
        return False
    try:
        expires = float(holder.get("expires_epoch") or 0.0)
    except (TypeError, ValueError):
        return False
    return bool(expires) and time.time() < expires


def describe(holder: dict | None) -> str:
    """One line naming who has the tree, for an error message."""
    if not holder:
        return "another process"
    return "{job} (owner {owner}, pid {pid} on {host}, started {started})".format(
        job=holder.get("job", "an unnamed job"),
        owner=holder.get("owner", "?"),
        pid=holder.get("pid", "?"),
        host=holder.get("host", "?"),
        started=holder.get("started", "?"),
    )


class TreeBusy(RuntimeError):
    """Someone else is working in the build tree."""

    def __init__(self, holder: dict | None):
        self.holder = holder
        super().__init__(
            f"the build tree is busy: {describe(holder)}. "
            "Wait for it to finish, or pass --wait SECONDS."
        )


class JobLock:
    """Exclusive use of the build tree, as a context manager.

    with JobLock("nightly build", wait=3600):
        ...
    """

    def __init__(
        self,
        job: str,
        *,
        path: str | os.PathLike[str] | None = None,
        owner: str | None = None,
        lease: float = 0.0,
        wait: float = 0.0,
    ):
        self.path = Path(path) if path else default_lock_path()
        self.job = job
        self.owner = owner or f"pid-{os.getpid()}"
        self.lease = float(lease)
        self.wait = float(wait)
        self._fd: int | None = None

    def __enter__(self) -> "JobLock":
        self.acquire()
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self.release()
        return False

    def acquire(self) -> None:
        """Take the lock, or raise TreeBusy naming who has it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            self._wait_for_lock(fd)
            holder = read_holder(self.path)
            if lease_is_live(holder) and holder.get("owner") != self.owner:
                raise TreeBusy(holder)
        except BaseException:
            _drop(fd)
            os.close(fd)
            raise
        self._fd = fd
        self._write_holder()

    def release(self) -> None:
        """Give the lock back. A claim with a lease outlives this."""
        if self._fd is None:
            return
        holder = read_holder(self.path)
        # Clear our own note, but never a live lease. A later step of the
        # same job still needs the claim we took earlier.
        if holder and holder.get("owner") == self.owner and not lease_is_live(holder):
            with contextlib.suppress(OSError):
                _holder_path(self.path).unlink()
        _drop(self._fd)
        os.close(self._fd)
        self._fd = None

    def _wait_for_lock(self, fd: int) -> None:
        deadline = time.monotonic() + self.wait
        while not _take(fd):
            left = deadline - time.monotonic()
            if left <= 0:
                raise TreeBusy(read_holder(self.path))
            time.sleep(min(POLL_SECONDS, max(0.05, left)))

    def _write_holder(self) -> None:
        expires = time.time() + self.lease if self.lease else None
        if expires is None:
            # A plain step inside a job that already claimed the tree
            # keeps that claim, rather than quietly dropping it.
            standing = read_holder(self.path)
            if lease_is_live(standing) and standing.get("owner") == self.owner:
                expires = float(standing["expires_epoch"])
        holder = {
            "owner": self.owner,
            "job": self.job,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started": datetime.now(UTC).isoformat(timespec="seconds"),
            "expires": _iso(expires),
            "expires_epoch": expires,
        }
        _holder_path(self.path).write_text(
            json.dumps(holder, indent=2) + "\n", encoding="utf-8"
        )


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds")


def _status(path: Path) -> int:
    """Report without changing anything. 0 when the tree is free."""
    holder = read_holder(path)
    running = False
    if path.exists():
        fd = os.open(path, os.O_RDWR)
        try:
            running = not _take(fd)
            if not running:
                _drop(fd)
        finally:
            os.close(fd)
    live = lease_is_live(holder)
    if not running and not live:
        print(f"build tree free ({path})")
        return 0
    if running:
        print(f"build tree in use by {describe(holder)}")
    if live:
        print(f"lease held until {holder.get('expires')} by {describe(holder)}")
    return 1


def _release_claim(path: Path, owner: str | None) -> int:
    holder = read_holder(path)
    if holder is None:
        print("no claim on record")
        return 0
    if owner and holder.get("owner") != owner:
        print(f"will not release a claim held by {describe(holder)}", file=sys.stderr)
        return BUSY_EXIT
    with contextlib.suppress(OSError):
        _holder_path(path).unlink()
    print(f"released {describe(holder)}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="One writer at a time for the shared Chromium build tree."
    )
    ap.add_argument("--job", default="unnamed job", help="what is being run")
    ap.add_argument(
        "--owner",
        default=None,
        help="token shared by the steps of one job, so they pass the claim on",
    )
    ap.add_argument(
        "--lease",
        type=float,
        default=0.0,
        help="seconds this owner keeps the tree for, across several commands",
    )
    ap.add_argument(
        "--wait",
        type=float,
        default=0.0,
        help="seconds to wait for a busy tree before giving up",
    )
    ap.add_argument("--lock-file", default=None, help="override the lock path")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--acquire",
        action="store_true",
        help="run the command after -- under the lock (the default)",
    )
    mode.add_argument(
        "--claim", action="store_true", help="take a lease and exit, no command"
    )
    mode.add_argument("--release", action="store_true", help="drop this owner's lease")
    mode.add_argument("--status", action="store_true", help="say who has the tree")
    ap.add_argument("command", nargs=argparse.REMAINDER)
    return ap


def _do_claim(path: Path, args: argparse.Namespace) -> int:
    if not args.owner or not args.lease:
        print("a claim needs --owner and --lease SECONDS", file=sys.stderr)
        return 2
    lock = JobLock(
        args.job, path=path, owner=args.owner, lease=args.lease, wait=args.wait
    )
    try:
        lock.acquire()
    except TreeBusy as busy:
        print(str(busy), file=sys.stderr)
        return BUSY_EXIT
    lock.release()
    until = _iso(time.time() + args.lease)
    print(f"claimed the build tree for {args.owner} until {until}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    path = Path(args.lock_file) if args.lock_file else default_lock_path()

    if args.status:
        return _status(path)
    if args.release:
        return _release_claim(path, args.owner)
    if args.claim:
        return _do_claim(path, args)

    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        print("give a command to run after --", file=sys.stderr)
        return 2

    lock = JobLock(
        args.job, path=path, owner=args.owner, lease=args.lease, wait=args.wait
    )
    try:
        lock.acquire()
    except TreeBusy as busy:
        print(str(busy), file=sys.stderr)
        return BUSY_EXIT
    try:
        return subprocess.call(command)
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
