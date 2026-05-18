"""Tests for clock/oscillator configuration validation logic."""

from microchip_devtools.mcc.check_clock import (
    _compute_refclk_freq,
    _parse_mcc_core_yml,
    _parse_pbclk_from_core_yml,
    _parse_pragma_config,
    _parse_refclk_from_core_yml,
    _parse_refclk_from_plib_clk,
    check_clock_rules,
    check_pbclk_rules,
    check_refclk_rules,
)


CORE_YML = """
data:
  symbols:
    CONFIG_POSCMOD:
      attributes:
        id: CONFIG_POSCMOD
      children:
      - children:
        - attributes:
            value: EC
          type: User
        type: Values
      type: Combo
    CONFIG_FPLLICLK:
      attributes:
        id: CONFIG_FPLLICLK
      children:
      - children:
        - attributes:
            value: PLL_FRC
          type: User
        type: Values
      type: Combo
    CONFIG_FPLLMULT:
      attributes:
        id: CONFIG_FPLLMULT
      children:
      - children:
        - attributes:
            value: MUL_60
          type: User
        type: Values
      type: Combo
    CONFIG_UPLLEN:
      attributes:
        id: CONFIG_UPLLEN
      children:
      - children:
        - attributes:
            value: 'ON'
          type: User
        type: Values
      type: Combo
"""

INIT_C_OK = """
/*** DEVCFG1 ***/
#pragma config FNOSC =      SPLL
#pragma config POSCMOD =    EC

/*** DEVCFG2 ***/
#pragma config FPLLICLK =   PLL_FRC
#pragma config FPLLMULT =   MUL_60
#pragma config UPLLEN =     ON
"""

INIT_C_WRONG_MULT = """
#pragma config POSCMOD =    EC
#pragma config FPLLICLK =   PLL_FRC
#pragma config FPLLMULT =   MUL_50
#pragma config UPLLEN =     ON
"""

INIT_C_MISSING_KEY = """
#pragma config POSCMOD =    EC
#pragma config FPLLICLK =   PLL_FRC
#pragma config UPLLEN =     ON
"""


def test_parse_mcc_core_yml_extracts_all_keys():
    result = _parse_mcc_core_yml(CORE_YML)
    assert result["POSCMOD"]  == "EC"
    assert result["FPLLICLK"] == "PLL_FRC"
    assert result["FPLLMULT"] == "MUL_60"
    assert result["UPLLEN"]   == "ON"


def test_parse_mcc_core_yml_ignores_non_config_keys():
    yml = """
data:
  symbols:
    CPU_CLOCK_FREQUENCY: '120000000'
    CONFIG_POSCMOD:
      children:
      - children:
        - attributes:
            value: EC
          type: User
        type: Values
      type: Combo
"""
    result = _parse_mcc_core_yml(yml)
    assert "CPU_CLOCK_FREQUENCY" not in result
    assert result["POSCMOD"] == "EC"


def test_parse_pragma_config_extracts_all():
    result = _parse_pragma_config(INIT_C_OK)
    assert result["POSCMOD"]  == "EC"
    assert result["FPLLICLK"] == "PLL_FRC"
    assert result["FPLLMULT"] == "MUL_60"
    assert result["UPLLEN"]   == "ON"
    assert result["FNOSC"]    == "SPLL"


def test_parse_pragma_config_empty():
    assert _parse_pragma_config("/* no pragmas here */") == {}


def test_check_clock_rules_all_pass():
    mcc    = _parse_mcc_core_yml(CORE_YML)
    pragma = _parse_pragma_config(INIT_C_OK)
    rules  = {"POSCMOD": "EC", "FPLLICLK": "PLL_FRC", "FPLLMULT": "MUL_60",
              "UPLLEN": "ON"}
    assert check_clock_rules(mcc, pragma, rules) == 0


def test_check_clock_rules_detects_wrong_value_in_code():
    mcc    = _parse_mcc_core_yml(CORE_YML)
    pragma = _parse_pragma_config(INIT_C_WRONG_MULT)
    rules  = {"FPLLMULT": "MUL_60"}
    assert check_clock_rules(mcc, pragma, rules) == 1


def test_check_clock_rules_detects_missing_key_in_code():
    mcc    = _parse_mcc_core_yml(CORE_YML)
    pragma = _parse_pragma_config(INIT_C_MISSING_KEY)
    rules  = {"FPLLMULT": "MUL_60"}
    assert check_clock_rules(mcc, pragma, rules) == 1


def test_check_clock_rules_detects_missing_key_in_mcc():
    mcc    = {}
    pragma = _parse_pragma_config(INIT_C_OK)
    rules  = {"POSCMOD": "EC"}
    assert check_clock_rules(mcc, pragma, rules) == 1


