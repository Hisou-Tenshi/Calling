# Provider 探活面板

> ❌ **存在 1 条红通路（运行时在最外层 ban 掉；其余通路照常调用）** · 共 23 条通路 · 8 个类别

- 部署：**Calling primary 运行时（Calling secrets）**
- 生成时间：`2026-10-31 19:20:48`（北京时间 UTC+8） / `2026-10-31T11:20:48+00:00`（UTC）
- 环境：容器 · run `41196234074` · schema 4
- 探活方式：不真实调用模型（官方非生成端点：DNS/TCP/TLS → 列模型鉴权 → 模型列表 / count tokens）
- 全模型覆盖：**26 / 27**（96.3%）

## 总览

| 类别 | 通路数 | 绿 | 黄 | 红 | 未配置 | 模型覆盖 | 结论 |
|---|---|---|---|---|---|---|---|
| `claude` | 6 | 6 | 0 | 0 | 0 | 7/7 | ✅ 全部可用 |
| `gemini` | 4 | 4 | 0 | 0 | 0 | 6/6 | ✅ 全部可用 |
| `deepseek` | 3 | 2 | 0 | 1 | 0 | 2/2 | ❌ 1 条红 |
| `gpt` | 3 | 3 | 0 | 0 | 0 | 1/1 | ✅ 全部可用 |
| `glm` | 2 | 2 | 0 | 0 | 0 | 2/2 | ✅ 全部可用 |
| `magmarouter` | 1 | 1 | 0 | 0 | 0 | 5/6 | ✅ 全部可用 |
| `openrouter` | 1 | 1 | 0 | 0 | 0 | 1/1 | ✅ 全部可用 |
| `grok` | 3 | 3 | 0 | 0 | 0 | 2/2 | ✅ 全部可用 |
| **合计** | 23 | 22 | 0 | 1 | 0 | 26/27 | ❌ |

## 通路 × 模型矩阵

### `claude` · ✅ 全部可用（绿 6 / 黄 0 / 红 0 / 未配置 0）

| 通路 | claude-opus-5-5 | claude-opus-5 | claude-sonnet-5-5 | claude-sonnet-5 | claude-haiku-4-5 | claude-haiku-4-5-20251001 | claude-haiku-5-5 | 结论 | 延迟 |
|---|---|---|---|---|---|---|---|---|---|
| `Proxy 1 Base` | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ 可用 | 182.6 ms |
| `Proxy 1 Prime` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ 可用 | 181.5 ms |
| `Proxy 1 Max` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ 可用 | 176.4 ms |
| `Proxy 2` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 738.1 ms |
| `OpenRouter` | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ 可用 | 401.7 ms |
| `Official` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 123.2 ms |

### `gemini` · ✅ 全部可用（绿 4 / 黄 0 / 红 0 / 未配置 0）

| 通路 | gemini-4-argon | gemini-3.1-pro-preview | gemini-3.8-flash | gemini-3.7-flash | gemini-3.5-flash-lite | gemini-3.1-flash-lite | 结论 | 延迟 |
|---|---|---|---|---|---|---|---|---|
| `Gemini Proxy` | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 249.3 ms |
| `Gemini Proxy 2` | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ 可用 | 707.9 ms |
| `OpenRouter` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 41.9 ms |
| `Official` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 124.6 ms |

### `deepseek` · ❌ 1 条红（绿 2 / 黄 0 / 红 1 / 未配置 0）

| 通路 | deepseek-v4-pro | deepseek-flash | 结论 | 延迟 |
|---|---|---|---|---|
| `Official` | ✅ | ✅ | ✅ 可用 | 411.3 ms |
| `Fireworks DeepSeek Pro` | ❌ | ❌ | ❌ 模型不可用（模型级 ban） | 293.6 ms |
| `OpenRouter` | ✅ | ✅ | ✅ 可用 | 41.4 ms |

### `gpt` · ✅ 全部可用（绿 3 / 黄 0 / 红 0 / 未配置 0）

| 通路 | gpt-6-luna | 结论 | 延迟 |
|---|---|---|---|
| `GPT Proxy` | ✅ | ✅ 可用 | 713.4 ms |
| `OpenRouter` | ✅ | ✅ 可用 | 44.9 ms |
| `OpenAI` | ✅ | ✅ 可用 | 933.3 ms |

### `glm` · ✅ 全部可用（绿 2 / 黄 0 / 红 0 / 未配置 0）

