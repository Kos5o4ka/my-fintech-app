"""
Property-based tests for core financial calculations using Hypothesis.

Tests pure calculation functions in services/portfolio_service.py without
touching the database or Flask app context.
"""

import os

os.environ.setdefault("FLASK_TESTING", "1")

from types import SimpleNamespace  # noqa: E402

from hypothesis import assume, given  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from app.services.portfolio_service import (  # noqa: E402
    build_trade_entry,
    calc_portfolio_ytm,
    calc_sharpe_ratio,
    apply_ldv,
)
from app.constants import calc_ndfl, LDV_ANNUAL_DEDUCTION  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_sold_bond(
    buy_price: float, sell_price: float, amount: int = 1, commission: float = 0.0
) -> SimpleNamespace:
    """Minimal sold-bond object that satisfies portfolio_service functions."""
    return SimpleNamespace(
        id=1,
        isin="TST001",
        secid=None,
        name="Test Bond",
        buy_price=buy_price,
        sell_price=sell_price,
        amount=amount,
        broker_commission=commission,
        purchase_date=SimpleNamespace(strftime=lambda fmt: "2024-01-01"),
        sell_date=SimpleNamespace(strftime=lambda fmt: "2024-06-01"),
    )


# ── Floats strategy: finite, reasonable bond prices ──────────────────────────

_price = st.floats(
    min_value=10.0, max_value=50_000.0, allow_nan=False, allow_infinity=False
)
_amount = st.integers(min_value=1, max_value=10_000)
_return_factor = st.floats(
    min_value=0.5, max_value=2.0, allow_nan=False, allow_infinity=False
)


# ── build_trade_entry properties ──────────────────────────────────────────────


class TestTradeEntryProperties:
    @given(buy=_price, sell=_price, amount=_amount)
    def test_pnl_sign_matches_price_direction(self, buy, sell, amount):
        """P&L sign must match the direction: sell > buy → profit, sell < buy → loss.

        Uses assume() to skip cases where the difference is so small it rounds to 0
        at 2 decimal places — those cases are correctly reported as 0.00 P&L.
        """
        assume(round(abs(sell - buy) * amount, 2) > 0)
        bond = _make_sold_bond(buy, sell, amount)
        entry = build_trade_entry(bond)
        if sell > buy:
            assert entry["pnl"] > 0, f"Expected profit: buy={buy}, sell={sell}"
        elif sell < buy:
            assert entry["pnl"] < 0, f"Expected loss: buy={buy}, sell={sell}"
        else:
            assert entry["pnl"] == 0.0

    @given(buy=_price, sell=_price, amount=_amount)
    def test_pnl_scales_linearly_with_amount(self, buy, sell, amount):
        """Doubling the position doubles the P&L (no commission)."""
        bond1 = _make_sold_bond(buy, sell, amount)
        bond2 = _make_sold_bond(buy, sell, amount * 2)
        e1 = build_trade_entry(bond1)
        e2 = build_trade_entry(bond2)
        assert (
            abs(e2["pnl"] - e1["pnl"] * 2) < 0.02
        ), f"P&L should double: {e1['pnl']} × 2 ≠ {e2['pnl']}"

    @given(
        buy=_price,
        sell=_price,
        amount=_amount,
        commission=st.floats(
            min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False
        ),
    )
    def test_commission_reduces_pnl(self, buy, sell, amount, commission):
        """Adding a positive commission must reduce (or keep equal) P&L."""
        bond_no_comm = _make_sold_bond(buy, sell, amount, commission=0.0)
        bond_with_comm = _make_sold_bond(buy, sell, amount, commission=commission)
        e_no = build_trade_entry(bond_no_comm)
        e_with = build_trade_entry(bond_with_comm)
        assert (
            e_with["pnl"] <= e_no["pnl"] + 0.01
        ), f"Commission should reduce P&L: {e_with['pnl']} > {e_no['pnl']}"

    @given(buy=_price, sell=_price, amount=_amount)
    def test_sell_price_rounded_to_2dp(self, buy, sell, amount):
        """sell_price in the result must be rounded to 2 decimal places."""
        entry = build_trade_entry(_make_sold_bond(buy, sell, amount))
        rounded = round(entry["sell_price"], 2)
        assert entry["sell_price"] == rounded

    @given(buy=_price, sell=_price, amount=_amount)
    def test_buy_price_preserved(self, buy, sell, amount):
        """buy_price in result equals float(bond.buy_price) exactly."""
        bond = _make_sold_bond(buy, sell, amount)
        entry = build_trade_entry(bond)
        assert entry["buy_price"] == float(buy)

    @given(buy=_price, amount=_amount)
    def test_zero_pnl_when_buy_equals_sell(self, buy, amount):
        """When sell == buy with no commission, P&L is 0."""
        entry = build_trade_entry(_make_sold_bond(buy, buy, amount))
        assert entry["pnl"] == 0.0

    @given(buy=_price, sell=_price, amount=_amount)
    def test_pnl_pct_consistent_with_pnl(self, buy, sell, amount):
        """pnl_pct should be proportional to pnl / (buy * amount) × 100."""
        bond = _make_sold_bond(buy, sell, amount, commission=0.0)
        entry = build_trade_entry(bond)
        expected_pct = round(entry["pnl"] / (float(buy) * amount) * 100, 2)
        assert abs(entry["pnl_pct"] - expected_pct) < 0.02


