# 详细配置与运行说明

Python 3.12 + NoneBot2 + OneBot v11，NapCat 反向 WebSocket 接入，buddyproxy 提供兼容 OpenAI 的 DeepSeek 接口。处理白名单私聊文本和图片，支持按需语音回复、用户授权的后台复杂任务、定时主动执行和结果通知；无默认主动问候、Web 管理面板或多会话切换。

已增加可选 **Mem0 OSS / Letta 记忆块**和本地情感状态模块。默认 `MEMORY_BACKEND=none`，无需外部记忆服务即可聊天；情感模块默认启用。

## Windows 安装与启动

1. 安装 Python **3.12**（带 Python Launcher），打开项目目录。
2. 双击 `install.bat`，或运行 `powershell -ExecutionPolicy Bypass -File .\install.ps1`。安装会创建 `.venv`、安装依赖，并在首次安装时从 `.env.example` 生成 `.env` 和随机 OneBot 访问令牌；已有 `.env` 不会被覆盖。
3. 确保本机 buddyproxy 已启动，提供 `http://127.0.0.1:32126/v1`。密钥按以下优先级读取：进程环境 `LLM_API_KEY` → `OPENAI_API_KEY` → `CODEBUDDY_PROXY_API_KEY` → `.env` 中 `LLM_API_KEY` → `~/.codebuddy/proxy.env` 的 `CODEBUDDY_PROXY_API_KEY`（兼容 `OPENAI_API_KEY`）。无需复制代理密钥到项目。
4. 按下文配置 NapCat。双击 `start.bat`，或运行 `.\start.ps1`。关闭时按 Ctrl+C。
5. 用超级管理员 QQ **1574938194** 私聊机器人账号发送 `/help`，再发送普通文本。管理员账号与机器人登录账号应是不同 QQ；机器人自身消息会被忽略。

脚本始终以项目目录作为工作目录。启动前必须配置有效访问令牌；模型缺少密钥会在启动阶段报错。应用默认只监听本机 `127.0.0.1:8080`。

## NapCat 接入

项目支持独立的 NapCat 便携运行环境；须先按下面步骤准备运行目录，不替换系统 QQ。运行 `.\start-napcat-portable.ps1` 后打开 `http://127.0.0.1:6099/webui/`；QQ 扫码及手机确认由账号所有者完成。机器人可用 `.\start-background.ps1` 隐藏启动，进程号和日志保存在 `data/bot.pid`、`data/bot.stdout.log`、`data/bot.stderr.log`。不要重复启动同一数据库的机器人。

新机器可先运行 `.\.venv\Scripts\python.exe -m scripts.prepare_portable_napcat` 下载官方 Windows 一键安装包，再运行 `data\napcat-portable\installer\NapCatInstaller.exe` 安装其兼容的独立 QQ 环境。运行 `.\.venv\Scripts\python.exe -m scripts.setup_napcat` 可生成接入配置；便携安装的实际配置目录在 `NapCat.*.Shell\versions\版本号\resources\app\napcat\config`，须将生成的配置放到该目录，或通过 WebUI 手动设置。下载脚本校验官方提供的 SHA256，并检查压缩包路径。

