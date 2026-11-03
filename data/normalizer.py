"""把原始字段转为带证据的指标，保留缺失与冲突。"""
import hashlib
import json
from decimal import Decimal, InvalidOperation
from statistics import stdev
from math import sqrt
from core.schemas import Evidence, MetricValue, StockRecord, DatasetSnapshot


def parse_decimal(raw):
    """有限数值转 Decimal；缺失或非法值返回 None，绝不填零。"""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = Decimal(str(raw))
        return value if value.is_finite() else None
    except InvalidOperation:
        return None


def compute_yoy(current, prior, evidence=(), verified=False):
    """只有口径确认且前期基数大于零时才计算普通同比。"""
    current, prior = parse_decimal(current), parse_decimal(prior)
    if not verified:
        return MetricValue(quality="unverified", reason="财务累计口径待原始公告核验", evidence=evidence)
    if current is None or prior is None:
        return MetricValue(quality="missing", reason="缺少当期或上年同期数值", evidence=evidence)
    if prior <= 0:
        return MetricValue(quality="not_applicable", reason="上年同期非正，不能作为普通增长率筛选", evidence=evidence)
    return MetricValue(value=(current / prior - 1) * 100, quality="valid", evidence=evidence)


def compute_gross_margin(revenue, costs, evidence=(), verified=False):
    """按收入和成本计算毛利率；银行等缺成本时保持未知。"""
    revenue, costs = parse_decimal(revenue), parse_decimal(costs)
    if not verified:
        return MetricValue(quality="unverified", reason="财务口径待核验", evidence=evidence)
    if revenue is None or costs is None:
        return MetricValue(quality="missing", reason="营业收入或营业成本缺失", evidence=evidence)
    if revenue <= 0:
        return MetricValue(quality="not_applicable", reason="营业收入非正", evidence=evidence)
    return MetricValue(value=(revenue - costs) / revenue * 100, quality="valid", evidence=evidence)


def compute_volatility(prices, trading_days, evidence=()):
    """输入为日期-价格对与已完成交易日清单；检查最后 61 日连续性。"""
    days = sorted(set(trading_days))[-61:]
    pairs = list(prices)
    if len(days) < 61:
        return MetricValue(quality="missing", reason="不足 61 个交易日", evidence=evidence)
    mapping = {}
    for day, raw in pairs:
        if day in mapping:
            return MetricValue(quality="conflict", reason="历史价格日期重复", evidence=evidence)
        mapping[day] = parse_decimal(raw)
    values = [mapping.get(day) for day in days]
    if any(value is None or value <= 0 for value in values):
        return MetricValue(quality="missing", reason="交易日价格缺失或非正", evidence=evidence)
    returns = [float(values[i] / values[i - 1] - 1) for i in range(1, 61)]
    return MetricValue(value=Decimal(str(stdev(returns) * sqrt(252) * 100)), quality="valid", evidence=evidence)


def normalize_stock(code, envelope):
    """按预定股票池合并估值数据；未返回、重复股票均显式标记。"""
    rows = [row for row in envelope["data"]["item"] if isinstance(row, dict) and row.get("thscode") == code]
    row = rows[0] if len(rows) == 1 else {}
    values = []
    for field in ("pe_ttm", "pb_mrq"):
        raw = row.get(field)
        value = parse_decimal(raw)
        quality = "conflict" if len(rows) > 1 else "valid" if value is not None else "missing"
        reason = "返回了重复股票记录" if len(rows) > 1 else "" if value is not None else "供应商未返回有效字段"
        if quality == "valid":
            timestamp = envelope["data"].get("timestamp")
            try:
                from datetime import datetime
                age = datetime.fromisoformat(envelope["retrieved_at"]).timestamp() - float(timestamp) / 1000
                if age > 7 * 86400:
                    quality, reason = "stale", "供应商批次时间超过 7 天，按产品时效规则暂停筛选"
                elif age < -86400:
                    quality, reason = "conflict", "供应商批次时间异常超前"
            except (TypeError, ValueError, OverflowError):
                quality, reason = "unverified", "供应商批次时间缺失或无法解析"
        evidence = Evidence(endpoint=envelope["endpoint"], request_id=envelope["request_id"],
                            retrieved_at=envelope["retrieved_at"],
                            source_time=str(envelope["data"].get("timestamp")) if envelope["data"].get("timestamp") is not None else None,
                            raw_field=f"{code}.{field}", raw_value=str(raw) if raw is not None else None, unit="倍")
        values.append((field, MetricValue(value=value, quality=quality, reason=reason, evidence=(evidence,))))
    return StockRecord(thscode=code, name=row.get("name") or code, metrics=tuple(values))