# ── calc_sharpe_ratio properties ──────────────────────────────────────────────


class TestSharpeRatioProperties:
    @given(st.lists(_return_factor, min_size=0, max_size=2))
    def test_returns_none_for_fewer_than_3_trades(self, factors):
        """With < 3 data points, result must be None."""
        bonds = [_make_sold_bond(100.0, 100.0 * f) for f in factors]
        assert calc_sharpe_ratio(bonds) is None

    @given(st.lists(_return_factor, min_size=3, max_size=50))
    def test_sample_size_matches_input(self, factors):
        """result['sample_size'] must equal len(factors)."""
        bonds = [_make_sold_bond(100.0, 100.0 * f) for f in factors]
        result = calc_sharpe_ratio(bonds)
        assert result is not None
        assert result["sample_size"] == len(factors)

    @given(st.lists(_return_factor, min_size=3, max_size=50))
    def test_volatility_non_negative(self, factors):
        """Volatility (std dev) is always ≥ 0."""
        bonds = [_make_sold_bond(100.0, 100.0 * f) for f in factors]
        result = calc_sharpe_ratio(bonds)
        assert result is not None
        assert result["volatility_pct"] >= 0.0

    @given(
        st.lists(
            st.just(1.05),  # identical 5% return every trade
            min_size=3,
            max_size=20,
        )
    )
    def test_zero_volatility_returns_none_sharpe(self, factors):
        """All identical returns → zero volatility → sharpe should be None."""
        bonds = [_make_sold_bond(100.0, 100.0 * f) for f in factors]
        result = calc_sharpe_ratio(bonds)
        assert result is not None
        assert result["volatility_pct"] == 0.0
        assert result["sharpe"] is None

    @given(st.lists(_return_factor, min_size=3, max_size=30))
    def test_mean_return_sign_consistent(self, factors):
        """mean_return_pct sign matches whether average factor is > or < 1."""
        bonds = [_make_sold_bond(100.0, 100.0 * f) for f in factors]
        result = calc_sharpe_ratio(bonds)
        assert result is not None
        avg_factor = sum(factors) / len(factors)
        # avg_factor > 1 → average return > 0 → mean_return_pct > 0
        # avg_factor < 1 → average return < 0 → mean_return_pct < 0
        expected_positive = avg_factor > 1.0
        if (
            abs(avg_factor - 1.0) > 1e-4
        ):  # avoid floating point edge at exactly 1.0 / rounding to -0.0
            if expected_positive:
                assert result["mean_return_pct"] > 0
            else:
                assert result["mean_return_pct"] < 0

    @given(st.lists(_return_factor, min_size=3, max_size=30))
    def test_sharpe_keys_present(self, factors):
        """Result dict always contains the expected keys."""
        bonds = [_make_sold_bond(100.0, 100.0 * f) for f in factors]
        result = calc_sharpe_ratio(bonds)
        assert result is not None
        assert "sample_size" in result
        assert "mean_return_pct" in result
        assert "volatility_pct" in result


# ── calc_portfolio_ytm properties ─────────────────────────────────────────────


