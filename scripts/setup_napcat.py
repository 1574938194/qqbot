"""下载官方 NapCat Shell 到项目 data/napcat，并生成仅本机访问的接入配置。"""
import hashlib
import json
import os
import secrets
import zipfile
from pathlib import Path

import httpx
from dotenv import dotenv_values


def main():
    root = Path('data/napcat').resolve()
    root.mkdir(parents=True, exist_ok=True)
    env = dotenv_values('.env')
    token = os.getenv('ONEBOT_ACCESS_TOKEN') or env.get('ONEBOT_ACCESS_TOKEN')
    if not token or token == 'replace-with-random-token':
        raise SystemExit('请先配置项目 .env 的 ONEBOT_ACCESS_TOKEN。')
    with httpx.Client(timeout=httpx.Timeout(60, connect=20), follow_redirects=True, trust_env=False) as client:
        response = client.get('https://api.github.com/repos/NapNeko/NapCatQQ/releases/latest')
        response.raise_for_status()
        release = response.json()
        asset = next(a for a in release['assets'] if a['name'] == 'NapCat.Shell.zip')
        archive = root / ('NapCat.Shell.' + release['tag_name'] + '.zip')
        if not archive.exists():
            temporary = archive.with_suffix('.download')
            with client.stream('GET', asset['browser_download_url']) as download:
                download.raise_for_status()
                with temporary.open('wb') as output:
                    for chunk in download.iter_bytes():
                        output.write(chunk)
            digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
            expected = asset.get('digest')
            if expected and expected != 'sha256:' + digest:
                raise RuntimeError('官方摘要校验失败，未解压。')
            temporary.replace(archive)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if asset.get('digest') and asset['digest'] != 'sha256:' + digest:
            raise RuntimeError('已下载文件摘要不匹配，未解压。')
        installed = root / 'package'
        if not (installed / 'launcher.bat').exists():
            installed.mkdir(exist_ok=True)
            with zipfile.ZipFile(archive) as package:
                for member in package.infolist():
                    target = (installed / member.filename).resolve()
                    if not target.is_relative_to(installed.resolve()):
                        raise RuntimeError('发布包包含越界路径，未解压。')
                package.extractall(installed)
        configuration = installed / 'config'
        configuration.mkdir(exist_ok=True)
        onebot = configuration / 'onebot11.json'
        if not onebot.exists():
            onebot.write_text(json.dumps({'network': {
                'httpServers': [], 'httpClients': [], 'websocketServers': [],
                'websocketClients': [{'name': 'xiaonuan', 'enable': True,
                    'url': 'ws://127.0.0.1:8080/onebot/v11/', 'messagePostFormat': 'array',
                    'reportSelfMessage': False, 'reconnectInterval': 5000, 'token': token,
                    'debug': False, 'heartInterval': 30000}]}, 'musicSignUrl': '',
                    'enableLocalFile2Url': False, 'parseMultMsg': False}, ensure_ascii=False, indent=2), encoding='utf-8')
        webui = configuration / 'webui.json'
        if not webui.exists():
            webui.write_text(json.dumps({'host': '127.0.0.1', 'port': 6099,
                'token': secrets.token_hex(24), 'loginRate': 3}, indent=2), encoding='utf-8')
        # 本地日志不记私聊正文；第三方仍可能打印登录 QR/会话信息，请保管 data 目录。
        napcat = configuration / 'napcat.json'
        if not napcat.exists():
            napcat.write_text(json.dumps({'fileLog': False, 'consoleLog': True,
                'fileLogLevel': 'error', 'consoleLogLevel': 'info'}, indent=2), encoding='utf-8')
        (root / 'installation.json').write_text(json.dumps({'version': release['tag_name'],
            'asset_url': asset['browser_download_url'], 'sha256': digest,
            'official_digest_available': bool(asset.get('digest'))}, indent=2), encoding='utf-8')
        print('NapCat ' + release['tag_name'] + ' prepared at ' + str(installed))
        print('WebUI: http://127.0.0.1:6099/webui/ ; OneBot token configured, not printed.')


if __name__ == '__main__':
    main()