def build_snapshot(records, created_at, source_errors=(), available_metrics=("pe_ttm", "pb_mrq"), history_cutoff=None):
    """内容、质量、取数时间共同生成快照标识；结果不可原地修改。"""
    records = tuple(sorted(records, key=lambda record: record.thscode))
    payload = {"records": [r.model_dump(mode="json") for r in records], "created_at": created_at,
               "available_metrics": sorted(available_metrics), "history_cutoff": history_cutoff, "source_errors": list(source_errors), "universe_id": "a_share_demo_v1", "report_period": "2026-3"}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return DatasetSnapshot(id=digest, created_at=created_at, records=records, source_errors=tuple(source_errors), available_metrics=tuple(sorted(available_metrics)), history_cutoff=history_cutoff)


def source_evidence(envelope, field, raw, unit, report=None, formula=None, report_date=None):
    """统一保留请求参数、原字段、时间和单位，不包含鉴权头。"""
    return Evidence(endpoint=envelope["endpoint"], request_id=envelope.get("request_id"),
        retrieved_at=envelope["retrieved_at"], source_time=str(envelope["data"].get("timestamp")) if envelope["data"].get("timestamp") is not None else None,
        params=tuple((key, str(value)) for key,value in sorted(envelope.get("params", {}).items())),
        raw_field=field, raw_value=str(raw) if raw is not None else None, unit=unit,
        report_period=report, formula=formula, report_date=str(report_date) if report_date is not None else None,
        note="财务按年初至报告期末累计；供应商披露日期不能直接当历史首次披露时间" if report else "")


