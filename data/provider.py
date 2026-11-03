"""扶摇 HTTPS 客户端：业务错误和传输失败均不能伪装成空结果。"""
import re
from datetime import datetime, timezone
import httpx
from config import build_ssl_context

BASE_URL = "https://fuyao.aicubes.cn"
VALUATIONS = "/api/a-share/valuations/snapshot"
INCOME = "/api/a-share/financials/income-statements"
INDICATORS = "/api/a-share/financials/indicators"
HISTORY = "/api/a-share/prices/historical"
CALENDAR = "/api/a-share/calendar/trading-days"
ENDPOINTS = {VALUATIONS, INCOME, INDICATORS, HISTORY, CALENDAR}


class ProviderError(Exception):
    """只携带安全的错误类别与消息，不保留密钥或完整响应。"""
    def __init__(self, category, message):
        """构造供页面展示的安全异常。"""
        self.category = category
        super().__init__(message)


class FuyaoClient:
    """固定域名、有限超时；当前版本不自动重试，失败交由用户重试。"""
    def __init__(self, settings, transport=None):
        """依赖注入 transport 供离线测试；真实请求使用可信 CA。"""
        if not settings.fuyao_api_key:
            raise ProviderError("configuration", "尚未配置扶摇密钥")
        self.client = httpx.Client(base_url=BASE_URL, timeout=15,
                                  headers={"X-api-key": settings.fuyao_api_key},
                                  verify=build_ssl_context(settings), transport=transport)

    def close(self):
        """释放连接池。"""
        self.client.close()

    def request_json(self, path, params):
        """校验 HTTP、JSON、业务码和数据结构，并附取数时间。"""
        if path not in ENDPOINTS:
            raise ValueError("当前客户端尚未启用此端点")
        try:
            response = self.client.get(path, params=params)
        except httpx.TimeoutException:
            raise ProviderError("timeout", "扶摇请求超时，请稍后重试") from None
        except httpx.HTTPError:
            raise ProviderError("network", "扶摇连接失败，请检查网络或证书配置") from None
        if response.status_code == 429:
            raise ProviderError("rate_limit", "扶摇接口限流，请稍后重试")
        if response.status_code in (401, 403):
            raise ProviderError("authentication", "扶摇鉴权或接口权限不足")
        if response.status_code != 200:
            raise ProviderError("http", f"扶摇服务返回 HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            raise ProviderError("format", "扶摇返回的内容不是有效 JSON") from None
        if not isinstance(payload, dict):
            raise ProviderError("format", "扶摇响应结构不符合契约")
        if type(payload.get("code")) is not int or payload["code"] != 0:
            # 不回显供应商自由文本，避免把鉴权信息带到页面。
            raise ProviderError("business", "扶摇业务请求失败，未生成筛选结果")
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("abilities" if path == INDICATORS else "item"), list):
            raise ProviderError("format", "扶摇数据列表缺失或结构异常")
        return {"data": data, "request_id": payload.get("request_id"),
                "retrieved_at": datetime.now(timezone.utc).isoformat(), "endpoint": path, "params": params}

    def get_valuations(self, codes):
        """每批 1–100 个标准 A 股代码；去重后请求估值快照。"""
        codes = tuple(dict.fromkeys(codes))
        if not 1 <= len(codes) <= 100 or any(not re.fullmatch(r"\d{6}\.(SH|SZ)", c) for c in codes):
            raise ValueError("股票代码格式或批次数量不合法")
        return self.request_json(VALUATIONS, {"thscodes": ",".join(codes)})


    def check_code(self, code):
        """只接受标准沪深股票代码。"""
        if not re.fullmatch(r"\d{6}\.(SH|SZ)", code):
            raise ValueError("股票代码格式不合法")

    def get_income(self, code):
        """按季度末取最近八期累计利润表；口径见数据核验记录。"""
        self.check_code(code)
        return self.request_json(INCOME, {"thscode": code, "period": "quarterly", "limit": 8})

    def get_indicators(self, code, report):
        """仅查询固定报告期，用于与金额复算值交叉检查。"""
        self.check_code(code)
        if report != "2026-3":
            raise ValueError("当前仅支持 2026 年前三季度累计报告期")
        return self.request_json(INDICATORS, {"thscode": code, "report": report})

    def get_calendar(self, start, end):
        """查询真实交易日历，不用工作日猜测节假日。"""
        if start > end:
            raise ValueError("日期范围倒置")
        return self.request_json(CALENDAR, {"start_date": start.strftime("%Y%m%d"), "end_date": end.strftime("%Y%m%d")})

    def get_history(self, code, start, end):
        """前复权日线；区间端点以北京时间毫秒表达。"""
        from datetime import time
        from zoneinfo import ZoneInfo
        self.check_code(code)
        if start > end:
            raise ValueError("日期范围倒置")
        zone = ZoneInfo("Asia/Shanghai")
        start_ms = int(datetime.combine(start, time.min, zone).timestamp() * 1000)
        end_ms = int(datetime.combine(end, time.max, zone).timestamp() * 1000)
        return self.request_json(HISTORY, {"thscode": code, "interval": "1d", "adjust": "forward", "start": start_ms, "end": end_ms})
