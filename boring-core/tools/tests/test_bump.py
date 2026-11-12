"""bump.py's pure logic: patch sorting, state and resume, disk check,
args.gn from a build.py, build step detection, compile log reading.

Offline; nothing here touches a Chromium tree. Run with pytest.
"""

import os
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bump  # noqa: E402
import rebase_patch  # noqa: E402

# ------------------------------------------------------------ sorting

ORIGINAL = "one\ntwo\nthree\n"
PATCH = """diff --git a/f.txt b/f.txt
--- a/f.txt
+++ b/f.txt
@@ -1,3 +1,3 @@
 one
-two
+TWO
 three
"""
GONE = PATCH.replace("f.txt", "gone.txt")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.txt").write_text(ORIGINAL, encoding="utf-8", newline="\n")
    patches = tmp_path / "patches"
    (patches / "160").mkdir(parents=True)
    for name in ("applies", "refresh", "cannot", "drift"):
        (patches / f"{name}.patch").write_text(PATCH, encoding="utf-8", newline="\n")
    (patches / "gone.patch").write_text(GONE, encoding="utf-8", newline="\n")
    monkeypatch.setattr(rebase_patch, "PATCHES", str(patches))
    monkeypatch.setattr(rebase_patch, "CORE", str(tmp_path))
    return src, patches


def fake_git(placed):
    """git apply that answers per patch name: placed[name] is what -C1 writes."""

    def git_apply(src, patch, extra):
        name = os.path.basename(patch)
        stem = name[: -len(".patch")]
        ok = types.SimpleNamespace(returncode=0, stderr="")
        bad = types.SimpleNamespace(returncode=1, stderr="error: patch failed: f.txt:1")
        if "--reverse" in extra:
            return bad
        if extra == []:
            # The rebased copy written into patches/160 applies strictly.
            in_set = os.path.basename(os.path.dirname(patch)) == "160"
            return ok if stem == "applies" or in_set else bad
        if extra == ["-C1"]:
            if stem not in placed:
                return bad
            Path(src, "f.txt").write_text(placed[stem], encoding="utf-8", newline="\n")
            return ok
        return bad

    return git_apply


def test_sort_buckets_from_fake_git_results(tree, monkeypatch):
    src, patches = tree
    monkeypatch.setattr(
        rebase_patch,
        "git_apply",
        fake_git(
            {"refresh": "one\nTWO\nthree\n", "drift": "one\nTWO and more\nthree\n"}
        ),
    )

    def read(name):
        return Path(rebase_patch.patch_path(name, "160")).read_text(encoding="utf-8")

    def one(name):
        (src / "f.txt").write_text(ORIGINAL, encoding="utf-8", newline="\n")
        return rebase_patch.rebase_one(str(src), name, "160", False)

    names = [
        "applies.patch",
        "refresh.patch",
        "cannot.patch",
        "drift.patch",
        "gone.patch",
    ]
    rows = {r["patch"]: r for r in bump.sort_series(names, one, read)}

    assert rows["applies.patch"]["bucket"] == "applies"
    assert rows["refresh.patch"]["bucket"] == "refreshed", rows["refresh.patch"]
    assert (patches / "160" / "refresh.patch").exists()
    assert rows["cannot.patch"]["bucket"] == "conflict"
    assert rows["cannot.patch"]["state"] == "CANNOT PLACE"
    assert rows["drift.patch"]["bucket"] == "conflict"
    assert "changed lines differ" in rows["drift.patch"]["detail"]
    assert rows["gone.patch"]["bucket"] == "conflict"
    assert rows["gone.patch"]["state"] == "file gone"


def test_sort_treats_a_crash_and_unknown_states_as_conflicts():
    def one(name):
        if name == "boom":
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "bad")
        return {"a": ("already in the tree", ""), "b": ("no change", "no-op")}[name]

    rows = bump.sort_series(["a", "b", "boom"], one, lambda n: PATCH)
    assert [r["bucket"] for r in rows] == ["applies", "conflict", "conflict"]
    assert rows[2]["state"] == "ERROR"


def test_changed_lines_ignore_context_and_headers():
    moved = PATCH.replace("@@ -1,3 +1,3 @@", "@@ -40,3 +40,3 @@").replace(
        " one", " uno"
    )
    assert bump.changed_lines(moved) == bump.changed_lines(PATCH) == ["+TWO", "-two"]


