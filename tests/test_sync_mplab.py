"""Tests for mplab/sync_mplab.py."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from microchip_devtools.mplab.sync_mplab import (
    FolderNode,
    _serialize_element,
    build_source_tree,
    build_tree,
    discover_headers,
    existing_item_paths,
    parse_srcs_mk,
    to_mplab_rel,
    update_header_files,
    update_include_dirs,
    update_source_files,
    write_xml,
    main,
)

# ---------------------------------------------------------------------------
# Minimal configurations.xml fixture
# ---------------------------------------------------------------------------
_CONFIGURATIONS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<configurationDescriptor>
  <logicalFolder name="root" displayName="root" projectFiles="false">
    <logicalFolder name="HeaderFiles" displayName="Header Files" projectFiles="true"/>
    <logicalFolder name="SourceFiles" displayName="Source Files" projectFiles="true"/>
  </logicalFolder>
  <confs>
    <conf name="default">
      <toolsSet>
        <languageToolchain>XC32</languageToolchain>
      </toolsSet>
      <compile>
        <C32>
          <property key="extra-include-directories" value=""/>
        </C32>
        <C32CPP>
          <property key="extra-include-directories" value=""/>
        </C32CPP>
      </compile>
    </conf>
    <conf name="bootloaderApplication">
      <C32/>
      <C32CPP/>
    </conf>
  </confs>
</configurationDescriptor>
"""

_SRCS_MK = """\
CSRC += firmware/src/config/default/bsp/bsp.c
CSRC += firmware/src/app/app.c
INCS += -Ifirmware/src/config/default
INCS += -Ifirmware/src/app
"""


def _make_workspace(tmp_path: Path, project_name: str = "PRG-TEST") -> dict:
    """Create a minimal workspace under tmp_path. Returns relevant paths."""
    mplab_dir = tmp_path / "firmware" / f"{project_name}.X"
    nbproject = mplab_dir / "nbproject"
    nbproject.mkdir(parents=True)

    xml_path = nbproject / "configurations.xml"
    xml_path.write_text(_CONFIGURATIONS_XML, encoding="utf-8")

    makefile = nbproject / "Makefile-default.mk"
    makefile.write_text("# generated\n", encoding="utf-8")

    srcs_mk_path = tmp_path / "pymake" / "srcs.mk"
    srcs_mk_path.parent.mkdir(parents=True)
    srcs_mk_path.write_text(_SRCS_MK, encoding="utf-8")

    return {
        "mplab_dir": mplab_dir,
        "xml": xml_path,
        "makefile": makefile,
        "srcs_mk": srcs_mk_path,
    }


# ---------------------------------------------------------------------------
# parse_srcs_mk
# ---------------------------------------------------------------------------

def test_parse_srcs_mk_returns_sources_and_incs(tmp_path):
    path = tmp_path / "srcs.mk"
    path.write_text(_SRCS_MK, encoding="utf-8")
    csrc, incs, skip = parse_srcs_mk(path)
    assert csrc == ["firmware/src/config/default/bsp/bsp.c", "firmware/src/app/app.c"]
    assert incs == ["firmware/src/config/default", "firmware/src/app"]
    assert skip == []


def test_parse_srcs_mk_strips_trailing_slash(tmp_path):
    path = tmp_path / "srcs.mk"
    path.write_text("INCS += -Isrc/inc/\n", encoding="utf-8")
    _, incs, _ = parse_srcs_mk(path)
    assert incs == ["src/inc"]


def test_parse_srcs_mk_parses_skip_patterns(tmp_path):
    path = tmp_path / "srcs.mk"
    path.write_text(
        "CSRC += firmware/src/app/app.c\n"
        "SKIP_PATTERNS += firmware/IDU_Firmware/test\n"
        "SKIP_PATTERNS += firmware/IDU_Firmware/.template\n",
        encoding="utf-8",
    )
    _, _, skip = parse_srcs_mk(path)
    assert skip == [
        "firmware/IDU_Firmware/test",
        "firmware/IDU_Firmware/.template",
    ]


