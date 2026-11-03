"""构造数据测试：不代表真实股票或投资建议。"""
from decimal import Decimal
import pytest
from core.schemas import Condition, Strategy, MetricValue, StockRecord
from core.condition_validator import validate_strategy
from core.screening_engine import screen
from data.normalizer import build_snapshot, compute_yoy, compute_gross_margin, compute_volatility
from services.strategy_io import export_strategy, import_strategy
from services.screening_service import compare_results


def strategy(*pairs):
    """创建仅用于测试的 PE 条件。"""
    return Strategy(conditions=tuple(Condition(id=str(i), metric_id="pe_ttm", operator=op, value=v)
                                    for i, (op, v) in enumerate(pairs)))


def snapshot():
    """创建正常、负值和缺失三种质量场景。"""
    rows = [StockRecord(thscode=c, name=c, metrics=(("pe_ttm", MetricValue(value=v,
            quality="valid" if v is not None else "missing")),))
            for c, v in (("A", "10"), ("B", "20"), ("C", "-2"), ("D", None))]
    return build_snapshot(rows, "2026-11-04T00:00:00+08:00")


@pytest.mark.parametrize("value", [True, None, "NaN", "Infinity", "-Infinity", "abc", ""])
def test_invalid_number(value):
    """布尔和非有限值拒绝。"""
    with pytest.raises(ValueError):
        strategy((">", value))


@pytest.mark.parametrize("pairs", [[(">", "10"), ("<=", "10")], [("=", "10"), ("=", "11")], [("<", "2"), (">", "3")]])
def test_conflict(pairs):
    """检测开闭边界和等值冲突。"""
    with pytest.raises(ValueError, match="冲突"):
        validate_strategy(strategy(*pairs))


def test_boundary():
    """相等闭区间合法，缺失值保持未知。"""
    result = screen(snapshot(), strategy((">=", "10"), ("<=", "10")))
    assert [r.status for r in result.rows] == ["selected", "excluded", "excluded", "unknown"]


def test_fail_and_unknown():
    """排除时仍保留其他未知条件。"""
    s = Strategy(conditions=(Condition(id="a", metric_id="pe_ttm", operator=">", value=30),
                             Condition(id="b", metric_id="pb_mrq", operator=">", value=0)))
    row = screen(snapshot(), s).rows[0]
    assert row.status == "excluded"
    assert [e.status for e in row.evaluations] == ["fail", "unknown"]


def test_relaxation():
    """固定快照放宽上界，原入选集合不缩小。"""
    data = snapshot()
    a = screen(data, strategy((">", 0), ("<", 15)))
    b = screen(data, strategy((">", 0), ("<", 25)))
    assert compare_results(a, b) == [{"thscode": "B", "before": "excluded", "after": "selected"}]
    assert {r.thscode for r in a.rows if r.status == "selected"} < {r.thscode for r in b.rows if r.status == "selected"}
    with pytest.raises(ValueError):
        compare_results(a, b.model_copy(update={"snapshot_id": "different"}))


def test_roundtrip():
    """保存载入保留精度，限制空方案和文件大小。"""
    s = strategy((">", "10.00000001"))
    assert import_strategy(export_strategy(s)) == s
    with pytest.raises(ValueError):
        import_strategy(b" " * 102401)
    with pytest.raises(ValueError):
        Strategy(conditions=())


def test_finance():
    """亏损基数不套普通同比；银行缺失成本不填零。"""
    assert compute_yoy(-80, -100, verified=True).quality == "not_applicable"
    assert compute_yoy(120, 100).quality == "unverified"
    assert compute_yoy(120, 100, verified=True).value == Decimal("20")
    assert compute_gross_margin(100, None, verified=True).quality == "missing"
    assert compute_gross_margin(100, 120, verified=True).value == Decimal("-20")


def test_volatility():
    """恒价为零、缺一天未知、重复日期冲突。"""
    days = list(range(61))
    prices = [(d, 100) for d in days]
    assert compute_volatility(prices, days).value == 0
    assert compute_volatility(prices[:-1], days).quality == "missing"
    assert compute_volatility(prices + [(1, 100)], days).quality == "conflict"