def test_patch_files_tells_created_from_changed():
    created = "--- /dev/null\n+++ b/new.cc\n@@ -0,0 +1 @@\n+x\n"
    assert bump.patch_files(PATCH + created) == (["f.txt"], ["new.cc"])


# -------------------------------------------------------- state, resume


def test_state_resumes_at_the_first_stage_not_done(tmp_path):
    state = bump.new_state(
        "160.0.8200.10-1.1", tmp_path, tmp_path / "old", "r4/x", "tarball"
    )
    assert state["major"] == 160
    assert bump.next_stage(state) == "stage"
    for name in ("stage", "patchset", "pristine"):
        bump.mark(state, name, "done", "ok")
    bump.mark(state, "sort", "needs-human", "2 conflicts")
    path = tmp_path / "state.json"
    bump.save_state(path, state)
    again = bump.load_state(path)
    assert bump.next_stage(again) == "sort"
    assert again["stages"]["stage"]["note"] == "ok"


def test_redo_reruns_the_stage_and_everything_after(tmp_path):
    state = bump.new_state(
        "160.0.8200.10-1.1", tmp_path, tmp_path / "old", "b", "clone"
    )
    for name in bump.NAMES:
        bump.mark(state, name, "done")
    assert bump.next_stage(state) is None
    bump.redo(state, "gn")
    assert bump.next_stage(state) == "gn"
    assert state["stages"]["layer"]["status"] == "done"
    assert all(state["stages"][n]["status"] == "pending" for n in ("compile", "record"))


def test_no_state_file_means_a_new_bump(tmp_path):
    assert bump.load_state(tmp_path / "missing.json") is None


# ---------------------------------------------------------------- disk


def test_disk_need_shrinks_as_stages_finish(tmp_path):
    total = sum(gb for _, gb, _ in bump.STAGES)
    assert bump.disk_need_gb(None) == total
    state = bump.new_state("160.0.8200.10-1.1", tmp_path, tmp_path, "b", "tarball")
    bump.mark(state, "stage", "done")
    assert bump.disk_need_gb(state) == total - 45


def test_check_disk_compares_free_space(tmp_path):
    def usage(free_gb):
        return lambda _p: types.SimpleNamespace(free=free_gb * 2**30)

    ok, msg = bump.check_disk(tmp_path / "not" / "yet", 80, usage(120))
    assert ok and "120 GB free" in msg
    ok, _ = bump.check_disk(tmp_path, 80, usage(30))
    assert not ok


# ------------------------------------------------------------- args.gn

BUILD_PY = """
import importlib.util
import sys
from pathlib import Path

def main():
    if not args.ci or not (source_tree / 'out/Default').exists():
        # Output args.gn
        (source_tree / 'out/Default').mkdir(parents=True)
        gn_flags = (_ROOT_DIR / 'ungoogled-chromium' / 'flags.gn').read_text(encoding=ENCODING)
        gn_flags += '\\n'
        windows_flags = (_ROOT_DIR / 'flags.windows.gn').read_text(encoding=ENCODING)
        if args.x86:
            windows_flags = windows_flags.replace('x64', 'x86')
            windows_flags += '\\nv8_enable_drumbrake=false\\n'
        elif args.arm:
            windows_flags = windows_flags.replace('x64', 'arm64')
        if args.tarball:
            windows_flags += '\\nchrome_pgo_phase=0\\n'
        clang_spec = importlib.util.find_spec('clang')
        if clang_spec is None or not clang_spec.submodule_search_locations:
            get_logger().error('Python clang bindings not found. Install them with: pip install clang')
            sys.exit(1)
        libclang_so = source_tree / 'third_party' / 'llvm-build' / 'Release+Asserts' / 'bin' / 'libclang.dll'
        libclang_bindings_dir = Path(list(clang_spec.submodule_search_locations)[0]).parent
        windows_flags += f'\\nv8_metagen_libclang_so="{libclang_so.resolve().as_posix()}"\\n'
        windows_flags += f'v8_metagen_libclang_bindings_dir="{libclang_bindings_dir.resolve().as_posix()}"\\n'
        gn_flags += windows_flags
        (source_tree / 'out/Default/args.gn').write_text(gn_flags, encoding=ENCODING)

    if not args.ci or not os.path.exists('out\\\\Default\\\\gn.exe'):
        _run_build_process(
            sys.executable, 'tools\\\\gn\\\\bootstrap\\\\bootstrap.py', '-o', 'out\\\\Default\\\\gn.exe',
            '--skip-generate-buildfiles')
        _run_build_process('out\\\\Default\\\\gn.exe', 'gen', 'out\\\\Default', '--fail-on-unused-args')
    _run_build_process(sys.executable, 'tools\\\\rust\\\\build_bindgen.py', '--skip-test')
    _run_build_process(*ninja_commandline)
"""


