"""区分模型补充说明与确定性执行规则，保留原文供核对。"""
import re
import streamlit as st

MISSING_DATA_POLICY = (
    "缺失数据处理（系统固定规则）：缺失值不当作0，对应条件记为“无法判断”，"
    "不是“不满足”。如果其他条件明确不满足，该公司仍被排除；"
    "如果没有不满足的条件但存在缺失，该公司整体为“无法判断”，不会入选。"
)


def render_assumptions(assumptions):
    """缺失相关的模型原文仅供核对，不把它显示为待用户接受的处理政策。"""
    for note in assumptions:
        if re.search(r"缺失|缺少数据|无数据|空值|未知|无法判断|missing|null|unknown|\bnan\b", note, re.I):
            st.caption("AI补充说明涉及数据缺失；实际处理请以下方系统固定规则为准。")
            # 不删除原始输出；混合在同一句中的其他假设仍可展开检查。
            with st.expander("查看AI原始补充说明（未经核验，不改变系统规则）"):
                st.text(note)
        else:
            st.warning(f"待确认假设：{note}")
