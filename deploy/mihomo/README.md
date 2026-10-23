# 云端 Mihomo 代理

无桌面的 Ubuntu 云主机使用 Clash Verge 同款 Mihomo 内核，以 systemd 服务运行。当前固定官方版本 v1.19.33（linux-amd64-compatible），安装脚本校验 GitHub 发布的 SHA256。

## 安装

脚本适配当前 Ubuntu 24.04 x86_64 部署，依赖系统 Python3/PyYAML。先将官方压缩包及用户的 `proxy.txt` 放入权限 700 的 `/opt/qqbot/proxy-install/`，再以 root 运行 `install.py`。脚本拒绝覆盖已有配置和服务。

`proxy.txt` 可以是 Clash YAML 或订阅 URL。订阅下载需返回含 `proxies` 或 `proxy-providers` 的 Clash YAML；如果服务器无法获取订阅，可以先在可信环境下载，将结果私密保存为同目录的 `subscription.yaml`。不要把订阅、节点、生成配置或控制密钥加入版本库。

## 运行

- 显式 HTTP/SOCKS 混合代理：`127.0.0.1:7890`。
- 带随机密钥的控制接口：`127.0.0.1:9090`。
- 服务：`systemctl status mihomo`；开机自启。
- 配置：`/etc/mihomo/config.yaml`，root/mihomo 组可读。
- 原订阅地址：`/etc/mihomo/subscription.txt`，仅 root 可读。
- 控制密钥：`/etc/mihomo/controller.token`，仅 root 可读。
- 持久状态：`/var/lib/mihomo`，专用非 root 用户运行。

使用示例：

```sh
curl --proxy http://127.0.0.1:7890 https://www.google.com/generate_204 -o /dev/null -w '%{http_code}\n'
```

安装不启用 TUN、不更改系统 DNS/默认路由，也不自动修改 QQBot、buddyproxy 或 DSH 的联网配置。需要代理的应用应单独配置上述地址；直连本机服务应保留在 NO_PROXY 中，应用是否读取环境代理由其自身配置决定。

当前节点为导入时快照，并通过健康检查选择低延迟节点；没有启用完整订阅定期刷新。节点变更时需受控更新配置并先执行 `mihomo -t -d /var/lib/mihomo -f /etc/mihomo/config.yaml` 校验。共享出口可能耗尽 GitHub 未认证 API 限额，这与代理网络连通不同。
