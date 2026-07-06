import { NextResponse } from "next/server";
import { runPython } from "@/lib/python";

export const runtime = "nodejs";
export const maxDuration = 180;

// 月度复盘：执行评分卡 + 归因 + 因子体检（一次加载行情/财报，约 20-40 秒）。
// 复盘归因目前只支持 core_satellite；后端会对其他策略返回 error，而不是错误归因。
export async function GET(req: Request) {
  const strategy = new URL(req.url).searchParams.get("strategy") || "core_satellite";
  const r = await runPython(["-m", "quant_a.portfolio_web", "review", "--strategy", strategy], 150000);
  if (!r.ok) return NextResponse.json({ error: r.error }, { status: 500 });
  return NextResponse.json(r.data);
}
