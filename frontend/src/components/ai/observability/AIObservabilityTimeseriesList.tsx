import type { AIObservabilityTimeseries } from "../../../lib/aiObservability";

type Props = {
  timeseries: AIObservabilityTimeseries;
};

function formatDate(value: string) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short"
  }).format(new Date(value));
}

export function AIObservabilityTimeseriesList({ timeseries }: Props) {
  const points = timeseries.points.slice(-6).reverse();

  if (!points.length) {
    return (
      <div className="rounded-card border border-dashed border-app-border bg-app-bg p-6 text-center text-sm text-app-muted">
        Sem buckets no periodo selecionado.
      </div>
    );
  }

  return (
    <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
      {points.map((point) => (
        <div key={point.timestamp} className="rounded-card border border-app-border bg-app-bg p-3">
          <p className="text-xs text-app-muted">{formatDate(point.timestamp)}</p>
          <div className="mt-2 grid grid-cols-2 gap-2 text-sm text-app-text">
            <span>IA ok: {point.ai_success}</span>
            <span>IA falha: {point.ai_failed}</span>
            <span>Envio ok: {point.delivery_success}</span>
            <span>Envio falha: {point.delivery_failed}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
