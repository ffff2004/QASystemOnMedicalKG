# DeepSeek Flash API 调研：Text-to-Cypher

核对日期：2026-11-26。范围：DeepSeek 官方文档中的 OpenAI 兼容 Chat Completions API。

## 已核实的 API 行为

| 项目 | 结论 |
| --- | --- |
| 模型与端点 | 请求填 `model="deepseek-flash"`，当前由 `DeepSeek-V4.1-Flash-1017` 提供服务；`deepseek-v4-flash` 和 `deepseek-v4-flash-vision-exp` 只是仍可用的旧名。SDK 的 `base_url` 是 `https://api.deepseek.com`；HTTP 端点是 `POST https://api.deepseek.com/chat/completions`，使用 Bearer 认证。[Quick Start][quick-start] · [API Reference][chat] |
| Function calling | Flash 在 thinking 和 non-thinking 下均支持 `tools`。模型在 `message.tool_calls` 中返回函数名、调用 ID 和 JSON 字符串形式的参数，并不执行本地函数。客户端校验参数并执行，将原 assistant 消息与各自的 `role="tool"`、匹配的 `tool_call_id` 和结果一并传入下一次请求。有工具时 `tool_choice` 默认是 `auto`；`required` 或指定函数在 thinking 下返回 HTTP 400，须先关闭 thinking。[Tool Calls][tools] · [Thinking Mode：Tool Calls][thinking-tools] · [`tool_choice`][tool-choice] |
| JSON Output | 用 `response_format={"type":"json_object"}`。中文 system 或 user prompt 也应包含 `json` 一词、明确要求 JSON 并给出目标结构示例；读取 `message.content`。Chat Completions 的 `response_format` 只有 `text` 和 `json_object`，不校验应用的 schema，也不约束 `tool_calls` 的参数。设置足够的 `max_tokens`：`finish_reason="length"` 可能表示截断；无法识别为 JSON 的输出可被替换成空格，即使 `finish_reason="stop"` 也要检查空白并处理重试或报错。[JSON Output][json] · [API Reference][chat] |
| Thinking | 默认开启、effort 为 `high`。用 `thinking.type=enabled` 或 `disabled` 显式选择；Python OpenAI SDK 通过 `extra_body={"thinking":{"type":"disabled"}}` 等方式传此字段。未显式指定 `thinking` 时，`reasoning_effort="none"` 也可关闭。Thinking 下 `temperature` 不生效；Flash 的 `top_p` 有效范围为 `0.95`–`1.0`，non-thinking 下固定为 `1.0`。推理单独返回在 `message.reasoning_content`，不要当作最终答案解析。[Thinking Mode][thinking] · [API Reference][chat] |
| Thinking 的消息历史 | 在 thinking 模式下，后续请求只要携带 `tools`，就要完整回传历史 assistant 消息中的 `reasoning_content`，包括未发起工具调用的轮次；漏传可触发 HTTP 400。不带 `tools` 的请求无需回传，传了也会被忽略。[Thinking Mode][thinking] |

工具参数的 `strict` 是独立的 Beta 功能：用 `https://api.deepseek.com/beta`，且每个 function 都须设 `strict: true`；它只约束工具参数的 JSON Schema，不能证明其中的 Cypher 安全或正确。[Tool Calls：strict Mode][strict]

## Agent 历史预算：API 限制与项目取舍

**结论：DeepSeek 文档可以作为整次请求的 token 上限依据，不能推导出项目应保留多少 UTF-8 JSON 字节。** 现有 128 KiB 是已完成轮次的本地保留上限，不是模型窗口，也不检查活动轮的请求大小。[`llm_qa.py`](../llm_qa.py)

