"""服务器维护的指标白名单；财务累计口径有公告样本核验，逐股数据仍执行质量检查。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class MetricDefinition:
    """指标名称、单位、依赖与启用门槛。"""
    name: str
    unit: str
    source: str
    enabled: bool


METRICS = {
    "pe_ttm": MetricDefinition("市盈率 PE TTM", "倍", "valuations", True),
    "pb_mrq": MetricDefinition("市净率 PB MRQ", "倍", "valuations", True),
    "revenue_yoy": MetricDefinition("营业收入同比", "%", "income", True),
    "profit_yoy": MetricDefinition("归母净利润同比", "%", "income", True),
    "gross_margin": MetricDefinition("销售毛利率", "%", "income", True),
    "volatility_60d": MetricDefinition("60 日年化波动率", "%", "history", True),
}


def get_metric(metric_id):
    """按白名单查找指标；未知指标报错，不动态执行公式。"""
    if metric_id not in METRICS:
        raise ValueError(f"不支持的指标：{metric_id}")
    return METRICS[metric_id]


def list_enabled_metrics():
    """仅返回本次实现已接入且允许执行的指标。"""
    return {key: value for key, value in METRICS.items() if value.enabled}
