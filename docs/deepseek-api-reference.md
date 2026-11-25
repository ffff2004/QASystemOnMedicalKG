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

[quick-start]: https://api-docs.deepseek.com/quick_start/your_first_api_call.md
[chat]: https://api-docs.deepseek.com/api/create-chat-completion.md
[tools]: https://api-docs.deepseek.com/guides/tool_calls.md
[tool-choice]: https://api-docs.deepseek.com/api/create-chat-completion.md#schema-chat-completion-tool-choice-option
[thinking]: https://api-docs.deepseek.com/guides/thinking_mode.md
[thinking-tools]: https://api-docs.deepseek.com/guides/thinking_mode.md#tool-calls
[strict]: https://api-docs.deepseek.com/guides/tool_calls.md#strict-mode-beta
[json]: https://api-docs.deepseek.com/guides/json_mode.md