@pytest.fixture
def ung(tmp_path):
    (tmp_path / "ungoogled-chromium").mkdir()
    (tmp_path / "ungoogled-chromium" / "flags.gn").write_text(
        "is_official_build=true\n"
    )
    (tmp_path / "flags.windows.gn").write_text('target_cpu="x64"\n')
    site = tmp_path / "site" / "clang"
    spec = types.SimpleNamespace(submodule_search_locations=[str(site)])
    return tmp_path, (lambda name: spec if name == "clang" else None)


def test_args_gn_is_what_build_py_writes(ung):
    root, find_spec = ung
    out = bump.args_gn_from_build_py(BUILD_PY, root, False, find_spec)
    lib = (
        root / "build/src/third_party/llvm-build/Release+Asserts/bin/libclang.dll"
    ).resolve()
    assert out == (
        "is_official_build=true\n\n"
        'target_cpu="x64"\n\n'
        f'v8_metagen_libclang_so="{lib.as_posix()}"\n'
        f'v8_metagen_libclang_bindings_dir="{(root / "site").resolve().as_posix()}"\n'
    )
    assert "chrome_pgo_phase=0" in bump.args_gn_from_build_py(
        BUILD_PY, root, True, find_spec
    )


def test_args_gn_stops_where_build_py_would_exit(ung):
    root, _ = ung
    with pytest.raises(bump.NeedsHuman, match="pip install clang"):
        bump.args_gn_from_build_py(BUILD_PY, root, False, lambda _n: None)


def test_args_gn_stops_on_a_line_it_does_not_know(ung):
    root, find_spec = ung
    changed = BUILD_PY.replace(
        "gn_flags += windows_flags", "gn_flags += windows_flags + os.environ['EXTRA']"
    )
    with pytest.raises(bump.NeedsHuman, match="new to bump.py"):
        bump.args_gn_from_build_py(changed, root, False, find_spec)


def test_args_gn_refuses_to_read_outside_the_tree(ung, tmp_path_factory):
    root, find_spec = ung
    other = tmp_path_factory.mktemp("elsewhere") / "flags.gn"
    other.write_text("x=1\n")
    changed = BUILD_PY.replace(
        "(_ROOT_DIR / 'ungoogled-chromium' / 'flags.gn')", f"Path({str(other)!r})"
    )
    with pytest.raises(bump.NeedsHuman, match="outside"):
        bump.args_gn_from_build_py(changed, root, False, find_spec)


def with_line(line):
    """BUILD_PY with one more statement in the args.gn block."""
    marker = "        clang_spec = importlib.util.find_spec('clang')\n"
    assert marker in BUILD_PY
    return BUILD_PY.replace(marker, f"        {line}\n" + marker)


