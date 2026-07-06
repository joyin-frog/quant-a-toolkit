"use client";

import { useState } from "react";
import Link from "next/link";
import {
  InfoIcon,
  LineChartIcon,
  MoonIcon,
  NotebookPenIcon,
  PlayIcon,
  RefreshCwIcon,
  SunIcon,
} from "lucide-react";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import { toast } from "sonner";
import { useTheme } from "next-themes";

import { cn } from "@/lib/utils";
import { hasParam, useStrategies } from "@/lib/strategies";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { Spinner } from "@/components/ui/spinner";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Toaster } from "@/components/ui/sonner";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

type Holding = {
  sleeve: string;
  theme: string;
  code: string;
  name: string;
  price: number;
  lots: number;
  cost: number;
  weight: number;
};

type TransitionOrder = {
  action: "卖出" | "保留" | "买入";
  code: string;
  name: string;
  shares: number;
  price: number | null;
  amount: number | null;
  note: string;
};

type Result = {
  strategy_id: string;
  strategy_name: string;
  as_of: string;
  range: string;
  metrics: Record<string, number>;
  benchmark: Record<string, number>;
  rolling12m: Record<string, number>;
  core_sectors: Record<string, number>;
  avg_cash_pct: number;
  invested: number;
  cash_left: number;
  holdings_list: Holding[];
  curve: { date: string; strategy: number; benchmark: number | null }[];
  transition?: {
    summary: {
      account: string;
      as_of?: string;
      equity: number;
      cash_before: number;
      cash_after: number;
      n_sell: number;
      n_keep: number;
      n_buy: number;
      locked: string[];
    };
    orders: TransitionOrder[];
  } | null;
};

const pct = (x: number) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;
const yuan = (x: number) => `¥${Math.round(x).toLocaleString("zh-CN")}`;
// A股习惯：红涨绿跌。
const tone = (x: number) => (x > 0 ? "text-gain" : x < 0 ? "text-loss" : "text-foreground");

// 下次调仓日（按策略 cadence 声明的每月 day 号附近）。生成清单不锁死，只用它提醒。
function nextRebalance(day = 15) {
  const now = new Date();
  const target =
    now.getDate() < day
      ? new Date(now.getFullYear(), now.getMonth(), day)
      : new Date(now.getFullYear(), now.getMonth() + 1, day);
  const days = Math.ceil((target.getTime() - now.getTime()) / 86400000);
  return {
    day,
    date: target.toLocaleDateString("zh-CN"),
    days,
    inWindow: Math.abs(days) <= 1 || now.getDate() === day,
  };
}

const chartConfig = {
  strategy: { label: "本组合", color: "var(--chart-1)" },
  benchmark: { label: "沪深300等权基准", color: "var(--chart-2)" },
} satisfies ChartConfig;

// Item 3: Tooltip helper for jargon terms
function InfoTip({ content }: { content: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <InfoIcon className="ml-1 inline size-3.5 cursor-help text-muted-foreground" />
      </TooltipTrigger>
      <TooltipContent side="top">
        <span>{content}</span>
      </TooltipContent>
    </Tooltip>
  );
}

// Item 7: Theme toggle button
function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={resolvedTheme === "dark" ? "切换到亮色模式" : "切换到暗色模式"}
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
    >
      {resolvedTheme === "dark" ? (
        <SunIcon className="size-4" />
      ) : (
        <MoonIcon className="size-4" />
      )}
    </Button>
  );
}

function Metric({
  label,
  value,
  valueClass,
  hint,
  tooltip,
}: {
  label: string;
  value: string;
  valueClass?: string;
  hint?: string;
  tooltip?: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardDescription className="flex items-center">
          {label}
          {tooltip ? <InfoTip content={tooltip} /> : null}
        </CardDescription>
        <CardTitle className={cn("text-2xl tabular-nums", valueClass)}>{value}</CardTitle>
      </CardHeader>
      {hint ? (
        <CardContent>
          <p className="text-muted-foreground text-xs">{hint}</p>
        </CardContent>
      ) : null}
    </Card>
  );
}

