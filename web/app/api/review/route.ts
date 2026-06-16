import { NextResponse } from "next/server";
import { runPython } from "@/lib/python";

export const runtime = "nodejs";
export const maxDuration = 180;

// 月度复盘：执行评分卡 + 归因 + 因子体检（一次加载行情/财报，约 20-40 秒）。
export async function GET() {
  const r = await runPython(["-m", "quant_a.portfolio_web", "review"], 150000);
  if (!r.ok) return NextResponse.json({ error: r.error }, { status: 500 });
  return NextResponse.json(r.data);
}
