"""隔离测试计数库，防止软件回归消耗真实演示额度。"""
import pytest
from services.usage_guard import _cached_guard


@pytest.fixture(autouse=True)
def isolate_usage_budget(tmp_path, monkeypatch):
    """每项测试使用独立磁盘计数；测试前后清理进程单例。"""
    monkeypatch.setenv('USAGE_DB_PATH',str(tmp_path/'test_usage.sqlite3'))
    _cached_guard.cache_clear()
    yield
    _cached_guard.cache_clear()
