"""Tests for the approximate option-pricing helpers."""

from __future__ import annotations

import math

from momentum.options_recommendation.pricing import (
    annual_vol,
    atm_premium,
    call_premium,
    call_value_at,
    per_contract,
)


def test_annual_vol_prefers_iv_then_atr_then_fallback():
    assert annual_vol(0.45, 0.02, 0.4) == 0.45
    assert annual_vol(None, 0.02, 0.4) == 0.02 * math.sqrt(252.0)
    assert annual_vol(None, None, 0.4) == 0.4


def test_atm_premium_scales_with_vol_and_time():
    base = atm_premium(100.0, 0.4, 30, 0.4)
    assert base > 0
    assert atm_premium(100.0, 0.8, 30, 0.4) > base  # higher vol => richer
    assert atm_premium(100.0, 0.4, 120, 0.4) > base  # more time => richer


def test_call_premium_has_intrinsic_plus_extrinsic():
    atm_ext = atm_premium(100.0, 0.4, 30, 0.4)
    deep = call_premium(100.0, 88.0, 0.8, atm_ext)
    atm = call_premium(100.0, 100.0, 0.5, atm_ext)
    assert deep >= 12.0  # at least its intrinsic
    assert atm == atm_ext  # ATM has no intrinsic, full extrinsic factor (4*.5*.5=1)
    assert deep > atm  # deep ITM costs more (intrinsic dominates)


def test_call_premium_never_negative_and_contract_multiplier():
    assert call_premium(100.0, 200.0, 0.05, 1.0) >= 0.0
    assert per_contract(3.5) == 350.0


def test_call_value_at_is_intrinsic_only():
    assert call_value_at(120.0, 100.0) == 20.0
    assert call_value_at(90.0, 100.0) == 0.0
