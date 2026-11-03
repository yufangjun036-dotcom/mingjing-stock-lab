"""不可变领域契约；使用十进制数，禁止布尔值和非有限数字。"""
from decimal import Decimal, InvalidOperation
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Model(BaseModel):
    """所有模型禁止额外字段，避免未知输入被静默忽略。"""
    model_config = ConfigDict(extra="forbid", frozen=True)


class Condition(Model):
    """一条可执行条件；指标合法性由服务器字典再次检查。"""
    id: str = Field(min_length=1, max_length=40)
    metric_id: str
    operator: Literal[">", ">=", "<", "<=", "="]
    value: Decimal

    @field_validator("value", mode="before")
    @classmethod
    def finite_number(cls, value):
        """拒绝 bool、空值和 NaN/Infinity；保留未舍入的阈值。"""
        if isinstance(value, bool) or value is None:
            raise ValueError("阈值必须是有限数字")
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            raise ValueError("阈值必须是有限数字") from None
        if not number.is_finite():
            raise ValueError("阈值必须是有限数字")
        if abs(number) > Decimal("1e12") or len(number.as_tuple().digits) > 64:
            raise ValueError("阈值超出允许范围或精度")
        return number


class Strategy(Model):
    """版本化方案；报告期和演示股票池显式固定。"""
    schema_version: Literal["1.0"] = "1.0"
    universe_id: Literal["a_share_demo_v1"] = "a_share_demo_v1"
    report_period: Literal["2026-3"] = "2026-3"
    logic: Literal["AND"] = "AND"
    conditions: tuple[Condition, ...] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def unique_ids(self):
        """条件 ID 必须唯一，保证解释可以定位到条件。"""
        if len({c.id for c in self.conditions}) != len(self.conditions):
            raise ValueError("条件 ID 重复")
        return self


class Evidence(Model):
    """可公开的证据定位；永不存储请求头或密钥。"""
    source: str = "扶摇金融数据 API"
    endpoint: str
    request_id: str | None = None
    retrieved_at: str
    source_time: str | None = None
    raw_field: str
    raw_value: str | None = None
    unit: str
    formula: str | None = None
    params: tuple[tuple[str, str], ...] = ()
    report_period: str | None = None
    report_date: str | None = None
    note: str = ""


class MetricValue(Model):
    """只有 valid 数值可参与比较，其余状态保留具体原因。"""
    value: Decimal | None = None
    quality: Literal["valid", "missing", "not_applicable", "stale", "conflict", "unverified"]
    reason: str = ""
    evidence: tuple[Evidence, ...] = ()

    @model_validator(mode="after")
    def valid_value(self):
        """防止把缺失值或无限值标为正常数据。"""
        if self.value is not None and not self.value.is_finite():
            raise ValueError("指标值必须有限")
        if self.quality == "valid" and self.value is None:
            raise ValueError("有效指标必须有数值")
        return self


class StockRecord(Model):
    """以元组保存指标，避免嵌套字典修改既有快照。"""
    thscode: str
    name: str
    metrics: tuple[tuple[str, MetricValue], ...]


class DatasetSnapshot(Model):
    """一次取数形成的不可变快照；失败股票也必须保留。"""
    id: str
    created_at: str
    universe_id: str = "a_share_demo_v1"
    report_period: str = "2026-3"
    records: tuple[StockRecord, ...]
    source_errors: tuple[str, ...] = ()
    available_metrics: tuple[str, ...] = ("pe_ttm", "pb_mrq")
    history_cutoff: str | None = None


class ConditionEvaluation(Model):
    """确定性计算产生的逐条件结论。"""
    condition: Condition
    actual: MetricValue
    status: Literal["pass", "fail", "unknown"]


class StockEvaluation(Model):
    """股票总体状态以及全部条件明细。"""
    thscode: str
    name: str
    status: Literal["selected", "excluded", "unknown"]
    evaluations: tuple[ConditionEvaluation, ...]


class ScreeningResult(Model):
    """结果绑定当时的条件和数据快照，而非界面草案。"""
    id: str
    strategy: Strategy
    snapshot_id: str
    rows: tuple[StockEvaluation, ...]
