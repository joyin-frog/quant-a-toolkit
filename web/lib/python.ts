import { spawn } from "node:child_process";
import path from "node:path";

// eastmoney 不走系统代理（akshare 抓数）。
const NO_PROXY_HOSTS = ".eastmoney.com,push2his.eastmoney.com,.csindex.com.cn";

// 以子进程调项目的 Python（quant_a.*），解析它打到 stdout 的最后一行 JSON。
// venv 默认用 项目根/.venv，可用 QUANT_PYTHON 覆盖（git worktree 开发时 venv 在主检出）。
// 全程把调用/耗时/退出码打到 dev 终端，并实时转发 Python 的 stderr（进度/报错），方便排查。
export function runPython<T = unknown>(
  args: string[],
  timeoutMs = 180000,
  stdin?: string,
): Promise<{ ok: true; data: T } | { ok: false; error: string }> {
  const projectRoot = path.resolve(process.cwd(), "..");
  const python = process.env.QUANT_PYTHON || path.join(projectRoot, ".venv", "bin", "python");
  const label = `quant_a ${args.join(" ")}`;
  const t0 = Date.now();
  console.log(`[py] ▶ ${label}`);
  return new Promise((resolve) => {
    const proc = spawn(python, args, {
      cwd: projectRoot,
      env: {
        ...process.env,
        PYTHONPATH: "src",
        NO_PROXY: process.env.NO_PROXY ? `${process.env.NO_PROXY},${NO_PROXY_HOSTS}` : NO_PROXY_HOSTS,
        no_proxy: process.env.no_proxy ? `${process.env.no_proxy},${NO_PROXY_HOSTS}` : NO_PROXY_HOSTS,
      },
    });
    if (stdin !== undefined) {
      proc.stdin.write(stdin);
      proc.stdin.end();
    }
    let out = "";
    let err = "";
    const timer = setTimeout(() => {
      console.error(`[py] ⏱ 超时（${timeoutMs / 1000}s）已杀掉 ${label}`);
      proc.kill();
      resolve({ ok: false, error: "运行超时" });
    }, timeoutMs);
    proc.stdout.on("data", (d) => (out += d.toString()));
    proc.stderr.on("data", (d) => {
      const s = d.toString();
      err += s;
      // 实时把 Python 的进度/报错转到 dev 终端（每行加 [py] 前缀）。
      process.stderr.write(s.replace(/^/gm, "[py] "));
    });
    proc.on("error", (e) => {
      clearTimeout(timer);
      console.error(`[py] ✖ 无法启动 Python：${e.message}（python=${python}）`);
      resolve({ ok: false, error: `无法启动 Python：${e.message}` });
    });
    proc.on("close", (code) => {
      clearTimeout(timer);
      const dt = ((Date.now() - t0) / 1000).toFixed(1);
      if (code !== 0) {
        console.error(`[py] ✖ ${label} 退出码=${code} 用时=${dt}s`);
        resolve({ ok: false, error: err.slice(-800) || `运行失败 (code ${code})` });
        return;
      }
      console.log(`[py] ✓ ${label} 用时=${dt}s`);
      const line = out.trim().split("\n").filter(Boolean).pop() ?? "{}";
      try {
        resolve({ ok: true, data: JSON.parse(line) as T });
      } catch {
        console.error(`[py] ✖ 解析输出失败，最后一行：${line.slice(0, 200)}`);
        resolve({ ok: false, error: "解析 Python 输出失败" });
      }
    });
  });
}
