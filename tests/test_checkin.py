import httpx
import pytest

from qqbot.config import ADMIN, Settings
from qqbot.checkin import checkin
from qqbot.service import Service
from qqbot.store import Store


@pytest.mark.parametrize('status,payload,expected', [
    (200, {'summary': {'checkedIn': 2, 'alreadyDone': 1}, 'secret': 'do-not-show'}, '新签 2，已签 1'),
    (200, {'summary': {'unsupported': 1}}, '不支持 1'),
    (401, {}, '认证失败'), (404, {}, '不支持签到接口'),
    (500, {'message': 'do-not-show'}, '签到失败'),
    (200, {'summary': {'failed': 'do-not-show'}}, '签到失败'),
])
async def test_result(monkeypatch, status, payload, expected):
    original = httpx.AsyncClient
    def handle(request):
        assert request.url.path == '/direct-admin/api/codebuddy/checkin'
        assert request.method == 'POST'
        import json
        assert json.loads(request.content) == {}  # 跟随代理当前号池，不能固定为国际。
        assert request.headers['Authorization'].startswith('Basic ')
        return httpx.Response(status, json=payload)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(**kw, transport=httpx.MockTransport(handle)))
    result = await checkin(Settings(buddy_admin_password='private'))
    assert expected in result
    assert 'do-not-show' not in result
    assert 'private' not in result


async def test_permissions_and_no_history(tmp_path, monkeypatch):
    calls = []
    async def fake(config):
        calls.append(config)
        return '签到结果'
    monkeypatch.setattr('qqbot.service.checkin', fake)
    store = Store(str(tmp_path / 'test.db'))
    try:
        service = Service(store, None, Settings())
        assert await service.handle(123, '签到') is None
        store.grant(123, True)
        assert '只有超级管理员' in await service.handle(123, '签到')
        assert await service.handle(ADMIN, '签到', private=False) is None
        assert await service.handle(ADMIN, '签到', self_id=ADMIN) is None
        assert await service.handle(ADMIN, '签到') == '签到结果'
        assert '未知命令' in await service.handle(ADMIN, '/checkin')
        assert len(calls) == 1
        assert store.history(ADMIN) == []
    finally:
        store.close()


async def test_timeout_does_not_expose_error(monkeypatch):
    original = httpx.AsyncClient
    def handle(request):
        raise httpx.ReadTimeout('secret-upstream-error', request=request)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(**kw, transport=httpx.MockTransport(handle)))
    result = await checkin(Settings())
    assert '部分账号可能已签到' in result
    assert 'secret' not in result
