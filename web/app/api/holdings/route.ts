import { NextResponse } from "next/server";
import { runPython } from "@/lib/python";

export const runtime = "nodejs";
export const maxDuration = 120;

// 当前持仓盈亏（成本/现价/浮盈亏/今日涨跌 + 下次调仓日）。?refresh=1 会先快刷持仓股最新价（约20-30秒）。
export async function GET(req: Request) {
  const refresh = new URL(req.url).searchParams.get("refresh") === "1";
  const args = ["-m", "quant_a.portfolio_web", "holdings"];
  if (refresh) args.push("--refresh");
  const r = await runPython(args, refresh ? 90000 : 20000);
  if (!r.ok) return NextResponse.json({ error: r.error }, { status: 500 });
  return NextResponse.json(r.data);
}
