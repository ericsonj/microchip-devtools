"""Tests for mplab/sync_mplab.py."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from microchip_devtools.mplab.sync_mplab import (
    FolderNode,
    _serialize_element,
    build_source_tree,
    parse_srcs_mk,
    to_mplab_rel,
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
    csrc, incs = parse_srcs_mk(path)
    assert csrc == ["firmware/src/config/default/bsp/bsp.c", "firmware/src/app/app.c"]
    assert incs == ["firmware/src/config/default", "firmware/src/app"]


def test_parse_srcs_mk_strips_trailing_slash(tmp_path):
    path = tmp_path / "srcs.mk"
    path.write_text("INCS += -Isrc/inc/\n", encoding="utf-8")
    _, incs = parse_srcs_mk(path)
    assert incs == ["src/inc"]


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
    csrc, _ = parse_srcs_mk(path)
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

def test_main_silent_on_success(tmp_path, monkeypatch, capsys):
    _make_workspace(tmp_path, "PRG-TEST")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOLTU_PROJECT_NAME", "PRG-TEST")
    main()
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ""


def test_main_deletes_makefile_default(tmp_path, monkeypatch):
    paths = _make_workspace(tmp_path, "PRG-TEST")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOLTU_PROJECT_NAME", "PRG-TEST")
    assert paths["makefile"].exists()
    main()
    assert not paths["makefile"].exists()


def test_main_updates_xml(tmp_path, monkeypatch):
    _make_workspace(tmp_path, "PRG-TEST")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOLTU_PROJECT_NAME", "PRG-TEST")
    main()

    xml_path = tmp_path / "firmware" / "PRG-TEST.X" / "nbproject" / "configurations.xml"
    root = ET.parse(xml_path).getroot()
    items = [el.text for el in root.findall(".//itemPath")]
    assert any("app.c" in (i or "") for i in items)


def test_main_missing_configurations_xml_exits(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOLTU_PROJECT_NAME", "PRG-TEST")
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "ERROR" in capsys.readouterr().err


def test_main_missing_srcs_mk_exits(tmp_path, monkeypatch, capsys):
    paths = _make_workspace(tmp_path, "PRG-TEST")
    paths["srcs_mk"].unlink()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOLTU_PROJECT_NAME", "PRG-TEST")
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "ERROR" in capsys.readouterr().err


def test_main_no_makefile_default_ok(tmp_path, monkeypatch):
    paths = _make_workspace(tmp_path, "PRG-TEST")
    paths["makefile"].unlink()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOLTU_PROJECT_NAME", "PRG-TEST")
    main()  # must not raise
