# BTC 底部研究台

一个运行在 Windows 本地、完全依赖免费公开数据的 BTC 周期底部研究仪表盘。项目只读取公开市场与宏观数据，不接钱包、不保存交易所私钥、不自动下单，也不会自动配置公网端口转发。

公开源代码：[github.com/ywan0050-max/btc-bottom-research](https://github.com/ywan0050-max/btc-bottom-research)

当前版本以 Windows 本地个人研究为主，源代码、自动化测试和构建流程已发布到公开 GitHub 仓库。运行时数据库、Parquet、日志和本机地址不会随仓库分发。

## 软件许可证

本项目源代码采用 [GNU Affero General Public License v3.0 only](LICENSE)（SPDX：`AGPL-3.0-only`）发布。任何人都可以运行、研究、修改和分发代码，也可以用于商业场景；如果修改后的版本通过网络向用户提供服务，需要按 AGPL-3.0 向这些用户提供对应源代码。

软件许可证不授予第三方数据的再分发权。运行时获取的 Coin Metrics、FRED、Deribit 等数据仍分别受其来源条款约束，详见 [NOTICE.md](NOTICE.md)。

## 环境要求

- Windows 10/11 与 PowerShell 5.1 或更高版本
- Python 3.12
- Node.js 20.19 或更高版本（推荐 Node.js 22 LTS）与 npm
- 首次安装和刷新数据时可访问互联网

## 一键启动

安装 Python 3.12 和 Node.js 后，在项目根目录直接双击 `一键启动.cmd` 即可。启动器会自动完成以下操作：

- 首次运行时创建 `.venv`、安装 Python 和 npm 依赖、构建前端。
- 从 `8765` 开始自动选择可用端口并启动同源服务。
- 服务就绪后用默认浏览器打开实际本机地址。
- 如果研究台已经在运行，直接打开现有地址，不会重复启动第二个服务。

运行时请保留启动窗口；在窗口中按 `Ctrl+C` 可停止服务。该入口只对当次 PowerShell 进程使用 `ExecutionPolicy Bypass`，不会修改 Windows 的全局执行策略。

从 GitHub 下载 ZIP 或克隆仓库后，先进入解压/克隆得到的项目目录；不要把 README 中的示例路径当作固定安装位置。

## PowerShell 手动启动

在项目目录打开 PowerShell：

```powershell
Set-Location "C:\path\to\btc-bottom-research"
.\setup.ps1
.\start.ps1
```

如果 PowerShell 阻止当前会话运行本地脚本，可只对当前窗口放宽策略：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

`setup.ps1` 会创建 Python 3.12 的 `.venv`、安装 `requirements.txt`、使用 `npm.cmd` 安装前端依赖并构建 React 前端。启动器会保存依赖与前端输入文件的内容指纹；从 GitHub 更新代码后，如果 `requirements.txt`、npm 锁文件或前端源码发生变化，`start.ps1` 会自动更新环境或重新构建，不会继续使用旧产物。需要从 PowerShell 启动后自动打开页面时，使用 `.\start.ps1 -OpenBrowser`。

## 端口选择

前端构建产物与 FastAPI API 共用一个端口。启动器默认监听 `0.0.0.0`，从 `8765` 到 `8795` 依次检查，并在这一段均被占用时继续向更高端口寻找。

```powershell
# 自动选择端口
.\start.ps1

# 优先使用指定端口；占用时自动避让
.\start.ps1 -Port 8788

# 指定端口占用时直接报错
.\start.ps1 -Port 8788 -StrictPort

# 使用环境变量指定首选端口
$env:BTC_RESEARCH_PORT = "8788"
.\start.ps1

# 开发时启用 Uvicorn reload
.\start.ps1 -Reload
```

启动时会打印实际的本机地址和局域网地址，并把端口、监听地址、URL 与启动时间写入项目根目录的 `.runtime.json`。如果指定端口被占用，非严格模式会明确打印被占用的端口和最终端口。

## 手机局域网访问

1. 让电脑和手机连接同一个可信 Wi-Fi。
2. 启动项目并找到终端打印的“局域网地址”，例如 `http://192.168.1.23:8765`。
3. 在手机浏览器打开该地址。
4. 浏览器支持时可使用“添加到主屏幕”安装 PWA。

如果本机能打开、手机不能打开，通常是 Windows 防火墙未允许 Python 接收入站连接。优先在系统首次弹窗中只勾选“专用网络”。也可以管理员身份创建仅限专用网络和实际端口的规则，例如：

```powershell
New-NetFirewallRule -DisplayName "BTC Research 8765" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -Profile Private
```

请把示例端口替换成 `.runtime.json` 中的实际端口。不要在不可信公共网络启用规则，不要配置路由器端口转发，也不要把服务直接暴露到公网。

需要在外网私有访问时，可以在电脑和手机上分别安装 Tailscale，再通过电脑的 Tailscale IP 与实际端口访问。第一版不会自动安装或配置 Tailscale。

服务的 Host 检查只接受 localhost、回环/私有/链路本地 IP 和 Tailscale `100.64.0.0/10` 地址。请使用启动器打印的 IP 地址访问；任意公网域名、公网 IP 或直接端口转发会被拒绝。

## 数据源

| 来源 | 第一版序列 | 原始频率与单位 | 许可/说明 |
| --- | --- | --- | --- |
| Coin Metrics Community API | `PriceUSD`、`CapMVRVCur` | 日频；USD、比率 | 从 2016-01-01 开始；无需 API Key；数据标注为 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) |
| Blockchain.com Charts API（历史缓存） | `CoinDaysDestroyed`、`BlockchainPriceUSD` | 日频；coin-days、USD | CDD 端点已返回 404，停止主动刷新；旧真实缓存仅保留审计，CVDD 保持等待 |
| mempool.space Public API | `HashRate`、`MiningDifficulty` | 日频、每 2016 区块；EH/s、难度 | 无 API Key；用于 Hash Ribbons 与矿工压力研究，项目开源（AGPL-3.0） |
| U.S. Treasury Fiscal Data API | TGA Closing Balance | 工作日；million USD | 兼容 `close_today_bal` 为空而实际数值位于 `open_today_bal` 的返回行 |
| FRED CSV | `WALCL` | 周频；million USD | 美联储总资产 |
| FRED CSV | `RRPONTSYD` | 工作日；billion USD | 隔夜逆回购 |
| FRED CSV | `DGS10` | 工作日；percent | 美国 10 年期国债收益率 |
| FRED CSV | `DTWEXBGS` | 工作日；index | 广义贸易加权美元指数 |
| FRED CSV | `NFCI` | 周频；index | 芝加哥联储全国金融状况指数，正值相对趋紧 |
| FRED CSV | `BAMLH0A0HYM2` | 工作日；percent | 美国高收益债期权调整利差 |
| FRED CSV | `DFII10` | 工作日；percent | 美国 10 年期通胀指数债券实际收益率 |
| FRED CSV | `M2SL` | 月频；billion USD | 美国 M2 货币供应量；页面换算为 trillion USD，发布存在滞后 |
| DefiLlama Stablecoins API | `StablecoinSupplyUSD` | 日频；USD | 全链稳定币总流通量；无需 API Key；辅助观察，不与宏观净流动性拼接 |
| Alternative.me API | `FearGreedIndex` | 日频；0–100 指数 | 加密市场恐惧贪婪指数；无需 API Key；按来源要求标注归属 |
| Deribit Public API | BTC-PERPETUAL funding、OI、recent trades、固定 bps order book；BTC options IV、RR25、BF25 | 小时历史与实时快照；无需 API Key | 受 Deribit 服务条款约束；只代表 Deribit 单一市场 |

