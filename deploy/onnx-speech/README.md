# 完整 ONNX 多音色语音

三套 v2ProPlus 模型：`aoi` 悠木碧、`noto` 能登麻美子、`hayami` 早见沙织。`edge` 是原微软晓晓在线语音，由机器人直接调用。默认文字回复；`/say 内容` 单次朗读，`/voice on|off|both` 设置回复方式。

`/speaker list` 查看音色，`/speaker noto` 切换自己的音色，`/speaker reset` 恢复默认。选择保存在 SQLite，重启恢复，不影响其他用户。命令仅对白名单私聊生效，不调用聊天模型。克隆语音生成失败不会自动换成 Edge。

## 实现

基于 [Genie-TTS](https://github.com/High-Logic/Genie-TTS) 固定提交 `d347fd0f8683e9a362b69f59fa0a4799ddb5e828`（MIT）。GPT 编码器、首步/后续语义解码器、SoVITS 声学解码器全部由 ONNX Runtime CPU 执行；GPT 支持动态 QUInt8 和 FP16权重存储/FP32计算，SoVITS 保持 FP32。中文 BERT 使用 INT8 ONNX，中文发音使用 g2pM/拼音前端。

参考语音的 HuBERT、说话人向量、声学条件提前离线计算，每套声音保留自己的参考 WAV、准确日语转写和特征。运行镜像无需 Torch、HuBERT、SV 或显卡，无需本机开机。构建时检查 Torch 未安装，`/health` 报告 `torch_loaded=false`。只保留当前声音的 GPT 会话（FP16存储模式的首步/后续解码器按阶段分别加载并释放），切换时卸载旧会话；BERT 在文本特征计算后释放，再加载 SoVITS，生成后释放声学会话，避免两者的权重和工作区同时驻留。推理与模型切换串行。

标点转为程序内部 `TextToken` / `PauseToken`：弱停顿约120ms，分号/冒号约200ms，句间约300ms，以静音拼接实现，不把未训练的特殊占位符送进GPT。过短子句合并后再生成，避免零碎语音；数字时间的冒号保留。若某音色无法生成独立短片段，丢弃局部音频，以同一音色合并完整正文重试，优先保证不漏后句；该次中间停顿可能减少。修正提前终止时 `-0` 切片可能带入参考语义的边界；退化语义最多采样三次，仍失败明确报错。时长只用于退化检查，不能证明正文完整。

## 离线准备

模型、参考语音、转写、资源和哈希清单均为部署私有数据，不提交 Git。

1. `python prepare-source.py --checkout <新的完整源码目录>` 下载并固定上游版本，生成镜像需要的 `source/`。原项目与模型不被修改。
2. 在具备 Torch、ONNX 1.16.2、ONNX Runtime、NumPy、soundfile、soxr 的导出环境，为每套声音运行：

   ```text
   python export-models.py --checkout <完整Genie源码> --gpt <模型.ckpt> --sovits <模型.pth> --output <assets/aoi>
   python prepare-reference.py --gsv-source <完整GPT-SoVITS目录> --reference <3到10秒参考.wav> --output <assets/aoi>
   ```

   `noto`、`hayami` 分别使用对应模型和参考。导出环境需要原 GPT-SoVITS 的预训练 HuBERT/SV 资源；这些不会进入线上镜像。导出缓存保留，失败时不递归删除资产。
3. 将已有 `bert.int8.onnx` 和配套 `tokenizer.json` 放到 `assets/roberta/`。BERT 导出工具见 [旧语音目录](../gpt-sovits/README.md)。从 [Genie 资源库](https://huggingface.co/High-Logic/Genie) 获取 `G2P/ChineseG2P`、`G2P/EnglishG2P`，放到 `assets/resources/G2P/`，包括英文词典、分词和 NLTK 标注资源。记录下载提交，部署时不自动联网下载。
4. 准备私有 `profiles.json`，顶层恰为 `aoi`、`noto`、`hayami`；每项包含 `name`、与本套参考语音逐字对应的 `prompt_text`。参考语言为日语，输出支持中文和中英混合。
5. 准备环境安装 ONNX 1.16.2，Python 3.12 执行 `python prepare-assets.py --assets <assets> --profiles <profiles.json> --archive <assets.tar.gz>`。只打包运行需要的文件，排除 FP16/FP32 中间产物和原模型。启动校验 SHA256；缺失或校验失败不会报告就绪。

## 云端运行

```bash
docker build -t xiaoai-genie:onnx deploy/onnx-speech
docker run -d --name xiaoai-speech --restart unless-stopped --network host \
  --memory 1400m --memory-swap 5g --cpus 1.5 \
  -e ORT_THREADS=2 -v /opt/qqbot/onnx-speech/assets:/voices:ro \
  -v /opt/qqbot/voice/language/pyopenjtalk_dic:/usr/local/lib/python3.12/site-packages/pyopenjtalk/open_jtalk_dic_utf_8-1.11:ro \
  xiaoai-genie:onnx
```

PyOpenJTalk 字典需要提前准备并只读挂载。默认监听 `127.0.0.1:9880`，不开放公网端口。内存不足时可配置交换空间；交换不能替代物理内存，实际延迟必须在目标机器测量。Dockerfile 可用 `PYTHON_IMAGE` 指定已有基础镜像；只有该镜像已经包含编译器和 libgomp 时才能设置 `SYSTEM_DEPS=0`。

机器人 `.env`：

```dotenv
TTS_BACKEND=genie
TTS_BASE_URL=http://127.0.0.1:9880
TTS_DEFAULT_SPEAKER=aoi
TTS_TIMEOUT=180
TTS_MAX_CHARS=40
```

此后端不需要机器人配置 `TTS_REF_AUDIO`、`TTS_PROMPT_TEXT`，参考资料由语音服务的清单选择。单次短文本优先；HTTP `/tts` 请求为 `{"speaker":"noto","text":"你好"}`，返回单声道 32kHz PCM WAV。接口保留默认 `aoi`，兼容旧客户端的额外字段。服务不记录输入正文、参考转写或模型响应；验证错误由 FastAPI 返回，推理异常仅记录异常类型。

`/speaker edge` 需要服务器能访问微软 Edge 语音服务，朗读文本会发送给微软。三种 ONNX 声音的文本和参考均在本服务器处理。

## 更新与验收

替换前备份机器人 `.env`、SQLite 和旧语音容器；保留 NapCat 会话。先验证 `/health`、各声音多次 `/tts`、切换回原声音、WAV 时长/幅度，再切换机器人配置。检查 QQ 仍在线、人设摘要哈希不变、号池仍为国内。

机器人测试覆盖权限、独立持久化、重启、无自动换音色、排队请求保持原选择，以及模拟 OneBot 三种音色 `/say` 收发。模型端需额外做真实 ONNX 推理、冷/热延迟、内存/交换统计和人工试听；“生成 WAV”与“音色满意”分开验收。旧混合后端可使用原容器和 `TTS_BACKEND=gptsovits` 回滚。

### 本次部署测量（2026-10-21）

目标主机为2核、约2GB内存、无GPU。首轮传输测试中三种声音各测试8字短句和16字长句，另测试切换回悠木碧；7次请求均成功，响应约7.9–13.7秒，生成语音约1.1–4.9秒。此前混合后端的短句实测约42–58秒；这些是小样本的传输和时长记录，部分首版音频后续经试听发现截句，不能据此推断正文完整或比较相同朗读质量；文本、分段数量和系统负载都会影响耗时。

测试结束后 Docker 工作内存约544MiB；阶段加载会回收会话，后续进程RSS曾降到约301MiB。容器内存峰值仍达到1400MiB限制，并使用了少量交换空间，因此当前2GB服务器仍应保留交换空间，不能据空闲内存推断峰值。后台仅保留一套 GPT，切换并非同时常驻三套模型。

Windows及云端Linux各104项机器人测试通过，12项 ONNX 停顿/语义边界和2项采样/FP16存储测试通过；生产机器人通过模拟 OneBot 验证 `aoi/noto/hayami/edge` 均返回真实音频，Edge 真实生成MP3。QQ连接、人设哈希和历史保留已检查。新音色的最终音质、完整性和手机播放仍以用户实际试听为准。

### 采样与停顿修复

Genie 固定版本的图模板把采样噪声导出成 `RandomNormalLike`，而原 GPT-SoVITS `multinomial_sample_one_no_sync` 使用指数分布。`fix-sampler.py` 将其修正为 `-log(U)`，其中 `U` 限定在 `(0,1)`，用于 `argmax(probabilities / noise)`。导出脚本自动修正；已有资产升级时先停语音服务、备份模型和清单，再执行 `python fix-sampler.py --assets <assets>`，修复六个语义图并刷新 SHA256。`prepare-assets.py` 会拒绝旧采样图，启动清单需标记 `sampler=exponential-v1`。这是离线模型图修复，生产镜像仍不安装 ONNX Python 包或 Torch。

导出/修复环境运行 `python -m unittest test_engine test_sampler -v`；共14项测试，包括10000次采样与给定类别概率的对照。用户试听发现的“只念你好”另用本机离线ASR对生成音频检查后半句；ASR可能混淆同音字，不能代替最终音质试听。

### aoi 的精度选择

aoi 在INT8模型中仍出现个别截句，因此改为 `decoder_format=fp16-storage`：共享权重以FP16保存，每个CPU算子使用FP32，不再做INT8权重量化。noto和hayami保留当前INT8设置。此模式不是CPU原生FP16计算；[ONNX Runtime的FP16说明](https://onnxruntime.ai/docs/performance/model-optimizations/float16.html)主要针对GPU加速，不能据文件变小推断CPU提速。

`export-models.py` 同时输出 `.q8.onnx` 与 `.fp16-storage.onnx`；在私有profiles中为aoi指定 `"decoder_format":"fp16-storage"`，其他声音可省略或填q8。`prepare-assets.py`只打包该声音选择的图及配套外部权重；启动校验哈希。FP16存储模式分别加载首步与后续解码器，释放后才加载SoVITS，控制权重副本峰值。`test_sampler` 对CPU上原FP16权重的计算输出进行一致性验证。

最终aoi精度对照：同一句“你好，我是梦梦。”连续生成5次，离线ASR均识别出完整姓名；带逗号长句和两句话也保留全部分句。短句约10.6–13.1秒，长句/多句约21–22秒。noto由用户确认完整；aoi此次精度切换仍需手机端最终试听。这是有限样本验证，不保证任意文本都不存在发音或漏字问题。
