import { useQuery } from "@tanstack/react-query";
import {
  getAIObservabilityEvents,
  getAIObservabilitySummary,
  getAIObservabilityTimeseries,
  type AIObservabilityFilters,
  type AIObservabilityPeriod
} from "../lib/aiObservability";

const STALE_TIME_MS = 30_000;

function queryKeyFilters(filters: AIObservabilityFilters = {}) {
  const { period, provider, event_type, status, error_code, limit } = filters;
  return { period, provider, event_type, status, error_code, limit };
}

export const aiObservabilityQueryKey = (
  workspaceId: string | number | undefined,
  filters: AIObservabilityFilters = {}
) => ["workspaces", workspaceId, "ai-observability", queryKeyFilters(filters)];

export function useAIObservabilitySummary(
  workspaceId: string | number | undefined,
  period: AIObservabilityPeriod = "24h"
) {
  const filters = { period };
  return useQuery({
    queryKey: [...aiObservabilityQueryKey(workspaceId), "summary", filters],
    queryFn: () => getAIObservabilitySummary(workspaceId!, filters),
    enabled: Boolean(workspaceId),
    staleTime: STALE_TIME_MS
  });
}

export function useAIObservabilityTimeseries(
  workspaceId: string | number | undefined,
  period: AIObservabilityPeriod = "24h"
) {
  const filters = { period };
  return useQuery({
    queryKey: [...aiObservabilityQueryKey(workspaceId), "timeseries", filters],
    queryFn: () => getAIObservabilityTimeseries(workspaceId!, filters),
    enabled: Boolean(workspaceId),
    staleTime: STALE_TIME_MS
  });
}

export function useAIObservabilityEvents(
  workspaceId: string | number | undefined,
  filters: AIObservabilityFilters = {}
) {
  return useQuery({
    queryKey: [...aiObservabilityQueryKey(workspaceId), "events", filters],
    queryFn: () => getAIObservabilityEvents(workspaceId!, filters),
    enabled: Boolean(workspaceId),
    staleTime: STALE_TIME_MS
  });
}
