"""新手引导的确定性条件构建；不调用模型，不编造金融数据。"""
from decimal import Decimal, InvalidOperation
from core.intent_parser import IntentDraft, DraftCondition, draft_to_strategy

GUIDED_ORIGINAL = "经营改善、估值合理、走势相对稳定"


def positive_limit(value, label):
    """校验用户填写的上限；拒绝空值、非有限数和非正数。"""
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError(f"请填写{label}的数字上限") from None
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{label}上限必须是大于0的有限数字")
    return str(number)


def build_guided_draft(growth, valuation, stability, pe_limit="", vol_limit=""):
    """把明确选择映射到白名单条件，同时保留未覆盖意图及统计口径。"""
    allowed = (
        (growth, {"收入增加", "利润增加", "收入和利润都增加", "暂不筛经营变化"}),
        (valuation, {"教学示例", "自定上限", "暂不筛估值", "同行比较"}),
        (stability, {"教学示例", "自定上限", "暂不筛波动"}),
    )
    if any(choice not in options for choice, options in allowed):
        raise ValueError("请先回答三个问题；系统不会替你选择")
    if valuation == "同行比较":
        raise ValueError("当前没有已核验的同行比较能力。请选择其他方式，或明确暂不筛估值")
    rows, notes = [], []

    def add(metric, operator, value):
        """统一创建结构化条件，后续仍经过原有服务器校验器。"""
        rows.append(DraftCondition(metric_id=metric, operator=operator, value=value))

    if growth in {"收入增加", "收入和利润都增加"}:
        add("revenue_yoy", ">", "0")
    if growth in {"利润增加", "收入和利润都增加"}:
        add("profit_yoy", ">", "0")
    notes.append("经营改善 → " + ("本次未筛经营变化。" if growth == "暂不筛经营变化" else
        f"{growth}：2026年1–9月累计值与2025年同期相比，同比大于0%；不等于逐季或持续改善，非正基数按数据规则保留未知。"))
    if valuation != "暂不筛估值":
        limit = "25" if valuation == "教学示例" else positive_limit(pe_limit, "市盈率")
        add("pe_ttm", ">", "0")
        add("pe_ttm", "<", limit)
        notes.append(f"估值合理 → 只筛0 < 市盈率PE TTM < {limit}倍；正值条件也属于本次选择。这不能证明估值合理或股票值得买。" +
                     ("25倍是你选择的教学示例，不是行业标准。" if valuation == "教学示例" else "上限由你填写。"))
    else:
        notes.append("估值合理 → 本次未筛估值，结果不能称为满足‘估值合理’。")
    if stability != "暂不筛波动":
        limit = "30" if stability == "教学示例" else positive_limit(vol_limit, "年化波动率")
        add("volatility_60d", "<", limit)
        notes.append(f"走势相对稳定 → 近60个交易日收益率计算的年化波动率 < {limit}%；不是未来涨跌幅或最大亏损，也没有做同行比较。" +
                     ("30%是你选择的教学示例，不是安全标准。" if stability == "教学示例" else "上限由你填写。"))
    else:
        notes.append("走势相对稳定 → 本次未筛波动，结果不能称为满足‘走势稳定’。")
    if not rows:
        raise ValueError("三项都暂不筛时没有可执行条件，请至少选择一项")
    draft = IntentDraft(conditions=rows, assumptions=notes, clarifications=[], unsupported=[], refusal_reason="")
    # 复用原有白名单、数值长度和冲突校验，不形成旁路执行入口。
    draft_to_strategy(draft)
    return draft
