# 参与贡献

感谢你改进 BTC 底部研究台。项目优先保证数据可审计、口径可解释和 Windows 本地使用稳定，而不是追求指标数量。

## 开发环境

- Windows 10/11
- Python 3.12
- Node.js 20.19 或更高版本（推荐 Node.js 22 LTS）

```powershell
git clone <你的仓库地址>
Set-Location .\btc-bottom-research
.\setup.ps1
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\scripts\verify.ps1
```

`setup.ps1` 安装运行依赖并构建前端；测试依赖单独放在 `requirements-dev.txt`。

## 提交数据源改动前

新增来源必须同时满足：

1. 免费、无需交易所私钥或付费订阅。
2. 有稳定的公开接口或可审计的官方文件，不抓取未公开内部接口。
3. 在页面与 `NOTICE.md` 中写明来源、许可/条款、频率和原始单位。
4. 来源失败时保留旧真实缓存并标记过期；没有缓存时显示暂无数据。
5. 不生成示例行情，不用推导值冒充独立原始数据。
6. 单一来源或单一子序列失败不能阻断其他来源入库。

涉及评分时，请解释同源指标如何去重、缺失项如何处理，并补充单元测试。未经历史验证的阈值必须标记为实验规则，不能表述为概率或胜率。

## 验证要求

提交前至少运行：

```powershell
.\scripts\verify.ps1
```

脚本会执行 Python 语法检查、完整 pytest、依赖一致性检查和前端生产构建。涉及页面改动时还应检查桌面布局、浏览器控制台和 PWA 资源；涉及采集器时应说明真实接口验证结果。

## Pull Request

- 每个 PR 聚焦一个明确问题。
- 不提交 `.runtime.json`、DuckDB、Parquet、日志、缓存或本机路径。
- 不把访问令牌、Cookie、账户信息或浏览记录放入 Issue/PR。
- 对指标口径、数据条款或免责声明的变化同步更新 README 与 NOTICE。
