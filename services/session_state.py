"""恢复会话中的领域对象，兼容 Streamlit 热更新后的 Python 类重载。"""
from core.schemas import DatasetSnapshot, ScreeningResult
from core.intent_parser import IntentDraft


def rehydrate_state(state):
    """经 JSON 契约重建旧实例，避免旧类对象与新校验器类型不兼容。"""
    models = {'snapshot':DatasetSnapshot,'result':ScreeningResult,
              'comparison_base':ScreeningResult,'draft':IntentDraft}
    for key, model in models.items():
        value = state.get(key)
        if value is not None:
            # 序列化仅含数据契约字段，既不执行输入，也不重新联网。
            state[key] = model.model_validate_json(value.model_dump_json())
