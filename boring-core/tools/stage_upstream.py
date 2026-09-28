#!/usr/bin/env python3
r"""Prepare a second ungoogled-chromium source tree, ready to rebase onto.

Chromium ships security fixes every few weeks, so the base this browser
is built on goes stale on its own. Rebuilding the base we already have
is not an update; the source has to move to the newer tag first.

This stages that newer source somewhere else, so the tree that currently
builds is never touched. It stops as soon as the source is prepared and
patched. It does not configure or compile anything, because the point of
a staging tree is to find out what our own patches do against the new
source before spending a day of machine time on it.

It runs the same steps ungoogled-chromium's own build.py runs, by
importing the same modules from the staging checkout, so there is no
second copy of that logic to drift.

Google publishes the source tarball for some patch releases and not
others, and the ones it skips are often the ones with the security fixes
in them. --source clone takes the source from git at the exact tag
instead, which is what ungoogled's own build.py does when it is not
given --tarball. It is slower and much bigger; it is also the only way
to build a tag whose tarball was never published.

Usage:
  python stage_upstream.py --tag 153.0.8010.52-1.1 --dir E:\ung-153
  python stage_upstream.py --tag ... --dir ... --source clone
  python stage_upstream.py --tag ... --dir ... --clone-only
"""

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO = "https://github.com/ungoogled-software/ungoogled-chromium-windows"

# The tree that builds today. Never written to by this script.
LIVE_TREE = Path(r"E:\ung")


def run(args, **kwargs):
    print("+", " ".join(str(a) for a in args), flush=True)
    result = subprocess.run(args, **kwargs)
    if result.returncode != 0:
        sys.exit(f"failed ({result.returncode}): {' '.join(str(a) for a in args)}")
    return result


def clone(tag: str, dest: Path) -> None:
    """Checks out the ungoogled-chromium-windows repo at one tag.

    Shallow, and with its submodule, because the only thing wanted here
    is that tag's patches and download list.
    """
    if (dest / "build.py").exists():
        print("already cloned:", dest)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            tag,
            "--recurse-submodules",
            "--shallow-submodules",
            REPO,
            str(dest),
        ]
    )


def assemble_rust_toolchain(source_tree: Path) -> None:
    """Build third_party/rust-toolchain out of the per-arch downloads.

    The download list unpacks Rust into rust-toolchain-x64, -x86 and
    -arm, each a full install tree. The build wants one merged
    rust-toolchain holding the host's bin and every arch's lib, and
    nothing creates it but this step. Missing it, the build gets a long
    way in and then stops on a missing bindgen.exe.

    Same rules as ungoogled's build.py: lib from all three, bin from the
    host architecture only.
    """
    dst = source_tree / "third_party" / "rust-toolchain"
    flag = dst / "INSTALLED_VERSION"
    if flag.exists():
        print("rust toolchain already assembled")
        return

    host_is_64bit = sys.maxsize > 2**32
    x64 = source_tree / "third_party" / "rust-toolchain-x64"
    sources = [x64, source_tree / "third_party" / "rust-toolchain-x86",
               source_tree / "third_party" / "rust-toolchain-arm"]

    print("assembling the rust toolchain ...", flush=True)
    for src in sources:
        for part in ("bin", "lib"):
            if part == "bin" and host_is_64bit != (src == x64):
                continue
            target = dst / part
            target.mkdir(parents=True, exist_ok=True)
            for item in src.glob(f"*/{part}/*"):
                out = target / item.name
                if item.is_dir():
                    shutil.copytree(item, out, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, out)

    with open(flag, "w") as f:
        subprocess.run([str(x64 / "rustc" / "bin" / "rustc.exe"), "--version"],
                       stdout=f, check=True)
    print("rust toolchain at", dst)


# clone.py writes the output folder into .gclient with str(path), which
# on Windows is E:\ung-154\build\src. gclient reads .gclient as
# Python, where "\u" starts a unicode escape, so the sync stops with a
# syntax error. Upstream bug; the same path with forward slashes is fine.
_GCLIENT_WRITE = ".write_text(GC_CONFIG.replace('UC_OUT', str(args.output)))"
_GCLIENT_WRITE_FIXED = (
    ".write_text(GC_CONFIG.replace('UC_OUT', args.output.as_posix()))"
)


def fix_gclient_path(clone_py: Path) -> None:
    """Makes clone.py write a forward slash path into .gclient."""
    text = clone_py.read_text(encoding="utf-8")
    if _GCLIENT_WRITE_FIXED in text:
        return
    if text.count(_GCLIENT_WRITE) != 1:
        raise RuntimeError(
            f"{clone_py}: the .gclient line changed upstream; check whether "
            "the backslash fix is still needed"
        )
    clone_py.write_text(
        text.replace(_GCLIENT_WRITE, _GCLIENT_WRITE_FIXED), encoding="utf-8"
    )
    print("clone.py: .gclient gets a forward slash path")