所有来源都会独立记录刷新状态。FRED 的八个序列和 Deribit 的永续、盘口、期权指标也会分别记录成功或失败，因此某一个子请求失败不会阻止其他成功序列写入。刷新失败时不会生成或回退到虚构行情：已有真实缓存会保留并标记过期，没有缓存则显示“暂无数据”。Blockchain.com CDD 端点已经退役，因此默认不再请求它，也不会用网页抓取或不可审计数据补齐 CVDD。

数据来源页提供“CVDD 第三方月度参考”录入区。可以每月从 CoinGlass 或其他公开页面人工核验后保存页面地址、观测日期和实际读数；同一来源同一月份再次录入会更新原记录。当月存在多个来源时，页面显示中位数、最大差异和来源明细，超过 30 天未重新核验会标记过期。这些读数与原始 CDD 复算严格分开，不自动进入底部评分。为防止同一 Wi-Fi 下其他设备误写，CVDD 读取允许局域网访问，但写入接口只接受本机回环地址（`127.0.0.1` 或 `::1`）。

系统状态页显示最近 20 轮完整刷新历史，包括结果、成功来源数、写入行数、耗时与失败来源，并单独汇总每个来源当前的连续失败次数。总览在服务启动和每轮刷新结束后预计算并保存在内存中，普通 `/api/overview` 请求直接读取缓存；缓存计算状态、生成时间和年龄可在 `/api/health` 与系统状态页查看。

