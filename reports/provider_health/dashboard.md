# Provider 探活面板

> ❌ **存在 3 条红通路（运行时在最外层 ban 掉；其余通路照常调用）** · 共 23 条通路 · 8 个类别

- 部署：**Calling primary 运行时（Calling secrets）**
- 生成时间：`2026-11-10 13:45:19`（北京时间 UTC+8） / `2026-11-10T05:45:19+00:00`（UTC）
- 环境：容器 · run `42763826937` · schema 4
- 探活方式：不真实调用模型（官方非生成端点：DNS/TCP/TLS → 列模型鉴权 → 模型列表 / count tokens）
- 全模型覆盖：**26 / 27**（96.3%）

## 总览

| 类别 | 通路数 | 绿 | 黄 | 红 | 未配置 | 模型覆盖 | 结论 |
|---|---|---|---|---|---|---|---|
| `claude` | 6 | 6 | 0 | 0 | 0 | 7/7 | ✅ 全部可用 |
| `gemini` | 4 | 3 | 0 | 1 | 0 | 6/6 | ❌ 1 条红 |
| `deepseek` | 3 | 2 | 0 | 1 | 0 | 2/2 | ❌ 1 条红 |
| `gpt` | 3 | 2 | 0 | 1 | 0 | 1/1 | ❌ 1 条红 |
| `glm` | 2 | 2 | 0 | 0 | 0 | 2/2 | ✅ 全部可用 |
| `magmarouter` | 1 | 1 | 0 | 0 | 0 | 5/6 | ✅ 全部可用 |
| `openrouter` | 1 | 1 | 0 | 0 | 0 | 1/1 | ✅ 全部可用 |
| `grok` | 3 | 3 | 0 | 0 | 0 | 2/2 | ✅ 全部可用 |
| **合计** | 23 | 20 | 0 | 3 | 0 | 26/27 | ❌ |

## 通路 × 模型矩阵

### `claude` · ✅ 全部可用（绿 6 / 黄 0 / 红 0 / 未配置 0）

| 通路 | claude-opus-5-5 | claude-opus-5 | claude-sonnet-5-5 | claude-sonnet-5 | claude-haiku-4-5 | claude-haiku-4-5-20251001 | claude-haiku-5-5 | 结论 | 延迟 |
|---|---|---|---|---|---|---|---|---|---|
| `Proxy 1 Base` | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ 可用 | 137.4 ms |
| `Proxy 1 Prime` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ 可用 | 168 ms |
| `Proxy 1 Max` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ 可用 | 119.7 ms |
| `Proxy 2` | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ 可用 | 728.7 ms |
| `OpenRouter` | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ 可用 | 443.2 ms |
| `Official` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 234.7 ms |

### `gemini` · ❌ 1 条红（绿 3 / 黄 0 / 红 1 / 未配置 0）

| 通路 | gemini-4-argon | gemini-3.1-pro-preview | gemini-3.8-flash | gemini-3.7-flash | gemini-3.5-flash-lite | gemini-3.1-flash-lite | 结论 | 延迟 |
|---|---|---|---|---|---|---|---|---|
| `Gemini Proxy` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ key 被拒 | 412.4 ms |
| `Gemini Proxy 2` | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ | ✅ 可用 | 694.2 ms |
| `OpenRouter` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 1296.5 ms |
| `Official` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 134 ms |

### `deepseek` · ❌ 1 条红（绿 2 / 黄 0 / 红 1 / 未配置 0）

| 通路 | deepseek-v4-pro | deepseek-flash | 结论 | 延迟 |
|---|---|---|---|---|
| `Official` | ✅ | ✅ | ✅ 可用 | 365.7 ms |
| `Fireworks DeepSeek Pro` | ➖ | ➖ | ❌ key 被拒 | 117 ms |
| `OpenRouter` | ✅ | ✅ | ✅ 可用 | 80.7 ms |

### `gpt` · ❌ 1 条红（绿 2 / 黄 0 / 红 1 / 未配置 0）

| 通路 | gpt-6-luna | 结论 | 延迟 |
|---|---|---|---|
| `GPT Proxy` | ➖ | ❌ key 被拒 | 690.8 ms |
| `OpenRouter` | ✅ | ✅ 可用 | 80.3 ms |
| `OpenAI` | ✅ | ✅ 可用 | 948.7 ms |

### `glm` · ✅ 全部可用（绿 2 / 黄 0 / 红 0 / 未配置 0）