def fetch_source(root: Path, source: str) -> None:
    """Puts Chromium's source under build/src, by whichever route."""
    source_tree = root / "build" / "src"
    # A git checkout has BUILD.gn long before its dependencies are synced,
    # so the clone route only counts as done once clone.py has finished.
    clone_done = root / "build" / ".boring-clone-done"
    if source == "clone" and clone_done.exists():
        print("source already cloned:", source_tree)
        return
    if source != "clone" and (source_tree / "BUILD.gn").exists():
        print("source already unpacked:", source_tree)
        return
    if source == "clone":
        # ungoogled's own clone path: a depth 2 git checkout at the tag
        # plus a gclient sync of the dependencies, then the same
        # generated files the tarball would have shipped with.
        print("cloning the chromium source (this is the long one) ...", flush=True)
        fix_gclient_path(root / "ungoogled-chromium" / "utils" / "clone.py")
        # Relative on purpose. gclient names each GCS dependency
        # "<path>:<object>" and splits on the first colon, so an absolute
        # E:/... path sends node_modules to <root>\E instead.
        run(
            [
                sys.executable,
                str(root / "ungoogled-chromium" / "utils" / "clone.py"),
                "-o",
                "build/src",
                "-p",
                "win64",
            ],
            cwd=root,
        )
        # clone.py is safe to run again over a partial checkout (it
        # fetches and resets), so only a finished run is marked done.
        clone_done.write_text("clone.py finished\n", encoding="utf-8")
        return
    raise RuntimeError("fetch_source: tarball route is handled by prepare()")


NODE_MODULES_DEP = "src/third_party/node/node_modules"


def _gcs_pin(deps_text: str, dep: str) -> dict:
    """Reads bucket, object, sha256 and file name of one GCS dep in DEPS."""
    start = deps_text.find(f"'{dep}': {{")
    if start < 0:
        raise RuntimeError(f"DEPS has no {dep} entry")
    end = deps_text.find("\n  '", start + 1)
    block = deps_text[start:end]
    pin = {}
    for key in ("bucket", "object_name", "sha256sum", "output_file"):
        match = re.search(rf"'{key}': '([^']+)'", block)
        if not match:
            raise RuntimeError(f"DEPS {dep}: no {key}")
        pin[key] = match.group(1)
    return pin


def fetch_node_modules(source_tree: Path) -> None:
    """Makes sure third_party/node/node_modules is there.

    WebUI cannot compile without it. Chromium gates it on non_git_source,
    which clone.py turns off, and ungoogled's gclient patch lets this one
    through anyway. If that ever fails (it did once, from an absolute
    output path), fetch the object DEPS pins, check its sha256 and unpack
    it where gclient would have, tarball included, since the clone
    pruning list removes that tarball.
    """
    pin = _gcs_pin((source_tree / "DEPS").read_text(encoding="utf-8"),
                   NODE_MODULES_DEP)
    out = source_tree / NODE_MODULES_DEP.removeprefix("src/")
    tarball = out / pin["output_file"]
    if (out / ".package-lock.json").exists():
        print("node_modules already there")
        return

    url = f"https://storage.googleapis.com/{pin['bucket']}/{pin['object_name']}"
    print("fetching node_modules:", url, flush=True)
    out.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != pin["sha256sum"]:
        sys.exit(f"node_modules sha256 {digest}, DEPS pins {pin['sha256sum']}")
    tarball.write_bytes(data)
    with tarfile.open(tarball) as tar:
        tar.extractall(out, filter="data")
    if not (out / ".package-lock.json").exists():
        sys.exit(f"node_modules unpacked, but {out} has no .package-lock.json")
    print("node_modules at", out)


