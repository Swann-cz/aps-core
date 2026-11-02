# T-33 挑刺反例（回归用例）

来源：tasks/reports/T-33-redteam.md（Codex gpt-6-astra，2026-10-28；Claude 独立复跑 13/13 复现）。
`witnesses/` 是见证计划（存在可行计划的证据），不是标准答案。九级顺序 L1a/L1b/L1c/L2/L3a/L3b/L4/L5/L6。

| 用例 | 期望（T-34 修复后） | 见证计划九级 |
|---|---|---|
| R01-idle-line-shutdown | segment 判 ACCEPT，不崩溃；字典序不劣于见证 | 0/0/0/1/0/0/0/0/0 |
| R02-initial-over-cap | 同上 | 0/0/0/0/0/0/0/561/561 |
| R03-zero-demand | 同上 | 0/0/0/0/0/0/0/0/0 |
| R04-zero-tail-stop | 同上 | 0/0/0/0/0/0/0/0/0 |
| R05-unused-model-weekend | 判定器对见证判 ACCEPT（现判 C8 误判 REJECT）；segment 判 ACCEPT | 0/0/0/0/0/0/0/0/0 |
| R06-upstream-shutdown | segment ACCEPT；不劣于见证 | 200/200/140/0/0/0/0/216/660 |
| R07-fixed-weld-output | 同上 | 102/102/42/0/0/0/0/800/2848 |
| R08-overlap-mode-order | segment ACCEPT；不劣于见证；两条授权交换行序结果九级相同 | 0/0/0/0/0/20/0/0/0 |
| R09-excess-overtime | segment ACCEPT；不劣于见证 | 0/0/0/0/0/4/0/0/0 |
| R10-single-date-import | `.xlsx` 导入预检通过，转换结果等于 `.input.json` | 0/0/0/0/0/0/0/224/1120 |
| R11-buffer-scope | `.xlsx` 导入预检报错（缓冲区期初超物理上限，IMPORT_TEMPLATE v1.7 3.0a 第 3 条）；引擎判 INPUT_INVALID | — |
| R12-missing-off | `.xlsx` 导入预检报错（班制表缺 OFF，v1.7 §3.3）；引擎判 INPUT_INVALID，不崩溃 | — |
| R13-year-authorization-slow | segment ACCEPT，≤ 150 秒；不劣于见证 | 6515/1060743/41888.2/7/4/21/2/229/735 |
| V03-year-late-start | R03 全年变体（1–6 月零需求、7 月起投产，零期初）：segment ACCEPT | — |
| V04-year-single-full | R04 全年变体：segment ACCEPT | — |
| V05-year-only-a / only-b | R05 全年变体（登记两车型、只做一个）：segment ACCEPT | — |
