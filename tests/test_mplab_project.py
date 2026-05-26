from pathlib import Path

import pytest

from microchip_devtools.mplab.project import MPLABProject


class _Project(MPLABProject):
    processor = "32MK1024MCF064"
    linker_script = "firmware/app.ld"
    xc32_path = "/opt/microchip/xc32/v4.60/bin/"
    dfp_path = "/opt/microchip/dfp/1.12"
    target_elf = "build/firmware.elf"
    target_hex = "build/firmware.hex"
    target_bin = "build/firmware.bin"
    target_map = "build/firmware.map"
    target_memory_summary = "build/firmware.memsummary"


@pytest.fixture
def proj() -> _Project:
    return _Project()


# ── getCompilerSet ────────────────────────────────────────────────────────────

def test_compiler_set_uses_xc32_path(proj):
    result = proj.getCompilerSet()
    assert result["CC"] == "/opt/microchip/xc32/v4.60/bin/xc32-gcc"
    assert result["LD"] == "/opt/microchip/xc32/v4.60/bin/xc32-gcc"
    assert result["OBJCOPY"] == "/opt/microchip/xc32/v4.60/bin/xc32-objcopy"


def test_compiler_set_has_required_keys(proj):
    result = proj.getCompilerSet()
    for key in ("CC", "CXX", "LD", "AR", "AS", "OBJCOPY", "SIZE", "INCLUDES"):
        assert key in result, f"Missing key: {key}"
    assert isinstance(result["INCLUDES"], list)


def test_compiler_set_subclass_override():
    class _Custom(MPLABProject):
        xc32_path = "/custom/xc32/bin/"

    result = _Custom().getCompilerSet()
    assert result["CC"] == "/custom/xc32/bin/xc32-gcc"


# ── getCompilerOpts ───────────────────────────────────────────────────────────

def test_compiler_opts_processor_flag(proj):
    result = proj.getCompilerOpts()
    assert "-mprocessor=32MK1024MCF064" in result["MACHINE-OPTS"]


def test_compiler_opts_dfp_path(proj):
    result = proj.getCompilerOpts()
    assert "-mdfp=/opt/microchip/dfp/1.12" in result["MACHINE-OPTS"]


def test_compiler_opts_has_required_keys(proj):
    result = proj.getCompilerOpts()
    for key in ("MACHINE-OPTS", "OPTIMIZE-OPTS", "PREPROCESSOR-OPTS", "CONTROL-C-OPTS"):
        assert key in result, f"Missing key: {key}"


# ── getLinkerOpts ─────────────────────────────────────────────────────────────

def test_linker_opts_linker_script(proj):
    result = proj.getLinkerOpts()
    assert "-Tfirmware/app.ld" in result["LINKER-SCRIPT"]


def test_linker_opts_map_file(proj):
    result = proj.getLinkerOpts()
    assert any("build/firmware.map" in flag for flag in result["LINKER-OPTS"])


def test_linker_opts_memory_summary(proj):
    result = proj.getLinkerOpts()
    assert any("build/firmware.memsummary" in flag for flag in result["LINKER-OPTS"])


def test_linker_opts_gc_sections(proj):
    result = proj.getLinkerOpts()
    assert "-Wl,--gc-sections" in result["LINKER-OPTS"]


# ── mplab_walk ────────────────────────────────────────────────────────────────

def test_mplab_walk_dirs_before_files(proj):
    paths = [
        Path("a/b/file.c"),
        Path("a/file.c"),
        Path("a/b/c/file.c"),
    ]
    result = proj.mplab_walk(paths, set())
    result_strs = [str(p) for p in result]
    assert result_strs.index("a/b/c/file.c") < result_strs.index("a/file.c")
    assert result_strs.index("a/b/file.c") < result_strs.index("a/file.c")


def test_mplab_walk_case_insensitive_sort(proj):
    paths = [Path("src/Zoo.c"), Path("src/apple.c"), Path("src/Banana.c")]
    result = proj.mplab_walk(paths, set())
    names = [p.name for p in result]
    assert names == ["apple.c", "Banana.c", "Zoo.c"]


def test_mplab_walk_excluded_dropped(proj, tmp_path):
    f1 = tmp_path / "keep.c"
    f2 = tmp_path / "drop.c"
    f1.touch()
    f2.touch()
    result = proj.mplab_walk([f1, f2], excluded={f2.resolve()})
    assert f1 in result
    assert f2 not in result


def test_mplab_walk_empty_input(proj):
    assert proj.mplab_walk([], set()) == []


def test_mplab_walk_flat_files_no_dirs(proj):
    paths = [Path("c.c"), Path("a.c"), Path("b.c")]
    result = proj.mplab_walk(paths, set())
    assert [p.name for p in result] == ["a.c", "b.c", "c.c"]


def test_mplab_walk_sibling_dirs_sorted(proj):
    # src/z/ and src/a/ are siblings — a/ must come before z/
    paths = [Path("src/z/file.c"), Path("src/a/file.c")]
    result = proj.mplab_walk(paths, set())
    result_strs = [str(p) for p in result]
    assert result_strs.index("src/a/file.c") < result_strs.index("src/z/file.c")


def test_mplab_walk_depth_first_not_breadth_first(proj):
    # depth-first: src/a/b/deep.c comes before src/b/shallow.c
    paths = [Path("src/b/shallow.c"), Path("src/a/b/deep.c")]
    result = proj.mplab_walk(paths, set())
    result_strs = [str(p) for p in result]
    assert result_strs.index("src/a/b/deep.c") < result_strs.index("src/b/shallow.c")


def test_mplab_walk_multiple_files_same_dir(proj):
    paths = [Path("src/c.c"), Path("src/a.c"), Path("src/b.c")]
    result = proj.mplab_walk(paths, set())
    assert [p.name for p in result] == ["a.c", "b.c", "c.c"]


def test_mplab_walk_excluded_all_returns_empty(proj, tmp_path):
    f1 = tmp_path / "a.c"
    f2 = tmp_path / "b.c"
    f1.touch()
    f2.touch()
    result = proj.mplab_walk([f1, f2], excluded={f1.resolve(), f2.resolve()})
    assert result == []


def test_mplab_walk_preserves_path_objects(proj):
    paths = [Path("src/a.c"), Path("src/b.c")]
    result = proj.mplab_walk(paths, set())
    assert all(isinstance(p, Path) for p in result)


def test_sort_sources_delegates_to_mplab_walk(proj):
    paths = [Path("src/b.c"), Path("src/a/z.c"), Path("src/a.c")]
    result = proj.sort_sources(paths)
    result_strs = [str(p) for p in result]
    assert result_strs.index("src/a/z.c") < result_strs.index("src/a.c")
    assert result_strs.index("src/a/z.c") < result_strs.index("src/b.c")


def test_sort_modules_same_as_sort_sources(proj):
    paths = [Path("b_mk.py"), Path("a/z_mk.py"), Path("a_mk.py")]
    assert proj.sort_modules(paths) == proj.sort_sources(paths)
