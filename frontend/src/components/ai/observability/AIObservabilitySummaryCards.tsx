import type { AIObservabilitySummary } from "../../../lib/aiObservability";

type Props = {
  summary: AIObservabilitySummary;
};

function formatLatency(value: number | null) {
  if (value === null) return "-";
  if (value >= 1000) return `${(value / 1000).toFixed(1)}s`;
  return `${value}ms`;
}

export function AIObservabilitySummaryCards({ summary }: Props) {
  const retryCount = summary.totals.ai_provider_retrying + summary.totals.outbound_delivery_retrying;
  const cards = [
    { label: "IA agendada", value: summary.totals.ai_scheduled },
    { label: "IA sucesso", value: summary.totals.ai_provider_success },
    { label: "IA falha", value: summary.totals.ai_provider_failed },
    { label: "Delivery sucesso", value: summary.totals.outbound_delivery_success },
    { label: "Delivery falha", value: summary.totals.outbound_delivery_failed },
    { label: "Retentativas", value: retryCount },
    { label: "Latencia IA", value: formatLatency(summary.latency.ai_avg_latency_ms) },
    { label: "Latencia delivery", value: formatLatency(summary.latency.delivery_avg_latency_ms) }
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((card) => (
        <div key={card.label} className="rounded-card border border-app-border bg-app-bg p-4">
          <p className="text-xs font-medium uppercase text-app-muted">{card.label}</p>
          <p className="mt-2 text-2xl font-semibold text-white">{card.value}</p>
        </div>
      ))}
    </div>
  );
}
