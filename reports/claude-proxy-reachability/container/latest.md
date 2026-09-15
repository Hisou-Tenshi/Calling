# Claude 代理可达性检测报告

| 项目 | 值 |
|---|---|
| 检测时间（UTC） | `2026-09-15T02:14:03+00:00` |
| 运行环境 | **Tenshi 运行容器** · `d4e4e01467f5` / `linux 6.17.0-1022-azure` / Python `3.10.21` |
| GitHub | 本地运行（非 Actions 环境，结论不代表 GitHub runner） |
| Runner 出口 IP | `4.154.85.161` |
| 探测模型 | `claude-opus-4-6、claude-sonnet-4-6、claude-3-5-sonnet-20241022`（max_tokens=1，每通路最多 3 次） |

## 结论

> ⚠️ **4/5 个已配置通路可用**，异常通路：
>
> - `Proxy2`：❌ DNS 失败 —— DNS 解析失败：gaierror: [Errno -2] Name or service not known

## 一览

| 通路 | 说明 | 配置 | DNS | TCP | TLS | HTTP(messages) | 延迟 min/中位/max | 结论 |
|---|---|---|---|---|---|---|---|---|
| `Proxy1/Base` | 代理1 base 档 | ✅ | ✅ | ✅ | ✅ | 200、200、200 | 1806.8 / 2186.4 / 2527.6 ms | ✅ 可用 |
| `Proxy1/Prime` | 代理1 prime 档 | ✅ | ✅ | ✅ | ✅ | 200、200、200 | 150.1 / 152.0 / 154.0 ms | ✅ 可用 |
| `Proxy1/Max` | 代理1 max 档 | ✅ | ✅ | ✅ | ✅ | 200、200、200 | 2286.4 / 2524.5 / 3000.4 ms | ✅ 可用 |
| `Proxy2` | 代理2（独立域名） | ✅ | ❌ | — | — | —（无响应） | — | ❌ DNS 失败 |
| `Official` | Anthropic 官方（对照组） | ✅ | ✅ | ✅ | ✅ | 200、200、200 | 1540.7 / 1540.9 / 1778.1 ms | ✅ 可用 |

## 通路明细

### `Proxy1/Base`（代理1 base 档）

- base_url：`https://codeyu.shop`
- key：`sk-1…33ac（len=67）`（来自 `CLAUDE_PROXY_KEY_BASE`）
- 结论：**✅ 可用** —— 可达且可调用
- DNS：64.83.15.230 (IPv4)（67.3 ms）
- TCP：连通 64.83.15.230:443（100.8 ms）
- TLS：TLSv1.3 · TLS_AES_128_GCM_SHA256 (TLSv1.3, 128 bits) · ALPN=http/1.1（122.2 ms）
- 证书：`codeyu.shop` ← `YE1`（Let's Encrypt） · 到期 `Nov 29 23:35:39 2026 GMT`（剩 75 天） · SAN：codeyu.shop
- `GET /v1/models`：HTTP `200` · 138.6 ms
- `POST /v1/messages`：状态码 200、200、200 · 延迟 1806.8/2186.4/2527.6 ms · 实际使用模型 `claude-opus-4-6`
- 模型探测记录：
  - `claude-opus-4-6` → HTTP `200` · 1806.8 ms

  <details><summary>最后一次响应体（截断）</summary>

  ```json
  {"id":"msg_4a9f06e7c5cf4b5991a4667481b700e6","type":"message","role":"assistant","content":[{"type":"text","text":"pong"}],"stop_reason":"end_turn","model":"claude-opus-4-6","usage":{"input_tokens":3,"output_tokens":1}}
  ```

  </details>

### `Proxy1/Prime`（代理1 prime 档）

- base_url：`https://codeyu.shop`
- key：`sk-9…c44c（len=67）`（来自 `CLAUDE_PROXY_KEY_PRIME`）
- 结论：**✅ 可用** —— 可达且可调用
- DNS：64.83.15.230 (IPv4)（14.0 ms）
- TCP：连通 64.83.15.230:443（69.3 ms）
- TLS：TLSv1.3 · TLS_AES_128_GCM_SHA256 (TLSv1.3, 128 bits) · ALPN=http/1.1（87.0 ms）
- 证书：`codeyu.shop` ← `YE1`（Let's Encrypt） · 到期 `Nov 29 23:35:39 2026 GMT`（剩 75 天） · SAN：codeyu.shop
- `GET /v1/models`：HTTP `200` · 142.0 ms
- `POST /v1/messages`：状态码 200、200、200 · 延迟 150.1/152.0/154.0 ms · 实际使用模型 `claude-opus-4-6`
- 模型探测记录：
  - `claude-opus-4-6` → HTTP `200` · 150.1 ms

  <details><summary>最后一次响应体（截断）</summary>

  ```json
  {"id":"msg_01QaryquwU7vfXxC8VvgtTD1dy","type":"message","role":"assistant","model":"claude-opus-4-6","content":[{"type":"text","text":"pong"}],"stop_reason":"end_turn","stop_sequence":null,"stop_details":null,"container":null,"usage":{"input_tokens":8,"output_tokens":1,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":0},"server_tool_use":{"web_search_requests":0,"web_fetch_requests":0},"service_tier":"standard"},"context_management":{"applied_edits":[]}}
  ```

  </details>

### `Proxy1/Max`（代理1 max 档）

