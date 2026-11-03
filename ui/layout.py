"""页面导航与范围说明；与数据计算分离，便于调整展示方式。"""
import streamlit as st


def render_header():
    """呈现产品入口和固定研究范围；完整口径放在侧栏以减少主流程干扰。"""
    st.caption("明镜 / 可解释的股票研究")
    st.title("把选股想法，变成可验证的条件")
    st.write("描述需求、确认条件，再用真实数据查看入选与排除的原因。")
    st.info("六只样本研究版 · 六项指标 · 2026 年前三季度累计财务；不代表全市场筛选。")
    with st.sidebar:
        st.header("明镜选股")
        st.caption("自然语言智能选股与策略解释器")
        st.divider()
        st.markdown("**工作流程**\n\n01 描述需求\n\n02 检查并确认条件\n\n03 查看结果与证据")
        with st.expander("数据口径与使用边界", expanded=False):
            st.write("估值：PE TTM / PB MRQ，单位倍。财务：收入同比、归母净利同比、毛利率，单位 %；原始金额为人民币元。上年利润非正时不计算普通同比。")
            st.write("波动率：截至北京时间昨天及以前，最后 61 个真实交易日收盘价产生 60 个简单收益率，样本标准差×√252×100。前复权因子未独立重建。")
            st.write("累计口径已用茅台公告抽样核对，未逐股审计。取数时会用利润表复算并与供应商指标交叉验证。报告期固定，不自动发现最新财报。")
        st.caption("AI 只提出条件草案。Python 执行筛选并保留证据。本产品不提供收益保证或买卖建议。")


def condition_rows(strategy):
    """将方案转为中文表格；仅改变展示，不更改原始阈值及运算符。"""
    from core.metrics import get_metric
    return [{"指标": get_metric(c.metric_id).name, "关系": c.operator,
             "阈值": str(c.value), "单位": get_metric(c.metric_id).unit}
            for c in strategy.conditions]
