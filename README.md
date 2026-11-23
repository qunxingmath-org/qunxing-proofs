# 点亮的证明 · qunxing-proofs

在群星点亮的证明，以及 CI 复跑 Lean 检查的报告。

> 状态：搭建中。目录结构以群星的提交格式规范为准，定稿后补在这里。

## 这里放什么

- 自然语言证明；
- Lean 工程（锁定工具链和依赖版本）和本机检查参数；
- 题意复核记录（如果做了）；
- CI 复跑报告。

证明要用群星桌面端提交。直接向本仓库开的 PR 不会点亮星星。

## 复跑

- 本仓库的 GitHub Actions 会复跑收进来的 Lean 证明。开放题的"已解决"和"已否定"全部复跑，其余的排队复跑。
- 复跑只针对本仓库里的内容。
- 复跑通过，星星加上"Lean 已复跑"记号。
- 复跑失败，星星熄灭；记录保留，并写明原因。

## 声明

- 群星根据提交的材料和本机检查参数点亮星星，不另做人工验证，**不对结果的正确性负责**。
- "题面已复核"只在维护者锁定题面后才标。

## 不放密钥

本仓库不放任何密钥、令牌或个人信息。CI 会检查常见的密钥格式，发现了就不能合并。

## 许可

| 内容 | 许可 |
|---|---|
| Lean 代码 | [Apache-2.0](LICENSES/Apache-2.0.txt)，与 Mathlib 一致 |
| 证明文字、题意复核记录、说明文档 | [CC BY-SA 4.0](LICENSES/CC-BY-SA-4.0.txt) |
| 复跑报告、检查参数等结构化记录 | [CC0 1.0](LICENSES/CC0-1.0.txt) |

每个文件的许可写在 `REUSE.toml` 里。

---

**English.** Proofs that lit stars on Qunxing, and CI rerun reports of their Lean checks.

- Submit proofs through the Qunxing desktop app. Pull requests opened directly against this repository do not light stars.
- Qunxing lights stars based on submitted material and local check parameters. It does not vouch for correctness.
- No secrets are stored here.

Licenses: Lean code under Apache-2.0; proof texts under CC BY-SA 4.0; structured records under CC0 1.0.