_ASM_PATH = (
    "firmware/src/third_party/rtos/FreeRTOS"
    "/Source/portable/MPLAB/PIC32MK/port_asm.S"
)


def test_parse_srcs_mk_includes_asrc(tmp_path):
    path = tmp_path / "srcs.mk"
    path.write_text(
        "CSRC += firmware/src/app/app.c\n"
        f"ASSRC += {_ASM_PATH}\n",
        encoding="utf-8",
    )
    csrc, _, _ = parse_srcs_mk(path)
    assert "firmware/src/app/app.c" in csrc
    assert _ASM_PATH in csrc


def test_parse_srcs_mk_missing_file_exits(tmp_path):
    with pytest.raises(SystemExit) as exc:
        parse_srcs_mk(tmp_path / "missing.mk")
    assert exc.value.code == 1


def test_parse_srcs_mk_missing_file_prints_error(tmp_path, capsys):
    with pytest.raises(SystemExit):
        parse_srcs_mk(tmp_path / "missing.mk")
    assert "ERROR" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# to_mplab_rel
# ---------------------------------------------------------------------------

def test_to_mplab_rel_produces_forward_slashes(tmp_path):
    mplab_dir = tmp_path / "firmware" / "PRG-TEST.X"
    result = to_mplab_rel("src/app/app.c", mplab_dir)
    assert "\\" not in result


def test_to_mplab_rel_goes_up_two_levels(tmp_path):
    mplab_dir = tmp_path / "firmware" / "PRG-TEST.X"
    result = to_mplab_rel("src/app/app.c", mplab_dir)
    assert result.startswith("../../")


# ---------------------------------------------------------------------------
# FolderNode
# ---------------------------------------------------------------------------

def test_folder_node_add_file_flat():
    node = FolderNode("root")
    node.add_file(["app.c"], "../src/app/app.c")
    assert "../src/app/app.c" in node.files
    assert not node.children


def test_folder_node_add_file_nested():
    node = FolderNode("root")
    node.add_file(["config", "default", "bsp.c"], "../src/config/default/bsp.c")
    assert "config" in node.children
    assert "default" in node.children["config"].children
    default_node = node.children["config"].children["default"]
    assert "../src/config/default/bsp.c" in default_node.files


def test_folder_node_to_xml_produces_sorted_children():
    node = FolderNode("SourceFiles")
    node.add_file(["z_module", "z.c"], "z.c")
    node.add_file(["a_module", "a.c"], "a.c")
    parent = ET.Element("root")
    node.to_xml(parent)
    folders = [el.get("name") for el in parent.findall("logicalFolder")]
    assert folders == sorted(folders)


def test_folder_node_to_xml_item_path_text():
    node = FolderNode("SourceFiles")
    node.add_file(["app.c"], "../src/app/app.c")
    parent = ET.Element("root")
    node.to_xml(parent)
    items = [el.text for el in parent.findall("itemPath")]
    assert "../src/app/app.c" in items


# ---------------------------------------------------------------------------
# build_source_tree
# ---------------------------------------------------------------------------

