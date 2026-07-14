import { api } from "./api";
import { normalizeApiError, type NormalizedApiError } from "./apiErrors";

export type AIObservabilityPeriod = "24h" | "7d" | "30d";

export type AIObservabilityFilters = {
  period?: AIObservabilityPeriod;
  provider?: string;
  event_type?: string;
  status?: string;
  error_code?: string;
  limit?: number;
};

export type AIObservabilityTotals = {
  ai_scheduled: number;
  ai_skipped: number;
  ai_provider_attempt: number;
  ai_provider_success: number;
  ai_provider_failed: number;
  ai_provider_retrying: number;
  outbound_delivery_attempt: number;
  outbound_delivery_success: number;
  outbound_delivery_failed: number;
  outbound_delivery_retrying: number;
};

export type AIObservabilitySummary = {
  workspace_id: string;
  period: AIObservabilityPeriod;
  totals: AIObservabilityTotals;
  rates: {
    ai_success_rate: number;
    delivery_success_rate: number;
  };
  latency: {
    ai_avg_latency_ms: number | null;
    delivery_avg_latency_ms: number | null;
  };
  by_provider: Array<{
    provider: string;
    model_name: string;
    success: number;
    failed: number;
    retrying: number;
  }>;
  errors: Array<{
    error_code: string;
    count: number;
  }>;
};

export type AIObservabilityTimeseriesPoint = {
  timestamp: string;
  ai_success: number;
  ai_failed: number;
  delivery_success: number;
  delivery_failed: number;
};

export type AIObservabilityTimeseries = {
  workspace_id: string;
  period: AIObservabilityPeriod;
  bucket: "hour" | "day";
  points: AIObservabilityTimeseriesPoint[];
};

export type AIObservabilityEvent = {
  id: string;
  created_at: string;
  event_type: string;
  status: string;
  provider: string;
  model_name: string;
  reason_code: string;
  error_code: string;
  latency_ms: number | null;
  attempt_count: number | null;
  metadata: Record<string, unknown>;
};

export type AIObservabilityEventsResponse = {
  results: AIObservabilityEvent[];
};

export class AIObservabilityApiError extends Error {
  normalized: NormalizedApiError;

  constructor(error: unknown) {
    const normalized = normalizeApiError(error);
    super(normalized.message);
    this.name = "AIObservabilityApiError";
    this.normalized = normalized;
  }
}

function observabilityBaseUrl(workspaceId: string | number) {
  return `/api/workspaces/${workspaceId}/ai-observability/`;
}

function sanitizeFilters(filters: AIObservabilityFilters = {}) {
  const params: Record<string, string | number> = {};
  if (filters.period) params.period = filters.period;
  if (filters.provider) params.provider = filters.provider;
  if (filters.event_type) params.event_type = filters.event_type;
  if (filters.status) params.status = filters.status;
  if (filters.error_code) params.error_code = filters.error_code;
  if (filters.limit !== undefined) params.limit = filters.limit;
  return params;
}

async function wrapObservabilityRequest<T>(request: Promise<{ data: T }>): Promise<T> {
  try {
    const { data } = await request;
    return data;
  } catch (error) {
    throw new AIObservabilityApiError(error);
  }
}

export async function getAIObservabilitySummary(
  workspaceId: string | number,
  filters: AIObservabilityFilters = {}
) {
  return wrapObservabilityRequest<AIObservabilitySummary>(
    api.get(`${observabilityBaseUrl(workspaceId)}summary/`, { params: sanitizeFilters(filters) })
  );
}

export async function getAIObservabilityTimeseries(
  workspaceId: string | number,
  filters: AIObservabilityFilters = {}
) {
  return wrapObservabilityRequest<AIObservabilityTimeseries>(
    api.get(`${observabilityBaseUrl(workspaceId)}timeseries/`, { params: sanitizeFilters(filters) })
  );
}

export async function getAIObservabilityEvents(
  workspaceId: string | number,
  filters: AIObservabilityFilters = {}
) {
  return wrapObservabilityRequest<AIObservabilityEventsResponse>(
    api.get(`${observabilityBaseUrl(workspaceId)}events/`, { params: sanitizeFilters(filters) })
  );
}
