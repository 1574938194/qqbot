"""Buddyproxy 管理接口，不输出账号标识、凭据或原始错误。"""
from urllib.parse import urlsplit, urlunsplit

import httpx


async def checkin(config):
    url = urlsplit(config.base_url)
    endpoint = urlunsplit((url.scheme, url.netloc, '/direct-admin/api/codebuddy/checkin', '', ''))
    auth = httpx.BasicAuth('admin', config.buddy_admin_password) if config.buddy_admin_password else None
    try:
        async with httpx.AsyncClient(timeout=60, trust_env=False, auth=auth) as client:
            response = await client.post(endpoint, json={})
        if response.status_code in (401, 403):
            return '签到认证失败，请检查 BUDDY_ADMIN_PASSWORD。'
        if response.status_code == 404:
            return '当前 buddyproxy 不支持签到接口，请升级后重试。'
        response.raise_for_status()
        data = response.json()
        summary = data['summary']
        if not isinstance(summary, dict):
            raise ValueError('invalid summary')
        counts = []
        for key, label in [('checkedIn', '新签'), ('alreadyDone', '已签'), ('unsupported', '不支持'), ('skipped', '跳过'), ('failed', '失败')]:
            value = summary.get(key, 0)
            if type(value) is not int or value < 0:
                raise ValueError('invalid count')
            if value:
                counts.append(f'{label} {value}')
        site = data.get('poolSite')
        label = {'domestic': '国内', 'global': '国际'}.get(site)
        return 'buddyproxy 签到：' + ('，'.join(counts) if counts else '没有可签到账号。') + (f'\n号池：{label}' if label else '') + ('\n国际站通常没有签到活动。' if site == 'global' else '')
    except httpx.TimeoutException:
        return '签到请求超时，部分账号可能已签到，请稍后重试确认。'
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return '签到失败，请检查 buddyproxy 状态后重试。'


async def pool(config, args=''):
    action = args.strip().lower()
    target = {'cn': 'domestic', 'domestic': 'domestic', 'global': 'global'}.get(action)
    if action not in ('', 'status') and not target:
        return '格式：/pool 查看当前号池；/pool cn 国内；/pool global 国际。'
    url = urlsplit(config.base_url)
    endpoint = urlunsplit((url.scheme, url.netloc, '/direct-admin/api/' + ('pool-site' if target else 'status'), '', ''))
    auth = httpx.BasicAuth('admin', config.buddy_admin_password) if config.buddy_admin_password else None
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False, auth=auth) as client:
            response = await client.post(endpoint, json={'site': target}) if target else await client.get(endpoint)
        if response.status_code in (401, 403):
            return '号池认证失败，请检查 BUDDY_ADMIN_PASSWORD。'
        response.raise_for_status()
        data = response.json()
        site = data['poolSite']
        if data.get('ok') is not True or site not in ('domestic', 'global') or (target and site != target):
            raise ValueError('unconfirmed site')
        label = '国内' if site == 'domestic' else '国际'
        return (f'已切换 buddyproxy 默认号池：{label}（{site}），配置已保存。下一次聊天和签到使用该号池。'
                if target else f'当前 buddyproxy 默认号池：{label}（{site}）。') + '\n显式模型区域前缀或区域绑定 Key 会覆盖默认号池。'
    except httpx.TimeoutException:
        return '号池请求超时，切换结果暂时无法确认，请用 /pool 查询。'
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return '号池查询或切换失败，请检查 buddyproxy 状态后用 /pool 确认。'
