import { spawn } from "node:child_process";
import path from "node:path";
import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const maxDuration = 180;

// 网页后端：以子进程方式调用项目的 Python 策略（quant_a.cs_web），把它打到 stdout 的 JSON 透传给前端。
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const capital = Number(body.capital ?? 200000);
  const holdings = Number(body.holdings ?? 17);
  const aiWeight = Number(body.aiWeight ?? 0.15);

  // 项目根 = web/ 的上一级；Python 解释器默认用项目根的 .venv，可用 QUANT_PYTHON 覆盖
  // （本仓库在 git worktree 里开发时 venv 在主检出，需要覆盖）。
  const projectRoot = path.resolve(process.cwd(), "..");
  const python = process.env.QUANT_PYTHON || path.join(projectRoot, ".venv", "bin", "python");
  const args = [
    "-m", "quant_a.cs_web",
    "--capital", String(capital),
    "--holdings", String(holdings),
    "--ai_weight", String(aiWeight),
  ];

  return new Promise<Response>((resolve) => {
    const proc = spawn(python, args, {
      cwd: projectRoot,
      env: { ...process.env, PYTHONPATH: "src" },
    });
    let out = "";
    let err = "";
    proc.stdout.on("data", (d) => (out += d.toString()));
    proc.stderr.on("data", (d) => (err += d.toString()));
    proc.on("error", (e) =>
      resolve(NextResponse.json({ error: `无法启动 Python：${e.message}` }, { status: 500 })),
    );
    proc.on("close", (code) => {
      if (code !== 0) {
        resolve(NextResponse.json({ error: err.slice(-800) || `策略运行失败 (code ${code})` }, { status: 500 }));
        return;
      }
      // stdout 最后一行是 JSON（前面可能有零星告警）。
      const line = out.trim().split("\n").filter(Boolean).pop() ?? "";
      try {
        resolve(NextResponse.json(JSON.parse(line)));
      } catch {
        resolve(NextResponse.json({ error: "解析策略结果失败", raw: out.slice(-500) }, { status: 500 }));
      }
    });
  });
}
