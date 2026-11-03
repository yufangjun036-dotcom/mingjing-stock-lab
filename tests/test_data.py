"""HTTP 及业务异常测试，全部使用明确构造的响应。"""
import httpx
import pytest
from config import Settings
from data.provider import FuyaoClient, ProviderError
from data.normalizer import normalize_stock


@pytest.mark.parametrize("body", [{"code":1002}, {"code":3001}, {"code":0,"data":{}}, [], {"code":False}])
def test_business_errors(body):
    """HTTP 200 下业务错误和结构错误必须阻断。"""
    client = FuyaoClient(Settings(fuyao_api_key="test-only"), transport=httpx.MockTransport(lambda req: httpx.Response(200,json=body)))
    try:
        with pytest.raises(ProviderError):
            client.get_valuations(["600519.SH"])
    finally:
        client.close()


@pytest.mark.parametrize("status", [401,403,429,500])
def test_http_errors(status):
    """鉴权、限流与服务器故障不可产生正常结果。"""
    client = FuyaoClient(Settings(fuyao_api_key="test-only"), transport=httpx.MockTransport(lambda req: httpx.Response(status)))
    try:
        with pytest.raises(ProviderError):
            client.get_valuations(["600519.SH"])
    finally:
        client.close()


def test_empty_duplicate():
    """漏返回保留股票，重复股票标为冲突。"""
    env = {"endpoint":"/test","request_id":None,"retrieved_at":"2026-11-04","data":{"item":[]}}
    assert all(v.quality == "missing" for _,v in normalize_stock("600519.SH",env).metrics)
    env["data"]["item"] = [{"thscode":"600519.SH","pe_ttm":10}]*2
    assert all(v.quality == "conflict" for _,v in normalize_stock("600519.SH",env).metrics)
