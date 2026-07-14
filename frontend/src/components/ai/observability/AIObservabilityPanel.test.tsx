import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AIObservabilityPanel } from "./AIObservabilityPanel";

const useSummaryMock = vi.fn();
const useTimeseriesMock = vi.fn();
const useEventsMock = vi.fn();

vi.mock("../../../hooks/useAIObservability", () => ({
  useAIObservabilitySummary: (...args: unknown[]) => useSummaryMock(...args),
  useAIObservabilityTimeseries: (...args: unknown[]) => useTimeseriesMock(...args),
  useAIObservabilityEvents: (...args: unknown[]) => useEventsMock(...args)
}));

const summary = {
  workspace_id: "workspace-1",
  period: "24h",
  totals: {
    ai_scheduled: 10,
    ai_skipped: 2,
    ai_provider_attempt: 10,
    ai_provider_success: 8,
    ai_provider_failed: 1,
    ai_provider_retrying: 1,
    outbound_delivery_attempt: 8,
    outbound_delivery_success: 7,
    outbound_delivery_failed: 1,
    outbound_delivery_retrying: 1
  },
  rates: {
    ai_success_rate: 0.88,
    delivery_success_rate: 0.87
  },
  latency: {
    ai_avg_latency_ms: 1234,
    delivery_avg_latency_ms: 500
  },
  by_provider: [],
  errors: []
};

const timeseries = {
  workspace_id: "workspace-1",
  period: "24h",
  bucket: "hour",
  points: [
    {
      timestamp: "2026-07-14T10:00:00Z",
      ai_success: 8,
      ai_failed: 1,
      delivery_success: 7,
      delivery_failed: 1
    }
  ]
};

const events = {
  results: [
    {
      id: "event-1",
      created_at: "2026-07-14T10:10:00Z",
      event_type: "AI_PROVIDER_SUCCESS",
      status: "success",
      provider: "openai",
      model_name: "gpt-4o-mini",
      reason_code: "",
      error_code: "",
      latency_ms: 1234,
      attempt_count: 1,
      metadata: {
        source: "process_ai_response",
        api_key: "sk-secret",
        body: "conteudo sensivel",
        prompt: "prompt sensivel"
      }
    }
  ]
};

function mockReadyState() {
  useSummaryMock.mockReturnValue({ data: summary, isLoading: false, error: undefined });
  useTimeseriesMock.mockReturnValue({ data: timeseries, isLoading: false, error: undefined });
  useEventsMock.mockReturnValue({ data: events, isLoading: false, error: undefined });
}

describe("AIObservabilityPanel", () => {
  beforeEach(() => {
    useSummaryMock.mockReset();
    useTimeseriesMock.mockReset();
    useEventsMock.mockReset();
    mockReadyState();
  });

  it("renderiza cards, serie temporal e eventos recentes", () => {
    render(<AIObservabilityPanel workspaceId="workspace-1" />);

    expect(screen.getByText("IA agendada")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("IA sucesso")).toBeInTheDocument();
    expect(screen.getByText("AI_PROVIDER_SUCCESS")).toBeInTheDocument();
    expect(screen.getByText("gpt-4o-mini")).toBeInTheDocument();
    expect(screen.getByText("IA ok: 8")).toBeInTheDocument();
  });

  it("altera periodo das queries", async () => {
    const user = userEvent.setup();

    render(<AIObservabilityPanel workspaceId="workspace-1" />);
    await user.click(screen.getByRole("button", { name: "7d" }));

    expect(useSummaryMock).toHaveBeenLastCalledWith("workspace-1", "7d");
    expect(useTimeseriesMock).toHaveBeenLastCalledWith("workspace-1", "7d");
    expect(useEventsMock).toHaveBeenLastCalledWith("workspace-1", { period: "7d", limit: 25 });
  });

  it("renderiza loading e erro sanitizado", () => {
    useSummaryMock.mockReturnValueOnce({ data: undefined, isLoading: true, error: undefined });
    useTimeseriesMock.mockReturnValueOnce({ data: undefined, isLoading: false, error: undefined });
    useEventsMock.mockReturnValueOnce({ data: undefined, isLoading: false, error: undefined });
    const { rerender } = render(<AIObservabilityPanel workspaceId="workspace-1" />);

    expect(screen.getByText("Carregando observabilidade...")).toBeInTheDocument();

    useSummaryMock.mockReturnValueOnce({
      data: undefined,
      isLoading: false,
      error: { normalized: { message: "Erro sanitizado.", fieldErrors: {} } }
    });
    useTimeseriesMock.mockReturnValueOnce({ data: undefined, isLoading: false, error: undefined });
    useEventsMock.mockReturnValueOnce({ data: undefined, isLoading: false, error: undefined });
    rerender(<AIObservabilityPanel workspaceId="workspace-1" />);

    expect(screen.getByRole("alert")).toHaveTextContent("Erro sanitizado.");
  });

  it("nao renderiza metadados sensiveis dos eventos", () => {
    render(<AIObservabilityPanel workspaceId="workspace-1" />);

    expect(screen.queryByText("sk-secret")).not.toBeInTheDocument();
    expect(screen.queryByText("conteudo sensivel")).not.toBeInTheDocument();
    expect(screen.queryByText("prompt sensivel")).not.toBeInTheDocument();
  });

  it("renderiza estado vazio", () => {
    useSummaryMock.mockReturnValueOnce({ data: summary, isLoading: false, error: undefined });
    useTimeseriesMock.mockReturnValueOnce({ data: { ...timeseries, points: [] }, isLoading: false, error: undefined });
    useEventsMock.mockReturnValueOnce({ data: { results: [] }, isLoading: false, error: undefined });

    render(<AIObservabilityPanel workspaceId="workspace-1" />);

    expect(screen.getByText("Sem buckets no periodo selecionado.")).toBeInTheDocument();
    expect(screen.getByText("Nenhum evento no periodo selecionado.")).toBeInTheDocument();
  });
});
