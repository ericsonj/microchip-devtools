"""Tests for clock/oscillator configuration validation logic."""

from microchip_devtools.mcc.check_clock import (
    _compute_refclk_freq,
    _parse_mcc_core_yml,
    _parse_pbclk_from_core_yml,
    _parse_pbdiv_from_core_yml,
    _parse_pbdiv_from_plib_clk,
    _parse_pragma_config,
    _parse_refclk_from_core_yml,
    _parse_refclk_from_plib_clk,
    _parse_sysclk_from_core_yml,
    check_clock_rules,
    check_pbclk_rules,
    check_refclk_rules,
    check_scoped_rules,
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


def test_check_scoped_rules_code_only_pass(capsys):
    pragma = _parse_pragma_config(INIT_C_OK)
    assert check_scoped_rules(pragma, {"FNOSC": "SPLL"}, "CODE", verbose=True) == 0
    out = capsys.readouterr().out
    assert "[CODE] FNOSC" in out
    assert "MCC" not in out


def test_check_scoped_rules_missing_key_fails():
    assert check_scoped_rules({}, {"FNOSC": "SPLL"}, "CODE") == 1


def test_check_scoped_rules_mismatch_fails():
    pragma = _parse_pragma_config(INIT_C_OK)
    assert check_scoped_rules(pragma, {"FNOSC": "FRCDIV"}, "CODE") == 1


def test_check_scoped_rules_mcc_only_pass():
    mcc = _parse_mcc_core_yml(CORE_YML)
    assert check_scoped_rules(mcc, {"FPLLMULT": "MUL_60"}, "MCC ") == 0


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
    assert check_pbclk_rules(CORE_YML_PBCLK, {"PBCLK1_FREQ": "120000000"}) == 0


def test_check_pbclk_rules_freq_fail_wrong_value():
    failures = check_pbclk_rules(CORE_YML_PBCLK_WRONG_FREQ, {"PBCLK1_FREQ": "120000000"})
    assert failures >= 1


def test_check_pbclk_rules_enable_pass():
    assert check_pbclk_rules(CORE_YML_PBCLK, {"PBCLK2_ENABLE": "true"}) == 0


def test_check_pbclk_rules_enable_fail():
    failures = check_pbclk_rules(CORE_YML_PBCLK_DISABLED, {"PBCLK2_ENABLE": "true"})
    assert failures >= 1


def test_check_pbclk_rules_pbclk1_enable_implicit():
    # PBCLK1 has no ENABLE symbol — treated as implicitly true
    assert check_pbclk_rules(CORE_YML_PBCLK, {"PBCLK1_ENABLE": "true"}) == 0


# ---------------------------------------------------------------------------
# PBDIV (Peripheral Bus divisor) fixtures
# ---------------------------------------------------------------------------

CORE_YML_PBDIV = """
data:
  symbols:
    CONFIG_SYS_CLK_PBDIV1:
      attributes:
        id: CONFIG_SYS_CLK_PBDIV1
      children:
      - children:
        - attributes:
            value: '1'
          type: User
        type: Values
      type: Integer
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
    CONFIG_SYS_CLK_PBDIV2:
      attributes:
        id: CONFIG_SYS_CLK_PBDIV2
      children:
      - children:
        - attributes:
            value: '2'
          type: User
        type: Values
      type: Integer
"""

PLIB_CLK_PBDIV_OK = """
PB1DIVbits.PBDIV = 0;
PB2DIVbits.PBDIV = 1;
"""

PLIB_CLK_PBDIV_WRONG = """
PB1DIVbits.PBDIV = 2;
"""

PLIB_CLK_NO_PBDIV = "/* no PBnDIVbits here */"

INIT_C_FNOSC_SPLL = "#pragma config FNOSC =      SPLL\n"
INIT_C_FNOSC_FRC = "#pragma config FNOSC =      FRCDIV\n"


# ---------------------------------------------------------------------------
# PBDIV parser tests
# ---------------------------------------------------------------------------

def test_parse_pbdiv_from_core_yml_extracts_linear_divisor():
    assert _parse_pbdiv_from_core_yml(CORE_YML_PBDIV, 1) == 1
    assert _parse_pbdiv_from_core_yml(CORE_YML_PBDIV, 2) == 2


def test_parse_pbdiv_from_core_yml_missing_returns_none():
    assert _parse_pbdiv_from_core_yml(CORE_YML_PBDIV, 9) is None


def test_parse_pbdiv_from_plib_clk_computes_power_of_two():
    assert _parse_pbdiv_from_plib_clk(PLIB_CLK_PBDIV_OK, 1) == 1   # 2**0
    assert _parse_pbdiv_from_plib_clk(PLIB_CLK_PBDIV_OK, 2) == 2   # 2**1


def test_parse_pbdiv_from_plib_clk_missing_returns_none():
    assert _parse_pbdiv_from_plib_clk(PLIB_CLK_NO_PBDIV, 1) is None


# ---------------------------------------------------------------------------
# PBDIV checker tests
# ---------------------------------------------------------------------------

def test_check_pbclk_rules_div_pass():
    assert check_pbclk_rules(
        CORE_YML_PBDIV, {"PBCLK1_DIV": "1"},
        plib_clk_text=PLIB_CLK_PBDIV_OK,
    ) == 0


def test_check_pbclk_rules_div_pass_divide_by_two():
    assert check_pbclk_rules(
        CORE_YML_PBDIV, {"PBCLK2_DIV": "2"},
        plib_clk_text=PLIB_CLK_PBDIV_OK,
    ) == 0


def test_check_pbclk_rules_div_fail_mcc_mismatch():
    # core.yml PBDIV1=1 but expected 2
    failures = check_pbclk_rules(
        CORE_YML_PBDIV, {"PBCLK1_DIV": "2"},
        plib_clk_text=PLIB_CLK_PBDIV_OK,
    )
    assert failures >= 1


def test_check_pbclk_rules_div_fail_code_mismatch():
    # PB1DIVbits.PBDIV = 2 → divisor 4, expected 1 (MCC ok, CODE fails)
    failures = check_pbclk_rules(
        CORE_YML_PBDIV, {"PBCLK1_DIV": "1"},
        plib_clk_text=PLIB_CLK_PBDIV_WRONG,
    )
    assert failures >= 1


def test_check_pbclk_rules_div_fail_code_register_missing():
    failures = check_pbclk_rules(
        CORE_YML_PBDIV, {"PBCLK1_DIV": "1"},
        plib_clk_text=PLIB_CLK_NO_PBDIV,
    )
    assert failures >= 1


def test_check_pbclk_rules_div_fail_mcc_key_missing():
    failures = check_pbclk_rules(
        CORE_YML_PBDIV, {"PBCLK9_DIV": "1"},
        plib_clk_text=PLIB_CLK_PBDIV_OK,
    )
    assert failures >= 1


# ---------------------------------------------------------------------------
# SYS_CLK parser + DIV annotation (FNOSC source + computed PBCLK freq)
# ---------------------------------------------------------------------------

def test_parse_sysclk_from_core_yml_extracts_freq():
    assert _parse_sysclk_from_core_yml(CORE_YML_PBDIV) == 120000000


def test_parse_sysclk_from_core_yml_missing_returns_zero():
    assert _parse_sysclk_from_core_yml("data:\n  symbols: {}\n") == 0


def test_check_pbclk_rules_div_annotates_spll_freq(capsys):
    rc = check_pbclk_rules(
        CORE_YML_PBDIV, {"PBCLK1_DIV": "1"},
        verbose=True,
        plib_clk_text=PLIB_CLK_PBDIV_OK,
        init_c_text=INIT_C_FNOSC_SPLL,
    )
    assert rc == 0
    assert "SPLL 120000000Hz" in capsys.readouterr().out


def test_check_pbclk_rules_div_annotates_non_spll_name_only(capsys):
    rc = check_pbclk_rules(
        CORE_YML_PBDIV, {"PBCLK1_DIV": "1"},
        verbose=True,
        plib_clk_text=PLIB_CLK_PBDIV_OK,
        init_c_text=INIT_C_FNOSC_FRC,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "FRCDIV" in out
    assert "Hz" not in out
