// 策略元数据类型 + 拉取 hook：唯一来源是后端注册表（/api/strategies → strategy_web --list）。
// 前端不再硬编码策略清单/参数/仓位分层；新增策略零前端改动。
import { useEffect, useState } from "react";

export type ParamSpec = {
  name: string;
  kind: "number" | "integer" | "choice" | "text";
  default: number | string;
  label: string;
  choices?: string[];
  minimum?: number;
  maximum?: number;
  step?: number;
};

export type SleeveSpec = { value: string; label: string };

// 调仓节奏：monthly=每月 day 号附近、daily_signal=按信号每日执行、none=纯记账无节奏
export type Cadence = { kind: "monthly" | "daily_signal" | "none"; day?: number };

export type StrategyMeta = {
  strategy_id: string;
  name: string;
  description: string;
  params: ParamSpec[];
  sleeves: SleeveSpec[];
  // false = 纯记账账户（手动实盘/纸面跟踪）：记账页可选，主页"生成清单"不显示
  runnable?: boolean;
  cadence?: Cadence;
};

export function useStrategies() {
  const [strategies, setStrategies] = useState<StrategyMeta[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetch("/api/strategies");
        const json = await res.json();
        if (!res.ok) throw new Error(json.error ?? "加载策略列表失败");
        if (alive) setStrategies(json as StrategyMeta[]);
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      alive = false;
    };
  }, []);
  return { strategies, error };
}

export const hasParam = (meta: StrategyMeta | undefined, name: string) =>
  Boolean(meta?.params.some((p) => p.name === name));
