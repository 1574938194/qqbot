# DeepSeek Harness 任务后端

使用 [DeepSeek 官方 Harness](https://github.com/deepseek-ai/deepseek-harness) Python SDK `0.2.1rc2` 驱动同版本官方 Node CLI，取代旧 agent。模型通过 buddyproxy OpenAI Chat Completions 接口调用；默认 DeepSeek Messages 协议与此代理不兼容，因此 profile 使用官方 pi-ai adapter。浏览器使用官方实验性 Chrome DevTools MCP 插件与系统 Chromium。CLI 与插件共享 npm 依赖树；避免 standalone runtime 与外部插件的 Node 路径、模块实例冲突。

## 配置与构建

机器人配置 `DSH_BASE_URL=http://127.0.0.1:32128`、`DSH_TOKEN=独立随机令牌`。DSH 服务 `.env` 配置相同 `DSH_TOKEN`，另配 `DSH_MODEL_BASE_URL=http://127.0.0.1:32126/v1`、`DSH_MODEL_API_KEY`、`LLM_MODEL=deepseek-v4.1-flash`、`DSH_RUN_TIMEOUT=900`。文件权限设为600，不提交真实凭据。

在本目录准备 `wheels/`，从 PyPI 下载 requirements.txt 对应 Linux x86_64 wheel。构建前镜像需包含机器人依赖（FastAPI/httpx/uvicorn）：

```sh
python -m pip download --no-deps -d wheels -r requirements.txt
docker build --build-arg BOT_IMAGE=xiaoai-qqbot:identity-echo-fix -t xiaoai-dsh:0.2.1rc2 .
mkdir -p /opt/qqbot/dsh/state /opt/qqbot/deployment/data/tasks
cp profile.patch.yml /opt/qqbot/dsh/state/profile.patch.yml
chown -R 10001:10001 /opt/qqbot/dsh/state
# 确保任务父目录及旧任务目录允许 UID 10001 访问；不要更改聊天数据库权限。
docker run -d --name xiaoai-dsh --restart unless-stopped --network host \
 --env-file /opt/qqbot/dsh/.env --memory 900m --memory-swap 2g --cpus 1.5 \
 --pids-limit 256 --cap-drop ALL --security-opt no-new-privileges \
 -v /opt/qqbot/dsh/state:/state \
 -v /opt/qqbot/deployment/data/tasks:/work/tasks \
 xiaoai-dsh:0.2.1rc2
```

`GET /health` 返回引擎/版本；`POST /run` 需要独立令牌，只接受固定管理员。监听127.0.0.1，不向公网开放。服务一次执行一个任务，客户端断开或超时会终止其进程组。机器人同样限制执行时间。共享成果目录布局为 `/work/tasks/QQ号/任务ID`，会话目录为 `/state/homes/QQ号/任务ID`；都需备份，不能只备份机器人 SQLite。

## 能力与边界

开启 `/tools shell on` 后管理员使用 `/tool`。支持 bash/Python、读写文件、图片读取、Chromium 页面操作和公开 Git 仓库。浏览器无桌面界面；截图保存在任务目录。私有 GitHub、账号登录和其他 MCP 插件尚无凭据，不会自动借用桌面登录。可按上游 MCP 文档显式配置插件与专用环境变量，不能声称已连接未配置的服务。

默认禁用 DeepSeek 会话日志上传和插件库存上报，保留本地 state；不传陪伴人设与聊天历史。隔离容器为非 root，未挂载数据库或 Docker socket。任务 shell 仍能访问容器网络和模型凭据，勿执行不可信指令。`resume` 恢复会话，不保证恢复浏览器状态，也不能撤销副作用。

生成图片由机器人独立 Images API 处理，不依赖 DSH。使用 `/draw 描述` 或明确的“帮我画一张…”，`IMAGE_MODEL` 默认 `hunyuan-image-alpha`。QQ 与网页均直接显示生成图；聊天历史只记录请求与成功提示，刷新网页不会恢复原图。

## 可选 GitHub MCP

提供 `github.patch.example.yml` 模板，使用 [GitHub 官方远程 MCP](https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md) 只读接口。将专用最小权限 `GITHUB_TOKEN` 写入 DSH 私密 env 文件，再把模板复制为 state/github.patch.yml 并重建 DSH 容器；新任务或恢复会话时加载。删除该文件并重建即可关闭。当前部署未配置 Token，因此未启用、未做私有仓库真实验收。需要写操作时应按实际授权配置上游端点和 Token 权限。