| 通路 | glm-5.3 | glm-5.3-flash | 结论 | 延迟 |
|---|---|---|---|---|
| `Official` | ✅ | ✅ | ✅ 可用 | 326.7 ms |
| `OpenRouter` | ✅ | ✅ | ✅ 可用 | 43.1 ms |

### `magmarouter` · ✅ 全部可用（绿 1 / 黄 0 / 红 0 / 未配置 0）

| 通路 | deepseek-v4.1-flash-1017-xploded | glm-5.3-flash-xploded | glm-5.3-xploded | qwen3.8-27b-xploded | magma-1-xploded | mimo-v2.6-flash-xploded | 结论 | 延迟 |
|---|---|---|---|---|---|---|---|---|
| `MagmaRouter` | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ 可用 | 493.9 ms |

### `openrouter` · ✅ 全部可用（绿 1 / 黄 0 / 红 0 / 未配置 0）

| 通路 | cognitivecomputations/dolphin-mistral-24b-venice-edition | 结论 | 延迟 |
|---|---|---|---|
| `OpenRouter` | ✅ | ✅ 可用 | 45.1 ms |

### `grok` · ✅ 全部可用（绿 3 / 黄 0 / 红 0 / 未配置 0）

| 通路 | grok-4.7 | grok-4.6 | 结论 | 延迟 |
|---|---|---|---|---|
| `Grok Proxy` | ✅ | ✅ | ✅ 可用 | 711.4 ms |
| `OpenRouter` | ✅ | ✅ | ✅ 可用 | 41.9 ms |
| `Official` | ✅ | ✅ | ✅ 可用 | 145.3 ms |

## 最近历史（最近 12 次）

| 时间（北京） | claude | gemini | deepseek | gpt | glm | magmarouter | openrouter | grok |
|---|---|---|---|---|---|---|---|---|
| 2026-10-29 01:35:21 | ✅ | ❌ | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-10-29 05:57:33 | ✅ | ❌ | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-10-29 11:02:38 | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-10-29 19:53:28 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-10-30 01:42:13 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-10-30 06:05:46 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-10-30 11:08:00 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-10-30 19:46:41 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-10-31 01:20:49 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-10-31 05:45:38 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-10-31 10:55:07 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-10-31 19:20:48 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |

**通路历史可用率**（可用 = 绿 + 黄；红才算不可用，分母是有结论的次数）：

| 通路 | 可用率 | 可用/观测 |
|---|---|---|
| `claude / Proxy 1 Base` | 100% | 16/16 |
| `claude / Proxy 1 Prime` | 100% | 16/16 |
| `claude / Proxy 1 Max` | 100% | 16/16 |
| `claude / Proxy 2` | 100% | 16/16 |
| `claude / Official` | 100% | 16/16 |
| `gemini / Gemini Proxy` | 88% | 14/16 |
| `gemini / Gemini Proxy 2` | 100% | 16/16 |
| `gemini / OpenRouter` | 100% | 16/16 |
| `gemini / Official` | 100% | 16/16 |
| `deepseek / Official` | 100% | 16/16 |
| `deepseek / Fireworks DeepSeek Pro` | 44% | 7/16 |
| `deepseek / OpenRouter` | 100% | 16/16 |
| `gpt / GPT Proxy` | 100% | 16/16 |
| `gpt / OpenRouter` | 100% | 16/16 |
| `gpt / OpenAI` | 100% | 16/16 |
| `glm / Official` | 100% | 16/16 |
| `glm / OpenRouter` | 100% | 16/16 |
| `magmarouter / MagmaRouter` | 100% | 16/16 |
| `openrouter / OpenRouter` | 100% | 16/16 |
| `grok / Grok Proxy` | 100% | 16/16 |
| `grok / OpenRouter` | 100% | 16/16 |
| `grok / Official` | 100% | 16/16 |
| `claude / OpenRouter` | 100% | 9/9 |

## 图例与说明

- ✅ **绿**：三层检查通过（网络 / 鉴权 / 模型），运行时照常调用。
- ⚠️ **黄**：端点通/活，只是这次探测请求本身不理想（探测模型不在该档模型列表里、429 限流等）。**不 ban**，照常调用。
- ❌ **红**：运行时在最外层 ban 掉这条通路，自动走下一档；不影响其它通路。
- ➖ **未配置**：没配 key / URL，跳过，不参与判定。
- fail-open：模型层拿不到结论时按「没结论」处理（不 ban）；探活不真实调用模型，只走官方非生成端点，不产生生成费用。
- 本文件由 `scripts/build_provider_health_dashboard.py` 从 `data/provider_health.json` + `reports/provider_health/history.jsonl` 生成，纯静态、同输入同输出。
