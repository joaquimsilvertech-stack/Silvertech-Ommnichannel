import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import {
  getAIObservabilityEvents,
  getAIObservabilitySummary,
  getAIObservabilityTimeseries
} from "./aiObservability";

describe("aiObservability API client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("chama URLs corretas para summary, timeseries e events", async () => {
    const spy = vi.spyOn(api, "get").mockResolvedValue({ data: { results: [] } });

    await getAIObservabilitySummary("workspace-1", { period: "24h" });
    await getAIObservabilityTimeseries("workspace-1", { period: "7d" });
    await getAIObservabilityEvents("workspace-1", { period: "30d", limit: 10 });

    expect(spy).toHaveBeenNthCalledWith(1, "/api/workspaces/workspace-1/ai-observability/summary/", {
      params: { period: "24h" }
    });
    expect(spy).toHaveBeenNthCalledWith(2, "/api/workspaces/workspace-1/ai-observability/timeseries/", {
      params: { period: "7d" }
    });
    expect(spy).toHaveBeenNthCalledWith(3, "/api/workspaces/workspace-1/ai-observability/events/", {
      params: { period: "30d", limit: 10 }
    });
  });

  it("nao inclui segredo em filtros enviados", async () => {
    const spy = vi.spyOn(api, "get").mockResolvedValueOnce({ data: { results: [] } });

    await getAIObservabilityEvents("workspace-1", {
      period: "24h",
      provider: "openai",
      status: "failed",
      error_code: "AI_PROVIDER_TIMEOUT",
      api_key: "sk-secret",
      body: "conteudo"
    } as never);

    expect(spy).toHaveBeenCalledWith("/api/workspaces/workspace-1/ai-observability/events/", {
      params: {
        period: "24h",
        provider: "openai",
        status: "failed",
        error_code: "AI_PROVIDER_TIMEOUT"
      }
    });
  });
});
