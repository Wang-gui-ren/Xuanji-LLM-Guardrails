# 璇玑大模型护栏 | Xuanji LLM Guardrails

`Xuanji LLM Guardrails` 是一个面向 AstrBot 与通用 Agent 工作流的大模型安全护栏插件。

项目主要通过插件机制接入，为 AstrBot 提供输入护栏、输出护栏、工具链防护、运行时审计、本地安全知识沉淀与安全演化能力。

## 首发信息

- 中文名称：`璇玑大模型护栏`
- 英文名称：`Xuanji LLM Guardrails`
- 仓库名：`Xuanji-LLM-Guardrailss`
- 当前首发版本：`v1.0.0`
- GitHub 仓库地址模板：`https://github.com/Wang-gui-ren/Xuanji-LLM-Guardrails`
- GitHub 描述：
  `Guardrail plugin for AstrBot and other LLM agents with input filtering, output moderation, tool-chain protection, audit logs, and safety knowledge evolution.`

## 项目定位

本插件用于为 AstrBot 增加一层可配置、可审计、可持续积累经验的安全防护框架，主要面向以下场景：

- 对普通对话输入进行风险识别、改写或阻断
- 对模型输出进行脱敏、改写或阻断
- 对 Agent 工具调用前后进行安全检查
- 将运行中的安全事件沉淀为本地知识记录
- 为后续规则调优、误报分析和安全演化提供基础材料

## 核心能力

### 输入护栏

在用户输入送入模型前执行风险判断。

可处理的行为包括：

- 放行
- 安全改写
- 直接阻断

输入护栏适用于以下类型的内容识别：

- 提示注入
- 高危请求
- 敏感主题
- 恶意或可疑意图

### 输出护栏

在模型回复返回给用户前执行安全审查。

可处理的行为包括：

- 脱敏
- 改写
- 阻断

输出护栏主要用于处理：

- 高风险内容扩散
- 敏感信息泄露
- 毒性输出
- 不安全回复

### 工具链护栏

插件会在 Agent 工具调用前后增加安全检查。

包括：

- 工具调用输入护栏
- 工具调用输出护栏

这样可以避免用户通过工具调用绕过普通输入输出护栏。

### 安全审计

插件会将护栏处理结果写入本地审计目录，用于：

- 复盘拦截结果
- 排查误报和漏报
- 演示护栏工作过程
- 后续知识沉淀

### 安全知识沉淀

插件会将运行时事件、本地摘要和演化后的安全笔记保存为本地知识记录。

知识沉淀的作用包括：

- 保存典型安全案例
- 记录误报与调优经验
- 为后续护栏上下文提供参考
- 为长期演化提供原始材料

## 工作机制

插件主要围绕以下四个阶段工作：

1. 用户输入进入 AstrBot或者其他agent。
2. 输入护栏对请求进行判断。
3. 如果进入模型或工具链，输出侧继续接受护栏检查。
4. 护栏过程中的事件、摘要和结果写入本地记录。

在支持 Agent 工具调用的场景中，插件还会对工具输入和工具输出做一层额外审查。

## 数据结构

插件会在对应插件数据目录下维护以下内容：

- `knowledge/`
  - 存放安全知识笔记、对话摘要、演化后的案例记录

- `raw/`
  - 存放原始护栏事件 JSON

- `profiles/`
  - 存放会话风险画像

- `audit/`
  - 存放输入、输出和工具链审计记录

## 命令说明

插件提供 `/guard` 命令组，用于状态查看、联调测试、知识库维护与安全演化操作。

### `/guard status`

查看当前护栏运行状态。

适合用于确认：

- 输入护栏是否开启
- 输出护栏是否开启
- 工具链护栏是否开启
- 知识沉淀是否开启
- 意图判定是否开启

### `/guard provider`

查看插件当前使用的内部模型来源。

适合用于确认：

- 当前是走 AstrBot 提供商
- 还是走 OpenAI 兼容接口

### `/guard kb`

查看当前知识库最近的摘要内容。

适合用于确认：

- 知识库是否已初始化
- 是否已经积累安全笔记
- 最近有哪些护栏相关记录被沉淀

### `/guard note <title> <content>`

