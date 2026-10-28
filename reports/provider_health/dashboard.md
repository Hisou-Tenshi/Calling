# Provider 探活面板

> ❌ **存在 1 条红通路（运行时在最外层 ban 掉；其余通路照常调用）** · 共 22 条通路 · 8 个类别

- 部署：**Calling primary 运行时（Calling secrets）**
- 生成时间：`2026-10-29 05:57:33`（北京时间 UTC+8） / `2026-10-28T21:57:33+00:00`（UTC）
- 环境：容器 · run `40775884720` · schema 4
- 探活方式：不真实调用模型（官方非生成端点：DNS/TCP/TLS → 列模型鉴权 → 模型列表 / count tokens）
- 全模型覆盖：**26 / 27**（96.3%）

## 总览

| 类别 | 通路数 | 绿 | 黄 | 红 | 未配置 | 模型覆盖 | 结论 |
|---|---|---|---|---|---|---|---|
| `claude` | 5 | 5 | 0 | 0 | 0 | 7/7 | ✅ 全部可用 |
| `gemini` | 4 | 3 | 0 | 1 | 0 | 6/6 | ❌ 1 条红 |
| `deepseek` | 3 | 2 | 1 | 0 | 0 | 2/2 | ⚠️ 1 条黄 |
| `gpt` | 3 | 3 | 0 | 0 | 0 | 1/1 | ✅ 全部可用 |
| `glm` | 2 | 2 | 0 | 0 | 0 | 2/2 | ✅ 全部可用 |
| `magmarouter` | 1 | 1 | 0 | 0 | 0 | 5/6 | ✅ 全部可用 |
| `openrouter` | 1 | 1 | 0 | 0 | 0 | 1/1 | ✅ 全部可用 |
| `grok` | 3 | 3 | 0 | 0 | 0 | 2/2 | ✅ 全部可用 |
| **合计** | 22 | 20 | 1 | 1 | 0 | 26/27 | ❌ |

## 通路 × 模型矩阵

### `claude` · ✅ 全部可用（绿 5 / 黄 0 / 红 0 / 未配置 0）

| 通路 | claude-opus-5-5 | claude-opus-5 | claude-sonnet-5-5 | claude-sonnet-5 | claude-haiku-4-5 | claude-haiku-4-5-20251001 | claude-haiku-5-5 | 结论 | 延迟 |
|---|---|---|---|---|---|---|---|---|---|
| `Proxy 1 Base` | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ | ⚠️ | ✅ 可用 | 155.5 ms |
| `Proxy 1 Prime` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ 可用 | 180.6 ms |
| `Proxy 1 Max` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ 可用 | 145.9 ms |
| `Proxy 2` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 821.9 ms |
| `Official` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 160 ms |

### `gemini` · ❌ 1 条红（绿 3 / 黄 0 / 红 1 / 未配置 0）

| 通路 | gemini-4-argon | gemini-3.1-pro-preview | gemini-3.8-flash | gemini-3.7-flash | gemini-3.5-flash-lite | gemini-3.1-flash-lite | 结论 | 延迟 |
|---|---|---|---|---|---|---|---|---|
| `Gemini Proxy` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ 上游错误 | 384.3 ms |
| `Gemini Proxy 2` | ✅ | ⚠️ | ✅ | ⚠️ | ⚠️ | ✅ | ✅ 可用 | 681 ms |
| `OpenRouter` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 372.2 ms |
| `Official` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 125.3 ms |

### `deepseek` · ⚠️ 1 条黄（绿 2 / 黄 1 / 红 0 / 未配置 0）

| 通路 | deepseek-v4-pro | deepseek-flash | 结论 | 延迟 |
|---|---|---|---|---|
| `Official` | ✅ | ✅ | ✅ 可用 | 361.6 ms |
| `Fireworks DeepSeek Pro` | ⚠️ | ⚠️ | ⚠️ 模型不可用 | 532.1 ms |
| `OpenRouter` | ✅ | ✅ | ✅ 可用 | 193.9 ms |

### `gpt` · ✅ 全部可用（绿 3 / 黄 0 / 红 0 / 未配置 0）

| 通路 | gpt-6-luna | 结论 | 延迟 |
|---|---|---|---|
| `GPT Proxy` | ✅ | ✅ 可用 | 688.9 ms |
| `OpenRouter` | ✅ | ✅ 可用 | 173.4 ms |
| `OpenAI` | ✅ | ✅ 可用 | 804.5 ms |

### `glm` · ✅ 全部可用（绿 2 / 黄 0 / 红 0 / 未配置 0）

