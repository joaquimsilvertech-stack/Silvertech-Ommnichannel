import type { AIObservabilityPeriod } from "../../../lib/aiObservability";

type Props = {
  value: AIObservabilityPeriod;
  onChange: (period: AIObservabilityPeriod) => void;
};

const PERIODS: Array<{ label: string; value: AIObservabilityPeriod }> = [
  { label: "24h", value: "24h" },
  { label: "7d", value: "7d" },
  { label: "30d", value: "30d" }
];

export function AIObservabilityPeriodFilter({ value, onChange }: Props) {
  return (
    <div className="inline-flex rounded-control border border-app-border bg-app-bg p-1" aria-label="Periodo da observabilidade">
      {PERIODS.map((period) => (
        <button
          key={period.value}
          type="button"
          className={
            value === period.value
              ? "rounded-control bg-app-primary px-3 py-1.5 text-xs font-semibold text-white"
              : "rounded-control px-3 py-1.5 text-xs font-semibold text-app-muted hover:text-white"
          }
          onClick={() => onChange(period.value)}
        >
          {period.label}
        </button>
      ))}
    </div>
  );
}
