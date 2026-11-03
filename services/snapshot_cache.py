"""五分钟进程内快照缓存：按凭据、范围、指标与日期隔离，不缓存失败快照。"""
from collections import OrderedDict
from hashlib import sha256
from threading import Lock
from time import monotonic
from datetime import datetime
from zoneinfo import ZoneInfo

TTL_SECONDS = 300
_CACHE = OrderedDict()
_LOCK = Lock()
# 固定数量锁避免不同策略无限生成锁对象；碰撞只影响速度，不影响数据隔离。
_FLIGHTS = [Lock() for _ in range(16)]


def namespace(api_key):
    """只在内存中使用不可逆凭据摘要，不输出或持久化密钥。"""
    return sha256(api_key.encode()).hexdigest()


def cache_key(scope, strategy, extra=None):
    """条件阈值不影响原数据；指标与报告期影响，跨北京时间日期不复用。"""
    metrics = {'pe_ttm', 'pb_mrq'} | {c.metric_id for c in strategy.conditions}
    if extra:
        metrics |= {c.metric_id for c in extra.conditions}
    if metrics & {'revenue_yoy', 'profit_yoy', 'gross_margin'}:
        metrics |= {'revenue_yoy', 'profit_yoy', 'gross_margin'}
    return (scope, strategy.universe_id, strategy.report_period, tuple(sorted(metrics)),
            datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat())


def get_snapshot(key):
    """仅返回仍有效的独立副本；不修改原始采集时间。"""
    with _LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            return None
        saved, snapshot = entry
        if monotonic() - saved >= TTL_SECONDS:
            del _CACHE[key]
            return None
        _CACHE.move_to_end(key)
        return snapshot.model_copy(deep=True)


def put_snapshot(key, snapshot):
    """接口失败不缓存；有效但业务字段未知仍保留原质量信息。"""
    if snapshot.source_errors:
        return
    with _LOCK:
        _CACHE[key] = (monotonic(), snapshot.model_copy(deep=True))
        _CACHE.move_to_end(key)
        while len(_CACHE) > 8:
            _CACHE.popitem(last=False)


def flight_lock(key):
    """同一键的同时冷查询共享取数结果，最多保留八份快照。"""
    return _FLIGHTS[hash(key) % len(_FLIGHTS)]
