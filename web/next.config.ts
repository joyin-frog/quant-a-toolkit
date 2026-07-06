import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 仓库上层还有 package-lock；显式限定 web，避免 Turbopack 扫描 ../.venv 的外部符号链接。
  turbopack: { root: process.cwd() },
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;
