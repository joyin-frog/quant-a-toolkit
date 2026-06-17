import { spawn } from "node:child_process";
import path from "node:path";
import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const maxDuration = 600;

// 刷新沪深300+AI行情到最新交易日（调 quant_a.refresh_cs）。约 3-5 分钟。
export async function POST() {
  const projectRoot = path.resolve(process.cwd(), "..");
  const python = process.env.QUANT_PYTHON || path.join(projectRoot, ".venv", "bin", "python");

  return new Promise<Response>((resolve) => {
    const noProxy = ".eastmoney.com,push2his.eastmoney.com,.csindex.com.cn";
    const proc = spawn(python, ["-m", "quant_a.refresh_cs"], {
      cwd: projectRoot,
      env: {
        ...process.env,
        PYTHONPATH: "src",
        NO_PROXY: process.env.NO_PROXY ? `${process.env.NO_PROXY},${noProxy}` : noProxy,
        no_proxy: process.env.no_proxy ? `${process.env.no_proxy},${noProxy}` : noProxy,
      },
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
        resolve(NextResponse.json({ error: err.slice(-800) || `刷新失败 (code ${code})` }, { status: 500 }));
        return;
      }
      const line = out.trim().split("\n").filter(Boolean).pop() ?? "{}";
      try {
        resolve(NextResponse.json(JSON.parse(line)));
      } catch {
        resolve(NextResponse.json({ error: "解析刷新结果失败" }, { status: 500 }));
      }
    });
  });
}
