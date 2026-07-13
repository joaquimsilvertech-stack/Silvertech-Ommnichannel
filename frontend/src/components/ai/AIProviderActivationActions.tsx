import { Power, XCircle } from "@phosphor-icons/react";
import { useState } from "react";
import { Button } from "../Button";
import { normalizeApiError } from "../../lib/apiErrors";
import { useActivateAIProvider, useDeactivateAIProvider } from "../../hooks/useAIProviders";
import type { WorkspaceAIProviderConfig } from "../../lib/aiProviders";

type Props = {
  workspaceId: string | number;
  provider: WorkspaceAIProviderConfig;
};

export function AIProviderActivationActions({ workspaceId, provider }: Props) {
  const [error, setError] = useState<string>();
  const activateMutation = useActivateAIProvider(workspaceId);
  const deactivateMutation = useDeactivateAIProvider(workspaceId);
  const isLoading = activateMutation.isPending || deactivateMutation.isPending;

  async function activate() {
    setError(undefined);
    try {
      await activateMutation.mutateAsync(provider.id);
    } catch (requestError) {
      const normalized = normalizeApiError(requestError);
      setError(normalized.errorCode ? `${normalized.message} (${normalized.errorCode})` : normalized.message);
    }
  }

  async function deactivate() {
    setError(undefined);
    try {
      await deactivateMutation.mutateAsync(provider.id);
    } catch (requestError) {
      setError(normalizeApiError(requestError).message);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {provider.is_active ? (
          <Button disabled={isLoading} icon={<XCircle size={16} />} onClick={deactivate} type="button" variant="surface">
            {deactivateMutation.isPending ? "Desativando..." : "Desativar"}
          </Button>
        ) : (
          <Button
            disabled={isLoading || !provider.has_api_key || !provider.is_supported}
            icon={<Power size={16} />}
            onClick={activate}
            type="button"
          >
            {activateMutation.isPending ? "Ativando..." : "Ativar"}
          </Button>
        )}
      </div>
      <p className="text-xs text-app-muted">
        Ativar usa a chave salva e valida a conexao no backend. Outros providers do workspace podem ser desativados pelo backend.
      </p>
      {error ? (
        <p className="rounded-control border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-100" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