| 通路 | glm-5.3 | glm-5.3-flash | 结论 | 延迟 |
|---|---|---|---|---|
| `Official` | ✅ | ✅ | ✅ 可用 | 316.6 ms |
| `OpenRouter` | ✅ | ✅ | ✅ 可用 | 84.3 ms |

### `magmarouter` · ✅ 全部可用（绿 1 / 黄 0 / 红 0 / 未配置 0）

| 通路 | deepseek-v4.1-flash-1017-xploded | glm-5.3-flash-xploded | glm-5.3-xploded | qwen3.8-27b-xploded | magma-1-xploded | mimo-v2.6-flash-xploded | 结论 | 延迟 |
|---|---|---|---|---|---|---|---|---|
| `MagmaRouter` | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ 可用 | 689.1 ms |

### `openrouter` · ✅ 全部可用（绿 1 / 黄 0 / 红 0 / 未配置 0）

| 通路 | cognitivecomputations/dolphin-mistral-24b-venice-edition | 结论 | 延迟 |
|---|---|---|---|
| `OpenRouter` | ✅ | ✅ 可用 | 115.2 ms |

### `grok` · ✅ 全部可用（绿 3 / 黄 0 / 红 0 / 未配置 0）

| 通路 | grok-4.7 | grok-4.6 | 结论 | 延迟 |
|---|---|---|---|---|
| `Grok Proxy` | ✅ | ✅ | ✅ 可用 | 1468 ms |
| `OpenRouter` | ✅ | ✅ | ✅ 可用 | 136.4 ms |
| `Official` | ✅ | ✅ | ✅ 可用 | 133.9 ms |

## 最近历史（最近 12 次）

| 时间（北京） | claude | gemini | deepseek | gpt | glm | magmarouter | openrouter | grok |
|---|---|---|---|---|---|---|---|---|
| 2026-10-28 20:27:50 | ✅ | ⚠️ | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-10-28 21:07:04 | ✅ | ⚠️ | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-10-28 21:19:42 | ✅ | ⚠️ | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-10-28 22:52:00 | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-10-29 01:35:21 | ✅ | ❌ | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-10-29 05:57:33 | ✅ | ❌ | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ |

**通路历史可用率**（可用 = 绿 + 黄；红才算不可用，分母是有结论的次数）：

| 通路 | 可用率 | 可用/观测 |
|---|---|---|
| `claude / Proxy 1 Base` | 100% | 6/6 |
| `claude / Proxy 1 Prime` | 100% | 6/6 |
| `claude / Proxy 1 Max` | 100% | 6/6 |
| `claude / Proxy 2` | 100% | 6/6 |
| `claude / Official` | 100% | 6/6 |
| `gemini / Gemini Proxy` | 67% | 4/6 |
| `gemini / Gemini Proxy 2` | 100% | 6/6 |
| `gemini / OpenRouter` | 100% | 6/6 |
| `gemini / Official` | 100% | 6/6 |
| `deepseek / Official` | 100% | 6/6 |
| `deepseek / Fireworks DeepSeek Pro` | 100% | 6/6 |
| `deepseek / OpenRouter` | 100% | 6/6 |
| `gpt / GPT Proxy` | 100% | 6/6 |
| `gpt / OpenRouter` | 100% | 6/6 |
| `gpt / OpenAI` | 100% | 6/6 |
| `glm / Official` | 100% | 6/6 |
| `glm / OpenRouter` | 100% | 6/6 |
| `magmarouter / MagmaRouter` | 100% | 6/6 |
| `openrouter / OpenRouter` | 100% | 6/6 |
| `grok / Grok Proxy` | 100% | 6/6 |
| `grok / OpenRouter` | 100% | 6/6 |
| `grok / Official` | 100% | 6/6 |

## 图例与说明

- ✅ **绿**：三层检查通过（网络 / 鉴权 / 模型），运行时照常调用。
- ⚠️ **黄**：端点通/活，只是这次探测请求本身不理想（探测模型不在该档模型列表里、429 限流等）。**不 ban**，照常调用。
- ❌ **红**：运行时在最外层 ban 掉这条通路，自动走下一档；不影响其它通路。
- ➖ **未配置**：没配 key / URL，跳过，不参与判定。
- fail-open：模型层拿不到结论时按「没结论」处理（不 ban）；探活不真实调用模型，只走官方非生成端点，不产生生成费用。
- 本文件由 `scripts/build_provider_health_dashboard.py` 从 `data/provider_health.json` + `reports/provider_health/history.jsonl` 生成，纯静态、同输入同输出。
