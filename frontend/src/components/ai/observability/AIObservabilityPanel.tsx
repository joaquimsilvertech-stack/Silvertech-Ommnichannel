import { useMemo, useState } from "react";
import { Robot } from "@phosphor-icons/react";
import { normalizeApiError } from "../../../lib/apiErrors";
import type { AIObservabilityPeriod } from "../../../lib/aiObservability";
import {
  useAIObservabilityEvents,
  useAIObservabilitySummary,
  useAIObservabilityTimeseries
} from "../../../hooks/useAIObservability";
import { AIObservabilityEventsTable } from "./AIObservabilityEventsTable";
import { AIObservabilityPeriodFilter } from "./AIObservabilityPeriodFilter";
import { AIObservabilitySummaryCards } from "./AIObservabilitySummaryCards";
import { AIObservabilityTimeseriesList } from "./AIObservabilityTimeseriesList";

type Props = {
  workspaceId: string | number;
};

export function AIObservabilityPanel({ workspaceId }: Props) {
  const [period, setPeriod] = useState<AIObservabilityPeriod>("24h");
  const eventsFilters = useMemo(() => ({ period, limit: 25 }), [period]);
  const summaryQuery = useAIObservabilitySummary(workspaceId, period);
  const timeseriesQuery = useAIObservabilityTimeseries(workspaceId, period);
  const eventsQuery = useAIObservabilityEvents(workspaceId, eventsFilters);
  const isLoading = summaryQuery.isLoading || timeseriesQuery.isLoading || eventsQuery.isLoading;
  const error = summaryQuery.error || timeseriesQuery.error || eventsQuery.error;

  return (
    <section className="rounded-card border border-app-border bg-app-surface p-5 shadow-soft">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-control bg-app-infoBg text-app-secondary">
            <Robot size={20} weight="bold" />
          </span>
          <div>
            <h2 className="text-base font-semibold text-white">Observabilidade da IA</h2>
            <p className="text-sm text-app-muted">Eventos e metricas do workspace.</p>
          </div>
        </div>
        <AIObservabilityPeriodFilter value={period} onChange={setPeriod} />
      </div>

      {isLoading ? (
        <p className="mt-5 rounded-card border border-app-border bg-app-bg p-6 text-sm text-app-muted">
          Carregando observabilidade...
        </p>
      ) : error ? (
        <p className="mt-5 rounded-card border border-red-500/30 bg-red-500/10 p-6 text-sm text-red-100" role="alert">
          {normalizeApiError(error).message}
        </p>
      ) : summaryQuery.data && timeseriesQuery.data && eventsQuery.data ? (
        <div className="mt-5 space-y-5">
          <AIObservabilitySummaryCards summary={summaryQuery.data} />
          <div>
            <h3 className="mb-3 text-sm font-semibold text-white">Serie temporal</h3>
            <AIObservabilityTimeseriesList timeseries={timeseriesQuery.data} />
          </div>
          <div>
            <h3 className="mb-3 text-sm font-semibold text-white">Eventos recentes</h3>
            <AIObservabilityEventsTable events={eventsQuery.data.results} />
          </div>
        </div>
      ) : null}
    </section>
  );
}
