# Provider 探活面板

> ⚠️ **全部通路可用；2 条标黄（照常调用，不 ban）** · 共 22 条通路 · 8 个类别

- 部署：**Calling primary 运行时（Calling secrets）**
- 生成时间：`2026-10-28 20:27:50`（北京时间 UTC+8） / `2026-10-28T12:27:50+00:00`（UTC）
- 环境：容器 · run `40687515403` · schema 4
- 探活方式：不真实调用模型（官方非生成端点：DNS/TCP/TLS → 列模型鉴权 → 模型列表 / count tokens）
- 全模型覆盖：**26 / 27**（96.3%）

## 总览

| 类别 | 通路数 | 绿 | 黄 | 红 | 未配置 | 模型覆盖 | 结论 |
|---|---|---|---|---|---|---|---|
| `claude` | 5 | 5 | 0 | 0 | 0 | 7/7 | ✅ 全部可用 |
| `gemini` | 4 | 3 | 1 | 0 | 0 | 6/6 | ⚠️ 1 条黄 |
| `deepseek` | 3 | 2 | 1 | 0 | 0 | 2/2 | ⚠️ 1 条黄 |
| `gpt` | 3 | 3 | 0 | 0 | 0 | 1/1 | ✅ 全部可用 |
| `glm` | 2 | 2 | 0 | 0 | 0 | 2/2 | ✅ 全部可用 |
| `magmarouter` | 1 | 1 | 0 | 0 | 0 | 5/6 | ✅ 全部可用 |
| `openrouter` | 1 | 1 | 0 | 0 | 0 | 1/1 | ✅ 全部可用 |
| `grok` | 3 | 3 | 0 | 0 | 0 | 2/2 | ✅ 全部可用 |
| **合计** | 22 | 20 | 2 | 0 | 0 | 26/27 | ⚠️ |

## 通路 × 模型矩阵

### `claude` · ✅ 全部可用（绿 5 / 黄 0 / 红 0 / 未配置 0）

| 通路 | claude-opus-5-5 | claude-opus-5 | claude-sonnet-5-5 | claude-sonnet-5 | claude-haiku-4-5 | claude-haiku-4-5-20251001 | claude-haiku-5-5 | 结论 | 延迟 |
|---|---|---|---|---|---|---|---|---|---|
| `Proxy 1 Base` | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ | ⚠️ | ✅ 可用 | 225.2 ms |
| `Proxy 1 Prime` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ 可用 | 191.7 ms |
| `Proxy 1 Max` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ 可用 | 219.3 ms |
| `Proxy 2` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 743.6 ms |
| `Official` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 136.1 ms |

### `gemini` · ⚠️ 1 条黄（绿 3 / 黄 1 / 红 0 / 未配置 0）

| 通路 | gemini-4-argon | gemini-3.1-pro-preview | gemini-3.8-flash | gemini-3.7-flash | gemini-3.5-flash-lite | gemini-3.1-flash-lite | 结论 | 延迟 |
|---|---|---|---|---|---|---|---|---|
| `Gemini Proxy` | ⚠️ | ⚠️ | ❌ | ⚠️ | ⚠️ | ⚠️ | ⚠️ 模型不可用 | 252.8 ms |
| `Gemini Proxy 2` | ✅ | ⚠️ | ✅ | ⚠️ | ⚠️ | ✅ | ✅ 可用 | 710.5 ms |
| `OpenRouter` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 347.8 ms |
| `Official` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 119.1 ms |

### `deepseek` · ⚠️ 1 条黄（绿 2 / 黄 1 / 红 0 / 未配置 0）

| 通路 | deepseek-v4-pro | deepseek-flash | 结论 | 延迟 |
|---|---|---|---|---|
| `Official` | ✅ | ✅ | ✅ 可用 | 320.2 ms |
| `Fireworks DeepSeek Pro` | ⚠️ | ⚠️ | ⚠️ 模型不可用 | 327.2 ms |
| `OpenRouter` | ✅ | ✅ | ✅ 可用 | 45.9 ms |

### `gpt` · ✅ 全部可用（绿 3 / 黄 0 / 红 0 / 未配置 0）

| 通路 | gpt-6-luna | 结论 | 延迟 |
|---|---|---|---|
| `GPT Proxy` | ➖ | ✅ 可用 | 657.8 ms |
| `OpenRouter` | ✅ | ✅ 可用 | 69.8 ms |
| `OpenAI` | ✅ | ✅ 可用 | 941.9 ms |

