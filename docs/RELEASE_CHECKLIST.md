# GitHub 发布检查清单

## 必须完成

- [ ] 选择并添加明确的软件 `LICENSE`；确认它与维护者对商业使用的意图一致。
- [ ] `git status --short` 只包含计划发布的源代码与文档。
- [ ] `.\scripts\verify.ps1` 完整通过。
- [ ] GitHub Actions Windows CI 通过。
- [ ] 新安装环境双击 `一键启动.cmd` 能自动安装、构建、选端口并打开页面；已有环境在依赖或前端源码更新后能自动同步。
- [ ] `/api/health`、`/api/overview`、`/api/sources`、manifest、图标和 service worker 均返回成功。
- [ ] 真实进程验证指定端口占用时自动避让，并打印实际本机地址。
- [ ] 桌面视口没有横向溢出、空白图表或浏览器控制台错误。
- [ ] 数据来源页的许可、刷新状态、失败原因与实际启用状态一致。
- [ ] 仓库历史中没有 `.env`、DuckDB、Parquet、日志、Cookie、令牌或个人路径。
- [ ] README 明确写明不接钱包、不自动交易、不构成投资建议。

## 建议完成

- [ ] 在 GitHub 仓库设置中启用 Private vulnerability reporting。
- [ ] 启用分支保护，要求 CI 通过后才能合并。
- [ ] 添加一张已脱敏的桌面截图。
- [ ] 创建 `v0.1.0` 标签和 Release，说明当前指标口径、已知限制和数据条款。
- [ ] 在 Release 中只附源代码，不附本地数据库或数据导出。
