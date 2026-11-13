# 全通路探活报告

- 时间：`2026-11-13 11:45:53`（北京时间 UTC+8） / `2026-11-13T03:45:53+00:00`（UTC）
- 环境：容器 · run `43360727301`
- 部署：`calling` · Calling primary 运行时（Calling secrets）
- 方式：**不真实调用模型**（官方非生成端点：DNS/TCP/TLS → 列模型鉴权 → 全模型 模型列表 / count tokens 校验）
- 覆盖：claude（6 条 / 7 个模型）, gemini（4 条 / 6 个模型）, deepseek（2 条 / 2 个模型）, gpt（4 条 / 1 个模型）, glm（2 条 / 2 个模型）, magmarouter（1 条 / 6 个模型）, openrouter（1 条 / 1 个模型）, grok（3 条 / 2 个模型）

## 类别结论

| 类别 | 通路可用/总数 | 模型可用/总 | 结论 | 红通路 |
|---|---|---|---|---|
| `claude` | 6/6 | 7/7 | ✅ 绿（照常调用） | — |
| `gemini` | 3/4 | 6/6 | ✅ 绿（照常调用） | `Gemini Proxy` |
| `deepseek` | 2/2 | 2/2 | ✅ 绿（照常调用） | — |
| `gpt` | 4/4 | 1/1 | ✅ 绿（照常调用） | — |
| `glm` | 2/2 | 2/2 | ✅ 绿（照常调用） | — |
| `magmarouter` | 1/1 | 5/6 | ✅ 绿（照常调用） | — |
| `openrouter` | 1/1 | 1/1 | ✅ 绿（照常调用） | — |
| `grok` | 3/3 | 2/2 | ✅ 绿（照常调用） | — |

## 逐通路

| 类别 | 通路 | 代表模型 | 结论 | 网络 | 鉴权 | 模型校验 | 模型 | 延迟 | 说明 |
|---|---|---|---|---|---|---|---|---|---|
| `claude` | Proxy 1 Base | `claude-haiku-4-5` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 5/7 | 200.4 ms | 三层检查均通过 |
| `claude` | Proxy 1 Prime | `claude-haiku-4-5` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 6/7 | 199.4 ms | 三层检查均通过 |
| `claude` | Proxy 1 Max | `claude-haiku-4-5` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 6/7 | 193.2 ms | 三层检查均通过 |
| `claude` | Proxy 2 | `claude-haiku-4-5` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 7/7 | 773.5 ms | 三层检查均通过 |
| `claude` | OpenRouter | `anthropic/claude-haiku-4.5` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 6/7 | 322.6 ms | 三层检查均通过 |
| `claude` | Official | `claude-haiku-4-5` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 7/7 | 148.7 ms | 三层检查均通过 |
| `gemini` | Gemini Proxy | `gemini-3.5-flash-lite` | ❌ key 被拒 | ✅ | ❌ | ❌（count） | 0/6 | 179.9 ms | auth: key 被拒（401）：HTTP 401：Invalid API key；model: 6/6 个模型不可用：key 被拒（401）：HTTP 401：Invalid API key |
| `gemini` | Gemini Proxy 2 | `gemini-3.5-flash-lite` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 3/6 | 759.6 ms | 三层检查均通过 |
| `gemini` | OpenRouter | `google/gemini-3.5-flash-lite` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 6/6 | 158.2 ms | 三层检查均通过 |
| `gemini` | Official | `gemini-3.5-flash-lite` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 6/6 | 124.7 ms | 三层检查均通过 |
| `deepseek` | Official | `deepseek-flash` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 2/2 | 345.0 ms | 三层检查均通过 |
| `deepseek` | OpenRouter | `deepseek/deepseek-v4.1-flash-1017` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 2/2 | 60.1 ms | 三层检查均通过 |
| `gpt` | GPT Proxy | `gpt-6-luna` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 1/1 | 191.9 ms | 三层检查均通过 |
| `gpt` | GPT Proxy 2 | `gpt-6-luna` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 1/1 | 756.8 ms | 三层检查均通过 |
| `gpt` | OpenRouter | `openai/gpt-6-luna` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 1/1 | 38.6 ms | 三层检查均通过 |
| `gpt` | OpenAI | `gpt-6-luna` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 1/1 | 747.2 ms | 三层检查均通过 |
| `glm` | Official | `glm-5.3` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 2/2 | 278.8 ms | 三层检查均通过 |
| `glm` | OpenRouter | `z-ai/glm-5.3` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 2/2 | 43.4 ms | 三层检查均通过 |
| `magmarouter` | MagmaRouter | `mimo-v2.6-flash-xploded` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 5/6 | 579.3 ms | 三层检查均通过 |
| `openrouter` | OpenRouter | `cognitivecomputations/dolphin-mistral-24b-venice-edition` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 1/1 | 41.6 ms | 三层检查均通过 |
| `grok` | Grok Proxy | `grok-4.7` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 2/2 | 761.7 ms | 三层检查均通过 |
| `grok` | OpenRouter | `x-ai/grok-4.7` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 2/2 | 58.6 ms | 三层检查均通过 |
| `grok` | Official | `grok-4.7` | ✅ 可用 | ✅ | ✅ | ✅（列表） | 2/2 | 82.6 ms | 三层检查均通过 |

