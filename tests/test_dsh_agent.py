import json
from dataclasses import replace
from unittest.mock import AsyncMock
import httpx
import pytest
from qqbot.config import ADMIN, Settings
from qqbot.dsh_agent import DshAgent
from qqbot.llm import ModelError
from qqbot.image_generation import ImageReply

async def test_dsh_client_auth_payload_and_failure(monkeypatch):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'finish_reason':'completed','text':'实际结果'})
    client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr('qqbot.dsh_agent.httpx.AsyncClient',lambda **kwargs:client)
    agent=DshAgent(Settings(dsh_token='test-token'))
    task={'uid':ADMIN,'id':'abcd1234abcd','instruction':'核验文件'}
    assert await agent.run(task,'abcd12345678')=='实际结果'
    assert calls[0].headers['Authorization']=='Bearer test-token'
    payload=json.loads(calls[0].content)
    assert payload==dict(uid=ADMIN,task_id=task['id'],run_id='abcd12345678',instruction='核验文件')
    assert 'prompt' not in payload
    with pytest.raises(ModelError,match='管理员'):
        await agent.run({**task,'uid':123},'abcd12345678')

@pytest.mark.parametrize('url',['https://public.test','http://8.8.8.8','http://127.0.0.1:32128/path','http://key@localhost:32128'])
def test_dsh_only_loopback(url):
    with pytest.raises(ValueError,match='DSH_BASE_URL'):
        Settings(dsh_base_url=url)
