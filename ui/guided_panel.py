"""面向新手的三步澄清界面；规则模板与自由文本AI解析明确区分。"""
import streamlit as st
from core.guided_intent import GUIDED_ORIGINAL, build_guided_draft


def render_guided_panel():
    """返回已完成的条件草案；未完成时停止后续执行页面的渲染。"""
    st.subheader("把三个想法说明白")
    st.write(f"你正在细化的想法：{GUIDED_ORIGINAL}。")
    st.caption("这是固定问题引导，按你的选择生成条件，不调用AI。若你原先输入了其他需求，进入此流程意味着另建方案，不会自动保留那些条件。")
    st.markdown("**1 · 你想看哪一种经营变化？**")
    st.write("收入可以理解为公司卖产品、提供服务取得的收入；利润还要考虑成本等因素。收入增加，不代表利润一定增加。")
    growth = st.radio("选择经营变化", ["收入增加", "利润增加", "收入和利润都增加", "暂不筛经营变化"], index=None, key="guide_growth")
    st.caption("当前只能比较2026年1–9月与2025年同期的累计值。选择‘增加’表示同比大于0%，不能说明每个季度都在变好。亏损转盈利等非正基数情况暂不按普通同比判断。")
    st.markdown("**2 · 你想怎样检查估值？**")
    st.write("市盈率把股价与每股盈利作比较。它不是股票价格，也不能只凭一个数字判断贵不贵。当前没有已核验的同行比较功能。")
    valuation = st.radio("选择估值方式", ["教学示例", "自定上限", "暂不筛估值", "同行比较"], index=None,
        format_func=lambda x: {"教学示例":"先体验教学示例：市盈率大于0且小于25倍（不是合理估值标准）", "自定上限":"我来填写市盈率上限", "暂不筛估值":"我还不确定，明确暂不筛估值", "同行比较":"我希望与同行公司比较（当前不支持）"}[x], key="guide_valuation")
    pe_limit = st.text_input("市盈率上限（倍）", key="guide_pe") if valuation == "自定上限" else ""
    if valuation == "同行比较":
        st.warning("这项要求目前不能完成，不会用固定25倍冒充同行比较。你可以选择另一种方式，或明确暂不筛估值。")
    st.markdown("**3 · 你想怎样检查价格波动？**")
    st.write("波动率描述过去价格上下变化的幅度。数值较低只说明这一段历史的波动较小，不代表以后不会下跌。")
    stability = st.radio("选择波动方式", ["教学示例", "自定上限", "暂不筛波动"], index=None,
        format_func=lambda x: {"教学示例":"先体验教学示例：60日年化波动率小于30%（不是安全标准）", "自定上限":"我来填写年化波动率上限", "暂不筛波动":"我还不确定，明确暂不筛波动"}[x], key="guide_stability")
    vol_limit = st.text_input("年化波动率上限（%）", key="guide_vol") if stability == "自定上限" else ""
    st.caption("60日指60个交易日的收益率；年化是统一计量方式。30%不表示未来会涨跌30%，也不表示最多亏损30%。数据不足时显示无法判断。")
    # 与控件生命周期分开保存，返回修改时保持上下文；不代表已确认执行。
    st.session_state["guided_answers"] = {
        "guide_growth": growth, "guide_valuation": valuation,
        "guide_stability": stability, "guide_pe": pe_limit, "guide_vol": vol_limit,
    }
    draft = None
    try:
        draft = build_guided_draft(growth, valuation, stability, pe_limit, vol_limit)
    except ValueError as exc:
        st.info(str(exc))
    if draft:
        st.markdown("**请看：你的想法将被具体理解成什么**")
        for note in draft.assumptions:
            st.write(note)
        st.caption("下一步仍可编辑条件；只有再次勾选确认并点击取数，才会执行。选择暂不筛的项目不会被当成已经满足。")
    if st.button("把这些选择生成条件", disabled=draft is None, type="primary"):
        return draft
    if st.button("返回原方案，不应用这些选择"):
        st.session_state["guide_active"] = False
        st.rerun()
    st.stop()
