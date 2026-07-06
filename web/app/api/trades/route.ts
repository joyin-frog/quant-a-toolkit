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
  // 批量记账（一键按清单入账）：trades/flows 经 stdin JSON 传给 add-batch
  if (body.kind === "batch") {
    const strategy = String(body.strategy ?? "");
    if (!strategy) return NextResponse.json({ error: "缺少账户" }, { status: 400 });
    const r = await runPython(
      ["-m", "quant_a.portfolio_web", "add-batch", "--strategy", strategy],
      30000,
      JSON.stringify({ trades: body.trades ?? [], flows: body.flows ?? [] }),
    );
    if (!r.ok) return NextResponse.json({ error: r.error }, { status: 500 });
    return NextResponse.json(r.data);
  }
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

// 删除一笔记录（记错了删掉重录）。?id=&strategy=&kind=trade|cash
export async function DELETE(req: Request) {
  const url = new URL(req.url);
  const id = url.searchParams.get("id");
  const strategy = url.searchParams.get("strategy");
  const kind = url.searchParams.get("kind") === "cash" ? "del-cash" : "del-trade";
  if (!id || !strategy) return NextResponse.json({ error: "缺少 id 或账户" }, { status: 400 });
  const r = await runPython(["-m", "quant_a.portfolio_web", kind, "--id", id, "--strategy", strategy], 30000);
  if (!r.ok) return NextResponse.json({ error: r.error }, { status: 500 });
  return NextResponse.json(r.data);
}
