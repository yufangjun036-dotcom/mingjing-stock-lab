"""明镜选股入口：真实数据原型，所有执行由显式按钮触发。"""
import streamlit as st
from config import load_settings
from core.schemas import Condition, Strategy
from core.intent_parser import parse_intent, draft_to_strategy
from core.condition_validator import validate_strategy
from data.provider import FuyaoClient, ProviderError
from services.screening_service import run_screening, compare_results, compare_with_new_snapshot
from services.strategy_io import import_strategy, export_strategy
from ui.results_panel import render_results
from ui.condition_panel import render_condition_editor
from services.session_state import rehydrate_state
from pydantic import ValidationError


def main():
    """渲染意图、可编辑条件、结果和同快照比较。"""
    st.set_page_config(page_title="明镜选股", page_icon="🔎", layout="wide")
    st.title("明镜选股")
    st.write("把选股意图变成可以检查、修改和复算的条件。")
    st.info("六只样本研究版 · 6 项指标 · 2026 年前三季度累计财务。股票池固定，不代表全市场。")
    with st.expander("指标口径与使用边界"):
        st.write("估值：PE TTM / PB MRQ，单位倍；财务：收入同比、归母净利同比、毛利率，单位 %，金额为人民币元。上年利润非正时不计算普通增长率。")
        st.write("波动率：截至北京时间昨天及以前，最后 61 个真实交易日收盘价产生 60 个简单收益率，样本标准差×√252×100；供应商前复权因子未独立重建。")
        st.write("财务累计口径已用茅台原始公告抽样核对，其他股票不声称逐份公告审计；每次取数用利润表复算并与供应商指标交叉验证。固定报告期不代表自动发现最新报告。")
    st.caption("AI 提出草案 → 你确认条件 → Python 筛选 → 查看原字段证据。本产品不提供收益保证或买卖建议。")
    settings = load_settings()
    rehydrate_state(st.session_state)
    st.session_state.setdefault("conditions", [{"metric_id":"pe_ttm","operator":">","value":"0"},
                                                {"metric_id":"pe_ttm","operator":"<","value":"25"}])
    st.session_state.setdefault("editor_revision", 0)
    st.session_state.setdefault("blocked", False)
    with st.form("intent_form"):
        text = st.text_area("描述你的选股条件", max_chars=500, placeholder="例如：市盈率大于 0 且小于 25 倍")
        submitted = st.form_submit_button("让 AI 解析")
    if submitted:
        try:
            with st.spinner("正在解析意图…"):
                draft = parse_intent(text, settings)
            st.session_state["draft"] = draft
            st.session_state["blocked"] = bool(draft.clarifications or draft.unsupported or draft.refusal_reason)
            st.session_state["conditions"] = [c.model_dump() for c in draft.conditions]
            st.session_state["editor_revision"] += 1
        except ValueError as exc:
            st.error(str(exc))
            st.session_state["blocked"] = True
    draft = st.session_state.get("draft")
    if draft:
        for label, values in (("待确认假设",draft.assumptions),("请补充后重新解析",draft.clarifications),("当前不支持",draft.unsupported)):
            for value in values:
                st.warning(f"{label}：{value}")
        if draft.refusal_reason:
            st.error(draft.refusal_reason)
    if st.button("切换为独立手动方案"):
        # 明确放弃旧自然语言需求，避免误以为手动方案已经覆盖全部意图。
        st.session_state["draft"] = None
        st.session_state["blocked"] = False
        st.session_state["conditions"] = [{"metric_id":"pe_ttm","operator":">","value":"0"}]
        st.session_state["editor_revision"] += 1
        st.rerun()
    uploaded = st.file_uploader("载入已保存方案（只载入，不自动执行）", type=["json"])
    if uploaded and st.button("载入为手动草案"):
        try:
            imported = import_strategy(uploaded.getvalue())
            st.session_state["conditions"] = [{"metric_id":c.metric_id,"operator":c.operator,"value":str(c.value)} for c in imported.conditions]
            st.session_state["draft"] = None
            st.session_state["blocked"] = False
            st.session_state["editor_revision"] += 1
            st.rerun()
        except ValueError:
            st.error("方案文件无效、版本不支持或含未开放指标")
    st.subheader("检查和修改条件")
    st.caption("所有条件为 AND；指标名称注明单位，输入 20 表示 20% 或 20 倍。默认示例阈值不代表投资推荐。")
    edited = render_condition_editor(st.session_state["conditions"], st.session_state["editor_revision"])
    strategy = None
    try:
        strategy = validate_strategy(Strategy(conditions=tuple(Condition(id=f"c{i+1}", **row) for i,row in enumerate(edited))))
    except (ValueError, TypeError):
        st.warning("条件无效或存在冲突，请检查字段、数字及上下界。")
    confirm = st.checkbox("我已检查条件和假设，确认按上表执行", value=False)
    fresh = st.button("获取真实数据并筛选", disabled=strategy is None or st.session_state["blocked"] or not confirm)
    compare = st.button("使用原快照重算并比较", disabled=strategy is None or "result" not in st.session_state or st.session_state["blocked"] or not confirm)
    union = st.button("补齐新增指标，用新快照重算两方案", disabled=strategy is None or "result" not in st.session_state or st.session_state["blocked"] or not confirm)
    if fresh or compare or union:
        client = None
        try:
            client = FuyaoClient(settings)
            previous = st.session_state.get("result")
            with st.spinner("正在筛选…"):
                if union:
                    snapshot, baseline, result, changes = compare_with_new_snapshot(client, previous, strategy)
                else:
                    snapshot, result = run_screening(client, strategy, st.session_state.get("snapshot") if compare else None)
                    changes = compare_results(previous, result) if compare else None
                    baseline = previous if compare else None
            st.session_state["changes"] = changes
            st.session_state["comparison_base"] = baseline
            st.session_state["snapshot"],st.session_state["result"] = snapshot,result
            st.rerun()
        except ValidationError:
            st.error("数据结构校验失败，本次未生成新结果；请重新获取数据。")
        except (ProviderError, ValueError) as exc:
            st.error(str(exc))
            st.warning("本次执行未成功；下方如有结果仍是此前的旧结果。")
        finally:
            if client:
                client.close()
    if strategy:
        st.download_button("保存当前条件 JSON", export_strategy(strategy), "strategy.json", "application/json")
    if "result" in st.session_state:
        result = st.session_state["result"]
        if strategy != result.strategy:
            st.warning("草案已改变或无效；下方仍展示上一次执行结果，请确认后重算。")
        render_results(result, st.session_state["snapshot"])
        if st.session_state.get("changes") is not None:
            st.subheader("同快照条件变化影响")
            baseline = st.session_state.get("comparison_base")
            if baseline:
                st.caption("两个方案均在上方标识的同一个快照上执行。新增指标重取数时，基准方案也已重算。")
                st.write("基准条件", baseline.strategy.model_dump(mode="json")["conditions"])
                st.write("当前条件", result.strategy.model_dump(mode="json")["conditions"])
            st.write(st.session_state["changes"] or "没有股票改变筛选状态。")


if __name__ == "__main__":
    main()