### `glm` · ✅ 全部可用（绿 2 / 黄 0 / 红 0 / 未配置 0）

| 通路 | glm-5.3 | glm-5.3-flash | 结论 | 延迟 |
|---|---|---|---|---|
| `Official` | ✅ | ✅ | ✅ 可用 | 349.2 ms |
| `OpenRouter` | ✅ | ✅ | ✅ 可用 | 60.9 ms |

### `magmarouter` · ✅ 全部可用（绿 1 / 黄 0 / 红 0 / 未配置 0）

| 通路 | deepseek-v4.1-flash-1017-xploded | glm-5.3-flash-xploded | glm-5.3-xploded | qwen3.8-27b-xploded | magma-1-xploded | mimo-v2.6-flash-xploded | 结论 | 延迟 |
|---|---|---|---|---|---|---|---|---|
| `MagmaRouter` | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ 可用 | 615 ms |

### `openrouter` · ✅ 全部可用（绿 1 / 黄 0 / 红 0 / 未配置 0）

| 通路 | cognitivecomputations/dolphin-mistral-24b-venice-edition | 结论 | 延迟 |
|---|---|---|---|
| `OpenRouter` | ✅ | ✅ 可用 | 48.9 ms |

### `grok` · ✅ 全部可用（绿 3 / 黄 0 / 红 0 / 未配置 0）

| 通路 | grok-4.7 | grok-4.6 | 结论 | 延迟 |
|---|---|---|---|---|
| `Grok Proxy` | ➖ | ➖ | ✅ 可用 | 594.3 ms |
| `OpenRouter` | ✅ | ✅ | ✅ 可用 | 44.4 ms |
| `Official` | ✅ | ✅ | ✅ 可用 | 121.3 ms |

## 最近历史（最近 12 次）

| 时间（北京） | claude | gemini | deepseek | gpt | glm | magmarouter | openrouter | grok |
|---|---|---|---|---|---|---|---|---|
| 2026-10-28 20:27:50 | ✅ | ⚠️ | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ |

**通路历史可用率**（可用 = 绿 + 黄；红才算不可用，分母是有结论的次数）：

| 通路 | 可用率 | 可用/观测 |
|---|---|---|
| `claude / Proxy 1 Base` | 100% | 1/1 |
| `claude / Proxy 1 Prime` | 100% | 1/1 |
| `claude / Proxy 1 Max` | 100% | 1/1 |
| `claude / Proxy 2` | 100% | 1/1 |
| `claude / Official` | 100% | 1/1 |
| `gemini / Gemini Proxy` | 100% | 1/1 |
| `gemini / Gemini Proxy 2` | 100% | 1/1 |
| `gemini / OpenRouter` | 100% | 1/1 |
| `gemini / Official` | 100% | 1/1 |
| `deepseek / Official` | 100% | 1/1 |
| `deepseek / Fireworks DeepSeek Pro` | 100% | 1/1 |
| `deepseek / OpenRouter` | 100% | 1/1 |
| `gpt / GPT Proxy` | 100% | 1/1 |
| `gpt / OpenRouter` | 100% | 1/1 |
| `gpt / OpenAI` | 100% | 1/1 |
| `glm / Official` | 100% | 1/1 |
| `glm / OpenRouter` | 100% | 1/1 |
| `magmarouter / MagmaRouter` | 100% | 1/1 |
| `openrouter / OpenRouter` | 100% | 1/1 |
| `grok / Grok Proxy` | 100% | 1/1 |
| `grok / OpenRouter` | 100% | 1/1 |
| `grok / Official` | 100% | 1/1 |

## 图例与说明

- ✅ **绿**：三层检查通过（网络 / 鉴权 / 模型），运行时照常调用。
- ⚠️ **黄**：端点通/活，只是这次探测请求本身不理想（探测模型不在该档模型列表里、429 限流等）。**不 ban**，照常调用。
- ❌ **红**：运行时在最外层 ban 掉这条通路，自动走下一档；不影响其它通路。
- ➖ **未配置**：没配 key / URL，跳过，不参与判定。
- fail-open：模型层拿不到结论时按「没结论」处理（不 ban）；探活不真实调用模型，只走官方非生成端点，不产生生成费用。
- 本文件由 `scripts/build_provider_health_dashboard.py` 从 `data/provider_health.json` + `reports/provider_health/history.jsonl` 生成，纯静态、同输入同输出。
