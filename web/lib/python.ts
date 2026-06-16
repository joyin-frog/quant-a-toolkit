import { spawn } from "node:child_process";
import path from "node:path";

// 以子进程调项目的 Python（quant_a.*），解析它打到 stdout 的最后一行 JSON。
// venv 默认用 项目根/.venv，可用 QUANT_PYTHON 覆盖（git worktree 开发时 venv 在主检出）。
export function runPython<T = unknown>(
  args: string[],
  timeoutMs = 180000,
): Promise<{ ok: true; data: T } | { ok: false; error: string }> {
  const projectRoot = path.resolve(process.cwd(), "..");
  const python = process.env.QUANT_PYTHON || path.join(projectRoot, ".venv", "bin", "python");
  return new Promise((resolve) => {
    const proc = spawn(python, args, {
      cwd: projectRoot,
      env: { ...process.env, PYTHONPATH: "src" },
    });
    let out = "";
    let err = "";
    const timer = setTimeout(() => {
      proc.kill();
      resolve({ ok: false, error: "运行超时" });
    }, timeoutMs);
    proc.stdout.on("data", (d) => (out += d.toString()));
    proc.stderr.on("data", (d) => (err += d.toString()));
    proc.on("error", (e) => {
      clearTimeout(timer);
      resolve({ ok: false, error: e.message });
    });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        resolve({ ok: false, error: err.slice(-800) || `运行失败 (code ${code})` });
        return;
      }
      const line = out.trim().split("\n").filter(Boolean).pop() ?? "{}";
      try {
        resolve({ ok: true, data: JSON.parse(line) as T });
      } catch {
        resolve({ ok: false, error: "解析 Python 输出失败" });
      }
    });
  });
}
