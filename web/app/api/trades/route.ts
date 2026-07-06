import { NextResponse } from "next/server";
import { runPython } from "@/lib/python";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const strategy = new URL(req.url).searchParams.get("strategy") || "core_satellite";
  const r = await runPython(["-m", "quant_a.portfolio_web", "list", "--strategy", strategy], 30000);
  if (!r.ok) return NextResponse.json({ error: r.error }, { status: 500 });
  return NextResponse.json(r.data);
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  let args: string[];
  if (body.kind === "cash") {
    args = [
      "-m", "quant_a.portfolio_web", "add-cash",
      "--date", String(body.date),
      "--amount", String(body.amount),
      "--type", String(body.type ?? "deposit"),
      "--strategy", String(body.strategy ?? "core_satellite"),
    ];
  } else {
    args = [
      "-m", "quant_a.portfolio_web", "add-trade",
      "--date", String(body.date),
      "--code", String(body.code),
      "--name", String(body.name ?? ""),
      "--action", String(body.action),
      "--shares", String(body.shares),
      "--price", String(body.price),
      "--fee", String(body.fee ?? 0),
      "--sleeve", String(body.sleeve ?? ""),
      "--strategy", String(body.strategy ?? "core_satellite"),
    ];
  }
  const r = await runPython(args, 30000);
  if (!r.ok) return NextResponse.json({ error: r.error }, { status: 500 });
  return NextResponse.json(r.data);
}
