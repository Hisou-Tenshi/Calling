# Claude 代理可达性对照报告（两种运行环境）

- A（基线）：宿主 runner（A：GitHub Actions 1000012221）
- B（对照）：Tenshi 运行容器（B：d4e4e01467f5）

## 结论

> ⚠️ 两边都失败的通路：`Proxy2` → 更像代理侧 / 配置侧问题。

## 逐通路对照

| 通路 | A：宿主 runner | B：Tenshi 运行容器 | 说明 |
|---|---|---|---|
| `Proxy1/Base` | ✅ 可用 | ✅ 可用 | 两边一致可用 |
| `Proxy1/Prime` | ✅ 可用 | ✅ 可用 | 两边一致可用 |
| `Proxy1/Max` | ✅ 可用 | ✅ 可用 | 两边一致可用 |
| `Proxy2` | ❌ DNS 失败 | ❌ DNS 失败 | 两边一致失败（❌ DNS 失败）→ 偏代理侧 / 配置侧问题 |
| `Official` | ✅ 可用 | ✅ 可用 | 两边一致可用 |

## 失败细节

- `Proxy2`
  - A 宿主 runner：❌ DNS 失败 —— DNS: gaierror: [Errno -2] Name or service not known
  - B Tenshi 运行容器：❌ DNS 失败 —— DNS: gaierror: [Errno -2] Name or service not known

- 完整数据：两侧各自的 `latest.json` / `latest.md` / `latest.log`
