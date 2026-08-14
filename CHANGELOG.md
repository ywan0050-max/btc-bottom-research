# 变更记录

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 的基本格式。正式发布前的改动记录在 `Unreleased`。

## Unreleased

### 新增

- Windows 一键安装与启动、自动端口避让及局域网访问。
- Coin Metrics、美国财政部、FRED、mempool.space、DefiLlama 与 Alternative.me 免费公开数据采集。
- DuckDB 增量存储、Parquet 归档、来源级刷新历史与可解释因子模型。
- React 响应式 PWA、长期指标页、数据来源页及系统状态页。
- GitHub Actions Windows 验证流程、贡献指南与数据来源归属说明。
- `AGPL-3.0-only` 软件许可证及运行页面中的许可证入口。

### 修复

- 刷新期间在总览缓存完成前保持“刷新中”，避免完成状态与旧缓存短暂不一致。
- Windows PowerShell 执行策略阻止 `npm.ps1` 时改用 `npm.cmd`。
- 一键启动在依赖或前端源码变化后自动同步，并正确传播严格端口冲突的失败码。

### 调整

- 宏观长期模式默认暂停 Deribit 自动刷新，短周期缓存默认折叠展示。