@pytest.mark.parametrize(
    "line",
    [
        "(_ROOT_DIR / 'victim.txt').replace(Path(str(_ROOT_DIR / 'moved.txt')))",
        "(_ROOT_DIR / 'victim.txt').rename(_ROOT_DIR / 'moved.txt')",
        "(_ROOT_DIR / 'victim.txt').unlink()",
        "(_ROOT_DIR / 'victim.txt').write_text('x')",
        "(_ROOT_DIR / 'victim.txt').write_bytes(b'x')",
        "(_ROOT_DIR / 'new.txt').touch()",
        "(_ROOT_DIR / 'victim.txt').chmod(0)",
        "(_ROOT_DIR / 'victim.txt').symlink_to(_ROOT_DIR / 'moved.txt')",
        "(_ROOT_DIR / 'newdir').rmdir()",
        "x = (_ROOT_DIR / 'newdir').mkdir()",
        "x = (_ROOT_DIR / 'victim.txt').open('w')",
        "x = open(str(_ROOT_DIR / 'moved.txt'), 'w')",
        "Path.replace(_ROOT_DIR / 'victim.txt', _ROOT_DIR / 'moved.txt')",
    ],
)
def test_args_gn_never_writes_or_moves_a_file(ung, line):
    root, find_spec = ung
    (root / "victim.txt").write_text("keep", encoding="utf-8")
    before = sorted(p.name for p in root.iterdir())
    with pytest.raises(bump.NeedsHuman, match="build.py line"):
        bump.args_gn_from_build_py(with_line(line), root, False, find_spec)
    assert sorted(p.name for p in root.iterdir()) == before
    assert (root / "victim.txt").read_text(encoding="utf-8") == "keep"


def test_args_gn_names_the_write_in_its_stop(ung):
    root, find_spec = ung
    line = "(_ROOT_DIR / 'victim.txt').replace(_ROOT_DIR / 'moved.txt')"
    with pytest.raises(bump.NeedsHuman, match=r"writes, moves or runs.*replace"):
        bump.args_gn_from_build_py(with_line(line), root, False, find_spec)


def test_args_gn_still_allows_replace_on_a_string(ung):
    root, find_spec = ung
    line = "gn_flags = gn_flags.replace('official', 'official')"
    out = bump.args_gn_from_build_py(with_line(line), root, False, find_spec)
    assert out.startswith("is_official_build=true\n")


def test_args_gn_mkdir_statement_creates_nothing(ung):
    root, find_spec = ung
    out = bump.args_gn_from_build_py(BUILD_PY, root, False, find_spec)
    assert out
    assert not (root / "build").exists()  # build.py's own mkdir line was skipped


def test_args_gn_write_text_to_another_file_is_not_args_gn(ung):
    root, find_spec = ung
    other = "(_ROOT_DIR / 'other.txt').write_text(gn_flags, encoding=ENCODING)"
    with pytest.raises(bump.NeedsHuman, match="build.py line"):
        bump.args_gn_from_build_py(with_line(other), root, False, find_spec)
    assert not (root / "other.txt").exists()


@pytest.mark.parametrize(
    "name", ["smoke_all.x", "antigravity.x", "clang.cindex", "os", "", "..", "clang "]
)
def test_args_gn_looks_up_only_plain_allowed_modules(ung, name):
    root, _ = ung
    asked = []

    def spy(n):
        asked.append(n)
        return types.SimpleNamespace(submodule_search_locations=[str(root / "site" / "clang")])

    changed = BUILD_PY.replace("find_spec('clang')", f"find_spec({name!r})")
    with pytest.raises(bump.NeedsHuman, match="looks up module"):
        bump.args_gn_from_build_py(changed, root, False, spy)
    assert asked == []


def test_args_gn_has_no_way_to_reach_dunders(ung):
    root, find_spec = ung
    with pytest.raises(bump.NeedsHuman, match="build.py line"):
        bump.args_gn_from_build_py(
            with_line("x = args.__class__"), root, False, find_spec
        )


PREV_ARGS = (
    "chrome_pgo_phase=2\nis_official_build=true\nchrome_pgo_phase=0\n"
    'v8_metagen_libclang_so="E:/ung-157/x/libclang.dll"\n'
)


def test_args_diff_ignores_only_the_machine_paths():
    new = (
        "is_official_build=true\nchrome_pgo_phase=0\n"
        'v8_metagen_libclang_so="E:/ung-160/y/libclang.dll"\n'
        "v8_metagen_libclang_bindings_dir=\"C:/site\"\n"
    )
    assert bump.args_gn_diff(PREV_ARGS, new) == []
    flipped = new.replace("is_official_build=true", "is_official_build=false")
    flipped += "dcheck_always_on=true\n"
    assert bump.args_gn_diff(PREV_ARGS, flipped) == [
        "ADDED   dcheck_always_on=true",
        "CHANGED is_official_build: true -> false",
    ]
    removed = "chrome_pgo_phase=0\n"
    assert bump.args_gn_diff(PREV_ARGS, removed) == ["REMOVED is_official_build=true"]


