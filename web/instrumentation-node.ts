// 仅在 nodejs runtime 被 instrumentation.ts 动态导入 → 启动时打印配置体检横幅。
// 一眼看到 Python 在哪、数据齐不齐——有 ✗/0 基本就是"刷新/生成不行"的原因。
import * as fs from "node:fs";
import * as path from "node:path";

const root = path.resolve(process.cwd(), "..");
const python = process.env.QUANT_PYTHON || path.join(root, ".venv", "bin", "python");
const dataDir = path.join(root, "data");
const mark = (p: string) => (fs.existsSync(p) ? "✓" : "✗ 缺失");
const nCache = fs.existsSync(dataDir)
  ? fs.readdirSync(dataDir).filter((f) => /^\d{6}\.csv$/.test(f)).length
  : 0;

const line = "─".repeat(60);
console.log(line);
console.log("[quant-a web] 启动 · 配置体检");
console.log(`  项目根       ${root}`);
console.log(`  Python       ${python}  ${mark(python)}`);
console.log(`  data/        ${dataDir}  ${mark(dataDir)}`);
console.log(`  hs300 清单   ${mark(path.join(dataDir, "hs300_mainboard.csv"))}   行情缓存 ${nCache} 只`);
console.log(`  portfolio.db ${mark(path.join(dataDir, "portfolio.db"))}`);
console.log(`  QUANT_PYTHON ${process.env.QUANT_PYTHON ? "已设置" : "未设置（用项目根 .venv）"}`);
if (!fs.existsSync(python) || nCache === 0) {
  console.log("  ⚠ 上面有 ✗ 或 缓存=0 → 刷新/生成会失败：先按 CLAUDE.md 装好 .venv、抓好 data/");
}
console.log(line);
