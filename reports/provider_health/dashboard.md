# Provider 探活面板

> ❌ **存在 2 条红通路（运行时在最外层 ban 掉；其余通路照常调用）** · 共 23 条通路 · 8 个类别

- 部署：**Calling primary 运行时（Calling secrets）**
- 生成时间：`2026-11-04 06:47:26`（北京时间 UTC+8） / `2026-11-03T22:47:26+00:00`（UTC）
- 环境：容器 · run `41732280669` · schema 4
- 探活方式：不真实调用模型（官方非生成端点：DNS/TCP/TLS → 列模型鉴权 → 模型列表 / count tokens）
- 全模型覆盖：**26 / 27**（96.3%）

## 总览

| 类别 | 通路数 | 绿 | 黄 | 红 | 未配置 | 模型覆盖 | 结论 |
|---|---|---|---|---|---|---|---|
| `claude` | 6 | 6 | 0 | 0 | 0 | 7/7 | ✅ 全部可用 |
| `gemini` | 4 | 3 | 0 | 1 | 0 | 6/6 | ❌ 1 条红 |
| `deepseek` | 3 | 2 | 0 | 1 | 0 | 2/2 | ❌ 1 条红 |
| `gpt` | 3 | 3 | 0 | 0 | 0 | 1/1 | ✅ 全部可用 |
| `glm` | 2 | 2 | 0 | 0 | 0 | 2/2 | ✅ 全部可用 |
| `magmarouter` | 1 | 1 | 0 | 0 | 0 | 5/6 | ✅ 全部可用 |
| `openrouter` | 1 | 1 | 0 | 0 | 0 | 1/1 | ✅ 全部可用 |
| `grok` | 3 | 3 | 0 | 0 | 0 | 2/2 | ✅ 全部可用 |
| **合计** | 23 | 21 | 0 | 2 | 0 | 26/27 | ❌ |

## 通路 × 模型矩阵

### `claude` · ✅ 全部可用（绿 6 / 黄 0 / 红 0 / 未配置 0）

| 通路 | claude-opus-5-5 | claude-opus-5 | claude-sonnet-5-5 | claude-sonnet-5 | claude-haiku-4-5 | claude-haiku-4-5-20251001 | claude-haiku-5-5 | 结论 | 延迟 |
|---|---|---|---|---|---|---|---|---|---|
| `Proxy 1 Base` | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ 可用 | 170.9 ms |
| `Proxy 1 Prime` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ 可用 | 147.6 ms |
| `Proxy 1 Max` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ 可用 | 153.4 ms |
| `Proxy 2` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 733.8 ms |
| `OpenRouter` | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ 可用 | 400 ms |
| `Official` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 200.2 ms |

### `gemini` · ❌ 1 条红（绿 3 / 黄 0 / 红 1 / 未配置 0）

| 通路 | gemini-4-argon | gemini-3.1-pro-preview | gemini-3.8-flash | gemini-3.7-flash | gemini-3.5-flash-lite | gemini-3.1-flash-lite | 结论 | 延迟 |
|---|---|---|---|---|---|---|---|---|
| `Gemini Proxy` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ key 被拒 | 402.4 ms |
| `Gemini Proxy 2` | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ | ✅ 可用 | 683 ms |
| `OpenRouter` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 439.7 ms |
| `Official` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 可用 | 122.9 ms |

### `deepseek` · ❌ 1 条红（绿 2 / 黄 0 / 红 1 / 未配置 0）

| 通路 | deepseek-v4-pro | deepseek-flash | 结论 | 延迟 |
|---|---|---|---|---|
| `Official` | ✅ | ✅ | ✅ 可用 | 423.1 ms |
| `Fireworks DeepSeek Pro` | ❌ | ❌ | ❌ 模型不可用（模型级 ban） | 272.1 ms |
| `OpenRouter` | ✅ | ✅ | ✅ 可用 | 68.8 ms |

### `gpt` · ✅ 全部可用（绿 3 / 黄 0 / 红 0 / 未配置 0）

| 通路 | gpt-6-luna | 结论 | 延迟 |
|---|---|---|---|
| `GPT Proxy` | ✅ | ✅ 可用 | 724.5 ms |
| `OpenRouter` | ✅ | ✅ 可用 | 72.7 ms |
| `OpenAI` | ✅ | ✅ 可用 | 911 ms |

### `glm` · ✅ 全部可用（绿 2 / 黄 0 / 红 0 / 未配置 0）

