# QwenPaw + DeepSeek Harness

采用官方 QwenPaw **2.2.2.post1** 的会话、网页控制台、工作区和 ReMe 记忆管理；通过其原生 ACP 工具 `delegate_external_agent` 调用官方 DeepSeek Harness。QwenPaw 负责交互与调度，DSH 负责实际执行。没有再维护自制 JSON 工具循环。

## 边界

- QQ/NapCat 接入、白名单、头像、命名、人设上传、图片和语音继续由 NoneBot 网关处理。
- 每位 QQ 用户独立 `qq-QQ号` 工作区、会话与记忆。管理员先通过 `/task shell on` 授权 DSH；其他用户只有聊天权限。
- 闲聊直接回应；明确检索、浏览、文件、编程任务可自然语言触发 DSH；`/tool` 仍可显式发起，`/stop` 停止当前执行。
- `/tool` 使用独立任务执行记录，其命令和结果不进入 QwenPaw 陪伴会话；自然语言提出的任务属于当前对话。
- 人设原文单独存储，不回显到日志；当前名字独立同步。旧 SQLite 历史保留，并导入该用户的记忆资料。
- 接入独立 Mem0 后，每轮自动检索并注入历史资料，成功回复后后台提取用户事实；关闭重复的 ReMe 长期提取，QwenPaw 短期会话继续保存。首次请求会恢复本用户近期对话与摘要，详情见 `../mem0/README.md`。
- QwenPaw 原生上下文上限 260,000，达到 240,000 左右自动压缩；近期保留量由原生压缩器管理。QQ 的 SQLite 镜像压缩仍保留最近 6 轮。`/chat status` 的 token 数字是镜像估算。
- `/chat reset` 先停止工作区服务再删除会话与记忆，保留人设、`files` 和独立计划任务。已产生的外部操作无法通过清空撤销。
- QwenPaw 的主会话和文件持久化。DSH ACP 活跃连接在同进程内支持后续消息；QwenPaw 重启后，执行器需要新开连接并基于现有任务文件继续，不能保证自动恢复旧 ACP 连接。

## 构建与配置

先按 `../dsh/README.md` 构建 DSH Node/Chromium 镜像，再在本目录构建：

```sh
docker build --build-arg DSH_IMAGE=xiaoai-dsh:node-browser-health -t xiaoai-qwenpaw:qq-gateway .
```

配置仅保存在服务器的权限 600 文件，不提交仓库：

```dotenv
DSH_MODEL_BASE_URL=http://127.0.0.1:32126/v1
DSH_MODEL_API_KEY=
LLM_MODEL=deepseek-v4.1-flash
QQBOT_GATEWAY_TOKEN=
QWENPAW_WORKING_DIR=/state/qwenpaw
QWENPAW_WORKDIR=/state/qwenpaw
QWENPAW_TELEMETRY_DISABLED=true
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
TZ=Asia/Shanghai
```

生成独立随机网关令牌，两个容器使用相同值。把持久目录挂到 `/state`，所有权设为 UID 10001。首次运行镜像内 `/opt/qqbot-qwenpaw/bootstrap.py`，再启动默认命令。禁止挂载 Docker socket、宿主 SSH 私钥或原始 QQ SQLite 数据库。

NoneBot 设置 `AGENT_BACKEND=qwenpaw`、`QWENPAW_BASE_URL=http://127.0.0.1:8088` 和同一 `QQBOT_GATEWAY_TOKEN`；把 QwenPaw 持久目录额外挂到 NoneBot 的 `/qwenpaw:ro`，用于发送任务产生的附件。

`compat.py` 只将固定版本配置中压缩比例上限 0.9 放宽为 0.99，以允许 240000/260000；若上游 schema 改变立即构建失败，不自动猜测修改。升级 QwenPaw 前需重新验收插件 API、压缩、ACP、清空及附件投递。

## 访问

默认只监听本机，不对公网开放控制台。保持 SSH 隧道运行：

```powershell
ssh -i E:\proj\agent_key.pem -N -L 127.0.0.1:18080:127.0.0.1:8080 -L 127.0.0.1:18088:127.0.0.1:8088 root@110.40.226.103
```

QQ 同步调试页为 `http://127.0.0.1:18080/debug`，QwenPaw 原生管理台为 `http://127.0.0.1:18088`。管理台可执行任务，SSH 访问者应视为管理员。

健康检查为 `/api/healthz`。日志关闭 Console 原文输出，只转发最终正文和附件；模型思考、工具调用记录不会发送到 QQ。QwenPaw 工作区本身包含私密数据，备份应加密并限制读取权限。

回滚时先停新网关，再启动旧容器并恢复原 `.env`；不要覆盖较新的 SQLite 或删除 QwenPaw 状态。DSH、语音和 NapCat 服务无需随网关回滚。
