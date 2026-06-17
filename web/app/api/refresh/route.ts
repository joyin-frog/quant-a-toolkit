import { spawn } from "node:child_process";
import path from "node:path";

export const runtime = "nodejs";
export const maxDuration = 600;

const NO_PROXY_HOSTS = ".eastmoney.com,push2his.eastmoney.com,.csindex.com.cn";

// 刷新沪深300+AI行情（quant_a.refresh_cs，并行两遍）。流式返回 NDJSON：
//   {"type":"progress","done":120,"total":261,"fail":3,"phase":"pull"|"retry"}  逐条
//   {"type":"result", ...refresh的JSON}  或  {"type":"error","error":"..."}    最后一条
// 前端据此画进度条。Python 的 PROGRESS: 行从 stderr 解析,其余 stderr 照常打到 dev 终端。
export async function POST() {
  const projectRoot = path.resolve(process.cwd(), "..");
  const python = process.env.QUANT_PYTHON || path.join(projectRoot, ".venv", "bin", "python");
  const enc = new TextEncoder();
  const t0 = Date.now();

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      console.log("[py] ▶ quant_a -m quant_a.refresh_cs (stream)");
      const proc = spawn(python, ["-m", "quant_a.refresh_cs"], {
        cwd: projectRoot,
        env: {
          ...process.env,
          PYTHONPATH: "src",
          NO_PROXY: process.env.NO_PROXY ? `${process.env.NO_PROXY},${NO_PROXY_HOSTS}` : NO_PROXY_HOSTS,
          no_proxy: process.env.no_proxy ? `${process.env.no_proxy},${NO_PROXY_HOSTS}` : NO_PROXY_HOSTS,
        },
      });
      const send = (obj: unknown) => controller.enqueue(enc.encode(JSON.stringify(obj) + "\n"));
      let out = "";
      let errBuf = "";

      proc.stdout.on("data", (d) => (out += d.toString()));
      proc.stderr.on("data", (d) => {
        const s = d.toString();
        process.stderr.write(s.replace(/^/gm, "[py] ")); // dev 终端照常看
        errBuf += s;
        let i: number;
        while ((i = errBuf.indexOf("\n")) >= 0) {
          const line = errBuf.slice(0, i);
          errBuf = errBuf.slice(i + 1);
          const m = line.match(/^PROGRESS:(.+)$/);
          if (m) {
            try {
              send({ type: "progress", ...JSON.parse(m[1]) });
            } catch {
              /* 进度行损坏就跳过 */
            }
          }
        }
      });
      proc.on("error", (e) => {
        console.error(`[py] ✖ 无法启动 Python：${e.message}`);
        send({ type: "error", error: `无法启动 Python：${e.message}` });
        controller.close();
      });
      proc.on("close", (code) => {
        const dt = ((Date.now() - t0) / 1000).toFixed(1);
        console.log(`[py] ${code === 0 ? "✓" : "✖"} refresh 用时=${dt}s 退出码=${code}`);
        const jsonLine = out.trim().split("\n").filter(Boolean).pop() ?? "{}";
        if (code === 0) {
          try {
            send({ type: "result", result: JSON.parse(jsonLine) });
          } catch {
            send({ type: "error", error: "解析刷新结果失败" });
          }
        } else {
          send({ type: "error", error: "刷新失败（详见终端日志）" });
        }
        controller.close();
      });
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "application/x-ndjson; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
