from importlib.metadata import distribution

from microchip_devtools.list_cmds import COMMANDS


def _get_scripts() -> list[str]:
    dist = distribution("microchip-devtools")
    return [ep.name for ep in dist.entry_points if ep.group == "console_scripts"]


def test_all_scripts_listed_in_commands():
    scripts = set(_get_scripts())
    defined = {cmd for cmd, _ in COMMANDS}
    missing = scripts - defined
    assert (
        not missing
    ), f"Scripts defined in pyproject.toml but missing from COMMANDS: {missing}"


def test_commands_have_nonempty_entries():
    for cmd, desc in COMMANDS:
        assert cmd.strip(), "COMMANDS has entry with empty command name"
        assert desc.strip(), f"Command '{cmd}' has empty description"


def test_commands_have_the_same_number_of_entries():
    num_cmds = len(COMMANDS)
    assert num_cmds > 0, "COMMANDS is empty"
