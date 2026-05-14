"""Tests for clock/oscillator configuration validation logic."""

from microchip_devtools.mcc.check_clock import (
    _parse_mcc_core_yml,
    _parse_pragma_config,
    check_clock_rules,
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