| 通路 | glm-5.3 | glm-5.3-flash | 结论 | 延迟 |
|---|---|---|---|---|
| `Official` | ✅ | ✅ | ✅ 可用 | 321.4 ms |
| `OpenRouter` | ✅ | ✅ | ✅ 可用 | 108.9 ms |

### `magmarouter` · ✅ 全部可用（绿 1 / 黄 0 / 红 0 / 未配置 0）

| 通路 | deepseek-v4.1-flash-1017-xploded | glm-5.3-flash-xploded | glm-5.3-xploded | qwen3.8-27b-xploded | magma-1-xploded | mimo-v2.6-flash-xploded | 结论 | 延迟 |
|---|---|---|---|---|---|---|---|---|
| `MagmaRouter` | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ 可用 | 630.9 ms |

### `openrouter` · ✅ 全部可用（绿 1 / 黄 0 / 红 0 / 未配置 0）

| 通路 | cognitivecomputations/dolphin-mistral-24b-venice-edition | 结论 | 延迟 |
|---|---|---|---|
| `OpenRouter` | ✅ | ✅ 可用 | 75.8 ms |

### `grok` · ✅ 全部可用（绿 3 / 黄 0 / 红 0 / 未配置 0）

| 通路 | grok-4.7 | grok-4.6 | 结论 | 延迟 |
|---|---|---|---|---|
| `Grok Proxy` | ✅ | ✅ | ✅ 可用 | 696 ms |
| `OpenRouter` | ✅ | ✅ | ✅ 可用 | 97.8 ms |
| `Official` | ✅ | ✅ | ✅ 可用 | 134.3 ms |

## 最近历史（最近 12 次）

| 时间（北京） | claude | gemini | deepseek | gpt | glm | magmarouter | openrouter | grok |
|---|---|---|---|---|---|---|---|---|
| 2026-11-07 06:29:14 | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-07 11:24:12 | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-07 20:00:22 | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-08 01:18:40 | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-08 05:11:06 | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-08 10:52:58 | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-08 20:19:17 | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-09 05:27:09 | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-09 11:11:53 | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-09 22:30:54 | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-10 08:57:23 | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-10 13:45:19 | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |

**通路历史可用率**（可用 = 绿 + 黄；红才算不可用，分母是有结论的次数）：

| 通路 | 可用率 | 可用/观测 |
|---|---|---|
| `claude / Proxy 1 Base` | 100% | 46/46 |
| `claude / Proxy 1 Prime` | 100% | 46/46 |
| `claude / Proxy 1 Max` | 100% | 46/46 |
| `claude / Proxy 2` | 100% | 46/46 |
| `claude / Official` | 100% | 46/46 |
| `gemini / Gemini Proxy` | 43% | 20/46 |
| `gemini / Gemini Proxy 2` | 100% | 46/46 |
| `gemini / OpenRouter` | 100% | 46/46 |
| `gemini / Official` | 100% | 46/46 |
| `deepseek / Official` | 100% | 46/46 |
| `deepseek / Fireworks DeepSeek Pro` | 15% | 7/46 |
| `deepseek / OpenRouter` | 100% | 46/46 |
| `gpt / GPT Proxy` | 98% | 45/46 |
| `gpt / OpenRouter` | 100% | 46/46 |
| `gpt / OpenAI` | 100% | 46/46 |
| `glm / Official` | 100% | 46/46 |
| `glm / OpenRouter` | 100% | 46/46 |
| `magmarouter / MagmaRouter` | 100% | 46/46 |
| `openrouter / OpenRouter` | 100% | 46/46 |
| `grok / Grok Proxy` | 100% | 46/46 |
| `grok / OpenRouter` | 100% | 46/46 |
| `grok / Official` | 100% | 46/46 |
| `claude / OpenRouter` | 100% | 39/39 |

## 图例与说明

- ✅ **绿**：三层检查通过（网络 / 鉴权 / 模型），运行时照常调用。
- ⚠️ **黄**：端点通/活，只是这次探测请求本身不理想（探测模型不在该档模型列表里、429 限流等）。**不 ban**，照常调用。
- ❌ **红**：运行时在最外层 ban 掉这条通路，自动走下一档；不影响其它通路。
- ➖ **未配置**：没配 key / URL，跳过，不参与判定。
- fail-open：模型层拿不到结论时按「没结论」处理（不 ban）；探活不真实调用模型，只走官方非生成端点，不产生生成费用。
- 本文件由 `scripts/build_provider_health_dashboard.py` 从 `data/provider_health.json` + `reports/provider_health/history.jsonl` 生成，纯静态、同输入同输出。
