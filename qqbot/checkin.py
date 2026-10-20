"""Buddyproxy 管理接口签到，不输出账号标识及原始错误。"""
from urllib.parse import urlsplit, urlunsplit

import httpx


async def checkin(config):
    url = urlsplit(config.base_url)
    endpoint = urlunsplit((url.scheme, url.netloc, '/direct-admin/api/codebuddy/checkin', '', ''))
    auth = httpx.BasicAuth('admin', config.buddy_admin_password) if config.buddy_admin_password else None
    try:
        async with httpx.AsyncClient(timeout=60, trust_env=False, auth=auth) as client:
            response = await client.post(endpoint, json={'site': config.buddy_site})
        if response.status_code in (401, 403):
            return '签到认证失败，请检查 BUDDY_ADMIN_PASSWORD。'
        if response.status_code == 404:
            return '当前 buddyproxy 不支持签到接口，请升级后重试。'
        response.raise_for_status()
        summary = response.json()['summary']
        if not isinstance(summary, dict):
            raise ValueError('invalid summary')
        counts = []
        for key, label in [('checkedIn', '新签'), ('alreadyDone', '已签'), ('unsupported', '不支持'), ('skipped', '跳过'), ('failed', '失败')]:
            value = summary.get(key, 0)
            if type(value) is not int or value < 0:
                raise ValueError('invalid count')
            if value:
                counts.append(f'{label} {value}')
        return 'buddyproxy 签到：' + ('，'.join(counts) if counts else '没有可签到账号。') + ('\n国际站通常没有签到活动。' if config.buddy_site == 'global' else '')
    except httpx.TimeoutException:
        return '签到请求超时，部分账号可能已签到，请稍后重试确认。'
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return '签到失败，请检查 buddyproxy 状态后重试。'
