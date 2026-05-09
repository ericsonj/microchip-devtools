"""Tests for XC32 fmt=3 detection logic."""

import pytest
from voltu_devtools.xc32.validate_fmt3 import _is_fmt3_trigger


def test_all_zeros_not_fmt3():
    assert _is_fmt3_trigger(bytes([0x00] * 8)) is False


def test_uniform_nonzero_aligned_is_fmt3():
    data = bytes([0xAB, 0xCD, 0xEF, 0x12] * 4)
    assert _is_fmt3_trigger(data) is True


def test_uniform_nonzero_unaligned_is_fmt3():
    # 5 bytes: not divisible by 4 — this is the dangerous case
    data = bytes([0x01, 0x00, 0x00, 0x00, 0x01])
    assert _is_fmt3_trigger(data) is True


def test_non_uniform_bytes_not_fmt3():
    data = bytes([0x01, 0x02, 0x03, 0x04, 0x01, 0x02, 0x03, 0x05])
    assert _is_fmt3_trigger(data) is False


def test_too_short_not_fmt3():
    assert _is_fmt3_trigger(bytes([0xFF, 0xFF, 0xFF])) is False


def test_single_nonzero_word_is_fmt3():
    data = bytes([0xDE, 0xAD, 0xBE, 0xEF])
    assert _is_fmt3_trigger(data) is True
