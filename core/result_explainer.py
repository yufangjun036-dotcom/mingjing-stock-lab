"""仅根据引擎证据生成解释，不让语言模型编造入选理由。"""
from core.metrics import get_metric


def explain_condition(evaluation):
    """展示实际值、阈值和质量状态；所有单位来自服务器字典。"""
    c, actual = evaluation.condition, evaluation.actual
    metric = get_metric(c.metric_id)
    expected = f"{metric.name} {c.operator} {c.value} {metric.unit}"
    if evaluation.status == "unknown":
        return f"无法判断：{expected}；原因：{actual.reason or actual.quality}"
    verdict = "满足" if evaluation.status == "pass" else "不满足"
    return f"{verdict}：{expected}；实际 {actual.value:.4f} {metric.unit}（显示保留四位，判断使用未舍入值）"


def explain_stock(row):
    """保留失败及未知明细，不生成买卖建议。"""
    labels = {"selected": "入选", "excluded": "排除", "unknown": "无法判断"}
    return labels[row.status] + "；" + "；".join(map(explain_condition, row.evaluations))
