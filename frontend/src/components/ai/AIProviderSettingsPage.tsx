import { useMemo, useState } from "react";
import { Robot, WarningCircle } from "@phosphor-icons/react";
import { useParams } from "react-router-dom";
import { Button } from "../Button";
import { normalizeApiError } from "../../lib/apiErrors";
import { useAIProviders, useCreateAIProvider } from "../../hooks/useAIProviders";
import type { AIProviderConfigInput } from "../../lib/aiProviders";
import { AIProviderForm } from "./AIProviderForm";
import { AIProviderList } from "./AIProviderList";

export function AIProviderSettingsPage() {
  const params = useParams();
  const workspaceId = params.workspaceId;
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [success, setSuccess] = useState<string>();
  const [error, setError] = useState<string>();
  const providersQuery = useAIProviders(workspaceId);
  const createMutation = useCreateAIProvider(workspaceId);

  const activeProvider = useMemo(
    () => providersQuery.data?.find((provider) => provider.is_active),
    [providersQuery.data]
  );

  if (!workspaceId) {
    return (
      <section className="rounded-card border border-app-border bg-app-surface p-6 shadow-soft">
        <div className="flex items-center gap-3 text-red-100">
          <WarningCircle size={22} />
          <h1 className="text-lg font-semibold">Workspace nao informado</h1>
        </div>
        <p className="mt-3 text-sm text-app-muted">Acesse esta pagina pela rota /workspaces/:workspaceId/settings/ai.</p>
      </section>
    );
  }

  async function createProvider(payload: AIProviderConfigInput) {
    setSuccess(undefined);
    setError(undefined);
    try {
      await createMutation.mutateAsync(payload);
      setShowCreateForm(false);
      setSuccess("Provider criado com sucesso.");
    } catch (requestError) {
      setError(normalizeApiError(requestError).message);
      throw requestError;
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="max-w-3xl">
          <div className="mb-3 flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-control bg-app-infoBg text-app-secondary">
              <Robot size={22} weight="bold" />
            </span>
            <div>
              <h1 className="text-[28px] font-semibold leading-9 text-white">IA do workspace</h1>
              <p className="text-sm text-app-muted">Workspace {workspaceId}</p>
            </div>
          </div>
          <p className="text-sm leading-6 text-app-muted">
            Gerencie providers por workspace usando somente a API do Silvertech. Chaves sao write-only e nunca sao exibidas.
          </p>
        </div>
        <Button onClick={() => setShowCreateForm((current) => !current)} type="button">
          {showCreateForm ? "Fechar formulario" : "Novo provider"}
        </Button>
      </div>

      <section className="rounded-card border border-app-border bg-app-surface p-5 shadow-soft">
        <h2 className="text-base font-semibold text-white">Provider ativo</h2>
        <p className="mt-2 text-sm text-app-muted">
          {activeProvider ? `${activeProvider.provider} usando ${activeProvider.model_name}` : "Nenhum provider ativo neste workspace."}
        </p>
      </section>

      {success ? <p className="rounded-control bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100">{success}</p> : null}
      {error ? (
        <p className="rounded-control border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-100" role="alert">
          {error}
        </p>
      ) : null}

      {showCreateForm ? (
        <AIProviderForm isSubmitting={createMutation.isPending} mode="create" onCancel={() => setShowCreateForm(false)} onSubmit={createProvider} />
      ) : null}

      {providersQuery.isLoading ? (
        <p className="rounded-card border border-app-border bg-app-surface p-6 text-sm text-app-muted">Carregando providers...</p>
      ) : providersQuery.isError ? (
        <p className="rounded-card border border-red-500/30 bg-red-500/10 p-6 text-sm text-red-100" role="alert">
          {normalizeApiError(providersQuery.error).message}
        </p>
      ) : (
        <AIProviderList providers={providersQuery.data ?? []} workspaceId={workspaceId} />
      )}
    </div>
  );
}
