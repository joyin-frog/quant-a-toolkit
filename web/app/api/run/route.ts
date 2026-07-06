import { NextResponse } from "next/server";
import { runPython } from "@/lib/python";

export const runtime = "nodejs";
export const maxDuration = 180;

// 网页后端：以子进程调统一策略入口（quant_a.strategy_web），把 stdout 的 JSON 透传给前端。
// 只转发请求里出现的参数；策略支持哪些参数由后端注册表（StrategyDefinition）决定。
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const strategy = String(body.strategy ?? "core_satellite");
  const args = ["-m", "quant_a.strategy_web", "--strategy", strategy];
  const flags: [string, unknown][] = [
    ["--capital", body.capital],
    ["--holdings", body.holdings],
    ["--ai_weight", body.ai_weight ?? body.aiWeight],
    ["--universe", body.universe],
  ];
  for (const [flag, value] of flags) {
    if (value !== undefined && value !== null && value !== "") args.push(flag, String(value));
  }

  const r = await runPython(args, 170000);
  if (!r.ok) return NextResponse.json({ error: r.error }, { status: 500 });
  return NextResponse.json(r.data);
}
