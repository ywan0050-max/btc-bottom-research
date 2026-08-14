import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LineChart as EChartsLineChart, ScatterChart as EChartsScatterChart } from "echarts/charts";
import {
  GridComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import {
  Activity,
  Archive,
  Bitcoin,
  ChartNoAxesCombined,
  ChevronDown,
  CircleAlert,
  CircleCheck,
  Clock3,
  Database,
  ExternalLink,
  Gauge,
  GitBranch,
  HardDrive,
  History,
  LayoutDashboard,
  RefreshCw,
  Save,
  Server,
  Settings,
  ShieldCheck,
  Timer,
  TrendingDown,
  TrendingUp,
  Pickaxe,
  Wifi,
} from "lucide-react";

echarts.use([
  EChartsLineChart,
  EChartsScatterChart,
  GridComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
  CanvasRenderer,
]);

const NAV_ITEMS = [
  { id: "overview", label: "总览", icon: LayoutDashboard },
  { id: "factor", label: "因子模型", icon: GitBranch },
  { id: "metrics", label: "指标", icon: Activity },
  { id: "sources", label: "数据来源", icon: Database },
  { id: "system", label: "系统状态", icon: Settings },
];

const SOURCE_LABELS = {
  coinmetrics_community: "Coin Metrics",
  blockchain_charts: "Blockchain.com",
  mempool_space: "mempool.space",
  us_treasury_fiscal_data: "美国财政部",
  fred: "FRED",
  deribit_public: "Deribit",
  defillama_stablecoins: "DefiLlama",
  alternative_fear_greed: "Alternative.me",
};

const METRIC_LABELS = {
  PriceUSD: "BTC 价格",
  CapMVRVCur: "MVRV",
  CoinDaysDestroyed: "币龄销毁（CDD）",
  BlockchainPriceUSD: "Blockchain.com BTC 价格",
  TGA: "TGA 余额",
  FedAssets: "美联储总资产",
  OvernightRRP: "隔夜逆回购",
  US10Y: "美国 10 年期收益率",
  BroadDollar: "广义美元指数",
  FinancialConditions: "芝加哥联储金融条件指数",
  HighYieldSpread: "美国高收益债利差",
  US10YReal: "美国 10 年实际利率",
  USM2: "美国 M2 货币供应量",
  StablecoinSupplyUSD: "全链稳定币供应量",
  FearGreedIndex: "恐惧贪婪指数",
  HashRate: "BTC 全网算力",
  MiningDifficulty: "BTC 挖矿难度",
  FundingRate8h: "8 小时资金费率",
  OpenInterestUSD: "未平仓量（OI）",
  TradeCVDUSD: "近期成交量差（CVD）",
  OrderBookImbalance25bps: "25 bps 订单簿失衡",
  ATMIV7D: "7 天平值 IV",
  ATMIV30D: "30 天平值 IV",
  ATMIV90D: "90 天平值 IV",
  RR25_7D: "7 天 25Delta RR",
  RR25_30D: "30 天 25Delta RR",
  RR25_90D: "90 天 25Delta RR",
  BF25_30D: "30 天 25Delta BF",
  IVTermSlope7D30D: "IV 期限斜率 7D-30D",
  IVTermSlope30D90D: "IV 期限斜率 30D-90D",
};

const FREQUENCY_LABELS = {
  daily: "日频",
  "business day": "工作日",
  weekly: "周频",
  monthly: "月频",
  hourly: "小时",
  snapshot: "快照",
};

const LONG_TERM_METRICS = new Set([
  "PriceUSD", "CapMVRVCur", "TGA", "FedAssets", "OvernightRRP", "US10Y",
  "BroadDollar", "FinancialConditions", "HighYieldSpread", "US10YReal",
  "HashRate", "MiningDifficulty",
  "StablecoinSupplyUSD", "FearGreedIndex",
  "USM2",
]);

const SHORT_CYCLE_METRICS = new Set([
  "FundingRate8h", "OpenInterestUSD", "TradeCVDUSD", "OrderBookImbalance25bps",
  "ATMIV7D", "ATMIV30D", "ATMIV90D", "RR25_7D", "RR25_30D", "RR25_90D",
  "BF25_30D", "IVTermSlope7D30D", "IVTermSlope30D90D",
]);

const STATUS_LABELS = {
  ok: "正常",
  partial: "部分失败",
  error: "失败",
  running: "刷新中",
  queued: "排队中",
  idle: "空闲",
  cached: "历史缓存",
  never: "尚未刷新",
  retired: "端点已退役",
  paused: "宏观模式暂停",
};

async function requestJson(path, options) {
  const response = await fetch(path, { cache: "no-store", ...options });
  if (!response.ok) {
    throw new Error(`${path} 返回 ${response.status}`);
  }
  return response.json();
}

function humanizeRefreshError(error) {
  const text = String(error || "");
  if (/Macro mode pauses Deribit/i.test(text)) {
    return "宏观长期模式已暂停 Deribit 自动刷新；设置 BTC_RESEARCH_ENABLE_DERIBIT=1 可重新启用。";
  }
  if (/CDD chart endpoints now return 404/i.test(text)) {
    return "CDD 公共端点已退役；停止主动刷新并保留旧真实缓存。";
  }
  if (/WinError 10013|access.*socket|套接字|网络不可达/i.test(text)) {
    return "网络连接受限，已保留上次真实缓存；请用普通 Windows 权限启动并检查防火墙。";
  }
  if (/404 Not Found/i.test(text)) {
    return "公开接口暂不提供该序列，其他指标仍可独立刷新；没有历史缓存时显示暂无数据。";
  }
  if (/Timeout|timed out|超时/i.test(text)) {
    return "来源请求超时，已保留上次真实缓存；其他来源仍可独立刷新。";
  }
  return text.length > 180 ? `${text.slice(0, 180)}…` : text;
}

function formatNumber(value, options = {}) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "暂无数据";
  return new Intl.NumberFormat("zh-CN", options).format(Number(value));
}

function formatPercent(value, signed = false) {
  if (value === null || value === undefined) return "暂无数据";
  const prefix = signed && value > 0 ? "+" : "";
  return `${prefix}${formatNumber(value, { maximumFractionDigits: 1, minimumFractionDigits: 1 })}%`;
}

function formatDate(value, includeTime = false) {
  if (!value) return "暂无";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "暂无";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    ...(includeTime ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}),
  }).format(date);
}

