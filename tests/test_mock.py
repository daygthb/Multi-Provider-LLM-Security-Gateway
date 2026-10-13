import httpx

from gateway.mock import app
from gateway.providers import Provider
from gateway.settings import Settings
from tests.test_providers import chat, config


async def test_real_mock_adapter_json_and_stream():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mock"
    ) as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/v1/models")).json()["data"][0]["id"] == "mock-model"
        provider = Provider(config(), client, Settings(environment="test"))
        for stream in [False, True]:
            result = await provider.complete(chat(stream))
            assert result.text == "Mock response: Hello"
            assert result.total_tokens > 0
