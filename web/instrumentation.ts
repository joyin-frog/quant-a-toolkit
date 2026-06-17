// Next 启动钩子。Node 专属的配置体检放到 ./instrumentation-node，仅在 nodejs runtime 动态导入，
// 否则 node:fs / node:path 会被 Edge runtime 的打包分析报警（虽不影响运行，但污染日志）。
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("./instrumentation-node");
  }
}
