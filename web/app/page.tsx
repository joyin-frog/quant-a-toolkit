"use client";

import { useState } from "react";
import Link from "next/link";
import { LineChartIcon, NotebookPenIcon, PlayIcon, RefreshCwIcon } from "lucide-react";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Toaster } from "@/components/ui/sonner";

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

type Result = {
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
};

const pct = (x: number) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;
const yuan = (x: number) => `¥${Math.round(x).toLocaleString("zh-CN")}`;
// A股习惯：红涨绿跌。
const tone = (x: number) => (x > 0 ? "text-gain" : x < 0 ? "text-loss" : "text-foreground");

// 下次调仓日（每月 15 号附近）。生成清单不锁死，只用它提醒——非调仓日仅作预览。
function nextRebalance() {
  const REBAL_DAY = 15;
  const now = new Date();
  const target =
    now.getDate() < REBAL_DAY
      ? new Date(now.getFullYear(), now.getMonth(), REBAL_DAY)
      : new Date(now.getFullYear(), now.getMonth() + 1, REBAL_DAY);
  const days = Math.ceil((target.getTime() - now.getTime()) / 86400000);
  return {
    date: target.toLocaleDateString("zh-CN"),
    days,
    inWindow: Math.abs(days) <= 1 || now.getDate() === REBAL_DAY,
  };
}

const chartConfig = {
  strategy: { label: "本组合", color: "var(--chart-1)" },
  benchmark: { label: "沪深300等权基准", color: "var(--chart-2)" },
} satisfies ChartConfig;

function Metric({
  label,
  value,
  valueClass,
  hint,
}: {
  label: string;
  value: string;
  valueClass?: string;
  hint?: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>{label}</CardDescription>
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

function Results({ data }: { data: Result }) {
  const m = data.metrics;
  const r = data.rolling12m;
  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Metric label="总收益" value={pct(m.total_return)} valueClass={tone(m.total_return)} hint={data.range} />
        <Metric label="年化收益" value={pct(m.annualized_return)} valueClass={tone(m.annualized_return)} />
        <Metric label="最大回撤" value={pct(m.max_drawdown)} valueClass={tone(m.max_drawdown)} />
        <Metric label="夏普比率" value={m.sharpe.toFixed(2)} valueClass="text-primary" />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>净值曲线</CardTitle>
          <CardDescription>
            vs 基准 · 滚动12月中位{" "}
            <span className={cn("font-medium", tone(r.median))}>{pct(r.median)}</span> · 为正{" "}
            {(r.pct_positive * 100).toFixed(0)}%
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ChartContainer config={chartConfig} className="h-[300px] w-full">
            <LineChart data={data.curve} margin={{ left: 4, right: 12, top: 8 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="date" tickLine={false} axisLine={false} minTickGap={48} />
              <YAxis tickLine={false} axisLine={false} width={40} />
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
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>本月下单清单（截至 {data.as_of}）</CardTitle>
          <CardDescription>
            投入 {yuan(data.invested)} · 剩余现金 {yuan(data.cash_left)} · 共{" "}
            {data.holdings_list.length} 只 · 核心行业：
            {Object.entries(data.core_sectors)
              .map(([k, v]) => `${k}${v}`)
              .join(" ") || "已分散"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
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
                <TableRow key={h.code}>
                  <TableCell>
                    <Badge variant={h.sleeve === "核心" ? "secondary" : "default"}>
                      {h.sleeve === "核心" ? "核心" : `AI·${h.theme}`}
                    </Badge>
                  </TableCell>
                  <TableCell className="tabular-nums">{h.code}</TableCell>
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
        </CardContent>
        <CardFooter>
          <p className="text-muted-foreground text-xs">⚠️ AI卫星是主动赌注；涨跌停就跳过。</p>
        </CardFooter>
      </Card>
    </div>
  );
}

function EmptyHint() {
  return (
    <Card className="border-dashed">
      <CardContent className="text-muted-foreground flex min-h-[280px] flex-col items-center justify-center gap-3 text-center text-sm">
        <LineChartIcon className="text-primary size-8" />
        <p>填参数 → ① 刷新 → ② 生成</p>
      </CardContent>
    </Card>
  );
}

export default function Page() {
  const [capital, setCapital] = useState(200000);
  const [holdings, setHoldings] = useState(17);
  const [aiWeight, setAiWeight] = useState(0.15);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [data, setData] = useState<Result | null>(null);
  const rebal = nextRebalance();

  async function refresh() {
    setRefreshing(true);
    const t = toast.loading("刷新行情中…（约 1-2 分钟，终端可看进度）");
    try {
      const res = await fetch("/api/refresh", { method: "POST" });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error ?? "刷新失败");
      toast.success(
        `行情已更新：${json.ok}/${json.total} 只${json.fail ? `（${json.fail} 只失败，下次补）` : ""}`,
        { id: t },
      );
    } catch (e) {
      toast.error((e as Error).message, { id: t });
    } finally {
      setRefreshing(false);
    }
  }

  async function run() {
    setLoading(true);
    try {
      const res = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ capital, holdings, aiWeight }),
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
    <main className="mx-auto flex max-w-6xl flex-col gap-6 p-6">
      <Toaster position="top-center" />
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold">
            核心-卫星 <span className="text-primary">月度调仓</span>
          </h1>
          <p className="text-muted-foreground text-sm">沪深300核心 + AI卫星</p>
        </div>
        <Link
          href="/portfolio"
          className="text-primary hover:text-primary/80 flex items-center gap-1.5 text-sm font-medium"
        >
          <NotebookPenIcon className="size-4" />
          实盘记账与绩效
        </Link>
      </header>

      <div className="grid items-start gap-6 lg:grid-cols-[340px_minmax(0,1fr)]">
        <Card className="lg:sticky lg:top-6">
          <CardHeader>
            <CardTitle>参数</CardTitle>
          </CardHeader>
          <CardContent>
            <FieldGroup>
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
              <Field>
                <FieldLabel>
                  核心持仓只数：<span className="text-primary">{holdings}</span>
                </FieldLabel>
                <Slider
                  min={10}
                  max={30}
                  step={1}
                  value={[holdings]}
                  onValueChange={(v) => setHoldings(v[0])}
                />
              </Field>
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
            </FieldGroup>
          </CardContent>
          <CardFooter className="flex-col items-stretch gap-3">
            <Button variant="outline" onClick={refresh} disabled={refreshing || loading}>
              {refreshing ? (
                <Spinner data-icon="inline-start" />
              ) : (
                <RefreshCwIcon data-icon="inline-start" />
              )}
              {refreshing ? "刷新中…" : "① 刷新行情"}
            </Button>
            <Button onClick={run} disabled={loading || refreshing}>
              {loading ? <Spinner data-icon="inline-start" /> : <PlayIcon data-icon="inline-start" />}
              {loading ? "回测中…" : "② 生成清单"}
            </Button>
            <p className={cn("text-xs", rebal.inWindow ? "text-primary" : "text-muted-foreground")}>
              {rebal.inWindow
                ? `今天是调仓日（每月15号）`
                : `距下次调仓 ${rebal.days} 天（${rebal.date}）· 非调仓日生成仅作预览，别下单`}
            </p>
          </CardFooter>
        </Card>

        <div className="flex flex-col gap-6">
          {loading && !data ? (
            <Skeleton className="h-[400px] w-full" />
          ) : data ? (
            <Results data={data} />
          ) : (
            <EmptyHint />
          )}
        </div>
      </div>
    </main>
  );
}
