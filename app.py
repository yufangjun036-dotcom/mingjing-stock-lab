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
from ui.layout import render_header
from ui.comparison_panel import render_comparison
from services.session_state import rehydrate_state
from pydantic import ValidationError


def main():
    """渲染意图、可编辑条件、结果和同快照比较。"""
    st.set_page_config(page_title="明镜选股", page_icon="🔎", layout="wide")
    render_header()
    settings = load_settings()
    rehydrate_state(st.session_state)
    st.session_state.setdefault("conditions", [{"metric_id":"pe_ttm","operator":">","value":"0"},
                                                {"metric_id":"pe_ttm","operator":"<","value":"25"}])
    st.session_state.setdefault("editor_revision", 0)
    st.session_state.setdefault("blocked", False)
    st.subheader("01 · 描述选股需求")
    st.caption("先明确你关心的指标与阈值；模糊表达会请求澄清，AI 不会直接替你执行。")
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
    with st.expander("方案文件 · 导入已保存的条件"):
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
    st.subheader("02 · 检查条件并执行")
    st.caption("所有条件为 AND；指标名称注明单位，输入 20 表示 20% 或 20 倍。默认示例阈值不代表投资推荐。")
    edited = render_condition_editor(st.session_state["conditions"], st.session_state["editor_revision"])
    strategy = None
    try:
        strategy = validate_strategy(Strategy(conditions=tuple(Condition(id=f"c{i+1}", **row) for i,row in enumerate(edited))))
    except (ValueError, TypeError):
        st.warning("条件无效或存在冲突，请检查字段、数字及上下界。")
    # 确认绑定当前有效方案和模型草案；修改条件或假设后必须重新检查。
    # 在创建本轮复选框之前清空状态，普通重跑且上下文未变时保留勾选。
    confirmation_context = (
        strategy.model_dump_json() if strategy else None,
        draft.model_dump_json() if draft else None,
        st.session_state["editor_revision"],
    )
    if st.session_state.get("confirmation_context") != confirmation_context:
        st.session_state["confirmed_current_strategy"] = False
        st.session_state["confirmation_context"] = confirmation_context
    confirm = st.checkbox("我已检查条件和假设，确认按上表执行", key="confirmed_current_strategy")
    fresh = st.button("获取真实数据并筛选", type="primary", disabled=strategy is None or st.session_state["blocked"] or not confirm)
    with st.expander("比较修改前后 · 使用同一份数据解释变化"):
        st.caption("已有结果后再修改条件。原快照缺少新增指标时，选择补齐数据，两个方案会一起重算。")
        compare = st.button("使用原快照重算并比较", disabled=strategy is None or "result" not in st.session_state or st.session_state["blocked"] or not confirm)
        union = st.button("补齐新增指标，用新快照重算两方案", disabled=strategy is None or "result" not in st.session_state or st.session_state["blocked"] or not confirm)
    if fresh or compare or union:
        client = None
        try:
            # 原快照比较纯本地执行；仅新取数或补齐指标时创建鉴权客户端。
            if fresh or union:
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
            render_comparison(st.session_state.get("comparison_base"), result,
                              st.session_state["changes"])



if __name__ == "__main__":
    main()