BTC 现货 ETF 每日净流入暂不接入。SEC EDGAR 官方 API 免费且无需 Key，但提供的是申报历史和 XBRL 财务事实，不直接提供统一的每日 BTC ETF 净流入；常见净流入表通常由第三方依据份额、持仓和 NAV 二次计算。目前没有确认到许可清楚、口径统一、长期稳定的免费正式 API，因此项目不抓取网页表格或调用未公开接口来补数。

点击“刷新”后，页面会显示来源级进度、完成数量和已用时间。来源完成后立即更新状态；等待较慢来源时仍可看到其他来源已经成功或失败。

## 分层刷新与归档

服务启动时会执行一次已启用来源的增量刷新。之后按来源频率分层调度：

- 宏观长期模式默认暂停 Deribit 自动刷新，避免单一短周期市场的网络超时反复污染全局状态；设置 `BTC_RESEARCH_ENABLE_DERIBIT=1` 后每 15 分钟刷新。
- DefiLlama 全链稳定币供应量与 Alternative.me 恐惧贪婪指数作为长期辅助观察，使用免费公开 API 并增量入库；完成回测前不参与底部评分。
- Coin Metrics、mempool.space、Treasury、FRED、DefiLlama 和 Alternative.me 默认每 6 小时刷新。
- 每次历史型请求都从 DuckDB 最新观测时间向前保留少量重叠窗口，再使用唯一键 upsert，不重复全量下载。
- Parquet 默认每 24 小时归档一次，按 `data/parquet/observations/year=YYYY/month=MM/` 月分区使用 Zstandard 压缩并原子替换。
- 每次有真实数据成功写入后都会保存一条带规则版本的评分历史，归档到 `data/parquet/scores/score_snapshots.parquet`。
- 手动刷新、快速调度和慢速调度共用同一个刷新锁，不会出现重叠采集任务。

可使用以下环境变量调整调度，但代码会执行最小间隔保护：

```powershell
$env:BTC_RESEARCH_DERIBIT_REFRESH_SECONDS = "900"
$env:BTC_RESEARCH_SLOW_REFRESH_SECONDS = "21600"
$env:BTC_RESEARCH_ARCHIVE_SECONDS = "86400"
$env:BTC_RESEARCH_PARQUET_DIR = (Join-Path $PWD "data\parquet")
$env:BTC_RESEARCH_COLLECTOR_TIMEOUT = "45"  # 单个数据源最长等待秒数
```

单个数据源超过总时限会独立标记失败，其他来源仍会继续完成；已有真实缓存会保留并标记过期。

## 指标口径

