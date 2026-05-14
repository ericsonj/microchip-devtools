"""Tests for microchip_devtools.setup_env._ui."""

from unittest.mock import patch

from microchip_devtools.setup_env._ui import offer_save_to_env, prompt_path


# ---------------------------------------------------------------------------
# prompt_path
# ---------------------------------------------------------------------------

def test_prompt_path_non_interactive():
    with patch("microchip_devtools.setup_env._ui._is_interactive", return_value=False):
        assert prompt_path("XC32 bin dir", "XC32_PATH") is None


def test_prompt_path_interactive_returns_stripped_path():
    with patch("microchip_devtools.setup_env._ui._is_interactive", return_value=True), \
         patch("rich.prompt.Prompt.ask", return_value="  /opt/xc32/bin  "):
        assert prompt_path("XC32 bin dir", "XC32_PATH") == "/opt/xc32/bin"


def test_prompt_path_interactive_empty_returns_none():
    with patch("microchip_devtools.setup_env._ui._is_interactive", return_value=True), \
         patch("rich.prompt.Prompt.ask", return_value=""):
        assert prompt_path("XC32 bin dir", "XC32_PATH") is None


def test_prompt_path_interactive_whitespace_only_returns_none():
    with patch("microchip_devtools.setup_env._ui._is_interactive", return_value=True), \
         patch("rich.prompt.Prompt.ask", return_value="   "):
        assert prompt_path("XC32 bin dir", "XC32_PATH") is None


def test_prompt_path_eoferror_returns_none():
    with patch("microchip_devtools.setup_env._ui._is_interactive", return_value=True), \
         patch("rich.prompt.Prompt.ask", side_effect=EOFError):
        assert prompt_path("XC32 bin dir", "XC32_PATH") is None


def test_prompt_path_keyboard_interrupt_returns_none():
    with patch("microchip_devtools.setup_env._ui._is_interactive", return_value=True), \
         patch("rich.prompt.Prompt.ask", side_effect=KeyboardInterrupt):
        assert prompt_path("XC32 bin dir", "XC32_PATH") is None


# ---------------------------------------------------------------------------
# offer_save_to_env
# ---------------------------------------------------------------------------

def test_offer_save_non_interactive_no_file_written(tmp_path):
    env_file = tmp_path / ".env"
    with patch("microchip_devtools.setup_env._ui._is_interactive", return_value=False):
        offer_save_to_env("XC32_PATH", "/opt/xc32/bin", env_file)
    assert not env_file.exists()


def test_offer_save_confirm_false_no_file_written(tmp_path):
    env_file = tmp_path / ".env"
    with patch("microchip_devtools.setup_env._ui._is_interactive", return_value=True), \
         patch("rich.prompt.Confirm.ask", return_value=False):
        offer_save_to_env("XC32_PATH", "/opt/xc32/bin", env_file)
    assert not env_file.exists()


def test_offer_save_confirm_true_writes_key_value(tmp_path):
    env_file = tmp_path / ".env"
    with patch("microchip_devtools.setup_env._ui._is_interactive", return_value=True), \
         patch("rich.prompt.Confirm.ask", return_value=True):
        offer_save_to_env("XC32_PATH", "/opt/xc32/bin", env_file)
    assert "XC32_PATH=/opt/xc32/bin" in env_file.read_text()


def test_offer_save_appends_to_existing_content(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING=value\n")
    with patch("microchip_devtools.setup_env._ui._is_interactive", return_value=True), \
         patch("rich.prompt.Confirm.ask", return_value=True):
        offer_save_to_env("DFP_PATH", "/opt/dfp", env_file)
    content = env_file.read_text()
    assert "EXISTING=value" in content
    assert "DFP_PATH=/opt/dfp" in content


def test_offer_save_eoferror_no_file_written(tmp_path):
    env_file = tmp_path / ".env"
    with patch("microchip_devtools.setup_env._ui._is_interactive", return_value=True), \
         patch("rich.prompt.Confirm.ask", side_effect=EOFError):
        offer_save_to_env("XC32_PATH", "/opt/xc32/bin", env_file)
    assert not env_file.exists()
