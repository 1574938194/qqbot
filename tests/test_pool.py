import json

import httpx
import pytest

from qqbot.checkin import pool
from qqbot.config import ADMIN, Settings
from qqbot.service import Service
from qqbot.store import Store


@pytest.mark.parametrize('arg,method,site', [('', 'GET', 'domestic'), ('status', 'GET', 'global'), ('cn', 'POST', 'domestic'), ('global', 'POST', 'global')])
async def test_pool_api(monkeypatch, arg, method, site):
    original = httpx.AsyncClient
    def handle(request):
        assert request.method == method
        assert request.headers['Authorization'].startswith('Basic ')
        if method == 'POST':
            assert request.url.path == '/direct-admin/api/pool-site'
            assert json.loads(request.content) == {'site': site}
        else:
            assert request.url.path == '/direct-admin/api/status'
        return httpx.Response(200, json={'ok': True, 'poolSite': site, 'apiKey': 'hidden-secret'})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(**kw, transport=httpx.MockTransport(handle)))
    result = await pool(Settings(buddy_admin_password='private'), arg)
    assert site in result
    assert 'hidden-secret' not in result and 'private' not in result
    assert ('配置已保存' in result) == (method == 'POST')


@pytest.mark.parametrize('status,payload', [(401, {}), (500, {}), (200, {'ok': False, 'poolSite': 'domestic'}), (200, {'ok': True, 'poolSite': 'global'})])
async def test_failure_is_not_success(monkeypatch, status, payload):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(**kw, transport=httpx.MockTransport(lambda r: httpx.Response(status, json=payload))))
    assert '已切换' not in await pool(Settings(), 'cn')


async def test_permissions_and_arguments(tmp_path, monkeypatch):
    calls = []
    async def fake(config, args):
        calls.append(args)
        return '号池结果'
    monkeypatch.setattr('qqbot.service.pool', fake)
    store = Store(str(tmp_path / 'db.sqlite3'))
    try:
        service = Service(store, None, Settings())
        assert await service.handle(123, '/pool cn') is None
        store.grant(123, True)
        assert '只有超级管理员' in await service.handle(123, '/pool global')
        assert await service.handle(ADMIN, '/pool cn', private=False) is None
        assert await service.handle(ADMIN, '/pool cn') == '号池结果'
        assert calls == ['cn'] and not store.history(ADMIN)
        assert '格式' in await pool(Settings(), 'unknown')
    finally:
        store.close()
