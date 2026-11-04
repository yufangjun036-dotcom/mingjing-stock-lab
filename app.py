"""明镜选股入口：真实数据原型，所有执行由显式按钮触发。"""
import streamlit as st
from uuid import uuid4
from contextlib import nullcontext
from services.usage_guard import get_usage_guard
from config import load_settings
from core.schemas import Condition, Strategy
from core.intent_parser import parse_intent, draft_to_strategy
from core.condition_validator import validate_strategy
from data.provider import FuyaoClient, ProviderError
from services.screening_service import run_screening, compare_results, compare_with_new_snapshot, cached_screening
from services.strategy_io import import_strategy, export_strategy
from ui.results_panel import render_results
from ui.intent_notes import render_assumptions, MISSING_DATA_POLICY
from ui.condition_panel import render_condition_editor
from ui.layout import render_header
from ui.external_operation import run_external_operation
from ui.comparison_panel import render_comparison
from ui.guided_panel import render_guided_panel
from ui.beginner_task_panel import render_beginner_task
from core.guided_intent import GUIDED_ORIGINAL
from services.session_state import rehydrate_state
from pydantic import ValidationError


def main():
    """渲染意图、可编辑条件、结果和同快照比较。"""
    st.set_page_config(page_title="明镜选股", page_icon="🔎", layout="wide")
    render_header()
    settings = load_settings()
    rehydrate_state(st.session_state)
    st.session_state.setdefault("usage_session", uuid4().hex)
    # 新手任务默认收起；展开只是查看引导，取数仍须点击任务按钮。
    with st.expander("第一次使用？跟着做一次（可选）", expanded=False):
        render_beginner_task(settings)
    st.session_state.setdefault("conditions", [{"metric_id":"pe_ttm","operator":">","value":"0"},
                                                {"metric_id":"pe_ttm","operator":"<","value":"25"}])
    st.session_state.setdefault("editor_revision", 0)
    st.session_state.setdefault("blocked", False)
    if st.button("不懂指标？从三个常见想法开始", key="start_guide"):
        # 控件离开页面后会被Streamlit清理，使用独立答案副本恢复已回答内容。
        for key, value in st.session_state.get("guided_answers", {}).items():
            st.session_state[key] = value
        st.session_state["guide_active"] = True
    guide_area = st.empty()
    if st.session_state.get("guide_active"):
        # 引导期间不展示可执行按钮；应用选择后重新生成草案并重置确认。
        with guide_area.container():
            guided = render_guided_panel()
        guide_area.empty()
        st.session_state["parse_error"] = None
        st.session_state["draft"] = guided
        st.session_state["intent_origin"] = "新手引导：" + GUIDED_ORIGINAL
        st.session_state["conditions"] = [c.model_dump() for c in guided.conditions]
        st.session_state["blocked"] = False
        st.session_state["editor_revision"] += 1
        st.session_state["guide_active"] = False
        st.rerun()
    st.subheader("01 · 形成筛选条件")
    # 有草案时收起重新输入入口，避免用户把引导说明复制回去重复解析。
    has_draft = st.session_state.get("draft") is not None
    input_area = st.expander("想换一种需求？展开重新描述", expanded=False) if has_draft else st.container()
    with input_area:
        st.caption("用自己的话描述需求，AI会转成下面的条件表；解析本身不会查询股票。")
        with st.form("intent_form"):
            text = st.text_area("描述你的选股条件", max_chars=500, placeholder="例如：市盈率大于 0 且小于 25 倍")
            submitted = st.form_submit_button("让 AI 解析")
    if submitted:
        try:
            if not 1 <= len(text.strip()) <= 500:
                raise ValueError("请输入 1–500 字的选股条件")
            # 同一会话重复提交相同成功输入直接复用草案，避免二次解析挤占取数额度。
            if text.strip() == st.session_state.get("parsed_input") and st.session_state.get("parsed_draft"):
                draft = st.session_state["parsed_draft"]
            else:
                with get_usage_guard().reserve(st.session_state["usage_session"]), st.spinner("正在解析意图…"):
                    draft = parse_intent(text, settings)
                st.session_state["parsed_input"] = text.strip()
                st.session_state["parsed_draft"] = draft
            st.session_state["parse_error"] = None
            st.session_state["intent_origin"] = text
            st.session_state["draft"] = draft
            st.session_state["blocked"] = bool(draft.clarifications or draft.unsupported or draft.refusal_reason)
            st.session_state["conditions"] = [c.model_dump() for c in draft.conditions]
            st.session_state["editor_revision"] += 1
        except ValueError as exc:
            # 失败原因跨重跑保留，不能只留下一个无法解释的灰按钮。
            st.session_state["parse_error"] = str(exc)
            st.session_state["blocked"] = True
    if st.session_state.get("parse_error"):
        st.error("这次解析未成功：" + st.session_state["parse_error"])
        st.warning("下面若有条件表，是此前的条件，不代表刚才的新输入。请重新解析，或明确恢复此前草案。")
        old = st.session_state.get("draft")
        if old is not None and not (old.clarifications or old.unsupported or old.refusal_reason):
            if st.button("放弃本次失败输入，恢复此前草案"):
                st.session_state["parse_error"] = None
                st.session_state["blocked"] = False
                st.session_state["editor_revision"] += 1
                st.rerun()
    draft = st.session_state.get("draft")
    if draft:
        if st.session_state["blocked"]:
            st.warning("需求还有未解决事项，请先处理下面的提示，再重新描述或使用新手引导。")
        else:
            st.success("条件已生成，无需复制回输入框。下一步：检查下面的条件表，勾选确认，再点击‘获取真实数据并筛选’。")
        with st.expander("查看原始描述（输入记录，不是解析结果）", expanded=False):
            st.text(st.session_state.get("intent_origin", "此前解析的需求"))
        st.caption("以下是生成条件时的解释，真正执行的是下面的条件表。手动修改表格后，请重新检查是否符合你的意思。")
        render_assumptions(draft.assumptions)
        for label, values in (("请补充后重新解析",draft.clarifications),("当前不支持",draft.unsupported)):
            for value in values:
                st.warning(f"{label}：{value}")
        if draft.refusal_reason:
            st.error(draft.refusal_reason)
    if st.button("切换为独立手动方案"):
        # 明确放弃旧自然语言需求，避免误以为手动方案已经覆盖全部意图。
        st.session_state["draft"] = None
        st.session_state["parse_error"] = None
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
                st.session_state["parse_error"] = None
                st.session_state["blocked"] = False
                st.session_state["editor_revision"] += 1
                st.rerun()
            except ValueError:
                st.error("方案文件无效、版本不支持或含未开放指标")
    st.subheader("02 · 检查条件并执行")
    st.info(MISSING_DATA_POLICY)
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
    if st.session_state["blocked"]:
        reasons = ([st.session_state["parse_error"]] if st.session_state.get("parse_error") else
                   ((draft.clarifications + draft.unsupported + ([draft.refusal_reason] if draft.refusal_reason else [])) if draft else []))
        st.warning("暂不能执行：" + "；".join(reasons or ["请重新解析需求或切换独立手动方案"]))
    elif strategy is None:
        st.warning("暂不能执行：条件表存在无效值或相互冲突的条件。")
    elif not confirm:
        st.caption("检查条件后勾选确认，即可执行。")
    st.caption("一次AI解析和一次真实取数分别计1次外部操作；重复解析相同输入、有效缓存及原快照比较不计次。")
    fresh = st.button("获取真实数据并筛选", type="primary", disabled=strategy is None or st.session_state["blocked"] or not confirm)
    with st.expander("比较修改前后 · 使用同一份数据解释变化"):
        st.caption("已有结果后再修改条件。原快照缺少新增指标时，选择补齐数据，两个方案会一起重算。")
        compare = st.button("使用原快照重算并比较", disabled=strategy is None or "result" not in st.session_state or st.session_state["blocked"] or not confirm)
        union = st.button("补齐新增指标，用新快照重算两方案", disabled=strategy is None or "result" not in st.session_state or st.session_state["blocked"] or not confirm)
    if fresh or compare or union:
        try:
            previous = st.session_state.get("result")
            if fresh or union:
                # 捕获只读参数，工作线程不访问Streamlit会话。
                operation = (lambda client: compare_with_new_snapshot(client, previous, strategy)) if union else (lambda client: run_screening(client, strategy))
                outcome = run_external_operation(settings, st.session_state["usage_session"], FuyaoClient, operation,
                    cached_operation=lambda: cached_screening(settings, strategy, previous if union else None))
                if union:
                    snapshot, baseline, result, changes = outcome
                else:
                    snapshot, result = outcome
                    baseline, changes = None, None
            else:
                snapshot, result = run_screening(None, strategy, st.session_state.get("snapshot"))
                changes = compare_results(previous, result)
                baseline = previous
            st.session_state["changes"] = changes
            st.session_state["comparison_base"] = baseline
            st.session_state["snapshot"],st.session_state["result"] = snapshot,result
            st.rerun()
        except ValidationError:
            st.error("数据结构校验失败，本次未生成新结果；请重新获取数据。")
        except (ProviderError, ValueError) as exc:
            st.error(str(exc))
            st.warning("本次执行未成功；下方如有结果仍是此前的旧结果。")
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
