"""Testes das funções puras de conversão de unidades em app/blockchain.py.

Não tocam na rede: só verificam a matemática e a formatação.
"""

from decimal import Decimal

import pytest

from app.blockchain import (
    InvalidAmountError,
    cents_to_kz,
    format_eur,
    format_kz,
    format_rate,
    humanize_seconds_ago,
    max_aoa_cents_for_liquidity,
    micro_to_eur,
    parse_kz_input,
    raw_rate_to_decimal,
)


def test_cents_to_kz():
    # 50.000,00 kz guardados como 5 000 000 cêntimos
    assert cents_to_kz(5_000_000) == Decimal("50000")


def test_format_kz():
    assert format_kz(5_000_000) == "50.000,00 kz"


def test_micro_to_eur():
    # 46,46 € guardados como 46 457 062 unidades de EURC (6 casas decimais)
    assert micro_to_eur(46_457_062) == Decimal("46.457062")


def test_format_eur():
    assert format_eur(46_457_062) == "46,46 €"


def test_raw_rate_to_decimal():
    # 1065,50 AOA/EUR guardados como 106 550 000 000 (8 casas decimais)
    assert raw_rate_to_decimal(106_550_000_000) == Decimal("1065.5")


def test_format_rate():
    assert format_rate(106_550_000_000) == "1065,50"


@pytest.mark.parametrize(
    "text,expected_cents",
    [
        ("50000", 5_000_000),
        ("50000,00", 5_000_000),
        ("50.000,00", 5_000_000),
        ("1234,56", 123_456),
    ],
)
def test_parse_kz_input_valid(text, expected_cents):
    assert parse_kz_input(text) == expected_cents


@pytest.mark.parametrize("text", ["", "   ", "abc", "-100", "0"])
def test_parse_kz_input_invalid(text):
    with pytest.raises(InvalidAmountError):
        parse_kz_input(text)


def test_humanize_seconds_ago_minutes():
    assert humanize_seconds_ago(130) == "há 2 minutos"


def test_humanize_seconds_ago_days():
    assert humanize_seconds_ago(3 * 86400) == "há 3 dias"


def test_max_aoa_cents_for_liquidity_matches_quote_example():
    # Liquidez igual ao 'net' do exemplo de 50.000 kz; o máximo seguro fica
    # um cêntimo de EURC abaixo, por causa do arredondamento por defeito do
    # Solidity (ver docstring da função).
    max_cents = max_aoa_cents_for_liquidity(
        available_liquidity_micro=46_457_062, rate_raw=106_550_000_000, spread_bps=100
    )
    assert max_cents == 4_999_999


def test_max_aoa_cents_for_liquidity_no_liquidity():
    assert max_aoa_cents_for_liquidity(0, 106_550_000_000, 100) == 0
