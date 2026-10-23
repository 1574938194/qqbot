"""为已安装 Mihomo 应用大陆/局域网直连规则；保留节点和控制密钥。"""
from pathlib import Path
import datetime
import json
import os
import shutil
import subprocess
import time
import urllib.request
import yaml


def main():
    config_path = Path('/etc/mihomo/config.yaml')
    config = yaml.safe_load(config_path.read_text())
    group = next(g['name'] for g in config['proxy-groups'] if g['name'].startswith('QQBOT_CLOUD_PROXY_'))
    work = Path('/var/lib/mihomo')
    directory = work/'rules';directory.mkdir(exist_ok=True)
    stat = work.stat();os.chown(directory, stat.st_uid, stat.st_gid)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'http':'http://127.0.0.1:7890','https':'http://127.0.0.1:7890'}))
    providers = config.setdefault('rule-providers', {})
    for key, kind, behavior in [('cn-domain','geosite','domain'), ('cn-ip','geoip','ipcidr')]:
        url = 'https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/' + kind + '/cn.mrs'
        with opener.open(url, timeout=30) as response:
            raw = response.read(16*1024*1024+1)
        if not raw or len(raw) > 16*1024*1024:
            raise ValueError('invalid rule download')
        path = directory/(key+'.mrs');temp=path.with_suffix('.new')
        temp.write_bytes(raw);temp.chmod(0o600);os.chown(temp, stat.st_uid, stat.st_gid);temp.replace(path)
        providers[key] = {'type':'http','behavior':behavior,'format':'mrs','url':url,
                          'path':'./rules/'+key+'.mrs','interval':86400,'proxy':group}
    config['mode']='rule'
    config['rules'] = [
        'DOMAIN,localhost,DIRECT', 'DOMAIN-SUFFIX,local,DIRECT', 'DOMAIN-SUFFIX,lan,DIRECT',
        'IP-CIDR,127.0.0.0/8,DIRECT,no-resolve', 'IP-CIDR,10.0.0.0/8,DIRECT,no-resolve',
        'IP-CIDR,172.16.0.0/12,DIRECT,no-resolve','IP-CIDR,192.168.0.0/16,DIRECT,no-resolve',
        'IP-CIDR,169.254.0.0/16,DIRECT,no-resolve','IP-CIDR,100.64.0.0/10,DIRECT,no-resolve',
        'IP-CIDR6,::1/128,DIRECT,no-resolve','IP-CIDR6,fc00::/7,DIRECT,no-resolve',
        'IP-CIDR6,fe80::/10,DIRECT,no-resolve',
        'RULE-SET,cn-domain,DIRECT','RULE-SET,cn-ip,DIRECT', 'MATCH,'+group]
    temp = config_path.with_name('.config-cn.yaml')
    temp.write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False));temp.chmod(0o640)
    oldstat=config_path.stat();os.chown(temp,oldstat.st_uid,oldstat.st_gid)
    checked = subprocess.run(['/usr/local/bin/mihomo','-t','-d',str(work),'-f',str(temp)],capture_output=True)
    if checked.returncode:
        temp.unlink()
        raise RuntimeError('new rule configuration invalid; old configuration unchanged')
    backup = config_path.with_name('config.before-cn-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.yaml')
    shutil.copy2(config_path, backup);backup.chmod(0o600)
    temp.replace(config_path)
    try:
        subprocess.run(['systemctl','restart','mihomo'],check=True,capture_output=True)
        request=urllib.request.Request('http://127.0.0.1:9090/rules',headers={'Authorization':'Bearer '+config['secret']})
        for _ in range(30):
            try:
                with urllib.request.urlopen(request, timeout=2) as response:rules=json.load(response)['rules']
                assert any(r.get('payload')=='cn-domain' and r.get('proxy')=='DIRECT' for r in rules)
                assert any(r.get('payload')=='cn-ip' and r.get('proxy')=='DIRECT' for r in rules)
                break
            except Exception:time.sleep(1)
        else:raise RuntimeError('active rules not confirmed')
        print('CHINA_BYPASS_ACTIVE','RULES',len(rules),'BACKUP',str(backup),flush=True)
    except Exception:
        shutil.copy2(backup,config_path);config_path.chmod(0o640);os.chown(config_path,oldstat.st_uid,oldstat.st_gid)
        subprocess.run(['systemctl','restart','mihomo'],check=True,capture_output=True)
        raise


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('CHINA_BYPASS_NOT_APPLIED',type(exc).__name__,flush=True)
        raise SystemExit(1)
