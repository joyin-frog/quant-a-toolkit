"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeftIcon, ClipboardCheckIcon, GaugeIcon, PlusIcon, RefreshCwIcon } from "lucide-react";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
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
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Toaster } from "@/components/ui/sonner";

type Trade = {
  id: number;
  date: string;
  code: string;
  name: string;
  action: string;
  shares: number;
  price: number;
  fee: number;
  sleeve: string;
};

type Position = {
  code: string;
  name: string;
  sleeve: string;
  shares: number;
  avg_cost: number;
  price: number;
  value: number;
  pnl: number;
  pnl_pct: number | null;
  today_pct: number | null;
};

type Holdings = {
  empty: boolean;
  as_of?: string;
  positions?: Position[];
  total_value?: number;
  total_pnl?: number;
  total_pnl_pct?: number | null;
  next_rebalance?: { next_date: string; days_until: number };
};

type Report = {
  empty: boolean;
  since?: string;
  as_of?: string;
  days?: number;
  equity_yuan?: number;
  real_metrics?: Record<string, number | null>;
  tracking_error?: number | null;
  drag_vs_backtest?: number | null;
  excess_vs_benchmark?: number | null;
  n_trades?: number;
  curve?: { date: string; real: number; strategy?: number | null; benchmark?: number | null }[];
};

type Review = {
  attribution: {
    empty: boolean;
    since?: string;
    as_of?: string;
    total_return?: number;
    benchmark_return?: number;
    excess?: number;
    by_sleeve?: Record<string, number>;
    top1_share_of_gains?: number;
    top3_share_of_gains?: number;
    holdings?: { code: string; name: string; sleeve: string; contrib: number; ret: number; pnl: number }[];
  };
  execution: {
    empty: boolean;
    rebalance_date?: string;
    grade?: string;
    coverage?: number;
    avg_slippage?: number;
    off_cycle_trades?: number;
    recommended?: number;
    bought?: number;
    matched?: number;
    missing?: string[];
    extra?: string[];
  };
  factor_health: {
    empty: boolean;
    recent_months?: number;
    factors?: { factor: string; ic_full: number; ic_recent: number | null; decay: number | null; ic_ir: number; n: number }[];
  };
};

const pct = (x?: number | null) =>
  x === null || x === undefined ? "—" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;
const pct0 = (x?: number | null) => (x === null || x === undefined ? "—" : `${Math.round(x * 100)}%`);
const yuan = (x?: number) => (x === undefined ? "—" : `¥${Math.round(x).toLocaleString("zh-CN")}`);
const tone = (x?: number | null) =>
  x === null || x === undefined || x === 0 ? "text-foreground" : x > 0 ? "text-gain" : "text-loss";
const gradeTone = (g?: string) =>
  g === "A" ? "text-gain" : g === "B" ? "text-primary" : g === "D" ? "text-loss" : "text-muted-foreground";
const today = () => new Date().toISOString().slice(0, 10);

const chartConfig = {
  real: { label: "实盘", color: "var(--chart-1)" },
  strategy: { label: "策略回测", color: "var(--chart-2)" },
  benchmark: { label: "基准", color: "var(--muted-foreground)" },
} satisfies ChartConfig;

const emptyTrade = {
  date: today(),
  code: "",
  name: "",
  action: "buy",
  shares: "",
  price: "",
  fee: "0",
  sleeve: "核心",
};

function Metric({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className={cn("text-xl tabular-nums", valueClass)}>{value}</CardTitle>
      </CardHeader>
    </Card>
  );
}

