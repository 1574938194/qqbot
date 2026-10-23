# Linux Docker 部署

网络受限时可指定构建源，依赖仍使用锁文件中的固定版本：

```bash
docker build \
  --build-arg PYTHON_IMAGE=docker.1ms.run/library/python:3.12-slim \
  --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
  -t xiaoai-qqbot:local .
```

默认使用 Docker Hub 和 PyPI；镜像加速源按自己的网络环境选择。Windows 专用依赖带平台标记，Linux 不安装。

管理员私聊发送 `签到`，自动跟随代理当前默认号池签到。管理员使用 `/pool` 查看、`/pool cn` 切国内、`/pool global` 切国际；代理启用管理密码时配置 `BUDDY_ADMIN_PASSWORD`，不使用聊天 API Key 代替。国际站可能返回“不支持”，不会伪报签到成功。超时后部分账号可能已完成，重试会返回“已签”。

使用 Python 3.12 容器运行机器人，宿主机运行 buddyproxy，NapCat 独立容器运行。`compose.yaml` 使用 Linux host 网络，机器人仅监听 `127.0.0.1:8080`；NapCat 也应使用 host 网络，以连接反向 WebSocket。

1. 安装 Docker（Compose 为可选），启动 buddyproxy 并确认宿主机 `127.0.0.1:32126/v1` 可用。
2. 从 `.env.example` 创建 `.env`，配置随机 OneBot Token。将代理凭据放在宿主机独立文件，权限设为600；Compose 默认只读挂载 `/root/.codebuddy/proxy.env`，可通过 `PROXY_ENV_PATH` 覆盖。
3. 运行 `docker compose up -d --build`。没有 Compose 时可用等价的 `docker build`、`docker run --network host --env-file .env -v 数据目录:/app/data -v 代理凭据:/root/.codebuddy/proxy.env:ro`。
4. NapCat 的 WebUI、HTTP/WS 监听仅绑定本机，通过 SSH 转发访问 WebUI。设置 WS 客户端为 `ws://127.0.0.1:8080/onebot/v11/`，Token 与项目一致。
5. 检查健康接口、QQ账号连接、管理员命令、真实聊天、图片和语音。

Linux 无 Windows SAPI 回退，可使用 Edge 或独立 ONNX 语音服务。agent 使用 [DSH 独立容器](../deploy/dsh/README.md)，shell 的“本机”是 DSH 容器；不要挂载 Docker socket。

网页聊天调试复用机器人端口，入口为 `/debug`。在电脑上用 `ssh -N -L 127.0.0.1:18080:127.0.0.1:8080 root@服务器地址` 建立转发，然后访问 `http://127.0.0.1:18080/debug`（密钥登录加 `-i 密钥路径`）。无需开放云防火墙端口，也无需 QQ 在线即可普通聊天。页面与超级管理员 QQ 共用上下文及权限，命令不进入聊天历史；后台任务通知仍发 QQ。入口拒绝非本机地址、非本机 Host 和跨站请求；通过页面内随机令牌访问 API。只允许 SSH 转发，不提供公网反向代理部署方式。

迁移前停止旧机器人，备份旧代码、配置、数据库以及 NapCat 全部挂载卷。先建立新版本目录再启动，保留旧目录及容器以便回滚。不同旧版数据库格式应先检查，不直接覆盖；本地Windows数据迁入Linux时检查任务文件路径和未投递通知。不能让同一个QQ同时在两台主机运行NapCat。

回滚时停止新机器人和新NapCat，恢复迁移前数据库备份与旧容器配置，再启动旧版本。模型凭据、QQ登录缓存、日志和数据库均不得提交到GitHub。

号池切换由 buddyproxy 官方管理 API 保存。代理启动建议通过 `CODEBUDDY_PROXY_ENV_FILE` 指定持久化配置文件，避免另外的进程环境或启动脚本固定 `CODEBUDDY_SITE`、`CODEBUDDY_BASE_URL` 等路由设置覆盖已保存的号池。项目不在启动时切换代理号池。显式 `cn:`/`global:` 模型前缀、绑定区域的 Key 或 `X-Site` 请求头仍会覆盖默认路由。