- BTC 价格变化：用最新日频观测与不晚于 7 日/30 日前的最近观测比较。
- 距历史高点回撤：以数据库中 2016 年以来的价格样本高点计算。
- 30 日实现波动率：最近 30 个日对数收益率的样本标准差，按 365 天年化。
- 200 周均线：最近 1,400 个日频价格观测的算术平均。
- MVRV 五年滚动百分位：当前 MVRV 在最近五年样本中的经验百分位。
- 已实现价格：使用同一观测日的 `PriceUSD / CapMVRVCur` 推导。
- NUPL：使用 `1 - 1 / MVRV` 推导；它与已实现价格、MVRV 属于同一份链上证据，不在评分中重复计权。
- Mayer Multiple：BTC 价格除以最近 200 个日频价格观测的均值，并计算五年滚动百分位。
- CVDD 近似值：原计划使用 Blockchain.com Charts 的日频 CDD 与同源日频价格复算，但该 CDD 端点已退役。旧真实缓存保留审计；找到许可清楚、稳定且可审计的替代原始序列前显示等待，不填充虚构值。
- CVDD 第三方月度参考：人工核验公开页面后保存来源名称、网址、日期和美元读数；同月多来源取中位数并显示差异。它允许少量网站口径误差，但不是原始链上复算值、不生成历史回填，也不参与评分。
- Hash Ribbons：使用 mempool.space 的全网日均算力比较 30 日与 60 日简单均线。30 日低于 60 日仅标记“矿工压力期”，反之标记“算力恢复期”；完成历史回测前不参与评分。
- 金融压力：FRED `NFCI`、`BAMLH0A0HYM2` 与 `DFII10` 分别表示金融条件、信用利差和实际利率，作为独立长期观察量；完成历史回测前不参与评分。
- 稳定币供应量：DefiLlama 汇总的全链稳定币美元流通量及其 30 日变化，作为加密原生流动性辅助观察；不与美联储/TGA/RRP 的宏观净流动性近似值拼接，回测前不参与评分。
- 恐惧贪婪指数：Alternative.me 的 0–100 日频加密市场情绪指数，作为周期情绪辅助观察；不等同于底部概率，回测前不参与评分。
- 美国 M2：FRED `M2SL` 月频货币供应量，原始单位 billion USD；页面换算为 trillion USD 并计算 12 个月变化。该序列发布滞后，回测前不参与评分。
- 净流动性近似值：`FedAssets / 1000 - TGA / 1000 - OvernightRRP`，统一为 billion USD 后计算。
- 资金费率：Deribit BTC-PERPETUAL 最近约 31 天的小时观测，数值口径为 8 小时费率百分比。
- OI：Deribit BTC-PERPETUAL 当前未平仓美元名义值；7 日变化需要本地定时快照积累满 7 天。
- 近期成交量差（CVD）：最近 1,000 笔 Deribit BTC-PERPETUAL 主动买入美元量减主动卖出美元量。该时间窗随成交活跃度变化，不代表全市场长期 CVD。
- 固定距离订单簿：从中间价上下 10、25、50、100 bps 范围内汇总 BTC-PERPETUAL 买卖美元深度；主指标 `OrderBookImbalance25bps` 使用 25 bps 深度失衡，避免固定档数随盘口密度变化。旧版前 50 档 `OrderBookImbalance` 历史会保留，但不与新序列混算。
- 当前盘口：以 Deribit BTC-PERPETUAL 当前快照统计中间价上下 25 bps 的买卖挂单美元深度差；它不是长期证据。
- 固定期限 ATM IV：从 Deribit BTC 期权标记 IV 构造 7、30、90 天平值 IV；相邻到期日之间按总方差插值，避免到期切换跳变。
- 25Delta Risk Reversal：`RR25 = IV(25Δ Call) - IV(25Δ Put)`，负值表示看跌保护更贵。
- 25Delta Butterfly：`BF25 = (IV(25Δ Call) + IV(25Δ Put)) / 2 - ATM IV`，表示两翼相对平值期权的波动率溢价。
- IV 期限斜率：分别计算 `ATMIV7D - ATMIV30D` 与 `ATMIV30D - ATMIV90D`，正值表示较短期限 IV 更高。

“净流动性近似值”只是跨来源、跨频率数据对齐后的研究代理指标，不是精确流动性，也不应被表述成精确值。

底部环境分由周期回撤、200 周均线距离和净流动性 30 日变化等当前可用组成项取平均，页面会逐项显示贡献。

BTC 长周期估值分独立显示。已实现价格和 NUPL 都由 MVRV 推导，所以只合并计权一次；CVDD 近似值只有在公开 CDD 与同源价格历史满足覆盖条件后才参与。

“因子模型”实验页把长期环境拆为链上估值 45%、价格周期 25%、宏观环境 30%；这部分是本项目主线。反转确认仅作为 Deribit 单一市场的短周期线索，拆为杠杆 25%、主动成交 30%、盘口 25%、期权 20%，不能视为全市场独立确认。组内覆盖不足 50% 时整组等待，缺失项不填零分。贡献值使用覆盖率调整后的有效权重，能够还原总分相对 50 分中性的偏移。页面同时显示最近五年变化率的 Spearman 排名相关；结构性同源关系单独标记，不作为独立确认。

反转确认分由资金费率 30 日低位、OI 7 日趋势、近期主动成交、25 bps 当前盘口和 25Delta 偏斜修复组成。只有 funding、OI、CVD 和订单簿当前数据均可用且未过期，并且至少三个因子组已有可计算分值时才显示总分；等待历史积累的组成项不参与平均，同时显示实际覆盖度。期权偏斜使用 30 天 RR25 的 24 小时变化，RR25 上升代表看跌保护溢价缓和。所有 Deribit 指标都只是单一市场短周期线索，不能替代全市场衍生品聚合数据，也不能用于推断长期宏观底部。第一版不再扩展 15 分钟成交桶或卖压吸收模型。