class TestPortfolioYtmProperties:
    @given(
        st.lists(
            st.tuples(
                st.floats(
                    min_value=1.0,
                    max_value=10_000.0,
                    allow_nan=False,
                    allow_infinity=False,
                ),  # current_value
                st.floats(
                    min_value=0.01,
                    max_value=30.0,
                    allow_nan=False,
                    allow_infinity=False,
                ),  # ytm
            ),
            min_size=1,
            max_size=20,
        )
    )
    def test_ytm_within_bounds(self, value_ytm_pairs):
        """Weighted avg YTM must be within [min(ytm), max(ytm)] of the portfolio."""
        portfolio = [{"current_value": v, "ytm": y} for v, y in value_ytm_pairs]
        total_value = sum(b["current_value"] for b in portfolio)
        assume(total_value > 0)

        result = calc_portfolio_ytm(portfolio, total_value)

        min_ytm = min(b["ytm"] for b in portfolio)
        max_ytm = max(b["ytm"] for b in portfolio)
        assert (
            min_ytm - 0.01 <= result <= max_ytm + 0.01
        ), f"YTM {result} outside [{min_ytm}, {max_ytm}]"

    def test_ytm_zero_for_empty_portfolio(self):
        """Empty portfolio → YTM = 0.0."""
        assert calc_portfolio_ytm([], 0.0) == 0.0

    def test_ytm_zero_when_total_value_is_zero(self):
        """Zero total value → YTM = 0.0 (avoid division by zero)."""
        portfolio = [{"current_value": 0.0, "ytm": 8.5}]
        assert calc_portfolio_ytm(portfolio, 0.0) == 0.0

    @given(
        value=st.floats(
            min_value=1.0, max_value=100_000.0, allow_nan=False, allow_infinity=False
        ),
        ytm=st.floats(
            min_value=0.01, max_value=30.0, allow_nan=False, allow_infinity=False
        ),
    )
    def test_single_bond_ytm_equals_bond_ytm(self, value, ytm):
        """Single-bond portfolio → weighted YTM equals that bond's YTM."""
        portfolio = [{"current_value": value, "ytm": ytm}]
        result = calc_portfolio_ytm(portfolio, value)
        assert abs(result - round(ytm, 2)) < 0.01


# ── Tax calculation properties ────────────────────────────────────────────────


class TestNdflProperties:
    @given(income=st.floats(min_value=0, max_value=100_000_000))
    def test_tax_never_exceeds_income(self, income):
        """Налог не может превышать доход."""
        assert calc_ndfl(income) <= income + 0.01

    @given(income=st.floats(min_value=0, max_value=2_400_000))
    def test_tax_13pct_below_threshold(self, income):
        """До 2.4 млн ставка ровно 13%."""
        assert abs(calc_ndfl(income) - round(income * 0.13, 2)) < 0.02

    @given(income=st.floats(min_value=2_400_001, max_value=100_000_000))
    def test_max_rate_15pct_for_securities(self, income):
        """Для ЦБ максимальная ставка 15% — нет 18/20/22% как в общей шкале."""
        tax = calc_ndfl(income)
        max_possible = round(income * 0.15, 2)
        assert tax <= max_possible + 0.01

    def test_example_from_law_54m(self):
        """Пример из закона: 5.4 млн → 312 000 (13%) + 450 000 (15%) = 762 000 ₽."""
        assert abs(calc_ndfl(5_400_000) - 762_000.0) < 1.0

    @given(income=st.floats(min_value=0, max_value=100_000_000))
    def test_tax_non_negative(self, income):
        """Налог всегда ≥ 0."""
        assert calc_ndfl(income) >= 0.0

    @given(
        a=st.floats(min_value=0, max_value=50_000_000),
        b=st.floats(min_value=0, max_value=50_000_000),
    )
    def test_tax_monotone(self, a, b):
        """Больший доход → больший или равный налог."""
        assume(a <= b)
        assert calc_ndfl(a) <= calc_ndfl(b) + 0.01


class TestApplyLdvProperties:
    @given(
        basis=st.floats(min_value=0, max_value=100_000_000),
        days=st.integers(min_value=0, max_value=365 * 2),
    )
    def test_no_ldv_below_3_years(self, basis, days):
        """До 3 лет вычет не применяется — база не меняется."""
        assert apply_ldv(basis, days) == basis

    @given(
        basis=st.floats(min_value=0, max_value=100_000_000),
        years=st.integers(min_value=3, max_value=30),
    )
    def test_ldv_scales_with_full_years(self, basis, years):
        """Вычет = 3M × полных лет, не фиксировано 1 год."""
        days = years * 365
        result = apply_ldv(basis, days)
        expected_deduction = LDV_ANNUAL_DEDUCTION * years
        if basis >= expected_deduction:
            assert abs(result - (basis - expected_deduction)) < 0.01
        else:
            assert result == 0.0

    @given(basis=st.floats(min_value=0, max_value=100_000_000))
    def test_ldv_result_non_negative(self, basis):
        """После вычета ЛДВ налоговая база не может стать отрицательной."""
        days = 5 * 365
        assert apply_ldv(basis, days) >= 0.0
