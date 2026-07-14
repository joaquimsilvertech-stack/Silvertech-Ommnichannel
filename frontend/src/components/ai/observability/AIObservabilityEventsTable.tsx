import type { AIObservabilityEvent } from "../../../lib/aiObservability";

type Props = {
  events: AIObservabilityEvent[];
};

function formatDate(value: string) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short"
  }).format(new Date(value));
}

function formatValue(value: string | number | null) {
  if (value === null || value === "") return "-";
  return String(value);
}

export function AIObservabilityEventsTable({ events }: Props) {
  if (!events.length) {
    return (
      <div className="rounded-card border border-dashed border-app-border bg-app-bg p-6 text-center text-sm text-app-muted">
        Nenhum evento no periodo selecionado.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-card border border-app-border bg-app-bg">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-app-border text-left text-sm">
          <thead className="bg-app-surface text-xs font-semibold uppercase text-app-muted">
            <tr>
              <th className="px-4 py-3">Data</th>
              <th className="px-4 py-3">Evento</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Provider</th>
              <th className="px-4 py-3">Modelo</th>
              <th className="px-4 py-3">Reason</th>
              <th className="px-4 py-3">Erro</th>
              <th className="px-4 py-3">Latencia</th>
              <th className="px-4 py-3">Tentativa</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-app-border">
            {events.map((event) => (
              <tr key={event.id} className="text-app-text">
                <td className="whitespace-nowrap px-4 py-3 text-app-muted">{formatDate(event.created_at)}</td>
                <td className="whitespace-nowrap px-4 py-3 font-medium text-white">{event.event_type}</td>
                <td className="whitespace-nowrap px-4 py-3">{event.status}</td>
                <td className="whitespace-nowrap px-4 py-3">{formatValue(event.provider)}</td>
                <td className="whitespace-nowrap px-4 py-3">{formatValue(event.model_name)}</td>
                <td className="whitespace-nowrap px-4 py-3">{formatValue(event.reason_code)}</td>
                <td className="whitespace-nowrap px-4 py-3">{formatValue(event.error_code)}</td>
                <td className="whitespace-nowrap px-4 py-3">{formatValue(event.latency_ms)}</td>
                <td className="whitespace-nowrap px-4 py-3">{formatValue(event.attempt_count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