@pytest.fixture
def args_bump(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", "")
    root, prev = tmp_path / "ung-160", tmp_path / "ung-157"
    (root / "build" / "src").mkdir(parents=True)
    (root / "boring-bump").mkdir()
    (root / "build.py").write_text(BUILD_PY, encoding="utf-8")
    (prev / "build" / "src" / "out" / "Default").mkdir(parents=True)
    state = {"major": 160, "prev": str(prev), "source": "tarball"}
    ns = types.SimpleNamespace(accept_args=False)
    monkeypatch.setattr(
        bump, "args_gn_from_build_py", lambda *a, **k: "is_official_build=false\n"
    )
    return bump.Bump(root, state, ns), prev, root, ns


def test_do_args_stops_for_a_changed_key_and_writes_nothing(args_bump, capsys):
    b, prev, root, _ns = args_bump
    (prev / "build/src/out/Default/args.gn").write_text(PREV_ARGS, encoding="utf-8")
    with pytest.raises(bump.NeedsHuman, match="--accept-args"):
        b.do_args()
    assert "CHANGED is_official_build: true -> false" in capsys.readouterr().out
    assert not (root / "build/src/out/Default/args.gn").exists()
    assert "CHANGED is_official_build" in (root / "boring-bump/args-diff.txt").read_text()


def test_do_args_goes_on_when_accepted_or_unchanged(args_bump):
    b, prev, root, ns = args_bump
    (prev / "build/src/out/Default/args.gn").write_text(PREV_ARGS, encoding="utf-8")
    ns.accept_args = True
    b.do_args()
    assert (root / "build/src/out/Default/args.gn").read_text() == (
        "is_official_build=false\n"
    )
    ns.accept_args = False
    (prev / "build/src/out/Default/args.gn").write_text(
        "is_official_build=false\n", encoding="utf-8"
    )
    b.do_args()  # nothing differs


def test_do_args_stops_when_there_is_no_previous_args_to_compare(args_bump):
    b, _prev, root, _ns = args_bump
    with pytest.raises(bump.NeedsHuman, match="no args.gn in the previous tree"):
        b.do_args()
    assert not (root / "build/src/out/Default/args.gn").exists()


SHA_A, SHA_B = "a" * 40, "b" * 40


def test_tag_pin_checks_the_clone_and_github():
    bump.check_tag_pin("t", SHA_A, SHA_A, SHA_A)
    with pytest.raises(bump.NeedsHuman, match="source changed under us"):
        bump.check_tag_pin("t", SHA_A, SHA_B, SHA_A)
    with pytest.raises(bump.NeedsHuman, match="moved tag t"):
        bump.check_tag_pin("t", SHA_A, SHA_A, SHA_B)
    with pytest.raises(bump.NeedsHuman, match="could not ask GitHub"):
        bump.check_tag_pin("t", SHA_A, SHA_A, None)


@pytest.fixture
def record_bump(tmp_path, monkeypatch):
    import stage_upstream

    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", "")
    core = tmp_path / "core"
    core.mkdir()
    (core / "UPSTREAM_VERSION").write_text(
        "# comment\n157.0.8103.38-1.1\n# commit " + SHA_B + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(bump, "CORE", core)
    monkeypatch.setattr(bump, "REPO", tmp_path)  # git grep finds nothing here
    root = tmp_path / "ung-160"
    root.mkdir()
    state = {
        "major": 160,
        "prev": str(tmp_path / "ung-157"),
        "source": "tarball",
        "tag": "160.0.1.2-1.1",
        "tag_sha": SHA_A,
    }
    heads = {"local": SHA_A, "remote": SHA_A}
    monkeypatch.setattr(stage_upstream, "head_sha", lambda _r: heads["local"])
    monkeypatch.setattr(stage_upstream, "remote_tag_sha", lambda _t: heads["remote"])
    b = bump.Bump(root, state, types.SimpleNamespace())
    return b, core / "UPSTREAM_VERSION", heads


def test_record_writes_the_tag_and_its_commit(record_bump):
    import upstream_watch

    b, path, _heads = record_bump
    b.do_record()
    assert path.read_text(encoding="utf-8") == (
        f"# comment\n160.0.1.2-1.1\n# commit {SHA_A}\n"
    )
    assert upstream_watch.read_current(path) == "160.0.1.2-1.1"


def test_record_refuses_a_tag_that_moved_and_writes_nothing(record_bump):
    b, path, heads = record_bump
    before = path.read_text(encoding="utf-8")
    heads["remote"] = SHA_B
    with pytest.raises(bump.NeedsHuman, match="moved tag"):
        b.do_record()
    heads["remote"], heads["local"] = SHA_A, SHA_B
    with pytest.raises(bump.NeedsHuman, match="changed under us"):
        b.do_record()
    assert path.read_text(encoding="utf-8") == before


def test_build_steps_know_build_pys_calls_and_flag_new_ones():
    kinds = [k for k, _ in bump.build_steps(BUILD_PY)]
    assert kinds == ["bootstrap", "gen", "bindgen", "ninja"]
    extra = (
        BUILD_PY + "\n    _run_build_process(sys.executable, 'tools\\\\new_step.py')\n"
    )
    assert [k for k, _ in bump.build_steps(extra)][-1] is None


REAL_BUILD_PY = Path(r"E:\ung-157\build.py")


@pytest.mark.skipif(not REAL_BUILD_PY.exists(), reason="no 157 tree on this machine")
def test_real_157_build_py_is_understood():
    """Reads only: the 157 tag's build.py, flags.gn and flags.windows.gn."""
    text = REAL_BUILD_PY.read_text(encoding="utf-8")
    assert all(k is not None for k, _ in bump.build_steps(text))
    assert {"bootstrap", "gen", "bindgen", "crubit", "ninja"} <= {
        k for k, _ in bump.build_steps(text)
    }
    spec = types.SimpleNamespace(submodule_search_locations=[r"C:\site\clang"])
    out = bump.args_gn_from_build_py(text, REAL_BUILD_PY.parent, False, lambda _n: spec)
    assert 'v8_metagen_libclang_bindings_dir="C:/site"' in out
    flags = (REAL_BUILD_PY.parent / "ungoogled-chromium" / "flags.gn").read_text(
        encoding="utf-8"
    )
    assert out.startswith(flags + "\n")


# ------------------------------------------------------------ compile log

LOG = """START Mon 11/09/2026 22:15:20
[1/100] CXX obj/base/a.obj
FAILED: obj/old.obj
DONE RC=1
START Tue 11/10/2026  8:33:46
[5/90] CXX obj/base/b.obj
[6/90] CXX obj/components/boring/lists/list_updater.obj
FAILED: obj/components/boring/lists/list_updater.obj
../../components/boring/lists/list_updater.cc(32,10): fatal error: 'crypto/signature_verifier.h' file not found
FAILED: obj/v8/x.obj
"""


def test_compile_status_reads_only_the_last_run():
    status, progress, failures = bump.compile_status(LOG + "DONE RC=1\n")
    assert status == "failed"
    assert progress == "6/90"
    assert "FAILED: obj/old.obj" not in failures
    assert len(failures) == 3
    assert bump.compile_status(LOG)[0] == "running"
    assert bump.compile_status("START x\n[9/9] LINK chrome.exe\nDONE RC=0\n")[0] == "ok"


def test_failures_in_our_code_are_told_apart():
    _, _, failures = bump.compile_status(LOG + "DONE RC=1\n")
    mine = bump.ours(failures, {"chrome/browser/chrome_content_browser_client.cc"})
    assert len(mine) == 2
    assert all("components/boring" in m for m in mine)
    assert bump.ours(["FAILED: obj/v8/x.obj"], {"x/y.cc"}) == []


# ---------------------------------------------------------- placement


def test_enclosing_function_skips_labels_and_includes():
    lines = ["void Foo() {", "  int a;", " public:", "#include <x>", "  Bar();", "}"]
    assert bump.enclosing(lines, 4) == "void Foo() {"
    assert bump.find_run(lines, ["  Bar();"]) == 4
    assert bump.find_run(lines, ["  Nope();"]) == -1


def test_scratch_dirs_are_only_ever_inside_the_state_dir(tmp_path):
    with pytest.raises(RuntimeError):
        bump.fresh_dir(tmp_path / "build" / "src")
    made = bump.fresh_dir(tmp_path / bump.STATE_DIR / "scan")
    assert made.is_dir()