export default function PortfolioPage() {
  const [form, setForm] = useState({ ...emptyTrade });
  const [cash, setCash] = useState({ date: today(), amount: "" });
  const [trades, setTrades] = useState<Trade[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [saving, setSaving] = useState(false);
  const [reporting, setReporting] = useState(false);
  const [holdings, setHoldings] = useState<Holdings | null>(null);
  const [hLoading, setHLoading] = useState(false);
  const [review, setReview] = useState<Review | null>(null);
  const [reviewing, setReviewing] = useState(false);

  const loadTrades = useCallback(async () => {
    const res = await fetch("/api/trades");
    if (res.ok) setTrades(await res.json());
  }, []);

  const loadHoldings = useCallback(async (refresh = false) => {
    setHLoading(true);
    try {
      const res = await fetch(`/api/holdings${refresh ? "?refresh=1" : ""}`);
      if (res.ok) setHoldings(await res.json());
      else toast.error("加载持仓失败");
    } finally {
      setHLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTrades();
    loadHoldings();
  }, [loadTrades, loadHoldings]);

  async function recordTrade() {
    if (!form.code || !form.shares || !form.price) {
      toast.error("代码、股数、成交价必填");
      return;
    }
    setSaving(true);
    try {
      const res = await fetch("/api/trades", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: "trade", ...form }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error ?? "记录失败");
      toast.success("已记录成交");
      setForm({ ...emptyTrade, date: form.date });
      await loadTrades();
      loadHoldings();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function recordCash() {
    if (!cash.amount) {
      toast.error("请输入入金金额");
      return;
    }
    const res = await fetch("/api/trades", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: "cash", ...cash }),
    });
    if (res.ok) {
      toast.success("已记录入金");
      setCash({ date: today(), amount: "" });
    } else {
      toast.error("入金记录失败");
    }
  }

  async function loadReport() {
    setReporting(true);
    const t = toast.loading("生成绩效中…");
    try {
      const res = await fetch("/api/portfolio");
      const json = await res.json();
      if (!res.ok) throw new Error(json.error ?? "失败");
      setReport(json);
      toast.success("绩效已更新", { id: t });
    } catch (e) {
      toast.error((e as Error).message, { id: t });
    } finally {
      setReporting(false);
    }
  }

  async function loadReview() {
    setReviewing(true);
    const t = toast.loading("生成复盘中…（约 20-40 秒）");
    try {
      const res = await fetch("/api/review");
      const json = await res.json();
      if (!res.ok) throw new Error(json.error ?? "失败");
      setReview(json);
      toast.success("复盘已生成", { id: t });
    } catch (e) {
      toast.error((e as Error).message, { id: t });
    } finally {
      setReviewing(false);
    }
  }

  const exec = review?.execution;
  const attr = review?.attribution;
  const fh = review?.factor_health;

  return (
    <main className="mx-auto flex max-w-[1600px] flex-col gap-6 p-6">
      <Toaster position="top-center" />
      <header className="flex flex-col gap-1">
        <Link
          href="/"
          className="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm"
        >
          <ArrowLeftIcon className="size-3.5" />
          返回月度调仓
        </Link>
        <h1 className="text-2xl font-semibold">
          实盘 <span className="text-primary">记账与绩效</span>
        </h1>
        <p className="text-muted-foreground text-sm">记真实成交 → 实盘 vs 回测/基准</p>
      </header>

      <div className="grid items-start gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
        <div className="flex flex-col gap-6 lg:sticky lg:top-6">
          <Card>
            <CardHeader>
              <CardTitle>记一笔成交</CardTitle>
            </CardHeader>
            <CardContent>
              <FieldGroup>
                <ToggleGroup
                  type="single"
                  variant="outline"
                  value={form.action}
                  onValueChange={(v) => v && setForm({ ...form, action: v })}
                  className="w-full"
                >
                  <ToggleGroupItem value="buy" className="flex-1">
                    买入
                  </ToggleGroupItem>
                  <ToggleGroupItem value="sell" className="flex-1">
                    卖出
                  </ToggleGroupItem>
                </ToggleGroup>
                <div className="grid grid-cols-2 gap-4">
                  <Field>
                    <FieldLabel htmlFor="date">日期</FieldLabel>
                    <Input
                      id="date"
                      type="date"
                      value={form.date}
                      onChange={(e) => setForm({ ...form, date: e.target.value })}
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="code">代码</FieldLabel>
                    <Input
                      id="code"
                      value={form.code}
                      placeholder="600926"
                      onChange={(e) => setForm({ ...form, code: e.target.value })}
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="name">名称</FieldLabel>
                    <Input
                      id="name"
                      value={form.name}
                      placeholder="杭州银行"
                      onChange={(e) => setForm({ ...form, name: e.target.value })}
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="shares">股数</FieldLabel>
                    <Input
                      id="shares"
                      type="number"
                      value={form.shares}
                      placeholder="500"
                      onChange={(e) => setForm({ ...form, shares: e.target.value })}
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="price">成交价</FieldLabel>
                    <Input
                      id="price"
                      type="number"
                      value={form.price}
                      placeholder="16.90"
                      onChange={(e) => setForm({ ...form, price: e.target.value })}
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="fee">手续费</FieldLabel>
                    <Input
                      id="fee"
                      type="number"
                      value={form.fee}
                      onChange={(e) => setForm({ ...form, fee: e.target.value })}
                    />
                  </Field>
                </div>
                <Button onClick={recordTrade} disabled={saving}>
                  {saving ? <Spinner data-icon="inline-start" /> : <PlusIcon data-icon="inline-start" />}
                  记录成交
                </Button>
              </FieldGroup>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>记入金</CardTitle>
            </CardHeader>
            <CardContent>
              <FieldGroup>
                <div className="grid grid-cols-2 gap-4">
                  <Field>
                    <FieldLabel htmlFor="cdate">日期</FieldLabel>
                    <Input
                      id="cdate"
                      type="date"
                      value={cash.date}
                      onChange={(e) => setCash({ ...cash, date: e.target.value })}
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="amount">金额</FieldLabel>
                    <Input
                      id="amount"
                      type="number"
                      value={cash.amount}
                      placeholder="200000"
                      onChange={(e) => setCash({ ...cash, amount: e.target.value })}
                    />
                  </Field>
                </div>
                <Button variant="outline" onClick={recordCash}>
                  <PlusIcon data-icon="inline-start" />
                  记入金
                </Button>
              </FieldGroup>
            </CardContent>
          </Card>
        </div>

        <div className="grid items-start gap-6 2xl:grid-cols-2">
          <Card className="2xl:col-span-2">
            <CardHeader className="flex-row items-center justify-between">
              <div className="flex flex-col gap-1.5">
                <CardTitle>当前持仓盈亏</CardTitle>
                {holdings && !holdings.empty ? (
                  <CardDescription>
                    截至 {holdings.as_of} · 距下次调仓 {holdings.next_rebalance?.days_until} 天
                  </CardDescription>
                ) : null}
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => loadHoldings(true)}
                disabled={hLoading}
              >
                {hLoading ? (
                  <Spinner data-icon="inline-start" />
                ) : (
                  <RefreshCwIcon data-icon="inline-start" />
                )}
                刷新价格
              </Button>
            </CardHeader>
            <CardContent>
              {holdings && !holdings.empty && holdings.positions ? (
                <div className="flex flex-col gap-4">
                  <div className="flex flex-wrap items-baseline gap-x-8 gap-y-1">
                    <span className="text-muted-foreground text-sm">
                      总市值 <span className="text-foreground font-medium tabular-nums">{yuan(holdings.total_value)}</span>
                    </span>
                    <span className="text-muted-foreground text-sm">
                      浮动盈亏{" "}
                      <span className={cn("text-lg font-semibold tabular-nums", tone(holdings.total_pnl_pct))}>
                        {yuan(holdings.total_pnl)}（{pct(holdings.total_pnl_pct)}）
                      </span>
                    </span>
                  </div>
                  <div className="max-h-[22rem] overflow-y-auto">
                  <Table>
                    <TableHeader className="bg-card sticky top-0 z-10">
                      <TableRow>
                        <TableHead>名称</TableHead>
                        <TableHead className="text-right">成本</TableHead>
                        <TableHead className="text-right">现价</TableHead>
                        <TableHead className="text-right">浮盈亏</TableHead>
                        <TableHead className="text-right">今日</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {holdings.positions.map((p) => (
                        <TableRow key={p.code}>
                          <TableCell className="font-medium">
                            {p.name}
                            <span className="text-muted-foreground ml-1.5 text-xs tabular-nums">
                              {p.shares}股
                            </span>
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{p.avg_cost.toFixed(2)}</TableCell>
                          <TableCell className="text-right tabular-nums">{p.price.toFixed(2)}</TableCell>
                          <TableCell className={cn("text-right tabular-nums", tone(p.pnl_pct))}>
                            {pct(p.pnl_pct)}
                          </TableCell>
                          <TableCell className={cn("text-right tabular-nums", tone(p.today_pct))}>
                            {pct(p.today_pct)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  </div>
                </div>
              ) : (
                <p className="text-muted-foreground py-6 text-center text-sm">还没有持仓（先记成交）</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <div className="flex flex-col gap-1.5">
                <CardTitle>实盘绩效</CardTitle>
                <CardDescription>
                  {report && !report.empty
                    ? `${report.since} ~ ${report.as_of} · ${report.days} 天 · 当前净值 ${yuan(report.equity_yuan)}`
                    : "记几笔成交后，点右侧生成"}
                </CardDescription>
              </div>
              <Button variant="outline" size="sm" onClick={loadReport} disabled={reporting}>
                {reporting ? (
                  <Spinner data-icon="inline-start" />
                ) : (
                  <GaugeIcon data-icon="inline-start" />
                )}
                生成绩效
              </Button>
            </CardHeader>
            <CardContent className="flex flex-col gap-6">
              {report && !report.empty ? (
                <>
                  <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                    <Metric
                      label="实盘总收益"
                      value={pct(report.real_metrics?.total_return)}
                      valueClass={tone(report.real_metrics?.total_return)}
                    />
                    <Metric
                      label="对基准超额"
                      value={pct(report.excess_vs_benchmark)}
                      valueClass={tone(report.excess_vs_benchmark)}
                    />
                    <Metric
                      label="对回测损耗"
                      value={pct(report.drag_vs_backtest)}
                      valueClass={tone(report.drag_vs_backtest)}
                    />
                    <Metric
                      label="跟踪误差(年化)"
                      value={
                        report.tracking_error === null || report.tracking_error === undefined
                          ? "—"
                          : `${(report.tracking_error * 100).toFixed(1)}%`
                      }
                      valueClass="text-primary"
                    />
                  </div>
                  <ChartContainer config={chartConfig} className="h-[280px] w-full">
                    <LineChart data={report.curve} margin={{ left: 4, right: 12, top: 8 }}>
                      <CartesianGrid vertical={false} />
                      <XAxis dataKey="date" tickLine={false} axisLine={false} minTickGap={48} />
                      <YAxis tickLine={false} axisLine={false} width={44} domain={["auto", "auto"]} />
                      <ChartTooltip content={<ChartTooltipContent />} />
                      <Line dataKey="real" stroke="var(--color-real)" strokeWidth={2.2} dot={false} />
                      <Line
                        dataKey="strategy"
                        stroke="var(--color-strategy)"
                        strokeWidth={1.5}
                        strokeDasharray="4 4"
                        dot={false}
                      />
                      <Line
                        dataKey="benchmark"
                        stroke="var(--color-benchmark)"
                        strokeWidth={1.5}
                        dot={false}
                      />
                    </LineChart>
                  </ChartContainer>
                  <p className="text-muted-foreground text-xs">实盘(实线) · 回测(虚线) · 基准</p>
                </>
              ) : (
                <p className="text-muted-foreground py-8 text-center text-sm">
                  记入金 + 成交后，点&quot;生成绩效&quot;
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <div className="flex flex-col gap-1.5">
                <CardTitle>执行评分卡</CardTitle>
                <CardDescription>
                  {exec && !exec.empty
                    ? `调仓日 ${exec.rebalance_date} · 推荐清单 vs 真实成交 · 打过程分`
                    : "对照「该买什么 vs 你真实成交」给操作打分"}
                </CardDescription>
              </div>
              <Button variant="outline" size="sm" onClick={loadReview} disabled={reviewing}>
                {reviewing ? <Spinner data-icon="inline-start" /> : <ClipboardCheckIcon data-icon="inline-start" />}
                生成复盘
              </Button>
            </CardHeader>
            <CardContent>
              {exec && !exec.empty ? (
                <div className="flex flex-col gap-4">
                  <div className="flex items-center gap-5">
                    <div
                      className={cn(
                        "bg-muted flex size-16 shrink-0 items-center justify-center rounded-xl text-4xl font-bold tabular-nums",
                        gradeTone(exec.grade),
                      )}
                    >
                      {exec.grade}
                    </div>
                    <div className="flex flex-wrap items-baseline gap-x-8 gap-y-1.5 text-sm">
                      <span className="text-muted-foreground">
                        覆盖率{" "}
                        <span className="text-foreground font-semibold tabular-nums">{pct0(exec.coverage)}</span>
                        <span className="ml-1 text-xs">（{exec.matched}/{exec.recommended} 只）</span>
                      </span>
                      <span className="text-muted-foreground">
                        平均滑点{" "}
                        <span className={cn("font-semibold tabular-nums", tone(exec.avg_slippage))}>
                          {pct(exec.avg_slippage)}
                        </span>
                      </span>
                      <span className="text-muted-foreground">
                        非调仓日乱动{" "}
                        <span className="text-foreground font-semibold tabular-nums">{exec.off_cycle_trades}</span> 笔
                      </span>
                    </div>
                  </div>
                  {exec.missing && exec.missing.length > 0 ? (
                    <p className="text-muted-foreground text-sm">漏买：{exec.missing.join("、")}</p>
                  ) : null}
                  {exec.extra && exec.extra.length > 0 ? (
                    <p className="text-muted-foreground text-sm">计划外买入：{exec.extra.join("、")}</p>
                  ) : null}
                </div>
              ) : (
                <p className="text-muted-foreground py-6 text-center text-sm">点&quot;生成复盘&quot;给这一期操作打分</p>
              )}
            </CardContent>
          </Card>

          {attr && !attr.empty ? (
            <Card>
              <CardHeader>
                <CardTitle>收益归因</CardTitle>
                <CardDescription>
                  {attr.since} ~ {attr.as_of} · 这段收益从哪来
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                <div className="grid grid-cols-3 gap-4">
                  <Metric label="实盘" value={pct(attr.total_return)} valueClass={tone(attr.total_return)} />
                  <Metric
                    label="基准(核心池等权)"
                    value={pct(attr.benchmark_return)}
                    valueClass={tone(attr.benchmark_return)}
                  />
                  <Metric label="超额(选股能力)" value={pct(attr.excess)} valueClass={tone(attr.excess)} />
                </div>
                <div className="text-muted-foreground flex flex-wrap items-baseline gap-x-6 gap-y-1.5 text-sm">
                  {Object.entries(attr.by_sleeve ?? {}).map(([k, v]) => (
                    <span key={k}>
                      {k} <span className={cn("font-semibold tabular-nums", tone(v))}>{pct(v)}</span>
                    </span>
                  ))}
                  <span>
                    集中度 前1{" "}
                    <span className="text-foreground font-semibold tabular-nums">{pct0(attr.top1_share_of_gains)}</span> / 前3{" "}
                    <span className="text-foreground font-semibold tabular-nums">{pct0(attr.top3_share_of_gains)}</span> 盈利
                  </span>
                </div>
                <div className="max-h-[22rem] overflow-y-auto">
                  <Table>
                    <TableHeader className="bg-card sticky top-0 z-10">
                      <TableRow>
                        <TableHead>名称</TableHead>
                        <TableHead>腿</TableHead>
                        <TableHead className="text-right">贡献</TableHead>
                        <TableHead className="text-right">自身</TableHead>
                        <TableHead className="text-right">盈亏</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {attr.holdings?.map((h) => (
                        <TableRow key={h.code}>
                          <TableCell className="font-medium">{h.name}</TableCell>
                          <TableCell>
                            <Badge variant={h.sleeve === "核心" ? "secondary" : "default"}>{h.sleeve}</Badge>
                          </TableCell>
                          <TableCell className={cn("text-right tabular-nums", tone(h.contrib))}>{pct(h.contrib)}</TableCell>
                          <TableCell className={cn("text-right tabular-nums", tone(h.ret))}>{pct(h.ret)}</TableCell>
                          <TableCell className={cn("text-right tabular-nums", tone(h.pnl))}>{yuan(h.pnl)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          ) : null}

          {fh && !fh.empty ? (
            <Card>
              <CardHeader>
                <CardTitle>因子体检</CardTitle>
                <CardDescription>
                  滚动 rank-IC：全程 vs 近 {fh.recent_months ?? 12} 月 · 季度看，持续衰减才调权重
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="max-h-[22rem] overflow-y-auto">
                  <Table>
                    <TableHeader className="bg-card sticky top-0 z-10">
                      <TableRow>
                        <TableHead>因子</TableHead>
                        <TableHead className="text-right">全程IC</TableHead>
                        <TableHead className="text-right">近一年</TableHead>
                        <TableHead className="text-right">衰减</TableHead>
                        <TableHead className="text-right">IC_IR</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {fh.factors?.map((f) => (
                        <TableRow key={f.factor}>
                          <TableCell className="font-medium">
                            {f.factor}
                            {f.decay !== null && f.decay !== undefined && f.decay < -0.02 ? (
                              <Badge variant="outline" className="text-loss ml-2">
                                衰减
                              </Badge>
                            ) : null}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{f.ic_full?.toFixed(3)}</TableCell>
                          <TableCell className={cn("text-right tabular-nums", tone(f.ic_recent))}>
                            {f.ic_recent === null || f.ic_recent === undefined ? "—" : f.ic_recent.toFixed(3)}
                          </TableCell>
                          <TableCell className={cn("text-right tabular-nums", tone(f.decay))}>
                            {f.decay === null || f.decay === undefined ? "—" : f.decay.toFixed(3)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{f.ic_ir?.toFixed(2)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                <p className="text-muted-foreground mt-3 text-xs">
                  IC&gt;0 且稳(IC_IR 高)=因子有效；近一年比全程明显掉(衰减&lt;-0.02)=钝化，可考虑降权（别因一两月就动）。
                </p>
              </CardContent>
            </Card>
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle>成交流水（{trades.length}）</CardTitle>
            </CardHeader>
            <CardContent>
              {trades.length ? (
                <div className="max-h-[24rem] overflow-y-auto">
                <Table>
                  <TableHeader className="bg-card sticky top-0 z-10">
                    <TableRow>
                      <TableHead>日期</TableHead>
                      <TableHead>方向</TableHead>
                      <TableHead>代码</TableHead>
                      <TableHead>名称</TableHead>
                      <TableHead className="text-right">股数</TableHead>
                      <TableHead className="text-right">成交价</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {trades.map((t) => (
                      <TableRow key={t.id}>
                        <TableCell className="tabular-nums">{t.date?.slice(0, 10)}</TableCell>
                        <TableCell>
                          <Badge variant={t.action === "buy" ? "default" : "secondary"}>
                            {t.action === "buy" ? "买" : "卖"}
                          </Badge>
                        </TableCell>
                        <TableCell className="tabular-nums">{t.code}</TableCell>
                        <TableCell>{t.name}</TableCell>
                        <TableCell className="text-right tabular-nums">{t.shares}</TableCell>
                        <TableCell className="text-right tabular-nums">{t.price?.toFixed(2)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                </div>
              ) : (
                <p className="text-muted-foreground py-6 text-center text-sm">还没有成交记录</p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </main>
  );
}
