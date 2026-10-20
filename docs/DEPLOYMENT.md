# Linux Docker 部署

网络受限时可指定构建源，依赖仍使用锁文件中的固定版本：

```bash
docker build \
  --build-arg PYTHON_IMAGE=docker.1ms.run/library/python:3.12-slim \
  --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
  -t xiaoai-qqbot:local .
```

默认使用 Docker Hub 和 PyPI；镜像加速源按自己的网络环境选择。Windows 专用依赖带平台标记，Linux 不安装。

管理员私聊发送 `签到`，通过代理管理接口给 `BUDDY_SITE` 指定的账号池签到。默认 `global`，国内站设为 `cn`；代理启用管理密码时配置 `BUDDY_ADMIN_PASSWORD`，不使用聊天 API Key 代替。国际站可能返回“不支持”，不会伪报签到成功。超时后部分账号可能已完成，重试会返回“已签”。

使用 Python 3.12 容器运行机器人，宿主机运行 buddyproxy，NapCat 独立容器运行。`compose.yaml` 使用 Linux host 网络，机器人仅监听 `127.0.0.1:8080`；NapCat 也应使用 host 网络，以连接反向 WebSocket。

1. 安装 Docker（Compose 为可选），启动 buddyproxy 并确认宿主机 `127.0.0.1:32126/v1` 可用。
2. 从 `.env.example` 创建 `.env`，配置随机 OneBot Token。将代理凭据放在宿主机独立文件，权限设为600；Compose 默认只读挂载 `/root/.codebuddy/proxy.env`，可通过 `PROXY_ENV_PATH` 覆盖。
3. 运行 `docker compose up -d --build`。没有 Compose 时可用等价的 `docker build`、`docker run --network host --env-file .env -v 数据目录:/app/data -v 代理凭据:/root/.codebuddy/proxy.env:ro`。
4. NapCat 的 WebUI、HTTP/WS 监听仅绑定本机，通过 SSH 转发访问 WebUI。设置 WS 客户端为 `ws://127.0.0.1:8080/onebot/v11/`，Token 与项目一致。
5. 检查健康接口、QQ账号连接、管理员命令、真实聊天、图片和语音。

Linux 使用 `TTS_BACKEND=edge`，无 Windows SAPI 回退。Python 命令工具可用，PowerShell 需要另行安装pwsh。shell执行的“本机”是机器人容器，不是宿主机；不要挂载Docker socket。

迁移前停止旧机器人，备份旧代码、配置、数据库以及 NapCat 全部挂载卷。先建立新版本目录再启动，保留旧目录及容器以便回滚。不同旧版数据库格式应先检查，不直接覆盖；本地Windows数据迁入Linux时检查任务文件路径和未投递通知。不能让同一个QQ同时在两台主机运行NapCat。

回滚时停止新机器人和新NapCat，恢复迁移前数据库备份与旧容器配置，再启动旧版本。模型凭据、QQ登录缓存、日志和数据库均不得提交到GitHub。