def select_report_pair(rows, report):
    """准确选择本年与上年同季度；重复记录、币种和期间冲突报错。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    year, quarter = map(int, report.split("-"))
    pair = []
    for selected_year in (year, year - 1):
        matches = [row for row in rows if isinstance(row, dict) and row.get("fiscal_year") == selected_year
                   and row.get("fiscal_period") == f"Q{quarter}"]
        if len(matches) > 1:
            raise ValueError("同报告期存在重复记录")
        if not matches:
            return None, None
        row = matches[0]
        if row.get("currency") != "CNY" or row.get("period") != "quarterly":
            raise ValueError("财报币种或期间类型不匹配")
        try:
            period_end = datetime.fromtimestamp(row["period_end_ms"] / 1000, ZoneInfo("Asia/Shanghai")).date()
        except (TypeError, ValueError, KeyError, OverflowError):
            raise ValueError("报告期末时间缺失或无效") from None
        if (period_end.year, period_end.month, period_end.day) != (selected_year, 9, 30):
            raise ValueError("报告期字段与期末日期冲突")
        pair.append(row)
    return tuple(pair)


def normalize_financials(code, income, indicators, report):
    """金额复算并与同源指标交叉验证；原文核验为样本验证而非逐股审计。"""
    fields = {"revenue_yoy": ("operating_income", "calculate_operating_income_yoy_growth_ratio"),
              "profit_yoy": ("parent_holder_net_profit", "calculate_parent_holder_net_profit_yoy_growth_ratio"),
              "gross_margin": ("operating_income", "sale_gross_margin")}
    try:
        current, prior = select_report_pair(income["data"]["item"], report)
        if current and any(row.get("thscode") != code for row in (current, prior)):
            raise ValueError("财报股票代码与请求不一致")
    except ValueError as exc:
        return {metric: MetricValue(quality="conflict", reason=str(exc)) for metric in fields}
    if current is None:
        return {metric: MetricValue(quality="missing", reason="缺少指定报告期或上年同期财报") for metric in fields}
    if indicators and (indicators["data"].get("thscode") != code or indicators["data"].get("report") != report):
        return {metric: MetricValue(quality="conflict", reason="财务指标代码或报告期不一致") for metric in fields}
    lookup = {}
    if indicators:
        for group in indicators["data"]["abilities"]:
            # 外层列表合法不代表嵌套列表合法；结构异常须显式标冲突，不能崩溃或当普通缺失。
            if not isinstance(group, dict) or not isinstance(group.get("indicators"), list):
                return {metric: MetricValue(quality="conflict", reason="财务指标分组结构异常") for metric in fields}
            for indicator in group["indicators"]:
                if not isinstance(indicator, dict) or not isinstance(indicator.get("index_id"), str):
                    return {metric: MetricValue(quality="conflict", reason="财务指标条目结构异常") for metric in fields}
                lookup.setdefault(indicator["index_id"], []).append(indicator.get("value"))
    results = {}
    for metric, (field, index_id) in fields.items():
        if metric == "gross_margin":
            inputs = ((current, "operating_income"), (current, "operating_costs"))
            formula = "(营业收入-营业成本)/营业收入×100，2026 年 1–9 月累计"
        else:
            inputs = ((current, field), (prior, field))
            formula = "(本年同期/上年同期-1)×100；年初至 9 月末累计；上年基数须为正"
        evidence = tuple(source_evidence(income, f"{code}.{row['fiscal_year']}Q3.{f}", row.get(f), "元", f"{row['fiscal_year']}-3",
                                         formula, row.get("report_date_ms")) for row,f in inputs)
        if metric == "gross_margin":
            value = compute_gross_margin(current.get("operating_income"), current.get("operating_costs"), evidence, verified=True)
        else:
            value = compute_yoy(current.get(field), prior.get(field), evidence, verified=True)
        samples = lookup.get(index_id, [])
        if value.quality == "valid":
            if indicators is None or len(samples) == 0 or (len(samples) == 1 and parse_decimal(samples[0]) is None):
                value = value.model_copy(update={"quality":"unverified", "reason":"复算值存在，但交叉核验指标缺失或调用失败"})
            elif len(samples) != 1:
                value = value.model_copy(update={"quality":"conflict", "reason":"交叉核验指标重复"})
            else:
                supplied = parse_decimal(samples[0])
                extra = source_evidence(indicators, f"{code}.{index_id}", samples[0], "%", report)
                value = value.model_copy(update={"evidence":value.evidence + (extra,)})
                tolerance = Decimal("0.0001" if metric == "gross_margin" else "0.000001")
                if abs(value.value - supplied) > tolerance:
                    value = value.model_copy(update={"quality":"conflict", "reason":"金额复算与供应商指标不一致"})
        results[metric] = value
    return results


def normalize_history(history, calendar, cutoff):
    """验证日历和复权元数据，保留 61 个价格及日历输入证据。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    if history["data"].get("adjust") != "forward" or history["data"].get("interval") != "1d":
        return MetricValue(quality="conflict", reason="日线复权方式或频率不一致")
    days, pairs = [], []
    zone = ZoneInfo("Asia/Shanghai")
    try:
        for row in calendar["data"]["item"]:
            day = datetime.fromtimestamp(row["date_ms"] / 1000, zone).date()
            if day.strftime("%Y%m%d") != row["date"] or day > cutoff:
                return MetricValue(quality="conflict", reason="交易日历日期字段冲突或越界")
            days.append(day)
        if len(days) != len(set(days)):
            return MetricValue(quality="conflict", reason="交易日历重复")
        for row in history["data"]["item"]:
            day = datetime.fromtimestamp(row["date_ms"] / 1000, zone).date()
            if day > cutoff:
                return MetricValue(quality="conflict", reason="历史价格超出已完成交易日范围")
            pairs.append((day, row.get("close_price")))
        if any(day not in set(days) for day,_ in pairs):
            return MetricValue(quality="conflict", reason="历史行情包含日历未标记的交易日")
    except (KeyError, TypeError, ValueError, OverflowError):
        return MetricValue(quality="conflict", reason="历史行情或日历结构异常")
    target = sorted(days)[-61:]
    evidence = (source_evidence(calendar, "item.date", ",".join(d.isoformat() for d in target), "交易日"),)
    formula = "最后61个交易日的60个简单收益率，样本标准差(ddof=1)×sqrt(252)×100；供应商前复权"
    evidence += tuple(source_evidence(history, f"{day.isoformat()}.close_price", price, "元/股", formula=formula)
                      for day,price in pairs if day in set(target))
    value = compute_volatility(pairs, days, evidence)
    if value.quality == "valid":
        value = value.model_copy(update={"reason":f"窗口 {target[0]} 至 {target[-1]}；前复权因子未独立重建"})
    return value
