"""Ubuntu 无桌面云主机：安装 Mihomo 本机显式代理；不改系统路由或 QQBot 配置。"""
from pathlib import Path
import gzip
import hashlib
import json
import os
import pwd
import secrets
import shutil
import subprocess
import time
import urllib.request
import yaml

ARCHIVE = Path('/opt/qqbot/proxy-install/mihomo-linux-amd64-compatible-v1.19.33.gz')
SOURCE = Path('/opt/qqbot/proxy-install/proxy.txt')
EXPECTED = '386508bfb1c72c43b6a0eda73708ecdce82546581b0ebcb16366c53757c622b6'


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


def main():
    if os.geteuid() != 0:
        raise RuntimeError('requires root')
    target = Path('/etc/mihomo')
    unit = Path('/etc/systemd/system/mihomo.service')
    if (target/'config.yaml').exists() or unit.exists():
        raise RuntimeError('Existing installation: inspect before replacing')
    assert hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() == EXPECTED
    SOURCE.chmod(0o600)
    source = SOURCE.read_text(encoding='utf-8-sig').strip()
    fetched = SOURCE.with_name('subscription.yaml')
    if fetched.exists():
        raw = fetched.read_bytes()
    elif source.startswith(('https://', 'http://')):
        request = urllib.request.Request(source, headers={'User-Agent': 'clash.meta', 'Accept': 'application/yaml,text/yaml,*/*'})
        # 不让配置中的 URL 出现在命令行或错误输出。
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=30) as response:
            raw = response.read(10*1024*1024+1)
        if len(raw) > 10*1024*1024:
            raise RuntimeError('subscription too large')
        fetched.write_bytes(raw)
        fetched.chmod(0o600)
    else:
        raw = source.encode()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise RuntimeError('Clash YAML subscription required')
    proxies, providers = data.get('proxies') or [], data.get('proxy-providers') or {}
    if not isinstance(proxies, list) or not isinstance(providers, dict) or not (proxies or providers):
        raise RuntimeError('No usable nodes/providers')
    groups = data.get('proxy-groups') or []
    names = [p['name'] for p in proxies if isinstance(p, dict) and isinstance(p.get('name'), str)]
    if not names and not providers:
        raise RuntimeError('No valid nodes')
    name = 'QQBOT_CLOUD_PROXY_' + secrets.token_hex(3)
    group = {'name': name, 'type': 'url-test', 'url': 'https://www.gstatic.com/generate_204',
             'interval': 300, 'tolerance': 50, 'lazy': True}
    if names:
        group['proxies'] = names
    else:
        group['use'] = list(providers)
    # 配置只保留出站节点及其依赖；入站、控制器和路由由本机固定管理。
    for provider in providers.values():
        if not isinstance(provider, dict):
            raise RuntimeError('invalid provider')
        if 'path' in provider:
            relative = Path(provider['path'])
            if relative.is_absolute() or '..' in relative.parts:
                raise RuntimeError('provider path outside state directory')
    token = secrets.token_urlsafe(32)
    config = {'mixed-port': 7890, 'allow-lan': False, 'bind-address': '127.0.0.1', 'mode': 'rule',
              'log-level': 'warning', 'ipv6': False, 'external-controller': '127.0.0.1:9090',
              'secret': token, 'tun': {'enable': False}, 'dns': {'enable': False},
              'profile': {'store-selected': True}, 'proxies': proxies, 'proxy-providers': providers,
              'proxy-groups': [group] + groups, 'rules': ['MATCH,'+name]}
    try:
        account = pwd.getpwnam('mihomo')
    except KeyError:
        run('useradd', '--system', '--home-dir', '/var/lib/mihomo', '--shell', '/usr/sbin/nologin', 'mihomo')
        account = pwd.getpwnam('mihomo')
    target.mkdir(mode=0o750, exist_ok=True)
    os.chown(target, 0, account.pw_gid)
    work = Path('/var/lib/mihomo');work.mkdir(mode=0o750, exist_ok=True)
    os.chown(work, account.pw_uid, account.pw_gid)
    binary = Path('/usr/local/bin/mihomo')
    if binary.exists():
        raise RuntimeError('Existing binary: inspect before replacing')
    with gzip.open(ARCHIVE, 'rb') as stream, binary.open('wb') as out:
        shutil.copyfileobj(stream, out)
    binary.chmod(0o755)
    config_path = target/'config.yaml'
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding='utf-8')
    config_path.chmod(0o640);os.chown(config_path, 0, account.pw_gid)
    (target/'controller.token').write_text(token);(target/'controller.token').chmod(0o600)
    shutil.copy2(SOURCE, target/'subscription.txt');(target/'subscription.txt').chmod(0o600)
    result = subprocess.run([str(binary), '-t', '-d', str(work), '-f', str(config_path)], capture_output=True, text=True)
    if result.returncode:
        log = SOURCE.with_name('validation.log');log.write_text(result.stdout+result.stderr);log.chmod(0o600)
        raise RuntimeError('Configuration validation failed; private diagnostic saved')
    unit.write_text('''[Unit]
Description=Mihomo local explicit proxy
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=mihomo
Group=mihomo
ExecStart=/usr/local/bin/mihomo -d /var/lib/mihomo -f /etc/mihomo/config.yaml
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/mihomo
CapabilityBoundingSet=
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
MemoryMax=256M
MemorySwapMax=128M
TasksMax=64
UMask=0077
[Install]
WantedBy=multi-user.target
''')
    run('systemctl', 'daemon-reload');run('systemctl', 'enable', '--now', 'mihomo')
    for _ in range(30):
        try:
            req = urllib.request.Request('http://127.0.0.1:9090/version', headers={'Authorization':'Bearer '+token})
            with urllib.request.urlopen(req, timeout=2) as response:
                version = json.load(response)
            break
        except Exception:
            time.sleep(1)
    else:
        raise RuntimeError('Mihomo API not ready')
    print('MIHOMO_INSTALLED', 'VERSION', version.get('version'), 'NODES', len(names),
          'PROVIDERS', len(providers), 'LISTEN', '127.0.0.1:7890', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # 订阅下载及 YAML 错误可能含私密 URL，不直接打印异常正文。
        print('INSTALL_NOT_COMPLETED', type(exc).__name__, flush=True)
        raise SystemExit(1)
