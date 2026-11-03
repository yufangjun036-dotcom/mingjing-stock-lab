"""验收补充：深层接口格式异常及传输失败，全部为构造异常数据。"""
import httpx
import pytest
from config import Settings
from data.provider import FuyaoClient, ProviderError
from data.normalizer import normalize_financials
from tests.test_financial_history import inputs


@pytest.mark.parametrize('malformed',[None,42,'invalid',{}])
def test_nested_indicators_malformed(malformed):
    """HTTP 顶层合法但嵌套指标不是列表时，应标冲突而非页面崩溃。"""
    income,indicators=inputs()
    indicators['data']['abilities'][0]['indicators']=malformed
    result=normalize_financials('600519.SH',income,indicators,'2026-3')
    assert all(v.quality=='conflict' for v in result.values())


@pytest.mark.parametrize('error',[httpx.ReadTimeout,httpx.ConnectError])
def test_transport_failure_safe(error):
    """传输失败必须转换为安全异常，不能携带请求密钥。"""
    def respond(request):
        """显式构造网络故障。"""
        raise error('secret-test-value',request=request)
    client=FuyaoClient(Settings(fuyao_api_key='secret-test-value'),transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(ProviderError) as caught:
            client.get_valuations(['600519.SH'])
        assert 'secret-test-value' not in str(caught.value)
    finally:
        client.close()


def test_malformed_json_safe():
    """非 JSON 服务页不能被当作空数据。"""
    client=FuyaoClient(Settings(fuyao_api_key='test'),transport=httpx.MockTransport(lambda req:httpx.Response(200,text='<html>Error</html>')))
    try:
        with pytest.raises(ProviderError) as caught:
            client.get_valuations(['600519.SH'])
        assert caught.value.category=='format'
    finally:
        client.close()
