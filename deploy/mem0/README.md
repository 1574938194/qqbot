# QQ 长期记忆：Mem0 OSS

本服务使用 **Mem0 SDK 2.2.1** 做事实提取、更新与语义检索；FastEmbed **0.9.0** 在 CPU 上运行 `BAAI/bge-small-zh-v1.5` ONNX 中文嵌入，Qdrant local 和 SQLite 历史持久化在 `/state`。不需要 GPU、PyTorch、独立 Qdrant 或 Postgres 服务。

`server.py` 是面向现有 QQ 网关的精简 REST 适配层，提供 `/memories`、`/search` 和 `/health`，不是完整 Mem0 管理台。接口参考 [官方 OSS REST 文档](https://github.com/mem0ai/mem0/blob/main/docs/open-source/features/rest-api.mdx)。

## 部署

先构建 QQ 网关基础镜像，再在本目录构建：

```sh
docker build -t xiaoai-mem0:onnx .
```

配置保存在服务器私密文件（权限 600），不提交仓库：

```dotenv
LLM_BASE_URL=http://127.0.0.1:32126/v1
LLM_API_KEY=
LLM_MODEL=deepseek-v4.1-flash
MEMORY_API_KEY=
MEM0_TELEMETRY=false
HF_HUB_DISABLE_XET=1
```

生成至少 24 字符的独立随机 `MEMORY_API_KEY`，把 `/state` 挂到持久目录并设为 UID/GID 10001。仅监听 `127.0.0.1:32129`，单进程单 worker 运行，禁止同时用其他进程打开同一 Qdrant local 数据目录。模型首次通过镜像下载到持久缓存，后续复用。

首次完成真实写入和检索验收后，可在服务环境中设置 `HF_HUB_OFFLINE=1` 并重建容器，避免重启时联网检查模型；冷启动尚未下载模型时不要提前开启。依赖版本保存在 `requirements.lock`，基础网关依赖沿用项目锁文件。

QQ 网关 `.env` 设置：

```dotenv
MEMORY_BACKEND=mem0
MEMORY_BASE_URL=http://127.0.0.1:32129
MEMORY_API_KEY=
MEMORY_TIMEOUT=120
```

两端使用相同记忆密钥。QwenPaw 网关插件也必须同步更新：`external_memory=true` 时关闭重复的 ReMe 长期提取；QwenPaw 原生短期会话仍保留。首次请求还会注入本用户最近 6 轮和摘要，迁移后不依赖模型自行找旧文件。

## 自动行为与排错

- 每轮陪伴请求前按用户作用域检索 Mem0，检索结果作为历史资料交给 QwenPaw，不能扩大工具授权。
- 成功对话后，仅用户自述进入 SQLite 待同步队列，后台提取事实，不延迟 QQ 正文投递。不写助手虚构经历、命令及命令结果或视觉模型识别资料。
- 首次启用后，现有对话中的用户自述分批补建一次；`/chat memory status` 查看待办，`/chat memory sync` 手动重试。后台也会自动重试，重启保留待办。
- `/chat memory clear` 更换用户作用域并删除原 Mem0 记忆，保留本地对话；`/chat reset` 同时清空短期会话、摘要和长期记忆。清空后不会因重启再次补建旧记忆。
- `/chat memory clear` 保留的短期历史仍可能包含旧事实；需要完全忘记请用 `/chat reset`。
- Mem0 不可用时继续使用本地及原生短期上下文，待同步数据保留。日志只记错误类别，不记录原文和密钥。
- 检查 `/health`、容器状态和 `/chat memory status`；仅有健康接口成功还不足以验收，需用独立测试作用域验证真实写入、中文检索、隔离、重启和删除。

备份 `/state` 和 QQ SQLite 时先停止对应写入进程，备份需限制读取权限。不要把向量库、模型缓存、记忆文件或密钥提交 Git。
