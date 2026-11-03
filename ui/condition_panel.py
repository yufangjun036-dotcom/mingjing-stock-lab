"""用中文指标名称呈现条件，隔离页面表示与内部字段 ID。"""
import streamlit as st
from core.metrics import list_enabled_metrics


def render_condition_editor(conditions, revision):
    """中文展示单位；返回白名单字段，交给服务器执行结构校验。"""
    metrics = list_enabled_metrics()
    labels = {key: f"{metric.name}（{metric.unit}）" for key,metric in metrics.items()}
    ids = {label: key for key,label in labels.items()}
    rows = [{"指标":labels.get(row["metric_id"], row["metric_id"]), "关系":row["operator"], "阈值":str(row["value"])} for row in conditions]
    edited = st.data_editor(rows, num_rows="dynamic", hide_index=True,
        column_config={"指标":st.column_config.SelectboxColumn(options=list(ids),required=True),
                       "关系":st.column_config.SelectboxColumn(options=[">",">=","<","<=","="],required=True),
                       "阈值":st.column_config.TextColumn(required=True)}, key=f"editor_{revision}")
    return [{"metric_id":ids.get(row.get("指标"), ""), "operator":row.get("关系"), "value":row.get("阈值")} for row in edited]
