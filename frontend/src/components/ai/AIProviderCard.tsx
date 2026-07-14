import { useState } from "react";
import { PencilSimple } from "@phosphor-icons/react";
import { Button } from "../Button";
import { normalizeApiError } from "../../lib/apiErrors";
import { useUpdateAIProvider } from "../../hooks/useAIProviders";
import type { AIProviderConfigInput, WorkspaceAIProviderConfig } from "../../lib/aiProviders";
import { AIProviderActivationActions } from "./AIProviderActivationActions";
import { AIProviderConnectionTestButton } from "./AIProviderConnectionTestButton";
import { AIProviderCredentialActions } from "./AIProviderCredentialActions";
import { AIProviderForm } from "./AIProviderForm";
import { AIProviderStatusBadge } from "./AIProviderStatusBadge";

type Props = {
  workspaceId: string | number;
  provider: WorkspaceAIProviderConfig;
};

function formatDate(value: string) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short"
  }).format(new Date(value));
}

export function AIProviderCard({ workspaceId, provider }: Props) {
  const [isEditing, setIsEditing] = useState(false);
  const [success, setSuccess] = useState<string>();
  const [error, setError] = useState<string>();
  const updateMutation = useUpdateAIProvider(workspaceId);

  async function updateProvider(payload: AIProviderConfigInput) {
    setSuccess(undefined);
    setError(undefined);
    try {
      await updateMutation.mutateAsync({ providerConfigId: provider.id, payload });
      setIsEditing(false);
      setSuccess("Provider atualizado com sucesso.");
    } catch (requestError) {
      setError(normalizeApiError(requestError).message);
      throw requestError;
    }
  }

  return (
    <article className="rounded-card border border-app-border bg-app-surface p-5 shadow-soft">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="text-lg font-semibold capitalize text-white">{provider.provider}</h3>
            <AIProviderStatusBadge provider={provider} />
          </div>
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-app-muted">Modelo</dt>
              <dd className="mt-1 break-words text-app-text">{provider.model_name || "-"}</dd>
            </div>
            <div>
              <dt className="text-app-muted">Atualizado em</dt>
              <dd className="mt-1 text-app-text">{formatDate(provider.updated_at)}</dd>
            </div>
          </dl>
        </div>
        <Button icon={<PencilSimple size={16} />} onClick={() => setIsEditing((current) => !current)} type="button" variant="surface">
          {isEditing ? "Fechar edicao" : "Editar"}
        </Button>
      </div>

      {success ? <p className="mt-4 rounded-control bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100">{success}</p> : null}
      {error ? (
        <p className="mt-4 rounded-control border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-100" role="alert">
          {error}
        </p>
      ) : null}

      <div className="mt-5 grid gap-4">
        {isEditing ? (
          <AIProviderForm
            isSubmitting={updateMutation.isPending}
            mode="edit"
            onCancel={() => setIsEditing(false)}
            onSubmit={updateProvider}
            provider={provider}
          />
        ) : null}
        <AIProviderConnectionTestButton providerConfigId={provider.id} workspaceId={workspaceId} />
        <AIProviderCredentialActions provider={provider} workspaceId={workspaceId} />
        <AIProviderActivationActions provider={provider} workspaceId={workspaceId} />
      </div>
    </article>
  );
}