## 全模型矩阵

> 行 = 运行时通路，列 = Tenshi 模型注册表（`src/config/models.py`）里该 provider 的**全部**模型；格：✅ 可用 / ⚠️ 限流（不 ban）/ ❌ 不可用（**模型级 ban**：运行时跳过该「通路×模型」组合） / — 未下结论（fail-open）/ ➖ 未配置。
> 逐模型的 verdict / HTTP 状态 / 延迟见 JSON 的 `paths.<通路>.models`。

### `claude`（模型 7/7 可用）

| 通路 | `claude-opus-5-5` | `claude-opus-5` | `claude-sonnet-5-5` | `claude-sonnet-5` | `claude-haiku-4-5` | `claude-haiku-4-5-20251001` | `claude-haiku-5-5` |
|---|---|---|---|---|---|---|---|
| Proxy 1 Base | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ |
| Proxy 1 Prime | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Proxy 1 Max | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Proxy 2 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| OpenRouter | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| Official | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

### `gemini`（模型 6/6 可用）

| 通路 | `gemini-4-argon` | `gemini-3.1-pro-preview` | `gemini-3.8-flash` | `gemini-3.7-flash` | `gemini-3.5-flash-lite` | `gemini-3.1-flash-lite` |
|---|---|---|---|---|---|---|
| Gemini Proxy | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Gemini Proxy 2 | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ |
| OpenRouter | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Official | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

### `deepseek`（模型 2/2 可用）

| 通路 | `deepseek-v4-pro` | `deepseek-flash` |
|---|---|---|
| Official | ✅ | ✅ |
| OpenRouter | ✅ | ✅ |

### `gpt`（模型 1/1 可用）

| 通路 | `gpt-6-luna` |
|---|---|
| GPT Proxy | ✅ |
| GPT Proxy 2 | ✅ |
| OpenRouter | ✅ |
| OpenAI | ✅ |

### `glm`（模型 2/2 可用）

| 通路 | `glm-5.3` | `glm-5.3-flash` |
|---|---|---|
| Official | ✅ | ✅ |
| OpenRouter | ✅ | ✅ |

### `magmarouter`（模型 5/6 可用）

| 通路 | `mimo-v2.6-flash-xploded` | `deepseek-v4.1-flash-1017-xploded` | `glm-5.3-flash-xploded` | `glm-5.3-xploded` | `qwen3.8-27b-xploded` | `magma-1-xploded` |
|---|---|---|---|---|---|---|
| MagmaRouter | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |

### `openrouter`（模型 1/1 可用）

| 通路 | `cognitivecomputations/dolphin-mistral…` |
|---|---|
| OpenRouter | ✅ |

### `grok`（模型 2/2 可用）

| 通路 | `grok-4.7` | `grok-4.6` |
|---|---|---|
| Grok Proxy | ✅ | ✅ |
| OpenRouter | ✅ | ✅ |
| Official | ✅ | ✅ |
