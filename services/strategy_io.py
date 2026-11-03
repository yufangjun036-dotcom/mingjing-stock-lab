"""版本化方案导入导出，不联网、不执行上传文件中的代码。"""
from core.schemas import Strategy
from core.condition_validator import validate_strategy


def export_strategy(strategy):
    """只导出条件白名单字段，无密钥和金融原始响应。"""
    return strategy.model_dump_json(indent=2).encode("utf-8")


def import_strategy(content):
    """限制文件大小，严格校验后返回待用户确认的方案。"""
    if len(content) > 100 * 1024:
        raise ValueError("方案文件不能超过 100 KB")
    return validate_strategy(Strategy.model_validate_json(content))
