"""结果展示和逐字段证据查看。"""
import streamlit as st
from core.result_explainer import explain_condition
from ui.layout import condition_rows

LABELS = {"selected":"入选", "excluded":"排除", "unknown":"无法判断"}


def render_results(result, snapshot):
    """展示绑定条件和快照时间，防止草案变化误标旧结果。"""
    st.divider()
    st.subheader("03 · 查看结果与证据")
    st.caption(f"固定六只开发样本 · 取数时间 {snapshot.created_at} · 快照 {snapshot.id[:12]}")
    st.caption("估值时间是供应商批次更新时间；逐股成交时间和估值分母未独立核验。结果不代表全市场筛选。")
    if snapshot.history_cutoff:
        st.caption(f"历史行情查询截止日：{snapshot.history_cutoff}；实际最后交易日见波动率证据。财务报告期：{snapshot.report_period}（累计）。")
    for error in snapshot.source_errors:
        st.error(error)
    if snapshot.source_errors:
        st.warning("部分数据源调用失败；相应条件保持未知，不是正常的零候选结果。")
    columns = st.columns(3)
    for column, (status,label) in zip(columns, LABELS.items()):
        column.metric(label, sum(r.status == status for r in result.rows))
    st.dataframe([{"股票代码":r.thscode,"股票名称":r.name,"结论":LABELS[r.status]} for r in result.rows], hide_index=True)
    with st.expander("查看本次实际执行的条件"):
        st.dataframe(condition_rows(result.strategy), hide_index=True)
    for row in result.rows:
        with st.expander(f"{row.name} ({row.thscode}) · {LABELS[row.status]}"):
            for evaluation in row.evaluations:
                st.write(explain_condition(evaluation))
                if evaluation.actual.reason:
                    st.caption(evaluation.actual.reason)
                if evaluation.actual.evidence:
                    with st.expander(f"查看条件 {evaluation.condition.id} 的原字段与来源"):
                        evidence = evaluation.actual.evidence
                        formulas = sorted({e.formula for e in evidence if e.formula})
                        for formula in formulas:
                            st.caption(formula)
                        st.dataframe([{"原字段":e.raw_field, "原值（未舍入）":e.raw_value,
                                       "单位":e.unit, "报告期":e.report_period or "不适用"}
                                      for e in evidence], hide_index=True, height=240)
                        # 同一请求只显示一次元数据，避免 61 条日线重复铺满页面。
                        metadata = {}
                        for e in evidence:
                            metadata[(e.endpoint,e.request_id)] = {"来源":e.source,"接口":e.endpoint,
                                "请求参数":dict(e.params),"请求编号":e.request_id,"取数时间":e.retrieved_at,
                                "供应商时间原值":e.source_time,"供应商披露时间原值":e.report_date,"口径提示":e.note}
                        for item in metadata.values():
                            st.json(item, expanded=False)