- **窗口与输出（已核实）。** `deepseek-flash` 当前路由到 `DeepSeek-V4.1-Flash-1017`；官方价目表的 1M / 384K，在 `GET /models` 的文档示例中分别是 `context_window=1,048,576` 和 `max_output_tokens=393,216`。Chat Completions 明确限制的是**输入加生成输出**，未另列固定输入上限；推理 token 属于生成输出。项目显式设定每次调用 `max_tokens=8192`，若为这 8,192 个 token 留足空间，**整个输入**至多 1,040,384 token（尚未扣估算余量），不是历史配额或实测拒绝阈值。旧 `deepseek-chat` / `deepseek-reasoner` 或开源模型卡自部署示例里的 `max_tokens ≥ 256K` 不是当前托管 API 限制。[Models & Pricing][pricing] · [Lists Models][models] · [Chat Completions][chat] · [Change Log][changes] · [模型卡][flash-card]
- **用量与预估（已核实 / 未验证）。** 响应的 `usage.prompt_tokens` = `prompt_cache_hit_tokens` + `prompt_cache_miss_tokens`（`prompt_tokens_details.cached_tokens` 同命中数）；`total_tokens` = `prompt_tokens` + `completion_tokens`，可选 `completion_tokens_details.reasoning_tokens` 是输出的子项。未在 DeepSeek 的公开 Chat Completions API 中找到请求前 token 计数端点；`GET /models` 只给模型元数据。官方提供 V4 文本 tokenizer ZIP，另有 Flash 1017 的 tokenizer 与 prompt encoder，以及可按 Chat Completions 格式渲染并计数的 `deepseek-recipe`。不能用字符比例或对原始 JSON 直接分词来代替完整 prompt 计数；本地编码与托管计数是否完全一致未获保证，实际以 `usage` 为准。本次未做带凭据的 API 测试。[Chat Completions：Usage][usage] · [Lists Models][models] · [Token & Token Usage][token-usage] · [模型卡][flash-card] · [deepseek-recipe][recipe]
- **重放与缓存（已核实）。** Thinking 请求携带 `tools` 时，保留的所有历史 assistant `reasoning_content` 都须完整重放并计入上下文，即使该 assistant 没有调用工具；不带 `tools` 时服务端忽略该字段。本项目最后一次调用即便 `tool_choice="none"` 也仍传 `tools`。缓存默认启用，需完整匹配已落盘的前缀单元；仅尽力命中、会过期。命中降低输入计费和重复计算延迟，但命中的 token 仍占窗口，不应从预算扣除。保持固定 prompt / 工具定义和追加式前缀有利于复用；删最老轮会改变历史前缀，不应按必定命中来定预算。[Thinking Mode][thinking] · [Context Caching][cache] · [Models & Pricing][pricing] · [`llm_qa.py`](../llm_qa.py)

**建议（非 API 要求）：** 暂保留 128 KiB 和整轮裁剪。若需调整，先用代表性的中文问答和长工具结果校准每次调用的 `usage`、冷缓存成本与延迟；如需增加 token 保护，按整个请求估算（system/schema、工具定义、保留的整轮和活动轮），为每次输出预留 8,192 token 和估算余量。每轮最多执行 4 次图谱查询，单次 `rows` 有 `cypher_graph.py` 的 32 KiB 紧凑 JSON 预算（不含外层 tool 消息）；活动轮还会累积 tool calls、结果和推理，不能拿历史上限覆盖。裁剪不要拆开 tool call 和对应 tool result。[`llm_qa.py`](../llm_qa.py) · [`cypher_graph.py`](../cypher_graph.py)

[quick-start]: https://api-docs.deepseek.com/quick_start/your_first_api_call.md
[chat]: https://api-docs.deepseek.com/api/create-chat-completion.md
[tools]: https://api-docs.deepseek.com/guides/tool_calls.md
[tool-choice]: https://api-docs.deepseek.com/api/create-chat-completion.md#schema-chat-completion-tool-choice-option
[thinking]: https://api-docs.deepseek.com/guides/thinking_mode.md
[thinking-tools]: https://api-docs.deepseek.com/guides/thinking_mode.md#tool-calls
[strict]: https://api-docs.deepseek.com/guides/tool_calls.md#strict-mode-beta
[json]: https://api-docs.deepseek.com/guides/json_mode.md
[pricing]: https://api-docs.deepseek.com/quick_start/pricing.md
[models]: https://api-docs.deepseek.com/api/list-models.md
[changes]: https://api-docs.deepseek.com/updates/#deepseek-v41-flash-1017-update
[usage]: https://api-docs.deepseek.com/api/create-chat-completion.md#schema-completion-usage
[token-usage]: https://api-docs.deepseek.com/quick_start/token_usage.md
[flash-card]: https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017
[recipe]: https://github.com/deepseek-ai/deepseek-recipe/blob/main/docs/tokenizer.md
[cache]: https://api-docs.deepseek.com/guides/kv_cache.md