function formatSignedBillions(value) {
  if (value === null || value === undefined) return "暂无数据";
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}$${formatNumber(Math.abs(value), { maximumFractionDigits: 1 })}B`;
}

function formatCompactUsd(value, signed = false) {
  if (value === null || value === undefined) return "暂无数据";
  const numeric = Number(value);
  const sign = signed && numeric > 0 ? "+" : numeric < 0 ? "-" : "";
  const absolute = Math.abs(numeric);
  if (absolute >= 1e9) return `${sign}$${formatNumber(absolute / 1e9, { maximumFractionDigits: 2 })}B`;
  if (absolute >= 1e6) return `${sign}$${formatNumber(absolute / 1e6, { maximumFractionDigits: 2 })}M`;
  if (absolute >= 1e3) return `${sign}$${formatNumber(absolute / 1e3, { maximumFractionDigits: 1 })}K`;
  return `${sign}$${formatNumber(absolute, { maximumFractionDigits: 0 })}`;
}

function formatAge(ageDays) {
  if (ageDays === null || ageDays === undefined) return "-";
  if (ageDays < 1) return `${formatNumber(ageDays * 24, { maximumFractionDigits: 1 })} 小时`;
  return `${formatNumber(ageDays, { maximumFractionDigits: 1 })} 天`;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "暂无";
  const value = Number(seconds);
  if (value < 60) return `${formatNumber(value, { maximumFractionDigits: 1 })} 秒`;
  return `${formatNumber(value / 60, { maximumFractionDigits: 1 })} 分钟`;
}

function statusClass(status) {
  if (status === "ok") return "status-ok";
  if (status === "error") return "status-error";
  if (status === "partial") return "status-warning";
  return "status-neutral";
}

function Status({ status, stale = false }) {
  const resolved = stale && !["retired", "paused"].includes(status) ? "error" : status;
  const Icon = resolved === "ok" ? CircleCheck : resolved === "error" ? CircleAlert : Clock3;
  return (
    <span className={`status ${statusClass(resolved)}`}>
      <Icon size={13} aria-hidden="true" />
      {["retired", "paused"].includes(status) ? STATUS_LABELS[status] : stale ? "已过期" : STATUS_LABELS[status] || status || "未知"}
    </span>
  );
}

function RefreshProgress({ refresh }) {
  if (!refresh || !["queued", "running"].includes(refresh.status)) return null;
  const entries = Object.entries(refresh.sources || {});
  const total = entries.length || refresh.scope?.length || 0;
  const completed = entries.filter(([, source]) => !["pending", "running"].includes(source.status)).length;
  const progress = total ? completed / total * 100 : 0;
  const elapsed = refresh.startedAt
    ? Math.max(0, Math.floor((Date.now() - new Date(refresh.startedAt).getTime()) / 1000))
    : 0;
  return (
    <section className="refresh-progress" aria-live="polite" aria-label="数据刷新进度">
      <div className="refresh-progress-head">
        <div><RefreshCw size={16} className="spin" aria-hidden="true" /><strong>{refresh.status === "queued" ? "刷新任务已排队" : "正在刷新公开数据"}</strong></div>
        <span>{completed}/{total || "-"} 个来源完成 · {elapsed} 秒</span>
      </div>
      <div className="refresh-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(progress)}>
        <i style={{ width: `${progress}%` }} />
      </div>
      <div className="refresh-source-list">
        {entries.map(([id, source]) => (
          <span key={id} className={`refresh-source refresh-source-${source.status}`}>
            {source.status === "running" || source.status === "pending" ? <Clock3 size={12} /> : source.status === "ok" ? <CircleCheck size={12} /> : <CircleAlert size={12} />}
            {SOURCE_LABELS[id] || source.name || id}
            <small>{source.status === "pending" ? "等待" : source.status === "running" ? "进行中" : source.status === "ok" ? "完成" : source.status === "partial" ? "部分完成" : "失败"}</small>
          </span>
        ))}
      </div>
    </section>
  );
}

function LineChart({ data, color, name, unit, referenceLine }) {
  const containerRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current || !data?.length) return undefined;
    const chart = echarts.init(containerRef.current, null, { renderer: "canvas" });
    chart.setOption({
      animationDuration: 350,
      color: [color],
      grid: { left: 12, right: 16, top: 20, bottom: 10, containLabel: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#17211f",
        borderWidth: 0,
        textStyle: { color: "#f7f8f5", fontSize: 12 },
        formatter(params) {
          const point = params[0];
          return `${formatDate(point.value[0])}<br/>${name}：${formatNumber(point.value[1], { maximumFractionDigits: 2 })}${unit}`;
        },
      },
      xAxis: {
        type: "time",
        axisLine: { lineStyle: { color: "#cbd2cc" } },
        axisTick: { show: false },
        axisLabel: { color: "#6a746d", hideOverlap: true, fontSize: 11 },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: {
          color: "#6a746d",
          fontSize: 11,
          formatter(value) {
            if (Math.abs(value) >= 1000) return `${Math.round(value / 1000)}k`;
            return formatNumber(value, { maximumFractionDigits: 1 });
          },
        },
        splitLine: { lineStyle: { color: "#e7ebe7" } },
      },
      series: [
        {
          name,
          type: "line",
          showSymbol: false,
          sampling: "lttb",
          lineStyle: { width: 2 },
          data: data.map((point) => [point.observedAt, point.value]),
          markLine: referenceLine
            ? {
                silent: true,
                symbol: "none",
                label: { formatter: referenceLine.label, color: "#7c6744" },
                lineStyle: { color: "#c39543", type: "dashed" },
                data: [{ yAxis: referenceLine.value }],
              }
            : undefined,
        },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [color, data, name, referenceLine, unit]);

  if (!data?.length) {
    return <div className="chart-empty">暂无真实数据</div>;
  }
  return <div ref={containerRef} className="chart-canvas" role="img" aria-label={`${name}历史图表`} />;
}

function FactorQuadrant({ model }) {
  const containerRef = useRef(null);
  const x = model?.quadrant?.x;
  const y = model?.quadrant?.y;

  useEffect(() => {
    if (!containerRef.current) return undefined;
    const chart = echarts.init(containerRef.current, null, { renderer: "canvas" });
    const yWaiting = y === null || y === undefined;
    chart.setOption({
      animationDuration: 350,
      grid: { left: 48, right: 18, top: 25, bottom: 43 },
      tooltip: {
        trigger: "item",
        formatter: () => yWaiting
          ? `长期环境：${x ?? "等待"}<br/>反转确认：等待有效数据`
          : `长期环境：${x}<br/>反转确认：${y}`,
      },
      xAxis: {
        type: "value",
        min: 0,
        max: 100,
        interval: 50,
        name: "长期底部环境 →",
        nameLocation: "middle",
        nameGap: 28,
        nameTextStyle: { color: "#606a64", fontSize: 11 },
        axisLabel: { color: "#6a746d", fontSize: 10 },
        axisLine: { lineStyle: { color: "#aeb8b1" } },
        splitLine: { lineStyle: { color: "#dfe4e0", type: "dashed" } },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 100,
        interval: 50,
        name: "反转确认 →",
        nameLocation: "middle",
        nameGap: 35,
        nameRotate: 90,
        nameTextStyle: { color: "#606a64", fontSize: 11 },
        axisLabel: { color: "#6a746d", fontSize: 10 },
        axisLine: { lineStyle: { color: "#aeb8b1" } },
        splitLine: { lineStyle: { color: "#dfe4e0", type: "dashed" } },
      },
      series: [{
        type: "scatter",
        symbolSize: 20,
        data: x == null ? [] : [[x, yWaiting ? 4 : y]],
        itemStyle: {
          color: yWaiting ? "#a96f18" : "#167d73",
          borderColor: "#ffffff",
          borderWidth: 3,
          shadowBlur: 6,
          shadowColor: "rgba(20, 40, 34, 0.2)",
        },
        label: {
          show: true,
          position: "top",
          distance: 8,
          color: "#27332d",
          fontSize: 11,
          formatter: yWaiting ? "反转等待" : `当前 ${x}, ${y}`,
        },
        markArea: {
          silent: true,
          label: { color: "#6b756e", fontSize: 10, position: "insideTopLeft" },
          data: [
            [{ name: "尚未形成底部", xAxis: 0, yAxis: 0, itemStyle: { color: "#f8eeee" } }, { xAxis: 50, yAxis: 50 }],
            [{ name: "底部正在磨出", xAxis: 50, yAxis: 0, itemStyle: { color: "#fbf5e8" } }, { xAxis: 100, yAxis: 50 }],
            [{ name: "超跌反弹风险", xAxis: 0, yAxis: 50, itemStyle: { color: "#eef3f5" } }, { xAxis: 50, yAxis: 100 }],
            [{ name: "底部开始确认", xAxis: 50, yAxis: 50, itemStyle: { color: "#eaf4ef" } }, { xAxis: 100, yAxis: 100 }],
          ],
        },
      }],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [model, x, y]);

  return <div ref={containerRef} className="factor-quadrant" role="img" aria-label="长期底部环境与反转确认四象限" />;
}

function MetricCard({ label, value, subtext, trend, stale, icon: Icon = Gauge }) {
  const TrendIcon = trend > 0 ? TrendingUp : trend < 0 ? TrendingDown : null;
  return (
    <article className="metric-card">
      <div className="metric-card-heading">
        <Icon size={17} aria-hidden="true" />
        <span>{label}</span>
        {stale && <span className="stale-dot" title="该指标已过期" aria-label="已过期" />}
      </div>
      <div className="metric-value">{value}</div>
      <div className={`metric-subtext ${trend > 0 ? "positive" : trend < 0 ? "negative" : ""}`}>
        {TrendIcon && <TrendIcon size={14} aria-hidden="true" />}
        <span>{subtext || " "}</span>
      </div>
    </article>
  );
}

function ScoreCard({ title, value, label, components, tone, icon: Icon }) {
  return (
    <article className={`score-card score-${tone}`}>
      <div className="score-heading">
        <div>
          <span className="eyebrow">{title}</span>
          <strong>{label}</strong>
        </div>
        <Icon size={20} aria-hidden="true" />
      </div>
      <div className="score-value">
        {value === null || value === undefined ? <span className="score-wait">等待</span> : <><b>{value}</b><span>/100</span></>}
      </div>
      <div className="score-components">
        {components?.length ? components.map((component) => {
          const componentValue = component.score ?? component.value;
          const waiting = componentValue === null || componentValue === undefined;
          return (
            <div className="score-component" key={component.key} title={component.detail || ""}>
              <span>{component.label}</span>
              <div className="score-bar"><i style={{ width: `${waiting ? 0 : Math.max(0, Math.min(100, componentValue))}%` }} /></div>
              <b>{waiting ? "待" : componentValue}</b>
            </div>
          );
        }) : <p className="score-empty">评分组成项等待真实数据</p>}
      </div>
    </article>
  );
}

function SectionHeader({ title, meta }) {
  return (
    <div className="section-heading">
      <h2>{title}</h2>
      {meta && <span>{meta}</span>}
    </div>
  );
}

function Overview({ overview, priceSeries, mvrvSeries, qualityByMetric, cvddReference }) {
  const market = overview?.market || {};
  const cycle = overview?.cycle || {};
  const macro = overview?.macro || {};
  const mining = overview?.mining || {};
  const derivatives = overview?.derivatives || {};
  const options = overview?.options || {};
  const scores = overview?.scores || {};
  return (
    <>
      <section className="score-grid" aria-label="评分概览">
        <ScoreCard
          title="底部环境分"
          value={scores.environment?.value}
          label={scores.environment?.label || "数据不足"}
          components={scores.environment?.components}
          tone="amber"
          icon={ChartNoAxesCombined}
        />
        <ScoreCard
          title="BTC 长周期估值"
          value={scores.cycle?.value}
          label={scores.cycle?.label || "等待长期估值数据"}
          components={scores.cycle?.components}
          tone="teal"
          icon={Bitcoin}
        />
        <ScoreCard
          title="反转确认（短线参考）"
          value={scores.reversal?.value}
          label={scores.reversal?.label || "等待衍生品与成交数据"}
          components={scores.reversal?.components}
          tone="green"
          icon={Activity}
        />
        <ScoreCard
          title="数据可信度"
          value={scores.confidence?.value}
          label="公开数据覆盖与时效"
          components={scores.confidence?.components}
          tone="blue"
          icon={ShieldCheck}
        />
      </section>

      <section>
          <SectionHeader title="市场指标" meta={`市场共同观测日 ${formatDate(market.asOf)}`} />
        <div className="metric-grid market-grid">
          <MetricCard
            label="BTC 最新价格"
            value={market.price == null ? "暂无数据" : `$${formatNumber(market.price, { maximumFractionDigits: 0 })}`}
            subtext={`7 日 ${formatPercent(market.priceChange7d, true)}`}
            trend={market.priceChange7d}
            stale={qualityByMetric.PriceUSD?.stale}
            icon={Bitcoin}
          />
          <MetricCard label="30 日价格变化" value={formatPercent(market.priceChange30d, true)} subtext="基于日频收盘观测" trend={market.priceChange30d} stale={qualityByMetric.PriceUSD?.stale} />
          <MetricCard label="距历史高点回撤" value={formatPercent(market.drawdownFromHigh)} subtext="2016 年以来样本高点" trend={market.drawdownFromHigh} stale={qualityByMetric.PriceUSD?.stale} />
          <MetricCard label="30 日实现波动率" value={formatPercent(market.realizedVol30d)} subtext="日对数收益年化" stale={qualityByMetric.PriceUSD?.stale} />
          <MetricCard label="200 周均线" value={market.ma200w == null ? "暂无数据" : `$${formatNumber(market.ma200w, { maximumFractionDigits: 0 })}`} subtext={`现价距离 ${formatPercent(market.distanceTo200w, true)}`} trend={market.distanceTo200w} stale={qualityByMetric.PriceUSD?.stale} />
          <MetricCard label="MVRV" value={formatNumber(market.mvrv, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} subtext={`五年百分位 ${formatPercent(market.mvrvPercentile5y)}`} stale={qualityByMetric.CapMVRVCur?.stale} icon={Gauge} />
        </div>
      </section>

      <section>
        <SectionHeader title="BTC 长周期估值" meta={`共同观测日 ${formatDate(cycle.observedAt)}`} />
        <div className="metric-grid cycle-grid">
          <MetricCard
            label="已实现价格"
            value={cycle.realizedPrice == null ? "暂无数据" : `$${formatNumber(cycle.realizedPrice, { maximumFractionDigits: 0 })}`}
            subtext={`现价距离 ${formatPercent(cycle.distanceToRealizedPrice, true)}`}
            trend={cycle.distanceToRealizedPrice == null ? null : -cycle.distanceToRealizedPrice}
            stale={qualityByMetric.PriceUSD?.stale || qualityByMetric.CapMVRVCur?.stale}
            icon={Bitcoin}
          />
          <MetricCard
            label="NUPL（推导）"
            value={formatPercent(cycle.nupl)}
            subtext="由 MVRV 推导，不是独立数据源"
            trend={cycle.nupl == null ? null : -cycle.nupl}
            stale={qualityByMetric.CapMVRVCur?.stale}
            icon={Gauge}
          />
          <MetricCard
            label="Mayer Multiple"
            value={formatNumber(cycle.mayerMultiple, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            subtext={`五年百分位 ${formatPercent(cycle.mayerPercentile5y)}`}
            trend={cycle.mayerPercentile5y == null ? null : 50 - cycle.mayerPercentile5y}
            stale={qualityByMetric.PriceUSD?.stale}
            icon={ChartNoAxesCombined}
          />
          <MetricCard
            label="CVDD 第三方月度参考"
            value={cvddReference?.available ? `$${formatNumber(cvddReference.medianValueUsd, { maximumFractionDigits: 0 })}` : "等待录入"}
            subtext={cvddReference?.available ? `${cvddReference.sourceCount} 个来源中位数 · 差异 ${formatPercent(cvddReference.spreadPercent)}` : "在数据来源页录入公开网站读数"}
            stale={cvddReference?.available && cvddReference.stale}
            icon={Clock3}
          />
        </div>
        <p className="method-note">已实现价格 = BTC 价格 / MVRV；NUPL = 1 - 1 / MVRV，因此两者与 MVRV 属于同一链上证据，只在评分中合并计权一次。CVDD 卡片是人工核验后保存的第三方月度参考中位数，不等同于本项目从原始 CDD 复算，也不参与评分。</p>
      </section>

      <section>
        <SectionHeader title="矿工与金融压力" meta="长期观察 · 暂不参与评分" />
        <div className="metric-grid macro-grid">
          <MetricCard label="BTC 全网算力" value={mining.hashRate == null ? "暂无数据" : `${formatNumber(mining.hashRate, { maximumFractionDigits: 1 })} EH/s`} subtext={`30 日均值 ${mining.hashRate30d == null ? "等待历史" : `${formatNumber(mining.hashRate30d, { maximumFractionDigits: 1 })} EH/s`}`} stale={qualityByMetric.HashRate?.stale} icon={Pickaxe} />
          <MetricCard label="Hash Ribbons" value={mining.hashRibbonStatus === "capitulation" ? "矿工压力期" : mining.hashRibbonStatus === "recovery" ? "算力恢复期" : "等待数据"} subtext={`30D 相对 60D ${formatPercent(mining.hashRibbonSpread, true)}`} trend={mining.hashRibbonSpread} stale={qualityByMetric.HashRate?.stale} icon={Activity} />
          <MetricCard label="挖矿难度" value={mining.difficulty == null ? "暂无数据" : formatNumber(mining.difficulty, { notation: "compact", maximumFractionDigits: 2 })} subtext={`本次调整 ${formatPercent(mining.difficultyAdjustment, true)}`} trend={mining.difficultyAdjustment} stale={qualityByMetric.MiningDifficulty?.stale} icon={Gauge} />
          <MetricCard label="金融条件指数 NFCI" value={formatNumber(macro.financialConditions, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} subtext="正值趋紧，负值趋松" trend={macro.financialConditions == null ? null : -macro.financialConditions} stale={qualityByMetric.FinancialConditions?.stale} icon={ChartNoAxesCombined} />
          <MetricCard label="美国高收益债利差" value={macro.highYieldSpread == null ? "暂无数据" : `${formatNumber(macro.highYieldSpread, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`} subtext="FRED · BAMLH0A0HYM2" stale={qualityByMetric.HighYieldSpread?.stale} icon={Activity} />
          <MetricCard label="美国 10 年实际利率" value={macro.us10yReal == null ? "暂无数据" : `${formatNumber(macro.us10yReal, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`} subtext="FRED · DFII10" stale={qualityByMetric.US10YReal?.stale} icon={Gauge} />
        </div>
        <p className="method-note">Hash Ribbons 采用全网日均算力的 30 日与 60 日简单均线：30 日低于 60 日只标记矿工压力，高于则标记恢复。金融条件、信用利差和实际利率先作为独立观察量；完成历史回测前不改变底部环境分。</p>
      </section>

      <section className="chart-grid">
        <article className="chart-panel">
          <SectionHeader title="BTC 价格" meta="USD · 日频" />
          <LineChart data={priceSeries} color="#167d73" name="BTC 价格" unit=" USD" />
        </article>
        <article className="chart-panel">
          <SectionHeader title="MVRV" meta="五年视窗" />
          <LineChart data={mvrvSeries} color="#b7791f" name="MVRV" unit="" referenceLine={{ value: 1, label: "1.0" }} />
        </article>
      </section>

      <details className="short-cycle-details">
        <summary className="short-cycle-summary">
          <span>
            <strong>短周期确认</strong>
            <small>Deribit 单一市场 · 13 项 · 默认收起</small>
          </span>
          <ChevronDown aria-hidden="true" size={19} />
        </summary>
        <div className="short-cycle-content">
          <section>
            <SectionHeader title="衍生品与成交参考" meta="Deribit 单一市场 · 不参与长期宏观结论" />
            <div className="metric-grid derivatives-grid">
          <MetricCard
            label="8 小时资金费率"
            value={derivatives.fundingRate8h == null ? "暂无数据" : `${formatNumber(derivatives.fundingRate8h, { minimumFractionDigits: 4, maximumFractionDigits: 4 })}%`}
            subtext={`30 日百分位 ${formatPercent(derivatives.fundingPercentile30d)}`}
            trend={derivatives.fundingRate8h == null ? null : -derivatives.fundingRate8h}
            stale={qualityByMetric.FundingRate8h?.stale}
            icon={Activity}
          />
          <MetricCard
            label="未平仓量（OI）"
            value={formatCompactUsd(derivatives.openInterestUsd)}
            subtext={derivatives.openInterestChange7d == null ? "Deribit USD 名义值 · 7 日变化等待积累" : `Deribit USD 名义值 · 7 日变化 ${formatPercent(derivatives.openInterestChange7d, true)}`}
            trend={derivatives.openInterestChange7d}
            stale={qualityByMetric.OpenInterestUSD?.stale}
            icon={Gauge}
          />
          <MetricCard
            label="近期成交量差（CVD）"
            value={formatCompactUsd(derivatives.tradeCvdUsd, true)}
            subtext={derivatives.tradeCount == null ? "暂无真实数据" : `${formatNumber(derivatives.tradeCount)} 笔 · 买卖差 ${formatPercent(derivatives.tradeFlowImbalance, true)}`}
            trend={derivatives.tradeFlowImbalance}
            stale={qualityByMetric.TradeCVDUSD?.stale}
            icon={TrendingUp}
          />
          <MetricCard
            label="25 bps 订单簿失衡"
            value={formatPercent(derivatives.orderBookImbalance, true)}
            subtext={derivatives.spreadBps == null ? "暂无真实数据" : `中间价固定距离 · 点差 ${formatNumber(derivatives.spreadBps, { maximumFractionDigits: 2 })} bps`}
            trend={derivatives.orderBookImbalance}
            stale={qualityByMetric.OrderBookImbalance25bps?.stale}
            icon={Database}
          />
            </div>
            <p className="method-note">CVD 为 Deribit 最近 1,000 笔 BTC 永续主动成交的滚动美元量差，时间窗随成交活跃度变化，不代表全市场长期 CVD。订单簿以中间价上下 10/25/50/100 bps 固定距离聚合，主指标使用 25 bps；这些只作短周期单一市场线索，不参与宏观长期结论。</p>
          </section>

          <section>
            <SectionHeader title="期权压力与偏斜" meta="Deribit BTC options · 固定期限" />
            <div className="metric-grid options-grid">
          <MetricCard label="7 天平值 IV" value={formatPercent(options.atmIv7d)} subtext={`7D-30D 斜率 ${formatPercent(options.termSlope7d30d, true)}`} trend={options.termSlope7d30d} stale={qualityByMetric.ATMIV7D?.stale} icon={Activity} />
          <MetricCard label="30 天平值 IV" value={formatPercent(options.atmIv30d)} subtext={options.ivMinusRealizedVol30d == null ? "等待实际波动率" : `高于实际波动 ${formatNumber(options.ivMinusRealizedVol30d, { maximumFractionDigits: 1 })} 点`} stale={qualityByMetric.ATMIV30D?.stale} icon={Gauge} />
          <MetricCard label="90 天平值 IV" value={formatPercent(options.atmIv90d)} subtext={`30D-90D 斜率 ${formatPercent(options.termSlope30d90d, true)}`} trend={options.termSlope30d90d} stale={qualityByMetric.ATMIV90D?.stale} icon={Activity} />
          <MetricCard label="30 天 25Delta RR" value={options.rr25_30d == null ? "暂无数据" : `${formatNumber(options.rr25_30d, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} vol`} subtext={options.rr25Change24h == null ? "24 小时变化等待积累" : `24 小时 ${formatNumber(options.rr25Change24h, { maximumFractionDigits: 2 })} vol`} trend={options.rr25_30d} stale={qualityByMetric.RR25_30D?.stale} icon={TrendingUp} />
          <MetricCard label="30 天 25Delta BF" value={options.bf25_30d == null ? "暂无数据" : `${formatNumber(options.bf25_30d, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} vol`} subtext="两翼平均 IV 相对平值 IV" trend={options.bf25_30d} stale={qualityByMetric.BF25_30D?.stale} icon={ChartNoAxesCombined} />
          <MetricCard label="偏斜修复状态" value={options.rr25Change24h == null ? "等待 24 小时" : formatNumber(options.rr25Change24h, { maximumFractionDigits: 2 })} subtext="RR25 上升代表看跌保护溢价缓和" trend={options.rr25Change24h} stale={qualityByMetric.RR25_30D?.stale} icon={ShieldCheck} />
            </div>
            <p className="method-note">RR25 = 25Δ Call IV - 25Δ Put IV，负值表示看跌保护更贵；BF25 = 两翼平均 IV - ATM IV。7/30/90 天指标使用相邻到期日总方差插值，避免换月跳变。当前使用 Deribit 标记 IV，只代表该市场，不直接作为见底结论。</p>
          </section>
        </div>
      </details>

      <section>
          <SectionHeader title="宏观流动性" meta={`净流动性共同观测日 ${formatDate(macro.netLiquidityObservedAt)} · 辅助序列独立标注`} />
        <div className="metric-grid macro-grid">
          <MetricCard label="TGA 当前余额" value={macro.tga == null ? "暂无数据" : `$${formatNumber(macro.tga / 1000, { maximumFractionDigits: 1 })}B`} subtext={`7 日变化 ${macro.tgaChange7d == null ? "暂无数据" : formatSignedBillions(macro.tgaChange7d / 1000)}`} trend={macro.tgaChange7d == null ? null : -macro.tgaChange7d} stale={qualityByMetric.TGA?.stale} icon={Database} />
          <MetricCard label="净流动性近似值" value={macro.netLiquidity == null ? "暂无数据" : `$${formatNumber(macro.netLiquidity, { maximumFractionDigits: 1 })}B`} subtext={`30 日变化 ${formatSignedBillions(macro.netLiquidityChange30d)}`} trend={macro.netLiquidityChange30d} stale={qualityByMetric.FedAssets?.stale || qualityByMetric.TGA?.stale || qualityByMetric.OvernightRRP?.stale} icon={ChartNoAxesCombined} />
          <MetricCard label="美国 10 年期收益率" value={macro.us10y == null ? "暂无数据" : `${formatNumber(macro.us10y, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`} subtext="FRED · DGS10" stale={qualityByMetric.US10Y?.stale} icon={Activity} />
          <MetricCard label="广义美元指数" value={formatNumber(macro.broadDollar, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} subtext="FRED · DTWEXBGS" stale={qualityByMetric.BroadDollar?.stale} icon={Gauge} />
          <MetricCard label="美国 M2 货币供应量" value={macro.usM2 == null ? "暂无数据" : `$${formatNumber(macro.usM2 / 1000, { maximumFractionDigits: 2 })}T`} subtext={`12 个月变化 ${formatPercent(macro.usM2Change12m, true)} · FRED M2SL`} trend={macro.usM2Change12m} stale={qualityByMetric.USM2?.stale} icon={ChartNoAxesCombined} />
          <MetricCard label="全链稳定币供应量" value={macro.stablecoinSupplyUsd == null ? "暂无数据" : `$${formatNumber(macro.stablecoinSupplyUsd / 1e9, { maximumFractionDigits: 1 })}B`} subtext={`30 日变化 ${formatPercent(macro.stablecoinSupplyChange30d, true)} · DefiLlama`} trend={macro.stablecoinSupplyChange30d} stale={qualityByMetric.StablecoinSupplyUSD?.stale} icon={Database} />
          <MetricCard label="恐惧贪婪指数" value={macro.fearGreed == null ? "暂无数据" : `${formatNumber(macro.fearGreed, { maximumFractionDigits: 0 })}/100`} subtext={`${macro.fearGreedClassification || "等待分类"} · Alternative.me`} trend={macro.fearGreed == null ? null : 50 - macro.fearGreed} stale={qualityByMetric.FearGreedIndex?.stale} icon={Activity} />
        </div>
        <p className="method-note">净流动性近似值 = 美联储总资产 / 1000 - TGA / 1000 - 隔夜逆回购，单位为十亿美元。该指标是研究近似值，不代表精确流动性。</p>
      </section>
    </>
  );
}

function FactorBucket({ bucket }) {
  return (
    <article className="factor-bucket">
      <div className="factor-bucket-head">
        <div><span>{bucket.label}</span><small>模型权重 {bucket.weight}% · 覆盖 {bucket.coverage}%</small></div>
        <strong>{bucket.score == null ? "等待" : bucket.score}</strong>
      </div>
      <div className="factor-bucket-bar"><i style={{ width: `${bucket.score || 0}%` }} /></div>
      <div className="factor-components-list">
        {bucket.components?.map((component) => (
          <div key={component.key} title={component.detail || ""}>
            <span>{component.label}</span>
            <small>{component.weight}%</small>
            <b>{component.score == null ? "待" : component.score}</b>
          </div>
        ))}
      </div>
    </article>
  );
}

function FactorModelView({ overview }) {
  const model = overview?.factorModel || {};
  const longTerm = model.longTerm || {};
  const reversal = model.reversal || {};
  return (
    <>
      <section>
        <SectionHeader title="底部因子模型" meta="实验版 · 同源去重 · 缺失不计零分" />
        <div className="factor-summary-grid">
          <article className="factor-map-panel">
            <FactorQuadrant model={model} />
          </article>
          <aside className="factor-readout">
            <div className="factor-readout-row">
              <span>长期底部环境</span>
              <strong>{longTerm.value == null ? "等待" : `${longTerm.value}/100`}</strong>
              <small>{longTerm.label || "数据不足"} · 覆盖 {longTerm.coverage || 0}%</small>
            </div>
            <div className="factor-readout-row">
              <span>反转确认</span>
              <strong>{reversal.value == null ? "等待" : `${reversal.value}/100`}</strong>
              <small>{reversal.label || "等待有效数据"} · 覆盖 {reversal.coverage || 0}%</small>
            </div>
            <div className="factor-readout-row">
              <span>数据可信度</span>
              <strong>{model.confidence == null ? "等待" : `${model.confidence}/100`}</strong>
              <small>只表示数据覆盖与时效，不改变市场方向</small>
            </div>
          </aside>
        </div>
      </section>

      <section>
        <SectionHeader title="长期底部环境" meta="链上估值 45% · 价格周期 25% · 宏观环境 30%" />
        <div className="factor-bucket-grid">
          {(longTerm.buckets || []).map((bucket) => <FactorBucket key={bucket.key} bucket={bucket} />)}
        </div>
      </section>

      <section>
        <SectionHeader title="相对中性值的贡献" meta="正值推高底部环境，负值压低" />
        <div className="contribution-panel">
          {(longTerm.contributions || []).map((item) => {
            const waiting = item.points == null;
            const width = waiting ? 0 : Math.min(50, Math.abs(item.points)) * 2;
            return (
              <div className="contribution-row" key={item.key}>
                <span>{item.label}<small>有效权重 {item.effectiveWeight == null ? "待" : `${item.effectiveWeight}%`}</small></span>
                <div className="contribution-track">
                  {!waiting && <i className={item.points >= 0 ? "contribution-positive" : "contribution-negative"} style={{ width: `${width}%` }} />}
                </div>
                <b>{waiting ? "待" : `${item.points > 0 ? "+" : ""}${item.points}`}</b>
              </div>
            );
          })}
        </div>
      </section>

      <section>
        <SectionHeader title="短周期市场线索" meta="Deribit 单一市场 · 与长期环境分开解读" />
        <div className="factor-bucket-grid reversal-bucket-grid">
          {(reversal.buckets || []).map((bucket) => <FactorBucket key={bucket.key} bucket={bucket} />)}
        </div>
      </section>

      <section>
        <SectionHeader title="指标关系" meta="长期宏观/链上方向参考 · Spearman 排名相关" />
        <div className="correlation-panel">
          {(model.correlations || []).map((item) => {
            const strength = item.value == null ? 0 : Math.min(1, Math.abs(item.value));
            return (
              <article className="correlation-row" key={item.key}>
                <div><strong>{item.left}</strong><span>与</span><strong>{item.right}</strong></div>
                <div className="correlation-meter"><i className={(item.value || 0) < 0 ? "negative" : "positive"} style={{ width: `${strength * 100}%` }} /></div>
                <b>{item.value == null ? "样本不足" : item.value.toFixed(2)}</b>
                <small>{item.note} · {formatNumber(item.samples || 0)} 个样本</small>
              </article>
            );
          })}
        </div>
      </section>

      <section className="factor-method">
        <SectionHeader title="模型约束" meta={model.version || "实验规则"} />
        <div className="factor-notes">
          {(model.notes || []).map((note) => <p key={note}>{note}</p>)}
        </div>
      </section>
    </>
  );
}

function QualityTable({ items, values }) {
  return (
    <div className="table-panel">
      <table className="data-table quality-table">
        <thead><tr><th>指标</th><th>当前值</th><th>频率</th><th>最新观测</th><th>年龄</th><th>状态</th></tr></thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.metric}>
              <td data-label="指标"><strong>{METRIC_LABELS[item.metric] || item.metric}</strong><small>{item.metric}</small></td>
              <td data-label="当前值">{values[item.metric]}</td>
              <td data-label="频率">{FREQUENCY_LABELS[item.frequency] || item.frequency}</td>
              <td data-label="最新观测">{formatDate(item.observedAt)}</td>
              <td data-label="年龄">{formatAge(item.ageDays)}</td>
              <td data-label="状态"><Status status={["retired", "paused", "error", "partial"].includes(item.refreshStatus) ? item.refreshStatus : item.available ? "ok" : "never"} stale={item.available && item.stale} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MetricsView({ overview }) {
  const market = overview?.market || {};
  const cycle = overview?.cycle || {};
  const macro = overview?.macro || {};
  const mining = overview?.mining || {};
  const derivatives = overview?.derivatives || {};
  const options = overview?.options || {};
  const values = {
    PriceUSD: market.price == null ? "暂无数据" : `$${formatNumber(market.price, { maximumFractionDigits: 0 })}`,
    CapMVRVCur: formatNumber(market.mvrv, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    CoinDaysDestroyed: "用于 CVDD 近似值",
    BlockchainPriceUSD: "与 CDD 同源对齐",
    TGA: macro.tga == null ? "暂无数据" : `$${formatNumber(macro.tga / 1000, { maximumFractionDigits: 1 })}B`,
    FedAssets: macro.netLiquidity == null ? "参与近似值" : "已参与计算",
    OvernightRRP: macro.netLiquidity == null ? "暂无数据" : "已参与计算",
    US10Y: macro.us10y == null ? "暂无数据" : `${formatNumber(macro.us10y, { maximumFractionDigits: 2 })}%`,
    BroadDollar: formatNumber(macro.broadDollar, { maximumFractionDigits: 2 }),
    FinancialConditions: formatNumber(macro.financialConditions, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    HighYieldSpread: macro.highYieldSpread == null ? "暂无数据" : `${formatNumber(macro.highYieldSpread, { maximumFractionDigits: 2 })}%`,
    US10YReal: macro.us10yReal == null ? "暂无数据" : `${formatNumber(macro.us10yReal, { maximumFractionDigits: 2 })}%`,
    USM2: macro.usM2 == null ? "暂无数据" : `$${formatNumber(macro.usM2 / 1000, { maximumFractionDigits: 2 })}T`,
    StablecoinSupplyUSD: macro.stablecoinSupplyUsd == null ? "暂无数据" : `$${formatNumber(macro.stablecoinSupplyUsd / 1e9, { maximumFractionDigits: 1 })}B`,
    FearGreedIndex: macro.fearGreed == null ? "暂无数据" : `${formatNumber(macro.fearGreed, { maximumFractionDigits: 0 })}/100`,
    HashRate: mining.hashRate == null ? "暂无数据" : `${formatNumber(mining.hashRate, { maximumFractionDigits: 1 })} EH/s`,
    MiningDifficulty: formatNumber(mining.difficulty, { notation: "compact", maximumFractionDigits: 2 }),
    FundingRate8h: derivatives.fundingRate8h == null ? "暂无数据" : `${formatNumber(derivatives.fundingRate8h, { minimumFractionDigits: 4, maximumFractionDigits: 4 })}%`,
    OpenInterestUSD: formatCompactUsd(derivatives.openInterestUsd),
    TradeCVDUSD: formatCompactUsd(derivatives.tradeCvdUsd, true),
    OrderBookImbalance25bps: formatPercent(derivatives.orderBookImbalance, true),
    ATMIV7D: formatPercent(options.atmIv7d),
    ATMIV30D: formatPercent(options.atmIv30d),
    ATMIV90D: formatPercent(options.atmIv90d),
    RR25_7D: options.rr25_7d == null ? "暂无数据" : `${formatNumber(options.rr25_7d, { maximumFractionDigits: 2 })} vol`,
    RR25_30D: options.rr25_30d == null ? "暂无数据" : `${formatNumber(options.rr25_30d, { maximumFractionDigits: 2 })} vol`,
    RR25_90D: options.rr25_90d == null ? "暂无数据" : `${formatNumber(options.rr25_90d, { maximumFractionDigits: 2 })} vol`,
    BF25_30D: options.bf25_30d == null ? "暂无数据" : `${formatNumber(options.bf25_30d, { maximumFractionDigits: 2 })} vol`,
    IVTermSlope7D30D: options.termSlope7d30d == null ? "暂无数据" : `${formatNumber(options.termSlope7d30d, { maximumFractionDigits: 2 })} vol`,
    IVTermSlope30D90D: options.termSlope30d90d == null ? "暂无数据" : `${formatNumber(options.termSlope30d90d, { maximumFractionDigits: 2 })} vol`,
  };
  const qualityItems = overview?.dataQuality || [];
  const primaryItems = qualityItems.filter((item) => !SHORT_CYCLE_METRICS.has(item.metric));
  const shortCycleItems = qualityItems.filter((item) => SHORT_CYCLE_METRICS.has(item.metric));
  const primaryAvailable = primaryItems.filter((item) => item.available).length;
  const shortCycleAvailable = shortCycleItems.filter((item) => item.available).length;
  const shortCycleStale = shortCycleItems.filter((item) => item.available && item.stale).length;
  return (
    <section>
      <SectionHeader title="长期与宏观指标" meta={`${primaryAvailable} / ${primaryItems.length} 项有真实数据`} />
      <QualityTable items={primaryItems} values={values} />
      {shortCycleItems.length > 0 && (
        <details className="short-cycle-details metrics-short-cycle">
          <summary className="short-cycle-summary">
            <span>
              <strong>短周期市场指标</strong>
              <small>Deribit 单一市场 · {shortCycleAvailable}/{shortCycleItems.length} 项有历史缓存{shortCycleStale ? ` · ${shortCycleStale} 项已过期` : ""} · 默认收起</small>
            </span>
            <ChevronDown aria-hidden="true" size={19} />
          </summary>
          <div className="short-cycle-content">
            <p className="short-cycle-intro">宏观长期模式暂停自动刷新。以下数据只用于反转确认研究，不参与长期底部环境分；旧真实缓存会保留并明确标记时效。</p>
            <QualityTable items={shortCycleItems} values={values} />
          </div>
        </details>
      )}
      <div className="metric-definitions">
        <h3>计算口径</h3>
        <dl>
          <div><dt>200 周均线</dt><dd>最近 1,400 个日频 BTC 价格观测的算术平均。</dd></div>
          <div><dt>30 日实现波动率</dt><dd>最近 30 个日对数收益率的样本标准差，按 365 天年化。</dd></div>
          <div><dt>MVRV 五年百分位</dt><dd>当前 MVRV 在最近五年日频样本中的经验百分位。</dd></div>
          <div><dt>已实现价格</dt><dd>使用同日 Coin Metrics 价格除以 MVRV 推导；它与 NUPL、MVRV 是同源证据，不重复计权。</dd></div>
          <div><dt>NUPL（推导）</dt><dd><code>1 - 1 / MVRV</code>，页面以百分比显示；不是额外采集的独立链上序列。</dd></div>
          <div><dt>Mayer Multiple</dt><dd>BTC 价格除以最近 200 个日频价格观测的均值，并以五年滚动百分位参与长周期估值。</dd></div>
          <div><dt>CVDD 与月度参考</dt><dd>原始 CDD 复算仍因公开端点退役而等待；数据来源页可人工保存多个公开网站的月度 CVDD 读数，首页只显示当月中位数和来源差异，不参与评分。</dd></div>
          <div><dt>稳定币供应量</dt><dd>DefiLlama 全链稳定币总流通量，作为加密原生流动性辅助观察；不与美联储/TGA/RRP 净流动性近似值拼接，也暂不参与评分。</dd></div>
          <div><dt>美国 M2</dt><dd>FRED M2SL 月频货币供应量，原始单位十亿美元；页面换算为万亿美元并显示 12 个月变化。发布存在滞后，暂不参与评分。</dd></div>
          <div><dt>恐惧贪婪指数</dt><dd>Alternative.me 0-100 日频情绪指数，作为周期情绪辅助观察；不等同于底部概率，也暂不参与评分。</dd></div>
          <div><dt>Hash Ribbons</dt><dd>mempool.space 全网日均算力的 30 日均线与 60 日均线比较，只展示压力/恢复状态；未回测前不参与评分。</dd></div>
          <div><dt>金融压力</dt><dd>NFCI、美国高收益债期权调整利差和 10 年实际利率均来自 FRED，用于区分流动性宽松与信用压力，暂不参与评分。</dd></div>
          <div><dt>近期成交量差（CVD）</dt><dd>Deribit BTC-PERPETUAL 最近 1,000 笔主动成交的买方美元量减卖方美元量，时间窗随成交活跃度变化；这是单一市场短周期线索。</dd></div>
          <div><dt>固定距离订单簿</dt><dd>按中间价上下 10/25/50/100 bps 汇总美元深度，主指标使用 25 bps；只展示当前快照，不作为长期底部证据。</dd></div>
          <div><dt>ATM IV 与期限结构</dt><dd>Deribit 标记隐含波动率按相邻到期日总方差插值为固定 7/30/90 天期限，短减长为期限斜率。</dd></div>
          <div><dt>25Delta RR / BF</dt><dd>RR25 为 25Δ Call IV 减 25Δ Put IV；BF25 为两翼平均 IV 减 ATM IV。当前过滤无报价、零 OI 和相对价差超过 100% 的合约，仍属于 Deribit 25Delta 近似值。</dd></div>
          <div><dt>反转确认分</dt><dd>资金费率、OI、主动成交、25 bps 盘口与 25Δ 偏斜修复组成；它们只代表 Deribit 单一市场短周期线索，等待项不伪造分值并显示实际覆盖度。</dd></div>
          <div><dt>BTC 长周期估值</dt><dd>MVRV/NUPL、Mayer Multiple 与 CVDD 近似值按独立证据分组；CVDD 数据不足时显示等待，不参与平均。</dd></div>
          <div><dt>数据可信度</dt><dd>当前长期主线启用指标的可用性 40%、观测新鲜度 25%、数据频率 10%、缓存未过期比例 25%。已退役 CDD 与宏观模式暂停的 Deribit 不扣分；分数只评价数据状态，不代表方向正确。</dd></div>
        </dl>
      </div>
    </section>
  );
}

function CvddReferencePanel({ reference, onSaved }) {
  const localWriteAllowed = ["127.0.0.1", "::1", "[::1]", "localhost"].includes(window.location.hostname);
  const [form, setForm] = useState({
    sourceName: "",
    sourceUrl: "",
    observedDate: new Date().toISOString().slice(0, 10),
    valueUsd: "",
    note: "",
  });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    if (!localWriteAllowed) {
      setMessage({ type: "error", text: "为避免局域网误写，请在本机地址打开页面后录入。" });
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      const result = await requestJson("/api/references/cvdd", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_name: form.sourceName,
          source_url: form.sourceUrl,
          observed_date: form.observedDate,
          value_usd: Number(form.valueUsd),
          note: form.note || null,
        }),
      });
      setMessage({ type: "ok", text: "月度参考值已保存；同一来源同一月份再次录入会更新原记录。" });
      setForm((current) => ({ ...current, valueUsd: "", note: "" }));
      onSaved(result.summary);
    } catch (saveError) {
      setMessage({ type: "error", text: `保存失败：${saveError.message}` });
    } finally {
      setSaving(false);
    }
  };

  const agreementLabel = {
    waiting: "等待数据",
    single_source: "单一来源，仅供参考",
    close: "多来源接近",
    mixed: "来源存在差异",
    divergent: "来源差异较大",
  }[reference?.agreement] || "等待数据";

  return (
    <section className="cvdd-reference-panel">
      <SectionHeader title="CVDD 第三方月度参考" meta="人工核验录入 · 多来源取中位数 · 不参与评分" />
      <div className="cvdd-reference-layout">
        <div className="cvdd-reference-summary">
          <div className="cvdd-reference-value">
            <span>最新月度中位数</span>
            <strong>{reference?.available ? `$${formatNumber(reference.medianValueUsd, { maximumFractionDigits: 0 })}` : "暂无数据"}</strong>
            <small>{reference?.available ? `${formatDate(reference.latestObservedAt)} · ${reference.sourceCount} 个来源` : "至少录入一个公开来源"}</small>
          </div>
          <div className="cvdd-reference-facts">
            <div><span>来源一致性</span><strong>{agreementLabel}</strong></div>
            <div><span>最大差异</span><strong>{formatPercent(reference?.spreadPercent)}</strong></div>
            <div><span>下次核验</span><strong>{formatDate(reference?.nextReviewAt)}</strong></div>
          </div>
          <div className="cvdd-reference-sources">
            {(reference?.sources || []).map((item) => (
              <a key={`${item.sourceName}-${item.observedMonth}`} href={item.sourceUrl} target="_blank" rel="noreferrer">
                <span>{item.sourceName}</span><strong>${formatNumber(item.valueUsd, { maximumFractionDigits: 0 })}</strong><ExternalLink size={12} />
              </a>
            ))}
            {!reference?.sources?.length && <p>尚未保存第三方 CVDD 月度读数。</p>}
          </div>
        </div>
        <form className="cvdd-reference-form" onSubmit={submit}>
          {!localWriteAllowed && <p className="cvdd-local-only"><ShieldCheck size={15} />局域网访问仅可查看；请在本机打开 http://127.0.0.1:实际端口 后录入。</p>}
          <label><span>来源名称</span><input required maxLength="100" value={form.sourceName} onChange={(event) => setForm({ ...form, sourceName: event.target.value })} placeholder="例如：CoinGlass" /></label>
          <label><span>公开页面地址</span><input required type="url" maxLength="500" value={form.sourceUrl} onChange={(event) => setForm({ ...form, sourceUrl: event.target.value })} placeholder="https://..." /></label>
          <div className="cvdd-form-row">
            <label><span>页面观测日期</span><input required type="date" value={form.observedDate} onChange={(event) => setForm({ ...form, observedDate: event.target.value })} /></label>
            <label><span>CVDD（USD）</span><input required type="number" min="1" max="10000000" step="0.01" value={form.valueUsd} onChange={(event) => setForm({ ...form, valueUsd: event.target.value })} placeholder="例如 45000" /></label>
          </div>
          <label><span>口径备注（可选）</span><input maxLength="500" value={form.note} onChange={(event) => setForm({ ...form, note: event.target.value })} placeholder="图表名称、读取时间或差异说明" /></label>
          <button type="submit" className="cvdd-save-button" disabled={saving || !localWriteAllowed}><Save size={15} />{saving ? "保存中" : localWriteAllowed ? "保存月度读数" : "仅限本机录入"}</button>
          {message && <p className={`cvdd-form-message ${message.type}`}>{message.text}</p>}
          <p className="cvdd-form-help">请只录入公开页面中实际看到的数值，并保留页面地址。系统不会自动把它当作原始链上复算结果。</p>
        </form>
      </div>
    </section>
  );
}

function SourcesView({ sources, cvddReference, onCvddSaved }) {
  return (
    <section>
      <CvddReferencePanel reference={cvddReference} onSaved={onCvddSaved} />
      <SectionHeader title="公开数据来源" meta="仅使用无需付费 API Key 的来源" />
      <div className="source-list">
        {(sources?.sources || []).map((source) => (
          <article className="source-card" key={source.id}>
            <div className="source-main">
              <div className="source-title-row">
                <h3>{source.name}</h3>
                <Status status={source.refresh?.status || "never"} />
              </div>
              <p>{source.description}</p>
              <a href={source.url} target="_blank" rel="noreferrer">访问来源 <ExternalLink size={13} aria-hidden="true" /></a>
              <span className="license">许可/条款：{source.license}</span>
            </div>
            <div className="source-stats">
              <div><span>最近刷新</span><strong>{formatDate(source.refresh?.finishedAt, true)}</strong></div>
              <div><span>写入行数（新增/修订）</span><strong>{formatNumber(source.refresh?.rowsWritten, { maximumFractionDigits: 0 })}</strong></div>
              <div><span>覆盖指标</span><strong>{source.metrics?.map((item) => METRIC_LABELS[item.metric] || item.metric).join("、") || "暂无"}</strong></div>
            </div>
            {source.refresh?.error && <p className="source-error" title={source.refresh.error}>{humanizeRefreshError(source.refresh.error)}</p>}
            {!source.active && source.note && <p className="source-error">该端点已停止主动刷新；旧真实缓存不会删除。</p>}
            {source.active && !source.enabled && <p className="source-error">宏观长期模式已暂停该短周期来源；旧真实缓存仍保留并标记时效。</p>}
          </article>
        ))}
        {!sources?.sources?.length && <div className="empty-panel">尚无来源刷新记录</div>}
      </div>
    </section>
  );
}

function SystemView({ health, refreshHistory }) {
  const runtime = health?.runtime || {};
  const refresh = health?.refresh || {};
  const scheduler = health?.scheduler || {};
  const archive = health?.archive || {};
  const overviewCache = health?.overviewCache || {};
  const historyRuns = refreshHistory?.runs || [];
  const consecutiveFailures = refreshHistory?.consecutiveFailures || [];
  const rows = [
    { icon: Wifi, label: "当前访问地址", value: window.location.origin },
    { icon: Server, label: "本机地址", value: runtime.localUrl || "暂无" },
    { icon: Wifi, label: "局域网地址", value: runtime.lanUrl || "未检测到" },
    { icon: Gauge, label: "实际监听端口", value: runtime.port || "暂无" },
    { icon: HardDrive, label: "DuckDB 路径", value: health?.database || "暂无" },
    { icon: RefreshCw, label: "刷新状态", value: STATUS_LABELS[refresh.status] || refresh.status || "未知" },
    { icon: Gauge, label: "总览预计算缓存", value: `${overviewCache.status === "ready" ? "正常" : overviewCache.status === "degraded" ? "使用上次缓存" : overviewCache.status === "error" ? "计算失败" : "尚未生成"}${overviewCache.ageSeconds !== null && overviewCache.ageSeconds !== undefined ? ` · ${formatDuration(overviewCache.ageSeconds)}前` : ""}` },
    { icon: Timer, label: "Deribit 自动刷新", value: scheduler.nextFastAt ? formatDate(scheduler.nextFastAt, true) : "宏观模式已暂停" },
    { icon: Timer, label: "下次慢速来源刷新", value: formatDate(scheduler.nextSlowAt, true) },
    { icon: Archive, label: "Parquet 归档", value: `${STATUS_LABELS[archive.status] || archive.status || "尚未运行"} · ${formatNumber(archive.filesWritten || 0)} 个文件` },
    { icon: HardDrive, label: "Parquet 路径", value: archive.path || "暂无" },
    { icon: Database, label: "可用指标", value: `${health?.metrics?.length || 0} 项` },
  ];
  return (
    <section>
      <SectionHeader title="系统状态" meta="本地单端口服务" />
      <div className="system-panel">
        {rows.map(({ icon: Icon, label, value }) => (
          <div className="system-row" key={label}>
            <Icon size={18} aria-hidden="true" />
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      <section className="system-history-section">
        <SectionHeader title="最近刷新历史" meta={`最近 ${historyRuns.length || 0}/20 轮`} />
        {consecutiveFailures.length > 0 && (
          <div className="failure-streaks" aria-label="来源连续失败次数">
            <strong>来源连续失败</strong>
            <div>
              {consecutiveFailures.map((item) => (
                <span key={item.source} title={item.error || ""}>
                  {SOURCE_LABELS[item.source] || item.source} · {item.count} 次
                </span>
              ))}
            </div>
          </div>
        )}
        <div className="table-panel refresh-history-panel">
          {historyRuns.length > 0 ? (
            <div className="table-scroll">
              <table className="data-table refresh-history-table">
                <thead>
                  <tr><th>开始时间</th><th>结果</th><th>来源</th><th>写入</th><th>耗时</th><th>失败来源</th></tr>
                </thead>
                <tbody>
                  {historyRuns.map((run) => {
                    const failedSources = (run.sources || []).filter((source) => source.status !== "ok");
                    return (
                      <tr key={run.startedAt}>
                        <td>{formatDate(run.startedAt, true)}</td>
                        <td><Status status={run.status} /></td>
                        <td>{run.okCount}/{run.sourceCount} 成功</td>
                        <td>{formatNumber(run.rowsWritten, { maximumFractionDigits: 0 })}</td>
                        <td>{formatDuration(run.durationSeconds)}</td>
                        <td>
                          {failedSources.length ? (
                            <span className="refresh-history-errors" title={failedSources.map((source) => `${SOURCE_LABELS[source.source] || source.source}: ${source.error || source.status}`).join("\n")}>
                              {failedSources.map((source) => SOURCE_LABELS[source.source] || source.source).join("、")}
                              <small>{humanizeRefreshError(failedSources[0].error)}</small>
                            </span>
                          ) : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : <div className="empty-panel compact-empty"><History size={18} />尚无完整刷新记录</div>}
        </div>
      </section>
      <div className="privacy-note">
        <ShieldCheck size={19} aria-hidden="true" />
        <p>服务默认监听局域网，但不会配置路由器端口转发，也不会主动暴露到公网。远程访问可另行使用 Tailscale 私有网络。</p>
      </div>
    </section>
  );
}

export default function App() {
  const [activeView, setActiveView] = useState("overview");
  const [overview, setOverview] = useState(null);
  const [sources, setSources] = useState(null);
  const [health, setHealth] = useState(null);
  const [priceSeries, setPriceSeries] = useState([]);
  const [mvrvSeries, setMvrvSeries] = useState([]);
  const [cvddReference, setCvddReference] = useState(null);
  const [refreshHistory, setRefreshHistory] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadDashboard = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    const results = await Promise.allSettled([
      requestJson("/api/overview"),
      requestJson("/api/sources"),
      requestJson("/api/health"),
      requestJson("/api/series/PriceUSD?limit=1825"),
      requestJson("/api/series/CapMVRVCur?limit=1825"),
      requestJson("/api/references/cvdd"),
      requestJson("/api/refresh-history?limit=20"),
    ]);
    const [overviewResult, sourcesResult, healthResult, priceResult, mvrvResult, cvddResult, refreshHistoryResult] = results;
    const coreFailures = [overviewResult, sourcesResult, healthResult].filter((result) => result.status === "rejected");
    if (overviewResult.status === "fulfilled") setOverview(overviewResult.value);
    if (sourcesResult.status === "fulfilled") setSources(sourcesResult.value);
    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    setPriceSeries(priceResult.status === "fulfilled" ? priceResult.value.data : []);
    setMvrvSeries(mvrvResult.status === "fulfilled" ? mvrvResult.value.data : []);
    if (cvddResult.status === "fulfilled") setCvddReference(cvddResult.value);
    if (refreshHistoryResult.status === "fulfilled") setRefreshHistory(refreshHistoryResult.value);
    setError(coreFailures.length ? coreFailures[0].reason.message : null);
    setLoading(false);
  }, []);

  useEffect(() => {
    loadDashboard();
    const interval = window.setInterval(() => loadDashboard(true), 60000);
    return () => window.clearInterval(interval);
  }, [loadDashboard]);

  useEffect(() => {
    const status = health?.refresh?.status || overview?.refresh?.status;
    if (!["queued", "running"].includes(status)) return undefined;
    const interval = window.setInterval(async () => {
      try {
        const latestHealth = await requestJson("/api/health");
        setHealth(latestHealth);
        if (!["queued", "running"].includes(latestHealth.refresh?.status)) {
          await loadDashboard(true);
        }
      } catch (pollError) {
        setError(pollError.message);
      }
    }, 2000);
    return () => window.clearInterval(interval);
  }, [health?.refresh?.status, loadDashboard, overview?.refresh?.status]);

  const refreshData = async () => {
    try {
      const response = await requestJson("/api/refresh", { method: "POST" });
      if (response.accepted) {
        setOverview((current) => current ? { ...current, refresh: response.refresh } : current);
        setHealth((current) => current ? { ...current, refresh: response.refresh } : current);
      }
      window.setTimeout(() => loadDashboard(true), 1200);
    } catch (refreshError) {
      setError(refreshError.message);
    }
  };

  const qualityByMetric = useMemo(
    () => Object.fromEntries((overview?.dataQuality || []).map((item) => [item.metric, item])),
    [overview],
  );
  const activeNav = NAV_ITEMS.find((item) => item.id === activeView) || NAV_ITEMS[0];
  const liveRefresh = health?.refresh || overview?.refresh;
  const isRefreshing = ["queued", "running"].includes(liveRefresh?.status);
  const staleCount = (overview?.dataQuality || []).filter(
    (item) => LONG_TERM_METRICS.has(item.metric) && item.stale,
  ).length;

  let content;
  if (activeView === "factor") content = <FactorModelView overview={overview} />;
  else if (activeView === "metrics") content = <MetricsView overview={overview} />;
  else if (activeView === "sources") content = <SourcesView sources={sources} cvddReference={cvddReference} onCvddSaved={setCvddReference} />;
  else if (activeView === "system") content = <SystemView health={health} refreshHistory={refreshHistory} />;
  else content = <Overview overview={overview} priceSeries={priceSeries} mvrvSeries={mvrvSeries} qualityByMetric={qualityByMetric} cvddReference={cvddReference} />;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark"><Bitcoin size={22} /></span><div><strong>BTC 底部研究台</strong><small>公开数据研究工具</small></div></div>
        <nav aria-label="主要导航">
          {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
            <button type="button" key={id} className={activeView === id ? "active" : ""} onClick={() => setActiveView(id)}>
              <Icon size={18} aria-hidden="true" /><span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-foot"><span>个人研究用途</span><small>不接钱包 · 不自动交易</small></div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div><p>BTC 底部研究台</p><h1>{activeNav.label}</h1></div>
          <div className="topbar-actions">
            <span className="as-of">更新 {formatDate(overview?.generatedAt, true)}</span>
            <button type="button" className="refresh-button" onClick={refreshData} disabled={isRefreshing} title="刷新公开数据">
              <RefreshCw size={16} className={isRefreshing ? "spin" : ""} aria-hidden="true" />
              <span>{isRefreshing ? "刷新中" : "刷新"}</span>
            </button>
          </div>
        </header>

        <div className="content">
          <RefreshProgress refresh={liveRefresh} />
          {error && <div className="notice notice-error"><CircleAlert size={17} /><span>接口暂时不可用：{error}</span></div>}
          {!error && staleCount > 0 && <div className="notice notice-warning"><Clock3 size={17} /><span>{staleCount} 项长期主线指标缺失或已过期，页面保留最后一次真实缓存并明确标记。</span></div>}
          {loading && !overview ? <div className="loading-state"><RefreshCw size={20} className="spin" /><span>正在读取研究数据</span></div> : content}
          <footer>
            <span>仅供个人研究，不构成投资建议。数据可能延迟、修订或暂时不可用。</span>
            <span className="footer-links">
              <a href="https://github.com/ywan0050-max/btc-bottom-research" target="_blank" rel="noreferrer">对应源代码</a>
              <a href="/LICENSE" target="_blank" rel="noreferrer">AGPL-3.0-only</a>
            </span>
          </footer>
        </div>
      </main>

      <nav className="bottom-nav" aria-label="手机导航">
        {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
          <button type="button" key={id} className={activeView === id ? "active" : ""} onClick={() => setActiveView(id)}>
            <Icon size={20} aria-hidden="true" /><span>{label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
