import { NextResponse } from "next/server";
import { runPython } from "@/lib/python";

export const runtime = "nodejs";
export const maxDuration = 180;

// 实盘绩效报告（重建实盘净值 + 对比回测/基准 + 跟踪误差）。会跑一次策略回测，约 30-60 秒。
export async function GET() {
  const r = await runPython(["-m", "quant_a.portfolio_web", "report"], 150000);
  if (!r.ok) return NextResponse.json({ error: r.error }, { status: 500 });
  return NextResponse.json(r.data);
}
