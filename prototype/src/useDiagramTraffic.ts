import { useEffect, useState } from "react";
import { jsonRequest } from "./api";
import type { DiagramTraffic, DiagramTrafficRequest } from "./diagramTraffic";

export function useDiagramTraffic(
  enabled: boolean,
  request: DiagramTrafficRequest | null,
) {
  const key = JSON.stringify(request);
  const [result, setResult] = useState<{
    key: string;
    data: DiagramTraffic;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setResult(null);
    setError("");
    setLoading(false);
    if (!enabled || key === "null") return;
    setLoading(true);
    void jsonRequest<DiagramTraffic>("/api/traffic/diagram", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: key,
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
