import { NextResponse } from "next/server";
import { runPython } from "@/lib/python";

export const runtime = "nodejs";
export const maxDuration = 180;

// 通用执行复盘：账户持仓 vs 对照策略目标清单 → 遵从率/该买没买/计划外持仓。
// 目标清单优先复用当日 reports/ 产物（秒回）；过期才现跑一次策略。
export async function GET(req: Request) {
  const url = new URL(req.url);
  const strategy = url.searchParams.get("strategy") || "manual";
  const target = url.searchParams.get("target");
  const args = ["-m", "quant_a.portfolio_web", "review-lite", "--strategy", strategy];
  if (target) args.push("--target", target);
  const r = await runPython(args, 150000);
  if (!r.ok) return NextResponse.json({ error: r.error }, { status: 500 });
  return NextResponse.json(r.data);
}