| 通路 | glm-5.3 | glm-5.3-flash | 结论 | 延迟 |
|---|---|---|---|---|
| `Official` | ✅ | ✅ | ✅ 可用 | 303.2 ms |
| `OpenRouter` | ✅ | ✅ | ✅ 可用 | 195.7 ms |

### `magmarouter` · ✅ 全部可用（绿 1 / 黄 0 / 红 0 / 未配置 0）

| 通路 | deepseek-v4.1-flash-1017-xploded | glm-5.3-flash-xploded | glm-5.3-xploded | qwen3.8-27b-xploded | magma-1-xploded | mimo-v2.6-flash-xploded | 结论 | 延迟 |
|---|---|---|---|---|---|---|---|---|
| `MagmaRouter` | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ 可用 | 692.4 ms |

### `openrouter` · ✅ 全部可用（绿 1 / 黄 0 / 红 0 / 未配置 0）

| 通路 | cognitivecomputations/dolphin-mistral-24b-venice-edition | 结论 | 延迟 |
|---|---|---|---|
| `OpenRouter` | ✅ | ✅ 可用 | 147.3 ms |

### `grok` · ✅ 全部可用（绿 3 / 黄 0 / 红 0 / 未配置 0）

| 通路 | grok-4.7 | grok-4.6 | 结论 | 延迟 |
|---|---|---|---|---|
| `Grok Proxy` | ✅ | ✅ | ✅ 可用 | 691.9 ms |
| `OpenRouter` | ✅ | ✅ | ✅ 可用 | 144.3 ms |
| `Official` | ✅ | ✅ | ✅ 可用 | 143.2 ms |

## 最近历史（最近 12 次）

| 时间（北京） | claude | gemini | deepseek | gpt | glm | magmarouter | openrouter | grok |
|---|---|---|---|---|---|---|---|---|
| 2026-10-31 10:55:07 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-10-31 19:20:48 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-01 00:25:52 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-01 04:46:07 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-01 10:45:59 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-01 20:08:36 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-02 05:27:15 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-02 10:56:11 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-02 21:58:55 | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-03 08:08:20 | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-03 21:07:10 | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2026-11-04 06:47:26 | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |

**通路历史可用率**（可用 = 绿 + 黄；红才算不可用，分母是有结论的次数）：

| 通路 | 可用率 | 可用/观测 |
|---|---|---|
| `claude / Proxy 1 Base` | 100% | 26/26 |
| `claude / Proxy 1 Prime` | 100% | 26/26 |
| `claude / Proxy 1 Max` | 100% | 26/26 |
| `claude / Proxy 2` | 100% | 26/26 |
| `claude / Official` | 100% | 26/26 |
| `gemini / Gemini Proxy` | 77% | 20/26 |
| `gemini / Gemini Proxy 2` | 100% | 26/26 |
| `gemini / OpenRouter` | 100% | 26/26 |
| `gemini / Official` | 100% | 26/26 |
| `deepseek / Official` | 100% | 26/26 |
| `deepseek / Fireworks DeepSeek Pro` | 27% | 7/26 |
| `deepseek / OpenRouter` | 100% | 26/26 |
| `gpt / GPT Proxy` | 100% | 26/26 |
| `gpt / OpenRouter` | 100% | 26/26 |
| `gpt / OpenAI` | 100% | 26/26 |
| `glm / Official` | 100% | 26/26 |
| `glm / OpenRouter` | 100% | 26/26 |
| `magmarouter / MagmaRouter` | 100% | 26/26 |
| `openrouter / OpenRouter` | 100% | 26/26 |
| `grok / Grok Proxy` | 100% | 26/26 |
| `grok / OpenRouter` | 100% | 26/26 |
| `grok / Official` | 100% | 26/26 |
| `claude / OpenRouter` | 100% | 19/19 |

## 图例与说明

- ✅ **绿**：三层检查通过（网络 / 鉴权 / 模型），运行时照常调用。
- ⚠️ **黄**：端点通/活，只是这次探测请求本身不理想（探测模型不在该档模型列表里、429 限流等）。**不 ban**，照常调用。
- ❌ **红**：运行时在最外层 ban 掉这条通路，自动走下一档；不影响其它通路。
- ➖ **未配置**：没配 key / URL，跳过，不参与判定。
- fail-open：模型层拿不到结论时按「没结论」处理（不 ban）；探活不真实调用模型，只走官方非生成端点，不产生生成费用。
- 本文件由 `scripts/build_provider_health_dashboard.py` 从 `data/provider_health.json` + `reports/provider_health/history.jsonl` 生成，纯静态、同输入同输出。
