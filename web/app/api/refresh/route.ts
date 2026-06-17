import { NextResponse } from "next/server";
import { runPython } from "@/lib/python";

export const runtime = "nodejs";
export const maxDuration = 600;

// 刷新沪深300+AI行情到最新交易日（调 quant_a.refresh_cs，并行两遍，约 1-2 分钟）。
// 进度/耗时/报错由 runPython 实时打到 dev 终端。
export async function POST() {
  const r = await runPython(["-m", "quant_a.refresh_cs"], 580000);
  if (!r.ok) return NextResponse.json({ error: r.error }, { status: 500 });
  return NextResponse.json(r.data);
}
