import type { WorkspaceAIProviderConfig } from "../../lib/aiProviders";
import { AIProviderCard } from "./AIProviderCard";

type Props = {
  workspaceId: string | number;
  providers: WorkspaceAIProviderConfig[];
};

export function AIProviderList({ workspaceId, providers }: Props) {
  if (!providers.length) {
    return (
      <div className="rounded-card border border-dashed border-app-border bg-app-surface p-8 text-center">
        <h2 className="text-base font-semibold text-white">Nenhum provider configurado</h2>
        <p className="mt-2 text-sm text-app-muted">Crie um provider para habilitar o motor de IA neste workspace.</p>
      </div>
    );
  }

  return (
    <div className="grid gap-5">
      {providers.map((provider) => (
        <AIProviderCard key={provider.id} provider={provider} workspaceId={workspaceId} />
      ))}
    </div>
  );
}
