# 数据来源、归属与再分发说明

软件源代码的许可证与第三方数据条款是两件独立的事情。仓库默认不包含运行时下载的 DuckDB 或 Parquet 数据；使用者直接从各公开来源获取数据，并应自行遵守来源的最新条款。

| 来源 | 项目用途 | 条款/归属提示 |
| --- | --- | --- |
| Coin Metrics Community API | BTC `PriceUSD`、`CapMVRVCur` | Community 数据标注为 **CC BY-NC 4.0**；需要署名且不得用于商业用途。参见 [Coin Metrics Community API](https://docs.coinmetrics.io/api/v4/) 与 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)。 |
| U.S. Treasury Fiscal Data | TGA 余额 | 美国政府公开数据；参见 [Fiscal Data](https://fiscaldata.treasury.gov/)。 |
| FRED | 宏观与市场序列 | 受 FRED 使用条款约束，底层序列可能另有条款；参见 [FRED Terms of Use](https://fred.stlouisfed.org/legal/)。 |
| mempool.space | 全网算力、挖矿难度 | 数据来自比特币网络；mempool 项目采用 AGPL-3.0。参见 [mempool.space API](https://mempool.space/docs/api/rest)。 |
| DefiLlama | 全链稳定币供应量 | 聚合公开数据，受 DefiLlama 条款与上游来源约束。参见 [DefiLlama](https://defillama.com/)。 |
| Alternative.me | 恐惧贪婪指数 | 使用公开 API，页面保留来源归属。参见 [Crypto Fear & Greed Index API](https://alternative.me/crypto/fear-and-greed-index/)。 |
| Deribit | BTC 永续与期权短周期参考 | 受 Deribit 服务条款约束，只代表 Deribit 单一市场。宏观模式默认暂停自动刷新。参见 [Deribit API](https://docs.deribit.com/)。 |
| Blockchain.com Charts | 已退役 CDD 端点的旧真实缓存 | 当前不主动刷新，不随仓库分发旧缓存；参见 [Blockchain.com Charts](https://www.blockchain.com/explorer/charts)。 |

## 对发布者的提示

- 不要把本地 `data/`、`.runtime.json` 或采集后的导出文件提交到 GitHub Release。
- 若公开展示、共享或重新分发 Coin Metrics 数据，应保留来源归属并遵守非商业限制。
- 对第三方网站人工记录的 CVDD 月度参考，只保存实际页面地址、读数和口径备注；不要暗示它是本项目从原始链上数据复算的结果。
- 上游条款可能变化。准备再分发数据集或用于组织/商业场景前，应重新核验最新条款。

本说明不是法律意见。
