import type { Icon } from "@phosphor-icons/react";
import { clsx } from "clsx";

type MetricCardProps = {
  label: string;
  value: string | number;
  detail: string;
  icon: Icon;
  tone?: "blue" | "green" | "neutral";
};

export function MetricCard({ label, value, detail, icon: IconComponent, tone = "neutral" }: MetricCardProps) {
  return (
    <section className="rounded-card border border-app-border bg-app-surface p-6 shadow-soft">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm leading-[22px] text-app-muted">{label}</p>
          <strong className="mt-2 block text-3xl font-semibold leading-[38px] text-app-text">{value}</strong>
        </div>
        <span
          className={clsx(
            "inline-flex h-11 w-11 items-center justify-center rounded-full",
            tone === "blue" && "bg-app-infoBg text-app-secondary",
            tone === "green" && "bg-app-successBg text-[#52C41A]",
            tone === "neutral" && "bg-app-menu text-app-muted"
          )}
        >
          <IconComponent size={22} weight="bold" />
        </span>
      </div>
      <p className="mt-4 text-sm leading-[22px] text-app-muted">{detail}</p>
    </section>
  );
}