def test_check_clock_rules_counts_multiple_failures():
    mcc    = {}
    pragma = {}
    rules  = {"POSCMOD": "EC", "FPLLMULT": "MUL_60"}
    # 2 keys × 2 sources = 4 failures
    assert check_clock_rules(mcc, pragma, rules) == 4


# ---------------------------------------------------------------------------
# REFCLK fixtures
# ---------------------------------------------------------------------------

CORE_YML_REFCLK = """
data:
  symbols:
    SYS_CLK_FREQ:
      attributes:
        id: SYS_CLK_FREQ
      children:
      - children:
        - attributes:
            value: '120000000'
          type: User
        type: Values
      type: String
    CONFIG_SYS_CLK_REFCLK4_ENABLE:
      attributes:
        id: CONFIG_SYS_CLK_REFCLK4_ENABLE
      children:
      - children:
        - attributes:
            value: 'true'
          type: User
        type: Values
      type: Boolean
    CONFIG_SYS_CLK_RODIV4:
      attributes:
        id: CONFIG_SYS_CLK_RODIV4
      children:
      - children:
        - attributes:
            value: '1'
          type: User
        type: Values
      type: Integer
    CONFIG_SYS_CLK_ROTRIM4:
      attributes:
        id: CONFIG_SYS_CLK_ROTRIM4
      children:
      - children:
        - attributes:
            value: '256'
          type: User
        type: Values
      type: Integer
"""

CORE_YML_REFCLK_DISABLED = CORE_YML_REFCLK.replace("value: 'true'", "value: 'false'")

CORE_YML_REFCLK_WRONG_RODIV = CORE_YML_REFCLK.replace(
    "CONFIG_SYS_CLK_RODIV4:\n      attributes:\n        id: CONFIG_SYS_CLK_RODIV4\n      children:\n      - children:\n        - attributes:\n            value: '1'",
    "CONFIG_SYS_CLK_RODIV4:\n      attributes:\n        id: CONFIG_SYS_CLK_RODIV4\n      children:\n      - children:\n        - attributes:\n            value: '2'",
)

PLIB_CLK_REFCLK_OK = """
/* Set up Reference Clock 4 */
REFO4CON = 0x10200;
REFO4TRIM = 0x80000000;
REFO4CONSET = 0x00008000;
"""

PLIB_CLK_REFCLK_OFF = """
REFO4CON = 0x10200;
REFO4TRIM = 0x80000000;
"""


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

def test_parse_refclk_from_core_yml_extracts_enable():
    result = _parse_refclk_from_core_yml(CORE_YML_REFCLK, 4)
    assert result["enable"] == "true"


def test_parse_refclk_from_core_yml_extracts_rodiv_rotrim():
    result = _parse_refclk_from_core_yml(CORE_YML_REFCLK, 4)
    assert result["sysclk"] == 120_000_000
    assert result["rodiv"]  == 1
    assert result["rotrim"] == 256


def test_parse_refclk_from_plib_clk_extracts_registers():
    result = _parse_refclk_from_plib_clk(PLIB_CLK_REFCLK_OK, 4)
    assert result["rodiv"]   == 1
    assert result["rotrim"]  == 256
    assert result["enabled"] is True


def test_parse_refclk_from_plib_clk_detects_not_enabled():
    result = _parse_refclk_from_plib_clk(PLIB_CLK_REFCLK_OFF, 4)
    assert result["enabled"] is False


def test_compute_refclk_freq_formula():
    # 120_000_000 / (2 * 1 * (1 + 256/512)) = 40_000_000
    assert _compute_refclk_freq(120_000_000, 1, 256) == 40_000_000.0


# ---------------------------------------------------------------------------
# Checker tests
# ---------------------------------------------------------------------------

def test_check_refclk_rules_enable_pass():
    assert check_refclk_rules(CORE_YML_REFCLK, PLIB_CLK_REFCLK_OK, {"REFCLK4_ENABLE": "true"}) == 0


def test_check_refclk_rules_enable_fail_mcc_disabled():
    failures = check_refclk_rules(CORE_YML_REFCLK_DISABLED, PLIB_CLK_REFCLK_OK, {"REFCLK4_ENABLE": "true"})
    assert failures >= 1


def test_check_refclk_rules_enable_fail_code_not_set():
    failures = check_refclk_rules(CORE_YML_REFCLK, PLIB_CLK_REFCLK_OFF, {"REFCLK4_ENABLE": "true"})
    assert failures >= 1


def test_check_refclk_rules_freq_pass():
    assert check_refclk_rules(CORE_YML_REFCLK, PLIB_CLK_REFCLK_OK, {"REFCLK4_FREQ": "40000000"}) == 0


def test_check_refclk_rules_freq_fail_wrong_rodiv():
    failures = check_refclk_rules(CORE_YML_REFCLK_WRONG_RODIV, PLIB_CLK_REFCLK_OK, {"REFCLK4_FREQ": "40000000"})
    assert failures >= 1