- base_url：`https://codeyu.shop`
- key：`sk-e…596f（len=67）`（来自 `CLAUDE_PROXY_KEY_MAX`）
- 结论：**✅ 可用** —— 可达且可调用
- DNS：64.83.15.230 (IPv4)（8.2 ms）
- TCP：连通 64.83.15.230:443（41.3 ms）
- TLS：TLSv1.3 · TLS_AES_128_GCM_SHA256 (TLSv1.3, 128 bits) · ALPN=http/1.1（88.3 ms）
- 证书：`codeyu.shop` ← `YE1`（Let's Encrypt） · 到期 `Nov 29 23:35:39 2026 GMT`（剩 75 天） · SAN：codeyu.shop
- `GET /v1/models`：HTTP `200` · 116.9 ms
- `POST /v1/messages`：状态码 200、200、200 · 延迟 2286.4/2524.5/3000.4 ms · 实际使用模型 `claude-opus-4-6`
- 模型探测记录：
  - `claude-opus-4-6` → HTTP `200` · 2286.4 ms

  <details><summary>最后一次响应体（截断）</summary>

  ```json
  {"id":"msg_011Cf4RCvlWd7whaGGVahsSR","type":"message","role":"assistant","model":"claude-opus-4-6","content":[],"stop_reason":"max_tokens","stop_sequence":null,"stop_details":null,"context_management":{"applied_edits":[]},"usage":{"cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0},"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"inference_geo":"not_available","input_tokens":19,"output_tokens":1,"output_tokens_details":{"thinking_tokens":0},"service_tier":"standard"}}
  ```

  </details>

### `Proxy2`（代理2（独立域名））

- base_url：`https://cursor.scihub.edu.kg/api`
- key：`cr_0…d189（len=67）`（来自 `CLAUDE_PROXY_KEY_2`）
- 结论：**❌ DNS 失败** —— DNS 解析失败：gaierror: [Errno -2] Name or service not known
- DNS：无记录（565.4 ms） · gaierror: [Errno -2] Name or service not known

### `Official`（Anthropic 官方（对照组））

- base_url：`https://api.anthropic.com`
- key：`sk-a…XwAA（len=108）`（来自 `CLAUDE_API_KEY`）
- 结论：**✅ 可用** —— 可达且可调用
- DNS：160.79.104.10 (IPv4)、2607:6bc0::10 (IPv6)（2.2 ms）
- TCP：连通 160.79.104.10:443（8.2 ms）
- TLS：TLSv1.3 · TLS_AES_256_GCM_SHA384 (TLSv1.3, 256 bits) · ALPN=http/1.1（41.8 ms）
- 证书：`api.anthropic.com` ← `WE1`（Google Trust Services） · 到期 `Oct 22 19:00:52 2026 GMT`（剩 37 天） · SAN：api.anthropic.com
- `GET /v1/models`：HTTP `200` · 210.2 ms
- `POST /v1/messages`：状态码 200、200、200 · 延迟 1540.7/1540.9/1778.1 ms · 实际使用模型 `claude-opus-4-6`
- 模型探测记录：
  - `claude-opus-4-6` → HTTP `200` · 1540.9 ms

  <details><summary>最后一次响应体（截断）</summary>

  ```json
  {"model":"claude-opus-4-6","id":"msg_011Cf4RCSGGVqdrib7eAZKZx","type":"message","role":"assistant","content":[],"container":null,"stop_reason":"max_tokens","stop_sequence":null,"stop_details":null,"usage":{"input_tokens":8,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":0},"output_tokens":1,"service_tier":"standard","inference_geo":"global"}}
  ```

  </details>

## 密钥形态体检

> 只统计「形态」（长度 / 首尾空白 / 控制字符 / 非 ASCII），**不输出任何密钥内容**。
> secret 里带换行或首尾空白时，anthropic SDK 会在本地就构造失败，症状正是
> `APIConnectionError: Connection error.`，很容易被误判成网络/代理故障。

| 通路 | 来源变量 | key（掩码） | key 形态 | base_url 形态 |
|---|---|---|---|---|
| `Proxy1/Base` | CLAUDE_PROXY_KEY_BASE | `sk-1…33ac（len=67）` | len=67 · 形态正常 | len=19 · 形态正常 |
| `Proxy1/Prime` | CLAUDE_PROXY_KEY_PRIME | `sk-9…c44c（len=67）` | len=67 · 形态正常 | len=19 · 形态正常 |
| `Proxy1/Max` | CLAUDE_PROXY_KEY_MAX | `sk-e…596f（len=67）` | len=67 · 形态正常 | len=19 · 形态正常 |
| `Proxy2` | CLAUDE_PROXY_KEY_2 | `cr_0…d189（len=67）` | len=67 · 形态正常 | len=32 · 形态正常 |
| `Official` | CLAUDE_API_KEY | `sk-a…XwAA（len=108）` | len=108 · 形态正常 | — |

## 判定口径与建议

- **DNS / TCP / TLS 全绿但 HTTP 401/403**：GitHub 出网没问题，问题在 key 或代理端授权。把本页的 runner 出口 IP 交给代理方，确认是否在许可范围。
- **TLS 握手失败 / 证书不受信**：代理换了证书或域名，或缺中间证书；SDK 侧同样会失败，应换通路。
- **TCP timeout / refused**：GitHub runner 到代理的链路不可达（被墙或代理侧限流），本机可能完全正常。
- **429 / 额度类错误**：网络与鉴权正常，按套餐/额度处理。
- **`Official` 是对照组**：官方与代理同时失败 → 看 runner 出网；只有代理失败 → 看代理侧。
- 原始数据 `latest.json` · 完整日志 `latest.log` · 历史趋势 `history.jsonl`