因子分数是手工阈值实验，尚未做历史回测，不代表概率、胜率或投资建议。数据可信度只评价指标覆盖、时效与频率，不评价方向正确性。

数据可信度的组成是：当前长期主线启用指标的可用性 40%、观测新鲜度 25%、数据频率 10%、缓存未过期比例 25%。已退役 CDD 和宏观模式默认暂停的 Deribit 不参与该分数；它们仍在指标页展示真实缓存与时效。不同频率使用不同过期阈值；启用指标最近一次刷新失败时，即使历史缓存仍在，也会明确标记为过期。

## API

- `GET /api/health`：服务、DuckDB、端口与刷新状态
- `GET /api/overview`：评分、市场指标、宏观指标和数据质量
- `GET /api/series/{metric}`：指定指标的真实历史序列
- `GET /api/scores`：带评分规则版本的历史评分快照；`environment` 与 `reversal` 对应因子模型总分，`cycle` 保留 BTC 长周期估值子模型
- `GET /api/references/cvdd`：CVDD 第三方月度参考汇总与历史
- `POST /api/references/cvdd`：保存或更新某一来源的当月 CVDD 公开读数，仅允许本机回环地址写入
- `GET /api/refresh-history?limit=20`：最近完整刷新历史与来源连续失败次数
- `GET /api/sources`：来源、许可、最近刷新和分指标刷新结果
- `POST /api/refresh`：请求刷新；已有刷新运行时不会启动重叠任务
- `GET /docs`：FastAPI 自动生成的本地 API 文档

所有 `/api/` 响应都使用 `no-store`。Service Worker 不拦截或缓存 API 请求。

## 开发与验证

运行依赖与开发测试依赖分开维护。首次开发时执行：

```powershell
.\setup.ps1
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

提交改动前运行统一验证脚本：

```powershell
.\scripts\verify.ps1
```

该脚本会检查 PowerShell 启动器与构建指纹、Python 语法和依赖、运行完整 pytest、执行前端生产构建、检查核心 API/PWA 资源和写接口保护、启动真实单端口进程验证端口避让，并检查 npm 高危漏洞。只需要离线跳过 npm 漏洞查询时可使用 `.\scripts\verify.ps1 -SkipAudit`。

公开仓库包含 Windows GitHub Actions：在 push、Pull Request 和手动触发时验证 Python 3.12、Node.js 22、单元测试、生产构建、依赖审计以及 FastAPI/前端/PWA 的单端口冒烟测试。CI 使用 `BTC_RESEARCH_DISABLE_BACKGROUND_TASKS=1` 禁止访问外部数据源；该变量仅用于测试与离线诊断，正常启动不要设置。

贡献规则见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全边界与私密报告方式见 [SECURITY.md](SECURITY.md)。

## 数据与隐私

DuckDB 默认位于 `data/research.duckdb`，保存从公开接口取得的数据、评分历史、刷新与归档日志。Parquet 默认位于 `data/parquet`。可通过 `BTC_RESEARCH_DB` 指定其他数据库路径，通过 `BTC_RESEARCH_HTTP_TIMEOUT` 调整 HTTP 超时秒数。旧的 `BTC_RESEARCH_REFRESH_SECONDS` 仍可作为慢速刷新间隔的兼容设置，新配置优先使用分层刷新环境变量。

这些运行时数据、缓存与本机配置均被 `.gitignore` 排除。仓库不会附带采集后的行情数据库。测试或多实例环境还可通过 `BTC_RESEARCH_RUNTIME_FILE` 指定独立的运行信息文件，避免覆盖默认 `.runtime.json`。第三方来源归属、非商业限制和再分发注意事项见 [NOTICE.md](NOTICE.md)；尤其是 Coin Metrics Community 数据采用 CC BY-NC 4.0，软件代码许可证不能替代或覆盖数据条款。

本项目仅供个人研究与软件实验。公开数据可能延迟、缺失、修订或出现口径变化；评分是可解释的研究规则，不是价格预测、交易信号或投资建议。任何投资决策与风险均由使用者自行承担。