def test_build_source_tree_groups_under_src_prefix(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mplab_dir = tmp_path / "firmware" / "PRG-TEST.X"
    # firmware/src/app/app.c → relpath from .X = ../src/app/app.c
    # strips leading ".." → tree: src > app > app.c
    csrc = ["firmware/src/app/app.c"]
    root = build_source_tree(csrc, mplab_dir)
    assert "src" in root.children
    assert "app" in root.children["src"].children


def test_build_source_tree_arbitrary_prefix_builds_tree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mplab_dir = tmp_path / "firmware" / "PRG-TEST.X"
    # IDU_Firmware/APP/BMS/bms.c → relpath = ../IDU_Firmware/APP/BMS/bms.c
    # strips leading ".." → tree: IDU_Firmware > APP > BMS > bms.c
    csrc = ["firmware/IDU_Firmware/APP/BMS/bms.c"]
    root = build_source_tree(csrc, mplab_dir)
    assert "IDU_Firmware" in root.children
    assert "APP" in root.children["IDU_Firmware"].children


def test_build_source_tree_adjacent_file_goes_flat(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mplab_dir = tmp_path / "firmware" / "PRG-TEST.X"
    # firmware/gen.c → relpath from .X = ../gen.c → strips ".." → ['gen.c'] → flat
    csrc = ["firmware/gen.c"]
    root = build_source_tree(csrc, mplab_dir)
    assert root.files
    assert not root.children


# ---------------------------------------------------------------------------
# update_source_files
# ---------------------------------------------------------------------------

def _parse_xml(text: str) -> ET.Element:
    return ET.fromstring(text)


def test_update_source_files_replaces_children():
    xml_root = _parse_xml(_CONFIGURATIONS_XML)
    source_tree = FolderNode("SourceFiles")
    source_tree.add_file(["app.c"], "../src/app/app.c")
    update_source_files(xml_root, source_tree)

    sf = xml_root.find(".//logicalFolder[@name='SourceFiles']")
    assert any(el.text == "../src/app/app.c" for el in sf.findall("itemPath"))


def test_update_source_files_missing_root_folder_exits():
    xml_root = ET.fromstring("<configurationDescriptor/>")
    with pytest.raises(SystemExit) as exc:
        update_source_files(xml_root, FolderNode("SourceFiles"))
    assert exc.value.code == 1


def test_update_source_files_missing_source_files_exits():
    xml_root = ET.fromstring(
        '<configurationDescriptor>'
        '<logicalFolder name="root"/>'
        '</configurationDescriptor>'
    )
    with pytest.raises(SystemExit) as exc:
        update_source_files(xml_root, FolderNode("SourceFiles"))
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# update_include_dirs
# ---------------------------------------------------------------------------

def test_update_include_dirs_sets_value(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mplab_dir = tmp_path / "firmware" / "PRG-TEST.X"
    xml_root = _parse_xml(_CONFIGURATIONS_XML)
    update_include_dirs(xml_root, ["firmware/src/app"], mplab_dir)

    for tag in ("C32", "C32CPP"):
        for section in xml_root.iter(tag):
            prop = section.find("property[@key='extra-include-directories']")
            assert prop is not None
            assert prop.get("value") != ""


def test_update_include_dirs_deduplicates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mplab_dir = tmp_path / "firmware" / "PRG-TEST.X"
    xml_root = _parse_xml(_CONFIGURATIONS_XML)
    update_include_dirs(xml_root, ["firmware/src/app", "firmware/src/app"], mplab_dir)

    for section in xml_root.iter("C32"):
        prop = section.find("property[@key='extra-include-directories']")
        parts = prop.get("value").split(";")
        assert len(parts) == len(set(parts))


def test_update_include_dirs_all_confs(tmp_path, monkeypatch):
    """All configs updated; missing property created in bootloaderApplication."""
    monkeypatch.chdir(tmp_path)
    mplab_dir = tmp_path / "firmware" / "PRG-TEST.X"
    xml_root = _parse_xml(_CONFIGURATIONS_XML)
    update_include_dirs(xml_root, ["firmware/src/app"], mplab_dir)

    all_c32 = list(xml_root.iter("C32"))
    all_c32cpp = list(xml_root.iter("C32CPP"))
    assert len(all_c32) == 2, "expected one C32 per conf"
    assert len(all_c32cpp) == 2, "expected one C32CPP per conf"

    for section in all_c32 + all_c32cpp:
        prop = section.find("property[@key='extra-include-directories']")
        assert prop is not None, f"property missing in {section.tag}"
        assert prop.get("value") != ""


# ---------------------------------------------------------------------------
# _serialize_element — MPLAB X attribute formatting
# ---------------------------------------------------------------------------

def test_serialize_short_tag_stays_single_line():
    el = ET.fromstring('<logicalFolder name="root" displayName="root" projectFiles="true"/>')
    lines = _serialize_element(el, depth=0)
    assert len(lines) == 1
    assert 'name="root"' in lines[0]
    assert 'displayName="root"' in lines[0]


def test_serialize_long_tag_wraps_attributes():
    # Single-line would be: "    <logicalFolder name="HeaderFilesLongName" displayName="Header Files Long" projectFiles="true"/>"
    # = 4 + 93 = 97 chars → wraps; but serializer returns one string with \n, not multiple list items
    el = ET.fromstring(
        '<logicalFolder name="HeaderFilesLongName" displayName="Header Files Long" projectFiles="true"/>'
    )
    lines = _serialize_element(el, depth=2)  # 4-space base
    assert len(lines) == 1
    text = lines[0]
    assert "\n" in text, "Long tag must wrap to multiple lines (embedded \\n)"
    parts = text.split("\n")
    cont_indent = "    " + " " * len("<logicalFolder ")  # depth=2 → 4 spaces + 15
    for part in parts[1:]:
        assert part.startswith(cont_indent), f"Misaligned continuation: {part!r}"


def test_serialize_continuation_aligns_to_tag_name_length():
    el = ET.fromstring(
        '<logicalFolder name="PRG-IDU-BOOT_pic32mk_mcm_curiosity_pro"'
        ' displayName="PRG-IDU-BOOT_pic32mk_mcm_curiosity_pro" projectFiles="true"/>'
    )
    lines = _serialize_element(el, depth=3)  # 6-space base
    assert len(lines) == 1
    text = lines[0]
    assert "\n" in text
    expected_cont = "      " + " " * len("<logicalFolder ")
    for part in text.split("\n")[1:]:
        assert part.startswith(expected_cont)


def test_serialize_property_long_value_wraps():
    long_value = ";".join(f"../src/path{i}" for i in range(15))
    el = ET.fromstring(f'<property key="extra-include-directories" value="{long_value}"/>')
    lines = _serialize_element(el, depth=4)  # 8-space base
    assert len(lines) == 1
    text = lines[0]
    assert "\n" in text
    cont_indent = "        " + " " * len("<property ")
    parts = text.split("\n")
    assert parts[1].startswith(cont_indent)


def test_serialize_self_closing_empty_element():
    el = ET.fromstring("<targetHeader/>")
    lines = _serialize_element(el, depth=2)
    assert lines == ["    <targetHeader/>"]


def test_serialize_text_element_inline():
    el = ET.fromstring("<itemPath>../src/app/app.c</itemPath>")
    lines = _serialize_element(el, depth=3)
    assert lines == ["      <itemPath>../src/app/app.c</itemPath>"]


def test_serialize_no_partial_wrap():
    # Verify all-or-nothing rule: wrapped tag emits \n-separated parts,
    # first part has no closing >, last part ends with />
    el = ET.fromstring(
        '<logicalFolder name="VeryLongFolderNameThatWillDefinitelyPushPastEightyCharsForSure"'
        ' displayName="Very Long Display Name That Is Also Quite Long" projectFiles="true"/>'
    )
    lines = _serialize_element(el, depth=0)
    assert len(lines) == 1
    text = lines[0]
    assert "\n" in text
    parts = text.split("\n")
    assert parts[-1].endswith("/>")
    for mid in parts[1:-1]:
        assert not mid.endswith(">")
        assert not mid.endswith("/>")


# ---------------------------------------------------------------------------
# write_xml
# ---------------------------------------------------------------------------

def test_write_xml_has_declaration(tmp_path):
    tree = ET.ElementTree(ET.fromstring(_CONFIGURATIONS_XML))
    out = tmp_path / "configurations.xml"
    write_xml(tree, out)
    content = out.read_text(encoding="utf-8")
    assert content.startswith('<?xml version="1.0" encoding="UTF-8"?>')


def test_write_xml_round_trips_source_files(tmp_path):
    xml_root = ET.fromstring(_CONFIGURATIONS_XML)
    sf = xml_root.find(".//logicalFolder[@name='SourceFiles']")
    item = ET.SubElement(sf, "itemPath")
    item.text = "../src/app/app.c"

    tree = ET.ElementTree(xml_root)
    out = tmp_path / "configurations.xml"
    write_xml(tree, out)

    reparsed = ET.parse(out).getroot()
    items = [el.text for el in reparsed.findall(".//itemPath")]
    assert "../src/app/app.c" in items


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------

def test_main_prints_summary_on_success(tmp_path, monkeypatch, capsys):
    _make_workspace_with_headers(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOLTU_PROJECT_NAME", "PRG-TEST")
    monkeypatch.setattr("sys.argv", ["sync-mplab"])
    main()
    out = capsys.readouterr().out
    assert "DRY RUN" not in out
    assert "app.c" in out
    assert "app.h" in out


def test_main_deletes_makefile_default(tmp_path, monkeypatch):
    paths = _make_workspace(tmp_path, "PRG-TEST")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOLTU_PROJECT_NAME", "PRG-TEST")
    monkeypatch.setattr("sys.argv", ["sync-mplab"])
    assert paths["makefile"].exists()
    main()
    assert not paths["makefile"].exists()


def test_main_updates_xml(tmp_path, monkeypatch):
    _make_workspace(tmp_path, "PRG-TEST")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOLTU_PROJECT_NAME", "PRG-TEST")
    monkeypatch.setattr("sys.argv", ["sync-mplab"])
    main()

    xml_path = tmp_path / "firmware" / "PRG-TEST.X" / "nbproject" / "configurations.xml"
    root = ET.parse(xml_path).getroot()
    items = [el.text for el in root.findall(".//itemPath")]
    assert any("app.c" in (i or "") for i in items)


def test_main_missing_configurations_xml_exits(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOLTU_PROJECT_NAME", "PRG-TEST")
    monkeypatch.setattr("sys.argv", ["sync-mplab"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "ERROR" in capsys.readouterr().err


def test_main_missing_srcs_mk_exits(tmp_path, monkeypatch, capsys):
    paths = _make_workspace(tmp_path, "PRG-TEST")
    paths["srcs_mk"].unlink()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOLTU_PROJECT_NAME", "PRG-TEST")
    monkeypatch.setattr("sys.argv", ["sync-mplab"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "ERROR" in capsys.readouterr().err


def test_main_no_makefile_default_ok(tmp_path, monkeypatch):
    paths = _make_workspace(tmp_path, "PRG-TEST")
    paths["makefile"].unlink()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOLTU_PROJECT_NAME", "PRG-TEST")
    monkeypatch.setattr("sys.argv", ["sync-mplab"])
    main()  # must not raise


# ---------------------------------------------------------------------------
# preserve-order (sort=False)
# ---------------------------------------------------------------------------

def test_folder_node_to_xml_preserve_order_files():
    node = FolderNode("SourceFiles")
    node.add_file(["z.c"], "z.c")
    node.add_file(["a.c"], "a.c")
    node.add_file(["m.c"], "m.c")
    parent = ET.Element("root")
    node.to_xml(parent, sort=False)
    items = [el.text for el in parent.findall("itemPath")]
    assert items == ["z.c", "a.c", "m.c"]


def test_folder_node_to_xml_preserve_order_children():
    node = FolderNode("SourceFiles")
    node.add_file(["z_module", "z.c"], "z.c")
    node.add_file(["a_module", "a.c"], "a.c")
    parent = ET.Element("root")
    node.to_xml(parent, sort=False)
    folders = [el.get("name") for el in parent.findall("logicalFolder")]
    assert folders == ["z_module", "a_module"]


def test_folder_node_to_xml_preserve_order_interleaved():
    # file before folder, then another folder, then file — depth-first must match srcs.mk
    node = FolderNode("SourceFiles")
    node.add_file(["app.c"], "../src/app.c")          # flat file first
    node.add_file(["config", "init.c"], "../src/config/init.c")  # enters subfolder
    node.add_file(["main.c"], "../src/main.c")         # flat file last
    parent = ET.Element("root")
    node.to_xml(parent, sort=False)
    # children of parent in emission order: itemPath(app.c), logicalFolder(config), itemPath(main.c)
    tags = [(el.tag, el.text or el.get("name")) for el in parent]
    assert tags == [
        ("itemPath", "../src/app.c"),
        ("logicalFolder", "config"),
        ("itemPath", "../src/main.c"),
    ]


def test_update_include_dirs_preserve_order(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mplab_dir = tmp_path / "firmware" / "PRG-TEST.X"
    xml_root = _parse_xml(_CONFIGURATIONS_XML)
    inc_dirs = ["firmware/src/zzz", "firmware/src/aaa", "firmware/src/mmm"]
    update_include_dirs(xml_root, inc_dirs, mplab_dir, sort=False)

    for section in xml_root.iter("C32"):
        prop = section.find("property[@key='extra-include-directories']")
        parts = prop.get("value").split(";")
        # order must match srcs.mk order, not alphabetical
        assert parts[0].endswith("zzz")
        assert parts[1].endswith("aaa")
        assert parts[2].endswith("mmm")


def test_update_include_dirs_preserve_order_deduplicates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mplab_dir = tmp_path / "firmware" / "PRG-TEST.X"
    xml_root = _parse_xml(_CONFIGURATIONS_XML)
    update_include_dirs(
        xml_root,
        ["firmware/src/zzz", "firmware/src/aaa", "firmware/src/zzz"],
        mplab_dir,
        sort=False,
    )

    for section in xml_root.iter("C32"):
        prop = section.find("property[@key='extra-include-directories']")
        parts = prop.get("value").split(";")
        assert len(parts) == len(set(parts))
        assert parts[0].endswith("zzz")
        assert parts[1].endswith("aaa")


# ---------------------------------------------------------------------------
# discover_headers
# ---------------------------------------------------------------------------

def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("/* header */\n", encoding="utf-8")


def test_discover_headers_finds_recursively(tmp_path):
    _touch(tmp_path / "firmware/src/config/default/bsp/bsp.h")
    _touch(tmp_path / "firmware/src/config/default/driver/templates/usb.h")
    headers = discover_headers(["firmware/src/config/default"], [], tmp_path)
    assert "firmware/src/config/default/bsp/bsp.h" in headers
    assert "firmware/src/config/default/driver/templates/usb.h" in headers


def test_discover_headers_dedups_overlapping_incs(tmp_path):
    # A deep .h reachable from both a deep and a shallow INCS dir → once only.
    _touch(tmp_path / "firmware/src/config/default/driver/usb/plib_usb.h")
    headers = discover_headers(
        [
            "firmware/src/config/default",
            "firmware/src/config/default/driver/usb",
        ],
        [],
        tmp_path,
    )
    assert headers.count("firmware/src/config/default/driver/usb/plib_usb.h") == 1


def test_discover_headers_skips_pattern_dir(tmp_path):
    _touch(tmp_path / "firmware/IDU_Firmware/HAL/hal.h")
    _touch(tmp_path / "firmware/IDU_Firmware/test/test_hal.h")
    headers = discover_headers(
        ["firmware/IDU_Firmware"],
        ["firmware/IDU_Firmware/test"],
        tmp_path,
    )
    assert "firmware/IDU_Firmware/HAL/hal.h" in headers
    assert "firmware/IDU_Firmware/test/test_hal.h" not in headers


def test_discover_headers_skips_pattern_file(tmp_path):
    _touch(tmp_path / "firmware/IDU_Firmware/keep.h")
    _touch(tmp_path / "firmware/IDU_Firmware/generated_skip.h")
    headers = discover_headers(
        ["firmware/IDU_Firmware"],
        ["firmware/IDU_Firmware/*_skip.h"],
        tmp_path,
    )
    assert "firmware/IDU_Firmware/keep.h" in headers
    assert "firmware/IDU_Firmware/generated_skip.h" not in headers


def test_discover_headers_skips_nonexistent_dir(tmp_path):
    # Must not raise even when the INCS dir is absent on disk.
    headers = discover_headers(["firmware/does/not/exist"], [], tmp_path)
    assert headers == []


# ---------------------------------------------------------------------------
# update_header_files
# ---------------------------------------------------------------------------

def test_update_header_files_rebuilds_folder():
    xml_root = _parse_xml(_CONFIGURATIONS_XML)
    header_tree = FolderNode("HeaderFiles")
    header_tree.add_file(["app", "app.h"], "../src/app/app.h")
    update_header_files(xml_root, header_tree)

    hf = xml_root.find(".//logicalFolder[@name='HeaderFiles']")
    assert hf.get("displayName") == "Header Files"
    assert any(el.text == "../src/app/app.h" for el in hf.iter("itemPath"))


def test_existing_item_paths_collects_recursively():
    xml_root = _parse_xml(_CONFIGURATIONS_XML)
    header_tree = FolderNode("HeaderFiles")
    header_tree.add_file(["a", "a.h"], "../src/a/a.h")
    header_tree.add_file(["b.h"], "../src/b.h")
    update_header_files(xml_root, header_tree)

    paths = existing_item_paths(xml_root, "HeaderFiles")
    assert paths == {"../src/a/a.h", "../src/b.h"}


# ---------------------------------------------------------------------------
# main() with headers + --dry-run
# ---------------------------------------------------------------------------

def _make_workspace_with_headers(tmp_path: Path) -> dict:
    """Workspace whose INCS dirs exist on disk and hold .h files (incl. a skipped one)."""
    paths = _make_workspace(tmp_path, "PRG-TEST")
    paths["srcs_mk"].write_text(
        "CSRC += firmware/src/app/app.c\n"
        "INCS += -Ifirmware/src/app\n"
        "SKIP_PATTERNS += firmware/src/app/test\n",
        encoding="utf-8",
    )
    _touch(tmp_path / "firmware/src/app/app.h")
    _touch(tmp_path / "firmware/src/app/sub/util.h")
    _touch(tmp_path / "firmware/src/app/test/test_app.h")
    return paths


def test_main_populates_header_files(tmp_path, monkeypatch):
    paths = _make_workspace_with_headers(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOLTU_PROJECT_NAME", "PRG-TEST")
    monkeypatch.setattr("sys.argv", ["sync-mplab"])
    main()

    root = ET.parse(paths["xml"]).getroot()
    hf = root.find(".//logicalFolder[@name='HeaderFiles']")
    headers = [el.text for el in hf.iter("itemPath")]
    assert any("app.h" in (h or "") for h in headers)
    assert any("util.h" in (h or "") for h in headers)
    # SKIP'd tree excluded
    assert not any("test_app.h" in (h or "") for h in headers)
    # Sources still synced (no regression)
    sf = root.find(".//logicalFolder[@name='SourceFiles']")
    assert any("app.c" in (el.text or "") for el in sf.iter("itemPath"))


def test_main_dry_run_writes_nothing(tmp_path, monkeypatch):
    paths = _make_workspace_with_headers(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOLTU_PROJECT_NAME", "PRG-TEST")
    monkeypatch.setattr("sys.argv", ["sync-mplab", "--dry-run"])

    xml_before = paths["xml"].read_text(encoding="utf-8")
    assert paths["makefile"].exists()
    main()

    assert paths["xml"].read_text(encoding="utf-8") == xml_before
    assert paths["makefile"].exists()  # Makefile NOT deleted in dry-run


def test_main_dry_run_reports_new_headers(tmp_path, monkeypatch, capsys):
    paths = _make_workspace_with_headers(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOLTU_PROJECT_NAME", "PRG-TEST")
    monkeypatch.setattr("sys.argv", ["sync-mplab", "--dry-run"])
    main()

    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "app.h" in out          # a new header is reported
    assert "test_app.h" not in out  # skipped header never appears