// Item 2 & 4: Skeleton for results area during loading
function ResultsSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}>
            <CardHeader>
              <Skeleton className="h-4 w-20" />
              <Skeleton className="mt-2 h-8 w-28" />
            </CardHeader>
          </Card>
        ))}
      </div>
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-32" />
          <Skeleton className="mt-1 h-4 w-48" />
        </CardHeader>
        <CardContent>
          {/* Item 4: Chart loading skeleton */}
          <div
            aria-label="净值曲线加载中"
            className="flex h-[300px] w-full flex-col items-center justify-center gap-4"
          >
            <Skeleton className="h-[260px] w-full" />
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-40" />
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

type BatchTrade = {
  date: string;
  code: string;
  name: string;
  action: "buy" | "sell";
  shares: number;
  price: number;
  sleeve: string;
  note: string;
};

function Results({
  data,
  onRecordBatch,
  batchSaving,
}: {
  data: Result;
  onRecordBatch: (account: string, trades: BatchTrade[], label: string) => void;
  batchSaving: boolean;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const transitionTrades = (): BatchTrade[] =>
    (data.transition?.orders ?? [])
      .filter((o) => o.action !== "保留" && o.price != null)
      .map((o) => ({
        date: today,
        code: o.code,
        name: o.name,
        action: o.action === "卖出" ? ("sell" as const) : ("buy" as const),
        shares: o.shares,
        price: o.price as number,
        sleeve: "自选",
        note: "按迁移清单价记账",
      }));
  const paperTrades = (): BatchTrade[] =>
    data.holdings_list.map((h) => ({
      date: today,
      code: h.code,
      name: h.name,
      action: "buy" as const,
      shares: h.lots * 100,
      price: h.price,
      sleeve: h.sleeve,
      note: "纸面跟踪·按清单价",
    }));
  const m = data.metrics;
  const r = data.rolling12m;

  // Item 1: Sleeve breakdown
  const coreHoldings = data.holdings_list.filter((h) => h.sleeve === "核心" || h.sleeve === "long");
  const aiHoldings = data.holdings_list.filter((h) => h.sleeve !== "核心" && h.sleeve !== "long");
  const coreCost = coreHoldings.reduce((s, h) => s + h.cost, 0);
  const aiCost = aiHoldings.reduce((s, h) => s + h.cost, 0);

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Metric
          label="总收益"
          value={pct(m.total_return)}
          valueClass={tone(m.total_return)}
          hint={data.range}
        />
        <Metric
          label="年化收益"
          value={pct(m.annualized_return)}
          valueClass={tone(m.annualized_return)}
          tooltip="以全年252交易日为基准，把回测期总收益折算成每年的等效收益率。"
        />
        <Metric
          label="最大回撤"
          value={pct(m.max_drawdown)}
          valueClass={tone(m.max_drawdown)}
          tooltip="回测期内从峰值跌到谷底的最大跌幅，衡量最坏情况下的亏损幅度。"
        />
        <Metric
          label="夏普比率"
          value={m.sharpe.toFixed(2)}
          valueClass="text-primary"
          tooltip="每承受一单位风险所获得的超额收益，越高越好（>1 算不错，>1.5 优秀）。"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>净值曲线</CardTitle>
          <CardDescription>
            {data.strategy_name} vs 对应股票池基准 · 滚动12月
            <InfoTip content="把回测期每12个月滑动一次，计算每段的年化收益，中位数反映「大多数时候」的真实感受。" />
            {" "}中位{" "}
            <span className={cn("font-medium", tone(r.median))}>{pct(r.median)}</span> · 为正{" "}
            {(r.pct_positive * 100).toFixed(0)}%
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Item 4: chart container with aria-label */}
          <div aria-label="本组合 vs 沪深300等权基准 净值曲线">
            <ChartContainer config={chartConfig} className="h-[300px] w-full">
              <LineChart data={data.curve} margin={{ left: 4, right: 12, top: 8 }}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="date" tickLine={false} axisLine={false} minTickGap={48} />
                <YAxis
                  tickLine={false}
                  axisLine={false}
                  width={48}
                  label={{ value: "净值(基1)", angle: -90, position: "insideLeft", offset: 12, style: { fontSize: 11 } }}
                />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Line dataKey="strategy" stroke="var(--color-strategy)" strokeWidth={2.2} dot={false} />
                <Line
                  dataKey="benchmark"
                  stroke="var(--color-benchmark)"
                  strokeWidth={1.5}
                  dot={false}
                />
              </LineChart>
            </ChartContainer>
          </div>
        </CardContent>
      </Card>

      {data.transition ? (
        <Card>
          <CardHeader>
            <CardTitle>
              迁移调仓清单 · {data.transition.summary.account === "manual" ? "手动实盘" : data.transition.summary.account}
              {data.transition.summary.as_of ? `（基准日 ${data.transition.summary.as_of}）` : ""}
            </CardTitle>
            <CardDescription>
              从现有持仓到目标组合：卖 {data.transition.summary.n_sell} · 留 {data.transition.summary.n_keep} · 买{" "}
              {data.transition.summary.n_buy}
              {data.transition.summary.locked.length
                ? ` · 锁仓 ${data.transition.summary.locked.join("、")}`
                : ""}{" "}
              · 迁移后现金约 {yuan(data.transition.summary.cash_after)}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>动作</TableHead>
                    <TableHead>代码</TableHead>
                    <TableHead>名称</TableHead>
                    <TableHead className="text-right">股数</TableHead>
                    <TableHead className="text-right">现价</TableHead>
                    <TableHead className="text-right">金额</TableHead>
                    <TableHead>说明</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.transition.orders.map((o) => (
                    <TableRow key={`${o.action}-${o.code}`}>
                      <TableCell>
                        <Badge
                          variant={o.action === "卖出" ? "destructive" : o.action === "买入" ? "default" : "secondary"}
                        >
                          {o.action}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-mono">{o.code}</TableCell>
                      <TableCell>{o.name}</TableCell>
                      <TableCell className="text-right tabular-nums">{o.shares}</TableCell>
                      <TableCell className="text-right tabular-nums">{o.price ?? "—"}</TableCell>
                      <TableCell className="text-right tabular-nums">{o.amount != null ? yuan(o.amount) : "—"}</TableCell>
                      <TableCell className="text-muted-foreground text-xs">{o.note}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <p className="text-muted-foreground mt-3 text-xs">
              ⚠️ 过渡建议：分批执行、卖出挑反弹日，别在恐慌盘一次性清；你实际怎么做记进账户，绩效报告会如实反映差异。
            </p>
            <Button
              size="sm"
              variant="outline"
              className="mt-3"
              disabled={batchSaving}
              onClick={() => onRecordBatch(data.transition!.summary.account, transitionTrades(), "迁移清单")}
            >
              {batchSaving ? <Spinner data-icon="inline-start" /> : null}
              一键按清单记入该账户（按清单价；实盘请事后核对成交价）
            </Button>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>策略持仓清单（截至 {data.as_of}）</CardTitle>
          <CardDescription>
            投入 {yuan(data.invested)} · 剩余现金 {yuan(data.cash_left)} ·{" "}
            {/* Item 1: Sleeve breakdown in title */}
            共 {data.holdings_list.length} 只（长期/核心 {coreHoldings.length} · 机动/卫星 {aiHoldings.length}）· 行业：
            {Object.entries(data.core_sectors)
              .map(([k, v]) => `${k}${v}`)
              .join(" ") || "已分散"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Item 5: Scrollable table with sticky header */}
          <div className="max-h-[26rem] overflow-y-auto">
            <Table>
              <TableHeader className="bg-card sticky top-0 z-10">
                <TableRow>
                  <TableHead>仓位</TableHead>
                  <TableHead>代码</TableHead>
                  <TableHead>名称</TableHead>
                  <TableHead className="text-right">现价</TableHead>
                  <TableHead className="text-right">手数</TableHead>
                  <TableHead className="text-right">金额</TableHead>
                  <TableHead className="text-right">权重</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.holdings_list.map((h) => (
                  <TableRow key={`${h.sleeve}-${h.code}`}>
                    <TableCell>
                      <Badge variant={h.sleeve === "核心" || h.sleeve === "long" ? "secondary" : "default"}>
                        {h.sleeve === "核心" ? "核心" : h.sleeve === "long" ? "底仓" : h.sleeve === "tactical" ? "机动" : h.theme ? `卫星·${h.theme}` : h.sleeve}
                      </Badge>
                    </TableCell>
                    {/* Item 10: font-mono for stock codes */}
                    <TableCell className="font-mono tabular-nums">{h.code}</TableCell>
                    <TableCell className="font-medium">{h.name}</TableCell>
                    <TableCell className="text-right tabular-nums">{h.price.toFixed(2)}</TableCell>
                    <TableCell className="text-right tabular-nums">{h.lots}</TableCell>
                    <TableCell className="text-right tabular-nums">{yuan(h.cost)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {(h.weight * 100).toFixed(1)}%
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
        <CardFooter className="flex flex-col items-start gap-2">
          {/* Item 1: Sleeve subtotal row */}
          <p className="text-muted-foreground text-xs tabular-nums">
            长期/核心投入 {yuan(coreCost)} · 机动/卫星投入 {yuan(aiCost)} · 现金 {yuan(data.cash_left)}
          </p>
          <p className="text-muted-foreground text-xs">⚠️ AI卫星是主动赌注；涨跌停就跳过。</p>
          {data.strategy_id === "ai_leader" && !data.transition ? (
            <Button
              size="sm"
              variant="outline"
              disabled={batchSaving}
              onClick={() => onRecordBatch("ai_paper", paperTrades(), "纸面清单")}
            >
              {batchSaving ? <Spinner data-icon="inline-start" /> : null}
              一键记为纸面成交 → AI纸面跟踪账户
            </Button>
          ) : null}
        </CardFooter>
      </Card>
    </div>
  );
}

// Item 8: Empty state for main page right panel
function EmptyHint() {
  return (
    <Card className="border-dashed">
      <CardContent className="text-muted-foreground flex min-h-[360px] flex-col items-center justify-center gap-4 text-center text-sm">
        <LineChartIcon className="text-primary size-10" />
        <div className="flex flex-col gap-1.5">
          <p className="text-foreground font-medium">还没有数据</p>
          <p>① 点左侧「刷新行情」拉取最新价格</p>
          <p>② 点「生成清单」跑回测 → 这里出净值曲线与下单清单</p>
        </div>
      </CardContent>
    </Card>
  );
}

// Item 4: Empty chart state
function ChartEmpty() {
  return (
    <div className="border-border flex h-[300px] w-full flex-col items-center justify-center gap-2 rounded-md border border-dashed">
      <LineChartIcon className="text-muted-foreground size-8" />
      <p className="text-muted-foreground text-sm">填参数 → 生成后这里出净值曲线</p>
    </div>
  );
}

export default function Page() {
  // 策略清单/参数声明来自后端注册表（/api/strategies），前端零硬编码。
  // 主页只列可回测策略；纯记账账户（手动实盘/纸面跟踪）在 /portfolio 页。
  const { strategies: allStrategies, error: strategiesError } = useStrategies();
  const strategies = allStrategies.filter((s) => s.runnable !== false);
  const [strategy, setStrategy] = useState("core_satellite");
  const meta = strategies.find((s) => s.strategy_id === strategy);
  const [capital, setCapital] = useState(200000);
  const [holdings, setHoldings] = useState(17);
  const [aiWeight, setAiWeight] = useState(0.15);
  const [universe, setUniverse] = useState("csi1000");
  const [account, setAccount] = useState("none"); // "none"=不迁移；其余为记账账户 id
  const [locked, setLocked] = useState("");
  const [loading, setLoading] = useState(false);
  const [batchSaving, setBatchSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number; fail: number; phase: string } | null>(null);
  const [data, setData] = useState<Result | null>(null);
  const cadence = meta?.cadence;
  const rebal = nextRebalance(cadence?.kind === "monthly" ? (cadence.day ?? 15) : 15);

  async function refresh() {
    setRefreshing(true);
    setProgress(null);
    const t = toast.loading("刷新行情中…");
    try {
      const res = await fetch("/api/refresh", { method: "POST" });
      if (!res.ok || !res.body) throw new Error("刷新启动失败");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let result: { ok: number; total: number; fail: number } | null = null;
      let failMsg: string | null = null;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl: number;
        while ((nl = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (!line) continue;
          const evt = JSON.parse(line);
          if (evt.type === "progress")
            setProgress({ done: evt.done, total: evt.total, fail: evt.fail, phase: evt.phase });
          else if (evt.type === "result") result = evt.result;
          else if (evt.type === "error") failMsg = evt.error;
        }
      }
      if (failMsg) throw new Error(failMsg);
      if (!result) throw new Error("刷新未返回结果");
      toast.success(
        `行情已更新：${result.ok}/${result.total} 只${result.fail ? `（${result.fail} 只失败，下次补）` : ""}`,
        { id: t },
      );
    } catch (e) {
      toast.error((e as Error).message, { id: t });
    } finally {
      setRefreshing(false);
      setProgress(null);
    }
  }

  async function recordBatch(accountId: string, trades: BatchTrade[], label: string) {
    if (!trades.length) {
      toast.error("清单里没有可记账的交易");
      return;
    }
    const accountName = allStrategies.find((s) => s.strategy_id === accountId)?.name ?? accountId;
    if (!window.confirm(`把 ${label} 的 ${trades.length} 笔交易按清单价记入「${accountName}」？\n实盘账户请事后按真实成交价核对（可在记账页删除重录）。`)) {
      return;
    }
    setBatchSaving(true);
    try {
      const res = await fetch("/api/trades", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: "batch", strategy: accountId, trades }),
      });
      const json = await res.json();
      if (!res.ok || json.error) throw new Error(json.error ?? "批量记账失败");
      toast.success(`已记入「${accountName}」：${json.trades} 笔成交，去记账页查看`);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBatchSaving(false);
    }
  }

  async function run() {
    setLoading(true);
    try {
      // 只发当前策略声明过的参数；后端注册表兜底过滤。
      const values: Record<string, number | string> = {
        capital,
        holdings,
        ai_weight: aiWeight,
        universe,
        account: account === "none" ? "" : account,
        locked: locked.trim(),
      };
      const body: Record<string, number | string> = { strategy };
      for (const p of meta?.params ?? []) {
        if (p.name in values) body[p.name] = values[p.name];
      }
      const res = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error ?? "运行失败");
      setData(json);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto flex max-w-[1600px] flex-col gap-6 p-6">
      <Toaster position="top-center" />
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold">
            {meta?.name ?? "策略"} <span className="text-primary">策略实验室</span>
          </h1>
          <p className="text-muted-foreground text-sm">{meta?.description ?? ""}</p>
        </div>
        {/* Item 7: Theme toggle + nav link in header */}
        <div className="flex items-center gap-2">
          <Link
            href="/portfolio"
            className="text-primary hover:text-primary/80 flex items-center gap-1.5 text-sm font-medium"
          >
            <NotebookPenIcon className="size-4" />
            实盘记账与绩效
          </Link>
          <ThemeToggle />
        </div>
      </header>

      <div className="grid items-start gap-6 lg:grid-cols-[340px_minmax(0,1fr)]">
        <Card className="lg:sticky lg:top-6">
          <CardHeader>
            <CardTitle>参数</CardTitle>
          </CardHeader>
          <CardContent>
            <FieldGroup>
              <Field>
                <FieldLabel>策略账户</FieldLabel>
                {strategiesError ? (
                  <p className="text-destructive text-xs">{strategiesError}</p>
                ) : null}
                <ToggleGroup
                  type="single"
                  variant="outline"
                  value={strategy}
                  onValueChange={(value) => {
                    if (value) {
                      setStrategy(value);
                      setData(null);
                      // 切换策略时把参数重置为该策略声明的默认值
                      const next = strategies.find((s) => s.strategy_id === value);
                      setAccount("none");
                      setLocked("");
                      for (const p of next?.params ?? []) {
                        if (p.name === "capital") setCapital(Number(p.default));
                        if (p.name === "holdings") setHoldings(Number(p.default));
                        if (p.name === "ai_weight") setAiWeight(Number(p.default));
                        if (p.name === "universe") setUniverse(String(p.default));
                      }
                    }
                  }}
                  className="grid grid-cols-2"
                >
                  {strategies.map((s) => (
                    <ToggleGroupItem key={s.strategy_id} value={s.strategy_id} aria-label={`选择${s.name}策略`}>
                      {s.name.length > 8 ? s.name.slice(0, 8) : s.name}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
              </Field>
              {hasParam(meta, "capital") ? (
                <Field>
                  <FieldLabel htmlFor="capital">本金（元）</FieldLabel>
                  <Input
                    id="capital"
                    type="number"
                    value={capital}
                    min={50000}
                    step={10000}
                    onChange={(e) => setCapital(Number(e.target.value))}
                  />
                </Field>
              ) : null}
              {hasParam(meta, "holdings") ? (
                <Field>
                  <FieldLabel>
                    {meta?.params.find((p) => p.name === "holdings")?.label ?? "持仓只数"}：
                    <span className="text-primary">{holdings}</span>
                  </FieldLabel>
                  <Slider
                    min={meta?.params.find((p) => p.name === "holdings")?.minimum ?? 10}
                    max={meta?.params.find((p) => p.name === "holdings")?.maximum ?? 30}
                    step={1}
                    value={[holdings]}
                    onValueChange={(v) => setHoldings(v[0])}
                  />
                </Field>
              ) : null}
              {hasParam(meta, "ai_weight") ? (
                <Field>
                  <FieldLabel>
                    AI 卫星比例：<span className="text-primary">{pct(aiWeight)}</span>
                  </FieldLabel>
                  <Slider
                    min={0}
                    max={0.3}
                    step={0.01}
                    value={[aiWeight]}
                    onValueChange={(v) => setAiWeight(v[0])}
                  />
                </Field>
              ) : null}
              {hasParam(meta, "universe") ? (
                <Field>
                  <FieldLabel>股票池</FieldLabel>
                  <ToggleGroup
                    type="single"
                    variant="outline"
                    value={universe}
                    onValueChange={(v) => v && setUniverse(v)}
                    className="grid grid-cols-2"
                  >
                    {(meta?.params.find((p) => p.name === "universe")?.choices ?? ["csi1000", "mainboard"]).map((c) => (
                      <ToggleGroupItem key={c} value={c}>
                        {c === "csi1000" ? "中证1000" : c === "mainboard" ? "全主板" : c}
                      </ToggleGroupItem>
                    ))}
                  </ToggleGroup>
                </Field>
              ) : null}
              {hasParam(meta, "account") ? (
                <Field>
                  <FieldLabel>从账户迁移</FieldLabel>
                  <ToggleGroup
                    type="single"
                    variant="outline"
                    value={account}
                    onValueChange={(v) => v && setAccount(v)}
                    className="grid grid-cols-3"
                  >
                    <ToggleGroupItem value="none">不迁移</ToggleGroupItem>
                    <ToggleGroupItem value="manual">手动实盘</ToggleGroupItem>
                    <ToggleGroupItem value="ai_paper">AI纸面</ToggleGroupItem>
                  </ToggleGroup>
                  <p className="text-muted-foreground text-xs">
                    选账户后，清单会从该账户的现有持仓出发给出 卖出/保留/买入 过渡方案
                  </p>
                </Field>
              ) : null}
              {hasParam(meta, "locked") && account !== "none" ? (
                <Field>
                  <FieldLabel htmlFor="locked">锁仓代码（策略不卖）</FieldLabel>
                  <Input
                    id="locked"
                    placeholder="如 600760,600176（逗号分隔）"
                    value={locked}
                    onChange={(e) => setLocked(e.target.value)}
                  />
                </Field>
              ) : null}
            </FieldGroup>
          </CardContent>
          <CardFooter className="flex-col items-stretch gap-3">
            <Button variant="outline" onClick={refresh} disabled={refreshing || loading}>
              {refreshing ? (
                <Spinner data-icon="inline-start" />
              ) : (
                <RefreshCwIcon data-icon="inline-start" />
              )}
              {refreshing
                ? progress
                  ? `${progress.phase === "retry" ? "补刷" : "拉取"} ${progress.done}/${progress.total}`
                  : "刷新中…"
                : "① 刷新行情"}
            </Button>
            {refreshing && progress ? (
              <div className="-mt-1 flex flex-col gap-1">
                {/* Item 9: progressbar role + aria attrs */}
                <div
                  className="bg-muted h-1.5 w-full overflow-hidden rounded-full"
                  role="progressbar"
                  aria-valuenow={progress.done}
                  aria-valuemin={0}
                  aria-valuemax={progress.total}
                  aria-label="刷新行情进度"
                >
                  <div
                    className="bg-primary h-full rounded-full transition-all duration-300"
                    style={{ width: `${Math.round((progress.done / Math.max(progress.total, 1)) * 100)}%` }}
                  />
                </div>
                <p className="text-muted-foreground text-xs tabular-nums">
                  {progress.phase === "retry" ? "补刷限流失败的 " : "拉取行情 "}
                  {progress.done}/{progress.total}
                  {progress.fail ? ` · 失败 ${progress.fail}` : ""}
                </p>
              </div>
            ) : null}
            <Button onClick={run} disabled={loading || refreshing}>
              {loading ? <Spinner data-icon="inline-start" /> : <PlayIcon data-icon="inline-start" />}
              {loading ? "回测中…" : "② 生成清单"}
            </Button>
            <p className={cn("text-xs", cadence?.kind === "monthly" && rebal.inWindow ? "text-primary" : "text-muted-foreground")}>
              {cadence?.kind === "daily_signal"
                ? "该策略按自身信号每日执行，生成结果仅作研究预览"
                : rebal.inWindow
                ? `今天是调仓日（每月${rebal.day}号附近）`
                : `距下次调仓 ${rebal.days} 天（${rebal.date}）· 非调仓日生成仅作预览，别下单`}
            </p>
          </CardFooter>
        </Card>

        <div className="flex flex-col gap-6">
          {/* Item 2 & 8: Loading skeleton vs empty state vs results */}
          {loading ? (
            <ResultsSkeleton />
          ) : data ? (
            <Results data={data} onRecordBatch={recordBatch} batchSaving={batchSaving} />
          ) : (
            // Item 8: proper empty state + Item 4: chart empty state within
            <div className="flex flex-col gap-6">
              <EmptyHint />
              <Card>
                <CardHeader>
                  <CardTitle>净值曲线</CardTitle>
                </CardHeader>
                <CardContent>
                  <ChartEmpty />
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
