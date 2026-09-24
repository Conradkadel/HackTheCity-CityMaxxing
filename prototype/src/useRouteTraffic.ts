import { useEffect, useState } from "react";
import { jsonRequest } from "./api";
import type { RouteTraffic } from "./traffic";

export function useRouteTraffic(enabled: boolean, routeKeys: string[]) {
  const key = JSON.stringify(routeKeys);
  const [result, setResult] = useState<{
    key: string;
    data: RouteTraffic;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setResult(null);
    setError("");
    setLoading(false);
    if (!enabled || key === "[]") return;
    setLoading(true);
    void jsonRequest<RouteTraffic>("/api/traffic/routes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ route_keys: JSON.parse(key) }),
      signal: controller.signal,
    })
      .then((data) => {
        if (!controller.signal.aborted) setResult({ key, data });
      })
      .catch((reason: Error) => {
        if (!controller.signal.aborted) setError(reason.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [enabled, key, attempt]);
  return {
    data: enabled && result?.key === key ? result.data : null,
    loading,
    error,
    retry: () => setAttempt((value) => value + 1),
  };
}
