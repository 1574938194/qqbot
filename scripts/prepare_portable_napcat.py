"""准备官方自带兼容 QQ 的 Windows 安装包，不替换系统 QQ。"""
import hashlib
import json
import zipfile
from pathlib import Path

import httpx


def main():
    root = Path('data/napcat-portable').resolve()
    root.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=httpx.Timeout(90, connect=20), follow_redirects=True, trust_env=False) as client:
        response = client.get('https://api.github.com/repos/NapNeko/NapCatQQ/releases/latest')
        response.raise_for_status()
        release = response.json()
        asset = next(a for a in release['assets'] if a['name'] == 'NapCat.Shell.Windows.OneKey.zip')
        print('Official asset: ' + asset['name'] + ', bytes=' + str(asset['size']), flush=True)
        archive = root / asset['name']
        if not archive.exists():
            partial = archive.with_suffix('.download')
            with client.stream('GET', asset['browser_download_url']) as response:
                response.raise_for_status()
                with partial.open('wb') as output:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
            partial.replace(archive)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if asset.get('digest') and asset['digest'] != 'sha256:' + digest:
            raise RuntimeError('官方摘要校验失败。')
        package = root / 'installer'
        package.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as files:
            if any(not (package / member.filename).resolve().is_relative_to(package) for member in files.infolist()):
                raise RuntimeError('发布包包含越界路径。')
            files.extractall(package)
        (root / 'installation.json').write_text(json.dumps({'version': release['tag_name'], 'sha256': digest,
            'asset_url': asset['browser_download_url'], 'official_digest_available': bool(asset.get('digest'))}, indent=2), encoding='utf-8')
        print('Prepared installer at ' + str(package), flush=True)


if __name__ == '__main__':
    main()