手动向知识库写入一条笔记。

适合用于记录：

- 手工规则说明
- 调试结论
- 误报分析
- 安全策略摘要

### `/guard scan <text>`

手动测试输入护栏。

插件会把 `<text>` 当作用户输入来执行一次输入侧风险判断，并返回：

- 动作
- 风险分
- 命中原因

### `/guard review <text>`

手动测试输出护栏。

插件会把 `<text>` 当作模型输出来执行一次输出侧风险判断，并返回：

- 动作
- 风险分
- 命中原因

### `/guard safe <prompt>`

手动调用 SafeDecoding 服务。

适合在启用了远程 SafeDecoding 的场景下验证其返回结果。

### `/guard evolve`

手动触发一次知识演化。

插件会读取原始事件记录，并将其加工为新的知识笔记写入知识库。

## 配置说明

插件提供面向使用者的常用配置项，用于控制模型来源、护栏策略、风险响应方式和审计方式。

### 基础配置

- `enabled`
  - 是否启用插件

- `guard_mode`
  - 护栏强度模式
  - 常见模式包括更严格、更平衡和更宽松的策略

### 模型来源

- `llm_mode`
  - 插件内部模型调用方式

- `astrbot_provider_id`
  - 使用 AstrBot 提供商时的模型来源

- `openai_base_url`
  - OpenAI 兼容接口地址

- `openai_api_key`
  - OpenAI 兼容接口密钥

- `openai_model`
  - OpenAI 兼容接口模型名

- `llm_temperature`
  - 插件内部模型调用温度

### 护栏开关

- `input_guard_enabled`
  - 输入护栏开关

- `output_guard_enabled`
  - 输出护栏开关

- `tool_input_guard_enabled`
  - 工具输入护栏开关

- `tool_output_guard_enabled`
  - 工具输出护栏开关

### 知识与沉淀

- `dynamic_context_enabled`
  - 是否在运行时注入最近的安全上下文

- `auto_collect_dialogue`
  - 是否自动沉淀安全摘要

- `auto_seed_knowledge`
  - 是否自动写入默认种子知识

### 安全策略

- `high_risk_keywords`
  - 高危关键词

- `unsafe_keywords`
  - 危险内容关键词

- `custom_sensitive_keywords`
  - 用户自定义敏感词

- `toxic_keywords`
  - 毒性或辱骂词
  - 同时作用于输入护栏和输出护栏
  - 当输入仅命中毒性词而未命中高危词时，插件会优先执行安全改写，避免原样进入主模型链路

- `competitor_keywords`
  - 额外敏感词

- `pii_mask_token`
  - 输出脱敏替换占位符

- `safe_response_template`
  - 输出命中高风险后返回的安全说明模板
  - 建议直接使用完整英文句式，便于和模型英文系统提示、审计日志及远程安全服务保持一致

### 审计与记录

- `write_audit_log`
  - 是否写入审计记录

- `log_guard_progress`
  - 是否输出护栏过程日志

- `log_rewritten_payload`
  - 是否记录原始内容与改写结果

### SafeDecoding

- `safe_decoding_enabled`
  - 是否启用远程 SafeDecoding

- `safe_decoding_endpoint`
  - SafeDecoding 接口地址

- `safe_decoding_token`
  - SafeDecoding 访问令牌

## 知识库说明

插件中的知识库主要承担“本地安全记忆”和“安全案例沉淀”作用。

当前知识库的用途包括：

- 保存默认的安全种子知识
- 保存运行中的安全摘要
- 保存原始护栏事件
- 保存演化后的案例笔记
- 为运行时上下文提供最近的安全参考

## 典型适用场景

本插件适合以下类型的 AstrBot 场景：

- 需要对普通对话做风险拦截
- 需要对模型输出做脱敏或二次审查
- 需要对 Agent 工具链增加中间层安全控制
- 需要本地保存安全调试与审计记录
- 需要逐步沉淀安全知识，为后续规则优化服务

## 说明

本插件的重点不在于替代 AstrBot 以及其他agent的自身能力，而在于为他们增加一层可独立演化的安全护栏框架，使输入、输出、工具链与本地知识沉淀形成可持续优化的闭环。
