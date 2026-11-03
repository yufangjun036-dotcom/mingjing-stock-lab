"""确定性筛选引擎：不调用 AI，不执行模型生成代码。"""
import hashlib
import operator
from core.schemas import ConditionEvaluation, MetricValue, StockEvaluation, ScreeningResult
from core.condition_validator import validate_strategy

OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "=": operator.eq}


def evaluate_condition(value, condition):
    """质量不合格时返回 unknown，正常值使用未舍入 Decimal 比较。"""
    status = "unknown"
    if value.quality == "valid":
        status = "pass" if OPS[condition.operator](value.value, condition.value) else "fail"
    return ConditionEvaluation(condition=condition, actual=value, status=status)


def evaluate_stock(stock, strategy):
    """任一失败即排除；没有失败但存在未知时无法判断。"""
    metrics = dict(stock.metrics)
    evaluations = tuple(evaluate_condition(metrics.get(c.metric_id, MetricValue(
        quality="missing", reason="快照没有该指标")), c) for c in strategy.conditions)
    states = {item.status for item in evaluations}
    status = "excluded" if "fail" in states else "unknown" if "unknown" in states else "selected"
    return StockEvaluation(thscode=stock.thscode, name=stock.name, status=status, evaluations=evaluations)


def screen(snapshot, strategy):
    """校验范围后覆盖全部股票；结果 ID 同时绑定条件和快照。"""
    validate_strategy(strategy)
    if (strategy.universe_id, strategy.report_period) != (snapshot.universe_id, snapshot.report_period):
        raise ValueError("方案与数据快照范围不一致")
    rows = tuple(evaluate_stock(stock, strategy) for stock in sorted(snapshot.records, key=lambda s: s.thscode))
    result_id = hashlib.sha256((snapshot.id + strategy.model_dump_json()).encode()).hexdigest()
    return ScreeningResult(id=result_id, strategy=strategy, snapshot_id=snapshot.id, rows=rows)
