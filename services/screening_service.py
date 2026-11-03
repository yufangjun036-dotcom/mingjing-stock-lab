"""按需取数、保存不可变快照，并在同一数据上比较条件变化。"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from core.condition_validator import validate_strategy
from core.screening_engine import screen
from core.schemas import MetricValue, StockRecord
from data.provider import ProviderError
from data.normalizer import normalize_stock, build_snapshot, normalize_financials, normalize_history

from services.snapshot_cache import namespace, cache_key, get_snapshot, put_snapshot, flight_lock

FINANCIALS = {"revenue_yoy", "profit_yoy", "gross_margin"}


def required_sources(strategy):
    """按指标收集依赖，避免估值策略也请求六份历史和财报。"""
    metrics = {c.metric_id for c in strategy.conditions}
    sources = {"valuations"}
    if metrics & FINANCIALS:
        sources.update(("income", "indicators"))
    if "volatility_60d" in metrics:
        sources.update(("calendar", "history"))
    return sources


def fetch_snapshot(client, strategy, extra_strategy=None, now=None):
    """真实客户端复用有效快照，并合并同数据范围的同时取数。"""
    scope = getattr(client, "cache_namespace", None)
    if not isinstance(scope, str) or now is not None:
        return _fetch_snapshot_uncached(client, strategy, extra_strategy, now)
    key = cache_key(scope, strategy, extra_strategy)
    lock = flight_lock(key)
    while not lock.acquire(timeout=0.1):
        cancelled = getattr(client, 'cancel_event', None)
        if cancelled is not None and cancelled.is_set():
            raise ProviderError('cancelled', '本次取数已取消')
    try:
        cached = get_snapshot(key)
        if cached is not None:
            return cached
        snapshot = _fetch_snapshot_uncached(client, strategy, extra_strategy, now)
        cancelled = getattr(client, 'cancel_event', None)
        if cancelled is None or not cancelled.is_set():
            put_snapshot(key, snapshot)
        return snapshot
    finally:
        lock.release()


def cached_screening(settings, strategy, baseline=None):
    """页面联网前查缓存：命中不创建客户端、不消耗外部调用额度。"""
    validate_strategy(strategy)
    snapshot = get_snapshot(cache_key(namespace(settings.fuyao_api_key), strategy,
                                      baseline.strategy if baseline else None))
    if snapshot is None:
        return None
    result = screen(snapshot, strategy)
    if baseline is None:
        return snapshot, result
    old = screen(snapshot, baseline.strategy)
    return snapshot, old, result, compare_results(old, result)


def _fetch_snapshot_uncached(client, strategy, extra_strategy=None, now=None):
    """最大两个股票任务并发；部分失败保留所有股票及安全错误。"""
    validate_strategy(strategy)
    if extra_strategy:
        validate_strategy(extra_strategy)
    metrics = {"pe_ttm", "pb_mrq"} | {c.metric_id for c in strategy.conditions}
    if extra_strategy:
        metrics |= {c.metric_id for c in extra_strategy.conditions}
    if metrics & FINANCIALS:
        metrics |= FINANCIALS
    universe = json.loads((Path(__file__).resolve().parents[1] / "data/universe.json").read_text())
    now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    # 保守地只用北京时间昨天及以前的日线，避免当天未完成 K 线。
    cutoff = now.astimezone(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)
    start = cutoff - timedelta(days=220)
    valuation = client.get_valuations(universe["codes"])
    calendar, errors = None, []
    if "volatility_60d" in metrics:
        try:
            calendar = client.get_calendar(start, cutoff)
        except ProviderError as exc:
            errors.append(f"交易日历：{exc}")

    def fetch_stock(code):
        """单股票任务按顺序请求，避免把端点并发扩大到线程数之外。"""
        base = normalize_stock(code, valuation)
        values, local_errors = dict(base.metrics), []
        if metrics & FINANCIALS:
            income, indicators = None, None
            try:
                income = client.get_income(code)
                indicators = client.get_indicators(code, strategy.report_period)
            except ProviderError as exc:
                local_errors.append(f"{code} 财务：{exc}")
            if income:
                values.update(normalize_financials(code, income, indicators, strategy.report_period))
            else:
                values.update({metric: MetricValue(quality="missing", reason="财务接口调用失败") for metric in FINANCIALS})
        if "volatility_60d" in metrics:
            if calendar is None:
                values["volatility_60d"] = MetricValue(quality="missing", reason="交易日历调用失败，不能确认连续交易日")
            else:
                try:
                    history = client.get_history(code, start, cutoff)
                    if history["data"].get("thscode") != code:
                        values["volatility_60d"] = MetricValue(quality="conflict", reason="历史行情返回股票不匹配")
                    else:
                        values["volatility_60d"] = normalize_history(history, calendar, cutoff)
                except ProviderError as exc:
                    local_errors.append(f"{code} 历史行情：{exc}")
                    values["volatility_60d"] = MetricValue(quality="missing", reason="历史行情接口调用失败")
        return StockRecord(thscode=code, name=base.name, metrics=tuple(sorted(values.items()))), local_errors

    with ThreadPoolExecutor(max_workers=2) as pool:
        collected = list(pool.map(fetch_stock, universe["codes"]))
    records = []
    for record, local_errors in collected:
        records.append(record)
        errors.extend(local_errors)
    return build_snapshot(records, now.isoformat(), source_errors=errors, available_metrics=metrics,
                          history_cutoff=cutoff.isoformat() if "volatility_60d" in metrics else None)


def run_screening(client, strategy, snapshot=None):
    """快照不包含新增指标时显式报错，不偷偷混入新数据。"""
    validate_strategy(strategy)
    if snapshot is None:
        snapshot = fetch_snapshot(client, strategy)
    missing = {c.metric_id for c in strategy.conditions} - set(snapshot.available_metrics)
    if missing:
        raise ValueError("原快照没有新增指标，请使用联合新快照重算两个方案")
    return snapshot, screen(snapshot, strategy)


def compare_results(base, new):
    """拒绝跨快照比较，返回每只发生变化的股票前后状态。"""
    if (base.snapshot_id, base.strategy.universe_id, base.strategy.report_period) != (
            new.snapshot_id, new.strategy.universe_id, new.strategy.report_period):
        raise ValueError("条件影响比较必须使用相同股票池、报告期和数据快照")
    old = {r.thscode: r.status for r in base.rows}
    if set(old) != {r.thscode for r in new.rows}:
        raise ValueError("结果股票范围不一致")
    return [{"thscode": r.thscode, "before": old[r.thscode], "after": r.status}
            for r in new.rows if old[r.thscode] != r.status]


def compare_with_new_snapshot(client, baseline, strategy):
    """以 A/B 联合依赖取一次新数据，再重算两方案后比较。"""
    snapshot = fetch_snapshot(client, strategy, extra_strategy=baseline.strategy)
    old = screen(snapshot, baseline.strategy)
    new = screen(snapshot, strategy)
    return snapshot, old, new, compare_results(old, new)