def prepare(dest: Path, disable_ssl_verification: bool, source: str = "tarball") -> None:
    """Downloads, prunes and patches the source, then stops.

    Mirrors the source preparation half of ungoogled's build.py. The
    compile half is deliberately left out.
    """
    root = dest.resolve()
    utils = root / "ungoogled-chromium" / "utils"
    if not utils.is_dir():
        sys.exit(f"no ungoogled-chromium submodule under {root}")

    sys.path.insert(0, str(utils))
    import domain_substitution  # noqa: E402
    import downloads  # noqa: E402
    import patches  # noqa: E402
    import prune_binaries  # noqa: E402
    from _common import ENCODING, USE_REGISTRY, ExtractorEnum  # noqa: E402

    sys.path.pop(0)

    source_tree = root / "build" / "src"
    cache = root / "build" / "download_cache"
    source_tree.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)

    extractors = {
        ExtractorEnum.SEVENZIP: USE_REGISTRY,
        ExtractorEnum.WINRAR: USE_REGISTRY,
    }

    if source == "clone":
        fetch_source(root, source)
        fetch_node_modules(source_tree)
    elif (source_tree / "BUILD.gn").exists():
        print("source already unpacked:", source_tree)
    else:
        print("downloading the chromium tarball ...", flush=True)
        info = downloads.DownloadInfo([root / "ungoogled-chromium" / "downloads.ini"])
        downloads.retrieve_downloads(info, cache, None, True, disable_ssl_verification)
        downloads.check_downloads(info, cache, None)
        print("unpacking ...", flush=True)
        downloads.unpack_downloads(info, cache, None, source_tree, extractors)

    print("downloading the windows extras ...", flush=True)
    win_info = downloads.DownloadInfo([root / "downloads.ini"])
    downloads.retrieve_downloads(win_info, cache, None, True, disable_ssl_verification)
    downloads.check_downloads(win_info, cache, None)

    # Pruning and patching cannot run twice over the same files, so a rerun
    # after a failure resumes from markers instead of starting over.
    prune_started = root / "build" / ".boring-prune-started"
    pruned = root / "build" / ".boring-pruned"
    patched = root / "build" / ".boring-patched"
    if patched.exists():
        print("already pruned, patched and substituted:", source_tree)
        assemble_rust_toolchain(source_tree)
        return

    if pruned.exists():
        print("already pruned")
    else:
        print("pruning binaries ...", flush=True)
        # A clone carries files the tarball never had, so ungoogled keeps a
        # longer pruning list in the windows repo for exactly this route.
        # build.py picks between them the same way.
        pruning_list = (
            root / "pruning.list"
            if source == "clone"
            else root / "ungoogled-chromium" / "pruning.list"
        )
        resumed = prune_started.exists()
        prune_started.write_text("pruning started\n", encoding="utf-8")
        unremovable = prune_binaries.prune_files(
            source_tree, pruning_list.read_text(encoding=ENCODING).splitlines()
        )
        if unremovable and not resumed:
            sys.exit(f"could not prune: {unremovable}")
        if unremovable:
            # Deleted by the earlier, interrupted run.
            print(f"{len(unremovable)} listed files were already gone")
        pruned.write_text("pruned\n", encoding="utf-8")

    for relative in (
        Path("third_party/microsoft_dxheaders/src"),
        Path("third_party/devtools-frontend/src/third_party/esbuild"),
    ):
        path = source_tree / relative
        if path.exists():
            shutil.rmtree(path)
            path.mkdir()

    print("unpacking the windows extras ...", flush=True)
    downloads.unpack_downloads(win_info, cache, None, source_tree, extractors)

    patch_bin = source_tree / "third_party/git/usr/bin/patch.exe"
    print("applying the ungoogled patches ...", flush=True)
    patches.apply_patches(
        patches.generate_patches_from_series(
            root / "ungoogled-chromium" / "patches", resolve=True
        ),
        source_tree,
        patch_bin_path=patch_bin,
    )
    print("applying the windows patches ...", flush=True)
    patches.apply_patches(
        patches.generate_patches_from_series(root / "patches", resolve=True),
        source_tree,
        patch_bin_path=patch_bin,
    )

    print("substituting domains ...", flush=True)
    domain_substitution.apply_substitution(
        root / "ungoogled-chromium" / "domain_regex.list",
        root / "domain_substitution.list",
        source_tree,
        None,
    )
    patched.write_text("patched and substituted\n", encoding="utf-8")

    assemble_rust_toolchain(source_tree)

    version = (source_tree / "chrome" / "VERSION").read_text(encoding=ENCODING)
    print("\nstaged source is ready at", source_tree)
    print(version.strip().replace("\n", " "))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True, help="ungoogled-chromium-windows tag")
    ap.add_argument("--dir", required=True, help="where to stage it, not E:\\ung")
    ap.add_argument("--clone-only", action="store_true")
    ap.add_argument(
        "--source",
        choices=("tarball", "clone"),
        default="tarball",
        help="where Chromium's source comes from. Use clone when Google "
        "never published the tarball for the tag.",
    )
    ap.add_argument("--disable-ssl-verification", action="store_true")
    args = ap.parse_args()

    dest = Path(args.dir).resolve()
    if dest == LIVE_TREE or LIVE_TREE in dest.parents:
        sys.exit("refusing to stage inside the tree that builds today")

    os.environ.setdefault("TMP", r"E:\tmp")
    os.environ.setdefault("TEMP", r"E:\tmp")
    Path(os.environ["TMP"]).mkdir(parents=True, exist_ok=True)

    clone(args.tag, dest)
    if args.clone_only:
        return
    prepare(dest, args.disable_ssl_verification, args.source)


if __name__ == "__main__":
    main()
