"""Tests for MCC peripheral config validation logic."""

from voltu_devtools.mcc.check_peripheral import (
    _parse_extern_handlers,
    _parse_handler_declarations,
    _parse_pmd_from_core_yml,
    _parse_pmd_from_plib_clk,
    check_pmd_registers,
    check_vector_stubs,
)


INTERRUPTS_C = """
void UART1_FAULT_Handler (void);
void UART1_RX_Handler (void);
void TIMER_1_Handler (void);
"""

INTERRUPTS_AS_OK = """
    .extern  UART1_FAULT_Handler
    .extern  UART1_RX_Handler
    .extern  TIMER_1_Handler
"""

INTERRUPTS_AS_MISSING = """
    .extern  UART1_FAULT_Handler
    .extern  TIMER_1_Handler
"""

CORE_YML = """
    PMD1_REG_VALUE:
      value: '16909060'
    PMD2_REG_VALUE:
      value: '255'
"""

PLIB_CLK_OK = """
    PMD1 = 0x01020304U;
    PMD2 = 0x000000FFU;
"""

PLIB_CLK_MISMATCH = """
    PMD1 = 0xDEADBEEFU;
    PMD2 = 0x000000FFU;
"""


def test_parse_handler_declarations():
    handlers = _parse_handler_declarations(INTERRUPTS_C)
    assert "UART1_FAULT_Handler" in handlers
    assert "UART1_RX_Handler" in handlers
    assert "TIMER_1_Handler" in handlers
    assert len(handlers) == 3


def test_parse_extern_handlers():
    externed = _parse_extern_handlers(INTERRUPTS_AS_OK)
    assert "UART1_FAULT_Handler" in externed
    assert "UART1_RX_Handler" in externed
    assert "TIMER_1_Handler" in externed


def test_check_vector_stubs_passes():
    failures = check_vector_stubs(INTERRUPTS_C, INTERRUPTS_AS_OK)
    assert failures == 0


def test_check_vector_stubs_detects_missing():
    failures = check_vector_stubs(INTERRUPTS_C, INTERRUPTS_AS_MISSING)
    assert failures == 1


def test_check_vector_stubs_known_missing_accepted():
    failures = check_vector_stubs(
        INTERRUPTS_C,
        INTERRUPTS_AS_MISSING,
        known_missing={"UART1_RX_Handler": "deliberately excluded"},
    )
    assert failures == 0


def test_parse_pmd_from_core_yml():
    pmd = _parse_pmd_from_core_yml(CORE_YML)
    assert pmd[1] == 16909060
    assert pmd[2] == 255


def test_parse_pmd_from_plib_clk():
    pmd = _parse_pmd_from_plib_clk(PLIB_CLK_OK)
    assert pmd[1] == 0x01020304
    assert pmd[2] == 0x000000FF


def test_check_pmd_passes():
    failures = check_pmd_registers(CORE_YML, PLIB_CLK_OK)
    assert failures == 0


def test_check_pmd_detects_mismatch():
    failures = check_pmd_registers(CORE_YML, PLIB_CLK_MISMATCH)
    assert failures == 1