遵循 [NapCat WebUI 配置指南](https://napneko.github.io/config/basic)，登录 WebUI 后在「网络配置」新建 **WebSocket 客户端**，保存并启用：

| 选项 | 值 |
| --- | --- |
| 名称 | `xiaonuan`（任意唯一名称） |
| URL | `ws://127.0.0.1:8080/onebot/v11/` |
| Token | 项目 `.env` 中 `ONEBOT_ACCESS_TOKEN` 的值 |
| 消息格式 | `array` |
| 上报自身消息 | 关闭 |
| 重连间隔 | `5000` ms |
| 心跳间隔 | `30000` ms |
| debug | 关闭 |

Token 是 OneBot 通信凭据，独立于 WebUI 登录 Token 和模型 API Key。两端值必须完全一致。连接方向为 NapCat → 本项目；项目无需配置 NapCat 的正向 WS 地址。上述路由来自 [NoneBot OneBot v11 配置文档](https://onebot.adapters.nonebot.dev/docs/guide/setup/)。这里的本机地址要求两者运行在同一台 Windows 主机；容器内的 `127.0.0.1` 指向容器本身。

## 命令

所有命令以 `/` 开头；未知命令返回帮助提示，不进入模型。非白名单、群消息、自身消息及包含语音/视频等不支持类型的消息静默忽略，不调用模型。支持文字、图片及两者混合输入。权限由业务代码检查，无法靠修改人设授权。

| 命令 | 权限与行为 |
| --- | --- |
| `/help` | 白名单用户查看自己可用命令 |
| `/chat status` | 模型、自己的历史轮数、摘要有无、上下文估算值 |
| `/chat compress` | 压缩自己的较早对话 |
| `/chat reset` | 删除自己的对话、摘要和情感状态，隔离并清理外部记忆，保留统一人设 |
| `/whitelist list` | 管理员查看白名单 |
| `/whitelist add QQ号` | 管理员授权聊天 |
| `/whitelist remove QQ号` | 管理员撤销权限，保留已有数据；管理员自身不可移除 |
| `/prompt show` | 管理员查看统一人设 |
| `/prompt set 内容` | 管理员修改统一人设，支持换行，各用户下一轮模型请求生效 |
| `/prompt reset` | 管理员恢复内置小暖人设 |
| `/profile name 角色名` | 管理员设置角色正式名字，下轮模型请求生效，保留原始人设正文 |
| `/profile nickname 昵称` | 管理员同步设置QQ昵称和角色昵称，QQ接口成功后保存 |
| `/profile avatar` | 管理员开启5分钟等待，期间其私聊发来的第一张图片用于更新机器人头像 |
| `/profile avatar cancel` | 管理员取消头像等待 |
| `/voice on`、`/voice off`、`/voice both` | 白名单用户分别开启语音、恢复文字、开启文字及语音回复；按用户保存，默认off |
| `/voice say 内容` | 白名单用户单次朗读内容，不调用聊天模型、不写聊天历史 |
| `/chat emotion` | 查看自己的情绪估算、互动熟悉度与成功互动轮数 |
| `/chat memory status` | 查看当前记忆后端、自己的同步/清理待办与本进程最近错误 |
| `/chat memory sync` | 重试自己的记忆同步/删除，单次最多处理 20 项 |
| `/chat memory clear` | 隔离并请求删除自己的外部长期记忆，保留本地对话和摘要 |
| `/tool 内容` | 显式授权本轮调用工具，其他聊天不调用工具 |
| `/task` | 查看任务、定时执行、查询、控制及成果命令 |
| `/task remind` | 创建无需模型的定时文本提醒 |
| `/tools` | 查看可用工具；管理员可显式启用或关闭本机命令 |

初始仅管理员可用。历史中的旧回复不会随着人设修改被改写。白名单撤销时，在途聊天请求也会在存储和回复前重新检查权限。

角色正式名与昵称单独持久化，组合到每轮 system 消息末尾，姓名冲突时优先于原文和旧对话。`/prompt show` 仍返回原始人设正文，`/prompt set`、`/prompt reset` 不清除单独设置的身份。可用 `/profile name 爱` 和 `/profile nickname 小爱` 让自我介绍和QQ显示昵称一致。设置值限1至32个字符且不能换行；原始人设文件不会被改写。

资料命令不调用模型，不受聊天排队影响。头像等待按机器人账号保存，重启后仍按原期限计时；再次 `/profile avatar` 会重新计时。普通文本不消耗等待，群图片和其他账号图片不触发；同一消息多图只用第一张。第一张图在更新前消耗资格，失败不会自动取下一张，需重新发命令。过期后图片恢复普通识图，其他白名单用户的图片也按普通识图处理。调用 NapCat 的 [set_qq_profile](https://napcat.apifox.cn/226657374e0) 和 [set_qq_avatar](https://napcat.apifox.cn/226658980e0)，QQ客户端可能需刷新资料才能显示；接口超时可能已生效，应先检查再重试。

## 配置

修改 `.env` 后重启。进程环境变量优先。上下文最大 260K，超过 240K tokens 时自动压缩（用量为估算值）。`COMPRESS_ROUNDS=0` 关闭按轮数触发；启用轮数触发时 `KEEP_ROUNDS` 必须小于 `COMPRESS_ROUNDS`。`COMPRESS_TOKENS` 必须大于 0 且小于 `CONTEXT_TOKENS`。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `HOST` / `PORT` | `127.0.0.1` / `8080` | NoneBot 监听地址 |
| `ONEBOT_ACCESS_TOKEN` | 安装时随机生成 | NapCat 两端一致 |
| `LLM_BASE_URL` | `http://127.0.0.1:32126/v1` | buddyproxy 地址 |
| `LLM_MODEL` | `deepseek-v4.1-flash` | 聊天、摘要共用模型 |
| `LLM_API_KEY` | 留空 | 留空时按上述优先级查找 |
| `LLM_TIMEOUT` | `90` | 单次模型请求超时秒数；超时不自动重试，明确限流按下述配置退避 |
| `CHAT_TIMEOUT` | `90` | QQ 请求总等待秒数，包含排队、压缩、限流及工具；到期取消在途请求 |
| `CHAT_NOTICE_SECONDS` | `8` | 尚未处理完时发送一次等待提示，须小于总等待上限 |
| `LLM_MIN_INTERVAL` | `1` | 本进程模型请求最小启动间隔秒数 |
| `LLM_RATE_BACKOFF` | `30` | 明确上游限流时首次退避秒数，下一次加倍，最多 120 秒 |
| `LLM_RATE_RETRIES` | `2` | 仅对明确 429/代理 `rate_limited` 重试次数，设 0 禁用 |
| `DB_PATH` | `data/buddy.sqlite3` | SQLite 文件 |
| `COMPRESS_ROUNDS` | `0` | 0 关闭按轮数触发；正数表示已有历史超过该轮数时压缩 |
| `KEEP_ROUNDS` | `6` | 压缩保留最近完整对话轮数 |
| `CONTEXT_TOKENS` | `260000` | 预计输入最大预算，压缩后仍超出则拒绝聊天请求 |
| `COMPRESS_TOKENS` | `240000` | 预计输入严格超过该值时自动摘要压缩 |
| `MAX_INPUT_TOKENS` | `6000` | 单条用户输入估算上限 |
| `MAX_REPLY_TOKENS` | `1200` | 聊天模型输出上限 |
| `SUMMARY_TOKENS` | `1600` | 摘要模型输出上限 |
| `MESSAGE_CHARS` | `1500` | QQ 纯文本每段字符数 |
| `MEMORY_BACKEND` | `none` | `none` / `mem0` / `letta`，一次只启用一个后端 |
| `MEMORY_BASE_URL` | 空 | 外部服务根地址，启用后必须填写，不加 `/v1` |
| `MEMORY_API_KEY` | 空 | 独立的记忆服务密钥，不复用 buddyproxy 密钥 |
| `MEMORY_TIMEOUT` | `12` | 每次记忆 HTTP 调用超时秒数 |
| `MEMORY_TOP_K` | `5` | Mem0 检索结果数 |
| `MEMORY_CHARS` | `2400` | 本轮检索文本总字符上限，同时为 Letta 记忆块字符上限 |
| `EMOTION_ENABLED` | `true` | `true`/`1`/`yes` 开启；`false` 关闭情感状态推演与注入 |
| `TASKS_ENABLED` | `true` | 启用任务命令、显式 /tool 工具调用和后台调度 |
| `TASK_WORKSPACE` | `data/tasks` | 任务成果目录，按用户 QQ 和任务 ID 隔离 |
| `TASK_POLL_SECONDS` | `1` | 调度和通知轮询间隔秒数 |
| `TASK_CONCURRENCY` | `2` | 总任务并发数，每个用户最多同时执行 1 个 |
| `TASK_MAX_PER_USER` | `50` | 每个用户的未结束任务数量上限 |
| `TASK_RUN_TIMEOUT` | `900` | 单轮后台任务总执行时间上限秒数 |
| `TASK_RESULT_CHARS` | `10000` | 单次工具结果进入模型上下文的字符上限，完整长结果另存文件 |

| 新配置 | 默认值 | 说明 |
|---|---|---|
| `DSH_BASE_URL` | `http://127.0.0.1:32128` | 只允许本机 HTTP 根地址 |
| `DSH_TOKEN` | 空 | 与 DSH 服务相同的独立随机令牌 |
| `IMAGE_MODEL` | `hunyuan-image-alpha` | buddyproxy 图片生成模型 |
| `IMAGE_TIMEOUT` | `150` | 生成和下载图片总超时秒数 |

## 后台任务、定时主动执行和工具

管理员人设上传：`/prompt upload` 开启5分钟接收窗口，下一条非命令私聊文本或 `.txt`/`.md` 文件替换统一人设，成功后关闭窗口，`/prompt cancel` 取消。等待状态持久化，重启后保留原截止时间。文件支持普通文件消息及OneBot `offline_file` 通知，通过NapCat私聊文件直链获取正文；不读取消息中提供的本地文件路径。最大512KB，支持UTF-8、带BOM的UTF-16和GB18030，超过人设上下文预算、空白、二进制、下载失败均保留旧人设，剩余时间内可重发。原文与确认不进入聊天/记忆，不调用LLM，也不回显提示词正文。五分钟过期后的普通文本恢复聊天处理；群消息及其他账号不会更新人设。

机器人保留 SQLite 任务调度、提醒、任务查询、成果文件和 QQ 通知，agent 执行改由官方 DeepSeek Harness 独立服务负责，自制 JSON 工具协议、搜索工具、笔记工具和模型循环已移除。旧笔记和步骤保留用于审计，不再作为工具开放。首次升级暂停旧 agent 任务，提醒照常；请核对旧操作后显式恢复，避免重放副作用。

管理员先执行 `/task shell on`，再通过 `/task run 任务描述` 创建后台 DSH 任务。其他白名单用户仍可使用提醒，不能使用 DSH。普通对话不提供通用工具。明确的“帮我画一张…”或 `/draw 描述` 直接调用 Images API，图片以 QQ 图片段或网页图片显示；生成失败不写成功历史。

```text
/task shell on
/tool 计算(17+25)*3，将结果保存为result.txt并读取确认
/tool 打开 https://example.com，读取标题并保存截图到 screenshot.png
/task list
/task show 任务ID
/task steps 任务ID
/task files 任务ID
/task file 任务ID result.txt
/task pause 任务ID
/task cancel 任务ID
/task resume 任务ID
/task retry 任务ID
/task remind in 10m 喝水
/task shell off
```

`resume` 使用相同 DSH 会话，恢复后必须核对实际副作用；`retry` 新开一轮。DSH 的详细模型/工具事件保存在独立 state 中，机器人步骤表记录整个 DSH 调用。进程中断且副作用不确定时暂停。浏览器恢复会新建实例，不承诺保留登录页面。关闭开关阻止后续任务，已有任务需 `/task cancel ID` 停止；已完成操作无法撤销。

DSH 在独立非 root 容器执行，只有任务成果目录与机器人共享，不挂载聊天数据库、人设或宿主机 Docker socket。容器可联网、可运行 shell，管理员应只提交可信任务；容器不是每个任务独立的安全边界。模型代理凭据在 DSH 容器内，不能把不可信代码当作无风险脚本执行。

提醒、周期任务、重启恢复、过期清理和 `/task` 查询继续可用。`/chat reset` 仅清空陪伴历史、摘要和情感状态，保留任务与成果。任务结果不加入陪伴历史。QQ 断线时任务可继续，通知落盘后重试；QQ 接收成功但响应丢失时仍可能重复通知。

详见 [DSH 部署和插件说明](../deploy/dsh/README.md)。公开 Git 仓库可通过 git/浏览器访问；私有 GitHub 和额外 MCP 需要独立配置凭据，当前不会自动读取桌面登录或 Git 凭据。

## 管理员本机命令

超级管理员先发送 `/task shell on`，之后其任务可调用 `shell` 执行 PowerShell 或 Python；`/task shell off` 关闭，开关跨重启保存。普通白名单用户即使在人设或任务中要求也不能调用或启用 shell。工具在任务目录启动隐藏子进程，限制执行时长、收集退出码与有界输出，取消/超时会终止该工具拥有的进程树；子进程环境不继承机器人和模型密钥变量。

**shell 具有运行机器人账户的本机权限，不是沙箱。** 工作目录限制只约束文件工具，不能约束管理员脚本。脚本能读取该账户可访问的文件和网络；只在信任任务内容时启用。关闭开关会阻止后续调用，正在执行的命令需同时 `/task cancel ID` 才会停止。不能撤销命令已经产生的副作用。

### 重启、清空与投递

每次工具调用前保存计划，之后将结果和执行消息同事务保存。正常停机取消正在等待的模型/工具；重启从已存检查点继续。如果进程在写文件、记笔记或命令执行中断，执行结果可能不确定，任务会暂停并说明，管理员/用户检查后显式 `/task resume ID`，模型会收到「先检查实际状态、不要直接重复副作用」的记录。任务数据库由操作系统文件锁保护，同一数据库只允许一个机器人进程启动，避免第二实例错误恢复正在执行的任务。

任务调度和结果通知由独立异步循环处理，QQ 断线不阻止任务执行。完成、失败或需要补充信息时，仅给任务所有者发纯文本通知；没有默认定时问候。通知内容与分段进度落盘，断线后自动重试；若 QQ 已接收但响应丢失，仍可能重复一段，无法保证 QQ API 恰好一次投递。`/task show` 随时可查结果，任务记录保存创建时机器人 QQ，只通过该机器人账号投递。撤销白名单会取消其未结束任务、停止后续工具和结果通知，已有记录保留。

`/chat reset` 仅清空陪伴记忆和情感状态，**保留独立任务、任务笔记及成果文件**，后台任务不写入陪伴历史，因此不会在清空后恢复旧聊天。停止定时工作请使用 `/task cancel ID`。`TASKS_ENABLED=false` 可在重启后整体禁用调度和任务工具，数据库记录保留。

## 图片识别与语音回复

`/profile avatar` 等待期间，管理员第一张图片只用于头像更新，不进入视觉模型；其他白名单私聊图片会先调用视觉识别请求（默认与聊天使用同一DeepSeek模型），再把明确标注为可能误识、非用户自述的图片描述交给当前陪伴模型回复。支持单图、多图及配文，默认最多3张，每张原文件最多5 MiB。图片通过可信NapCat缓存或QQ官方图片CDN取得，下载逐跳检查公网地址并固定连接IP，拒绝私网地址。解码检查像素上限，最长边压缩到1536，GIF只取首帧，重新编码JPEG以去除EXIF；不持久保存原图或base64。聊天历史只保存附言、带来源标注的识图描述及成功回复；识图推断不作为用户事实写入外部长期记忆，情绪模块只分析用户原配文。识图、聊天、清空仍使用同一用户锁。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `VISION_MODEL` | 跟随 `LLM_MODEL`，默认 `deepseek-v4.1-flash` | 通过同一buddyproxy识图，DeepSeek V4.1 Flash已用自造文字图片实际验证；可单独覆盖为其他视觉模型 |
| `VISION_MAX_IMAGES` | `3` | 单条消息图片数上限 |
| `VISION_MAX_BYTES` | `5242880` | 每张原图字节上限 |
| `VISION_TIMEOUT` | `40` | 图片下载及识别的总时限秒数，仍受CHAT_TIMEOUT约束 |
| `TTS_BACKEND` | `auto` | auto优先Edge在线语音、失败回退Windows SAPI；也可edge/sapi/gptsovits/none |
| `TTS_VOICE` | `zh-CN-XiaoxiaoNeural` | Edge中文女声音色；Windows回退使用系统默认语音 |
| `TTS_TIMEOUT` | `30` | 每段语音合成时限秒数 |
| `TTS_MAX_CHARS` | `500` | `/voice say` 字数上限；自动语音超过此长度分段合成和发送 |
| `TTS_BASE_URL` | `http://127.0.0.1:9880` | GPT-SoVITS API 地址 |
| `TTS_REF_AUDIO` | 空 | GPT-SoVITS 服务内的参考音频路径 |
| `TTS_PROMPT_TEXT` | 空 | 参考音频的准确转写，启用gptsovits时必填 |
| `TTS_PROMPT_LANG` | `all_ja` | 参考音频语言 |
| `TTS_TEXT_LANG` | `zh` | 合成正文语言 |

默认文字回复。`/voice on` 后只有成功的聊天正文会合成为语音，命令确认、错误提示和后台任务通知仍用文字；`/voice both` 同时发送正文与语音。语音生成或发送失败时回退完整文字并提示，避免吞掉成功回复。`/voice say 内容` 可直接测试。发出的音频使用OneBot `record` 消息段，由NapCat转换并发送QQ语音，不将音频base64当文字发送。撤销白名单后不再投递。

Edge合成使用 [edge-tts](https://github.com/rany2/edge-tts)，待朗读文本会发送到微软Edge语音服务；Windows本机合成可设置 `TTS_BACKEND=sapi`，音色依赖系统语音包。自托管克隆音色使用 `TTS_BACKEND=gptsovits`，部署方法见 [云端语音指南](../deploy/gpt-sovits/README.md)。该后端失败不会切换到其他音色，服务入口隐藏上游逐句文本日志，模型和参考音频不进入Git。输入语音转文字目前未实现。语音临时文件在合成后清理，正常运行不保存音频；显式验收脚本会保留固定测试音频供检查。

## Mem0 / Letta 长期记忆

聊天仍由 buddyproxy 的 DeepSeek 执行；外部记忆只提供持久资料，不能修改白名单或统一人设。推荐先接 Mem0 做语义检索；如果已有 Letta 服务，可以选用本项目的独立用户记忆块适配。本项目不创建 Letta Agent，也不让 Letta 接管聊天或工具调用。

**Mem0 OSS REST**：先按 [Mem0 官方自托管说明](https://docs.mem0.ai/open-source/setup) 部署服务，完成初始化并创建 API key。Mem0 自身需要配置抽取模型、嵌入模型和存储；buddyproxy 的聊天接口不等于嵌入服务，不能假定它能满足 embedding 请求。再设置：

```dotenv
MEMORY_BACKEND=mem0
MEMORY_BASE_URL=http://127.0.0.1:8888
MEMORY_API_KEY=填写本地服务的API密钥
```

适配器遵循 [Mem0 OSS REST API](https://docs.mem0.ai/open-source/features/rest-api)：`POST /memories` 写入用户自述，`POST /search` 带 `filters.user_id` 和 `top_k` 检索，`DELETE /memories?user_id=...` 删除。采用 `X-API-Key` 鉴权。当前 OSS 的批量删除接口要求管理员角色，因此应使用该独立 Mem0 服务中管理员创建的 API key；403 会保留清理待办，不会宣称外部删除成功。这里的 `8888` 是官方 Compose 示例宿主机端口，应以实际服务为准。**不兼容托管 Mem0 Platform 的 `/v1`、`/v2` 或 `/v3` API**；不要将 `api.mem0.ai` 填给 OSS 适配器。

**Letta blocks**：部署已有 Letta 服务或使用其云端 API，配置服务根地址与独立访问令牌，例如：

```dotenv
MEMORY_BACKEND=letta
MEMORY_BASE_URL=http://127.0.0.1:8283
MEMORY_API_KEY=填写Letta访问令牌
```

云端可改为 `https://api.letta.com`。接入的是 [Letta block 创建接口](https://docs.letta.com/api/resources/blocks/methods/create) 及 [更新接口](https://docs.letta.com/api/resources/blocks/methods/update)：每用户独立 block，使用 Bearer Token；查询时读取其记忆块，写入时额外调用一次 buddyproxy，将旧资料和新自述合并为有界记忆。这是结构化核心记忆，不是 Letta archival 语义检索。若超过字符上限或整理失败，保留旧记忆和待办，不截断覆盖。

每次聊天先检索资料，成功聊天后将用户自述加入 SQLite 同步队列，与对话及情感状态同事务落盘。每轮随后最多同步 3 项，可能增加回复等待时间；失败不影响已成功的聊天，`/chat memory status` 可见待办，下次成功聊天或 `/chat memory sync` 重试。队列跨重启恢复，摘要删除旧轮次不会丢失尚未同步的自述。只从用户自述提取记忆，避免把助手编造的经历存成用户事实。检索资料单独放在历史资料消息中，受字符预算约束；若挤占上下文预算，本轮舍弃检索资料，保留正式历史。

外部 `user_id` 是随机作用域而非原始 QQ 号，Letta block ID 存在本地数据库。`/chat reset` 会同时删除本地历史、摘要、情感状态、未写入队列，停用所有旧作用域并建立外部删除待办。外部服务离线时会明确显示未完成清理数；旧作用域立即停止检索，恢复服务后执行 `/chat memory sync`。`/chat memory clear` 仅清理长期记忆，不删除本地聊天或情感状态。切换服务地址/后端会使用不同作用域，旧服务的删除待办需切回原配置重试；不会自动迁移记忆。关闭情感模块不会删除其已存状态，`/chat reset` 才删除。

记忆同步采用至少一次重试，网络超时后可能出现重复 Mem0 事实；Letta 创建 block 后若响应丢失，可能存在未登记的孤立 block，需在外部服务按 `xiaonuan_` 标签清理。本项目不能保证外部服务备份、日志或异步处理中的物理删除；本地作用域隔离保证清空后不再读取旧记忆。外部服务仅在显式启用后收到用户自述及检索查询；默认不开启。

## 情感状态

情感状态不是给 AI 宣称真实感情，而是持续调节回复风格的本地模块：识别平静、低落、焦虑、疲惫、生气、开心、孤单；记录置信度、情绪倾向 `[-1,1]`、活跃度 `[0,1]`、互动熟悉度 `[20,100]` 与成功轮数。它不另发 LLM 请求，只分析当条文本，按用户持久化到 SQLite。

情绪与置信度按 6 小时半衰期回归平静。熟悉度每半小时最多增加 0.5，不因离线或负面情绪扣分；仅调节表达自然度，不触发主动消息或关系承诺。风格提示明确要求先回应用户当下情绪，不责怪离线、不索取陪伴。状态只在成功聊天后保存，模型失败、命令、超长输入与未授权事件不会增加轮数。`/chat emotion`、`/chat status` 始终标注为规则估算；规则虽处理常见否定、第三人叙述和引用，仍可能误判反讽、复杂语境，以用户表述为准。`/chat reset` 恢复初始状态。

## 记忆与并发行为

SQLite 保存白名单、统一人设、按 QQ 号隔离的完整轮次及摘要，重启恢复。每轮仅在得到非空、未因长度限制截断的最终正文后落盘，超时、认证失败、空回复均不写入该轮。只读取 `message.content`，不发送或保存 `reasoning_content`。QQ 输出通过文本消息段构造，即便正文包含 CQ 码也按普通文本发送。

参考 [AstrBot 上下文压缩文档](https://docs.astrbot.app/use/context-compress.html) 的摘要思路，将已有摘要与较早完整轮次合并，关注称呼、偏好、重要经历、情绪变化和未完话题；最近 6 轮保留原文。摘要用独立历史资料消息组织，不加入统一 system prompt。成功后同一 SQLite 事务更新摘要、删除对应旧轮次。失败保留原数据并提示重试，自动压缩失败时不会继续发起聊天请求。无可压缩旧轮次时，手动压缩会说明；超预算请求会要求缩短输入或清空。压缩已成功而之后聊天失败时，成功的摘要仍保留。

token 均为**估算值**：非 ASCII 每字符约 1.5 token、ASCII 每四字符约 1 token，加上消息开销。这不是 DeepSeek 实测分词或代理返回的精确用量；输入预算不含输出额度，配置时应给模型实际上下文限制留出输出余量。`/chat status` 展示当前已存上下文和情感风格提示，不含下一条消息及该轮临时检索资料。

同一用户的聊天、状态、手动/自动压缩、清空共用异步锁。清空会等待此前模型请求完成，然后删除其历史与摘要，避免旧请求在清空后恢复历史；不同用户的模型调用可并行。仅运行一个机器人进程，不支持多个实例共享数据库。长回复顺序分段；模型成功响应在 QQ 发送前落盘，若 QQ 断线导致发送失败，历史仍保留该轮，无自动补发。

默认日志级别 WARNING，避免 NoneBot 的事件 INFO 日志打印完整私聊；模型错误仅记录异常类型，不输出响应体、聊天或密钥。不要开启框架/HTTP debug 日志。数据库为本地明文，应妥善保管；备份时先停止机器人并复制整个 `data` 目录（包含可能存在的 WAL 文件）。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 显式向本机代理发起真实聊天和摘要，不连接 QQ，不写正式数据库
.\.venv\Scripts\python.exe -m scripts.verify_proxy
# 真实 DSH 任务验收，不使用正式数据库，不向 QQ 投递
.\.venv\Scripts\python.exe -m scripts.verify_tasks
# 自造测试图的真实视觉识别，以及固定短句的真实语音合成（不向QQ发送）
.\.venv\Scripts\python.exe -m scripts.verify_multimedia
.\.venv\Scripts\python.exe -m scripts.verify_multimedia voice
```

自动测试覆盖权限、静默过滤、越权命令、白名单撤销保留数据、多用户隔离、重启恢复、人设更新、清空摘要、连续与自动压缩、失败数据保留、过长输入、超预算拒绝、并发清空和模型错误脱敏。OneBot 集成测试会启动真实 NoneBot 服务，用本地模拟 NapCat WebSocket 验证 Token 鉴权、事件接收、群/自身/不支持类型过滤、普通图片多模态识别、头像优先和语音发送、纯文本分段发送与思考内容排除；模型侧使用本地 HTTP 模拟接口。

新增测试覆盖 Mem0 作用域过滤、Letta 记忆块创建/读取/更新/删除、失败队列恢复、清空与外部写入串行、外部故障降级及日志脱敏、记忆预算回退、情绪时间衰减与熟悉度限速。外部记忆 API 使用 MockTransport 契约测试，尚未在真实 Mem0/Letta 服务上验收；启用服务后可按「自述偏好 → 重启 → 检索偏好 → `/chat reset` → 确认不再检索旧偏好」检查，避免把仍在本地历史中的偏好误认为外部检索结果。

真实 QQ 验收须在 NapCat 登录并连接后进行：管理员 `/help` → 普通聊天 → 添加另一账号 → 双方发送不同个人信息检查隔离 → `/chat compress`（至少积累 7 轮）→ `/chat status` → 重启检查恢复 → `/chat reset` 检查轮数与摘要归零 → 撤销账号检查静默。群内消息与未授权账号不应触发模型。

## 排错

- **无法启动**：检查 Python 为 3.12、依赖安装成功、8080 未被占用，以及 `.env` Token 已替换。安装出错先查看 pip 网络/代理错误。
- **NapCat 未连接 / 403**：确认选择 WS 客户端、已启用、URL 路径完整、两端 Token 相同。WebUI Token 不能替代 OneBot Token。
- **检查运行状态**：访问 `http://127.0.0.1:8080/health`；`status=ready` 表示服务已启动，`connected_bots` 包含机器人 QQ 才表示 NapCat 已接入。此接口不返回令牌或聊天内容。
- **QQ 无回复**：检查发送者白名单、机器人 QQ 不是管理员自身、是私聊文字或图片；先发 `/help` 区分接入问题与模型问题。检查 NapCat 连接状态和 OneBot API 错误。
- **认证失败 / 模型不可用**：检查 buddyproxy 已运行、默认端口 `32126`、模型可用及密钥来源。环境变量中的旧密钥会覆盖文件配置。
- **超时 / 空回复 / 输出达上限**：检查代理和上游，稍后重试或缩短输入；必要时提高超时或输出额度。失败轮次不会写入，模型请求不自动重试。
- **压缩失败**：原数据保留，用 `/chat compress` 重试；检查代理可用性、摘要输出额度。超预算则缩短人设/输入，或用 `/chat reset` 清空自己的记忆。

项目结构：`bot.py` 为入口，`qqbot/plugin.py` 负责 OneBot 收发，`service.py` 负责权限和上下文，`store.py` 负责 SQLite，`llm.py` 负责代理调用，`memory.py` 负责外部记忆与持久待办，`emotion.py` 负责本地情感状态；测试位于 `tests/`。

`/task list` 只显示待执行、执行中、暂停和等待补充信息的任务；`/task list all` 包含保留的已结束历史。调度器每分钟自动清理结束满 7 天的成功、失败、取消任务及其执行、步骤和审计记录。尚未投递的通知会保留，循环任务和逾期待执行任务不按到期时间删除。生成文件和独立笔记保留。取消任务会停止旧通知重试。

管理员号池命令：`/pool`（或 `/pool status`）查看默认号池，`/pool cn` 切国内，`/pool global` 切国际。切换由代理保存，后续无显式区域绑定的聊天请求跟随默认号池；发送“签到”也跟随当前号池，不再读取 `BUDDY_SITE`。
