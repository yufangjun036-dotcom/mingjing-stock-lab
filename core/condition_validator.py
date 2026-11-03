"""对 AND 条件进行白名单检查及严格开闭区间冲突识别。"""
from collections import defaultdict
from core.metrics import get_metric
from core.schemas import Strategy


def detect_conflicts(conditions):
    """合并同指标上下界；等值约束同时作为闭区间上下界。"""
    groups = defaultdict(list)
    for condition in conditions:
        groups[condition.metric_id].append(condition)
    errors = []
    for metric_id, group in groups.items():
        lower, upper = [], []
        for c in group:
            if c.operator in (">", ">=", "="):
                lower.append((c.value, c.operator == ">"))
            if c.operator in ("<", "<=", "="):
                upper.append((c.value, c.operator == "<"))
        if lower and upper:
            lo = max(lower)
            # 相同上界时，严格小于比小于等于更紧。
            hi = min(upper, key=lambda bound: (bound[0], not bound[1]))
            if lo[0] > hi[0] or (lo[0] == hi[0] and (lo[1] or hi[1])):
                errors.append(f"{metric_id} 条件冲突：" + "、".join(c.id for c in group))
    return errors


def validate_strategy(strategy: Strategy):
    """拒绝未知、未启用及相互矛盾条件；返回可直接使用的方案。"""
    for c in strategy.conditions:
        metric = get_metric(c.metric_id)
        if not metric.enabled:
            raise ValueError(f"{metric.name} 尚未完成接入或口径核验，暂不可筛选")
    errors = detect_conflicts(strategy.conditions)
    if errors:
        raise ValueError("；".join(errors))
    return strategy
