import { NextResponse } from "next/server";
import { runPython } from "@/lib/python";

export const runtime = "nodejs";

// 策略元数据（id/名称/参数声明/仓位分层），来自后端注册表：前端表单据此渲染，
// 新增策略只需要在 Python 侧注册，前端不用改代码。进程内缓存 10 分钟。
let cache: { at: number; data: unknown } | null = null;

export async function GET() {
  if (cache && Date.now() - cache.at < 600_000) return NextResponse.json(cache.data);
  const r = await runPython(["-m", "quant_a.strategy_web", "--list"], 30000);
  if (!r.ok) return NextResponse.json({ error: r.error }, { status: 500 });
  cache = { at: Date.now(), data: r.data };
  return NextResponse.json(r.data);
}