# ---------------------------------------------------------------------------
# PBCLK fixtures
# ---------------------------------------------------------------------------

CORE_YML_PBCLK = """
data:
  symbols:
    CONFIG_SYS_CLK_PBCLK1_FREQ:
      attributes:
        id: CONFIG_SYS_CLK_PBCLK1_FREQ
      children:
      - children:
        - attributes:
            value: '120000000'
          type: User
        type: Values
      type: String
    CONFIG_SYS_CLK_PBCLK2_FREQ:
      attributes:
        id: CONFIG_SYS_CLK_PBCLK2_FREQ
      children:
      - children:
        - attributes:
            value: '120000000'
          type: User
        type: Values
      type: String
    CONFIG_SYS_CLK_PBCLK2_ENABLE:
      attributes:
        id: CONFIG_SYS_CLK_PBCLK2_ENABLE
      children:
      - children:
        - attributes:
            value: 'true'
          type: User
        type: Values
      type: Boolean
"""

CORE_YML_PBCLK_WRONG_FREQ = CORE_YML_PBCLK.replace(
    "CONFIG_SYS_CLK_PBCLK1_FREQ:\n      attributes:\n        id: CONFIG_SYS_CLK_PBCLK1_FREQ\n      children:\n      - children:\n        - attributes:\n            value: '120000000'",
    "CONFIG_SYS_CLK_PBCLK1_FREQ:\n      attributes:\n        id: CONFIG_SYS_CLK_PBCLK1_FREQ\n      children:\n      - children:\n        - attributes:\n            value: '60000000'",
)

CORE_YML_PBCLK_DISABLED = CORE_YML_PBCLK.replace("value: 'true'", "value: 'false'")

INIT_C_NO_PBCLK_PRAGMA = "/* no FPBDIV pragma here */"

INIT_C_WITH_PBCLK_PRAGMA = """
#pragma config FPBDIV2 = DIV_1
"""


# ---------------------------------------------------------------------------
# PBCLK parser tests
# ---------------------------------------------------------------------------

def test_parse_pbclk_from_core_yml_extracts_freq():
    result = _parse_pbclk_from_core_yml(CORE_YML_PBCLK, 1)
    assert result["freq"] == "120000000"


def test_parse_pbclk_from_core_yml_extracts_enable():
    result = _parse_pbclk_from_core_yml(CORE_YML_PBCLK, 2)
    assert result["enable"] == "true"


def test_parse_pbclk_from_core_yml_no_enable_symbol_for_pbclk1():
    result = _parse_pbclk_from_core_yml(CORE_YML_PBCLK, 1)
    assert result["enable"] is None


def test_parse_pbclk_from_core_yml_missing_returns_none():
    result = _parse_pbclk_from_core_yml(CORE_YML_PBCLK, 9)
    assert result["freq"] is None
    assert result["enable"] is None


# ---------------------------------------------------------------------------
# PBCLK checker tests
# ---------------------------------------------------------------------------

def test_check_pbclk_rules_freq_pass():
    assert check_pbclk_rules(CORE_YML_PBCLK, INIT_C_NO_PBCLK_PRAGMA, {"PBCLK1_FREQ": "120000000"}) == 0


def test_check_pbclk_rules_freq_fail_wrong_value():
    failures = check_pbclk_rules(CORE_YML_PBCLK_WRONG_FREQ, INIT_C_NO_PBCLK_PRAGMA, {"PBCLK1_FREQ": "120000000"})
    assert failures >= 1


def test_check_pbclk_rules_enable_pass():
    assert check_pbclk_rules(CORE_YML_PBCLK, INIT_C_NO_PBCLK_PRAGMA, {"PBCLK2_ENABLE": "true"}) == 0


def test_check_pbclk_rules_enable_fail():
    failures = check_pbclk_rules(CORE_YML_PBCLK_DISABLED, INIT_C_NO_PBCLK_PRAGMA, {"PBCLK2_ENABLE": "true"})
    assert failures >= 1


def test_check_pbclk_rules_pbclk1_enable_implicit():
    # PBCLK1 has no ENABLE symbol — treated as implicitly true
    assert check_pbclk_rules(CORE_YML_PBCLK, INIT_C_NO_PBCLK_PRAGMA, {"PBCLK1_ENABLE": "true"}) == 0


def test_check_pbclk_rules_skips_missing_pragma():
    # No FPBDIV2 pragma → SKIP (not a failure)
    assert check_pbclk_rules(CORE_YML_PBCLK, INIT_C_NO_PBCLK_PRAGMA, {"PBCLK2_FREQ": "120000000"}) == 0


def test_check_pbclk_rules_fails_on_wrong_pragma():
    # FPBDIV2 pragma present but wrong value
    failures = check_pbclk_rules(CORE_YML_PBCLK, INIT_C_WITH_PBCLK_PRAGMA, {"PBCLK2_FREQ": "60000000"})
    assert failures >= 1
