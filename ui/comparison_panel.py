"""方案变化展示：把引擎的状态代码转换为可读表格。"""
import streamlit as st
from ui.layout import condition_rows


def render_comparison(baseline, result, changes):
    """展示同快照的两套条件和状态变化；不重新计算、不调用外部接口。"""
    st.subheader("条件变化带来了什么影响")
    st.caption("两套条件使用同一快照；补齐新增指标时，基准方案也已重新计算。")
    if baseline:
        left, right = st.columns(2)
        with left:
            st.markdown("**修改前**")
            st.dataframe(condition_rows(baseline.strategy), hide_index=True)
        with right:
            st.markdown("**修改后**")
            st.dataframe(condition_rows(result.strategy), hide_index=True)
    if not changes:
        st.info("本次修改没有改变任何股票的筛选状态。")
        return
    labels = {"selected": "入选", "excluded": "排除", "unknown": "无法判断"}
    names = {row.thscode: row.name for row in result.rows}
    st.dataframe([{"股票": names.get(item["thscode"], item["thscode"]),
                   "股票代码": item["thscode"], "修改前": labels[item["before"]],
                   "修改后": labels[item["after"]]} for item in changes], hide_index=True)
