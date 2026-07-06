// 策略元数据类型 + 拉取 hook：唯一来源是后端注册表（/api/strategies → strategy_web --list）。
// 前端不再硬编码策略清单/参数/仓位分层；新增策略零前端改动。
import { useEffect, useState } from "react";

export type ParamSpec = {
  name: string;
  kind: "number" | "integer" | "choice";
  default: number | string;
  label: string;
  choices?: string[];
  minimum?: number;
  maximum?: number;
  step?: number;
};

export type SleeveSpec = { value: string; label: string };

export type StrategyMeta = {
  strategy_id: string;
  name: string;
  description: string;
  params: ParamSpec[];
  sleeves: SleeveSpec[];
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
