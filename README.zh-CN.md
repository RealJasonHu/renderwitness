# RenderWitness

> 截图 Diff 只能证明像素变了。**RenderWitness 判断用户体验是否真的坏了，并保留足够证据供人复核。**

[English](README.md) · [架构](docs/architecture.md) · [模型接入](docs/model-guide.md)

RenderWitness 是一个面向 Web 与桌面界面的证据优先视觉回归审查工具。它先通过确定性图像算法定位 baseline 与 candidate 之间的变化区域，再让视觉语言模型（VLM）判断这些变化属于无害渲染噪声、文本截断、控件缺失、布局错位还是内容变化，最后生成带原图、框选区域、指标与模型元数据的自包含 HTML + JSON 报告。

它不是“上传图片后聊天”的套壳 Demo：项目包含严格结构化输出、多模型兼容接口、本地模型路径、提示注入边界、可复现实验元数据、无密钥测试和 OCI 构建。

## 核心亮点

- **证据可追溯**：每条语义结论必须引用确定性检测出的区域编号。
- **中英文界面场景**：内置 Demo 同时覆盖中文 CTA 截断、导航控件消失和无害阴影变化。
- **本地优先**：通过 Ollama + Qwen3-VL 在本地分析，主程序不安装沉重的 PyTorch 依赖。
- **诚实的离线 Demo**：`demo` provider 是明确标注的确定性合成行为，只用于 CI 与上手体验，不冒充真实模型。
- **可移植报告**：HTML 与 JSON 中保留截图、证据框、哈希、阈值、模型身份与耗时，无需数据库。

## 30 秒运行

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

renderwitness demo --output reports/demo
```

命令会打印生成的 HTML 路径；直接用浏览器打开即可。整个 Demo 不需要 API Key、GPU 或联网。

分析自己的截图：

```bash
renderwitness compare baseline.png candidate.png \
  --provider demo \
  --output reports/my-change
```

## 接入真实本地 VLM

```bash
ollama pull qwen3-vl:4b

export RENDERWITNESS_BASE_URL=http://localhost:11434/v1
export RENDERWITNESS_API_KEY=ollama
export RENDERWITNESS_MODEL=qwen3-vl:4b

renderwitness compare examples/baseline.png examples/candidate.png \
  --provider openai-compatible \
  --output reports/qwen3-vl
```

同一适配器也可以连接 vLLM 或托管的 OpenAI-compatible 服务。模型返回内容会先通过 Pydantic 校验，再进入报告。

## 处理链路

```text
baseline + candidate 截图
          ↓
解码、色彩归一化、输入大小限制
          ↓
像素差异阈值 + 连通区域合并
          ↓
确定性证据框 → Demo provider / 真实 VLM
          ↓
严格结构化语义结论
          ↓
自包含 HTML + JSON 证据报告
```

即使模型调用失败或结论无效，确定性 Diff 证据也不会丢失。详细设计见 [docs/architecture.md](docs/architecture.md)。

## 开发验证

```bash
python -m pip install -e '.[dev]'
make test
make lint
make coverage
```

CI 覆盖 Python 3.11–3.13、包构建、OCI 镜像构建以及无密钥端到端 Demo。

## 项目边界与路线图

当前 0.1 版本面向相同尺寸的 PNG/JPEG/WebP 截图对。VLM 结论只用于辅助审查，不等于无障碍、安全或发布认证；证据框说明“哪里变了”，不自动证明因果关系。

后续计划包括 Playwright 场景采集、rootless Podman 双镜像运行器、DOM/无障碍树证据、视觉故障注入基准，以及 GitHub Pull Request 注释。

## 作者

由 [Zhexun Hu](https://github.com/RealJasonHu) 创建，用于集中展示 VLM 工程、视觉测试、开发者工具与容器能力。

项目采用 [MIT License](LICENSE)。
