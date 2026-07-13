import { clsx } from "clsx";
import type { WorkspaceAIProviderConfig } from "../../lib/aiProviders";

type Props = {
  provider: Pick<WorkspaceAIProviderConfig, "is_active" | "has_api_key" | "is_supported">;
};

export function AIProviderStatusBadge({ provider }: Props) {
  const statuses = [
    {
      label: provider.is_active ? "Ativo" : "Inativo",
      tone: provider.is_active ? "success" : "neutral"
    },
    {
      label: provider.has_api_key ? "Chave cadastrada" : "Sem chave",
      tone: provider.has_api_key ? "success" : "warning"
    },
    {
      label: provider.is_supported ? "Suportado" : "Nao suportado",
      tone: provider.is_supported ? "success" : "danger"
    }
  ] as const;

  return (
    <div className="flex flex-wrap gap-2" aria-label="Status do provider">
      {statuses.map((status) => (
        <span
          className={clsx(
            "inline-flex min-h-7 items-center rounded-pill border px-3 text-xs font-medium",
            status.tone === "success" && "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
            status.tone === "warning" && "border-amber-500/30 bg-amber-500/10 text-amber-200",
            status.tone === "danger" && "border-red-500/30 bg-red-500/10 text-red-200",
            status.tone === "neutral" && "border-app-border bg-app-menu text-app-muted"
          )}
          key={status.label}
        >
          {status.label}
        </span>
      ))}
    </div>
  );
}
