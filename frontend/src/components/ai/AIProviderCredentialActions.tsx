import { Key, Trash, WarningCircle } from "@phosphor-icons/react";
import { useState, type FormEvent } from "react";
import { Button } from "../Button";
import { useReplaceAIProviderCredentials, useRevokeAIProviderCredentials } from "../../hooks/useAIProviders";
import { normalizeApiError } from "../../lib/apiErrors";
import type { WorkspaceAIProviderConfig } from "../../lib/aiProviders";

type Props = {
  workspaceId: string | number;
  provider: WorkspaceAIProviderConfig;
};

export function AIProviderCredentialActions({ workspaceId, provider }: Props) {
  const [replacementKey, setReplacementKey] = useState("");
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const [success, setSuccess] = useState<string>();
  const [error, setError] = useState<string>();
  const replaceMutation = useReplaceAIProviderCredentials(workspaceId);
  const revokeMutation = useRevokeAIProviderCredentials(workspaceId);
  const isLoading = replaceMutation.isPending || revokeMutation.isPending;

  async function replaceCredentials(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSuccess(undefined);
    setError(undefined);
    setConfirmRevoke(false);

    try {
      await replaceMutation.replaceCredentials(provider.id, replacementKey);
      setSuccess("Chave substituida com sucesso.");
    } catch (requestError) {
      const normalized = normalizeApiError(requestError);
      setError(normalized.errorCode ? `${normalized.message} (${normalized.errorCode})` : normalized.message);
    } finally {
      setReplacementKey("");
    }
  }

  async function revokeCredentials() {
    if (!confirmRevoke) {
      setConfirmRevoke(true);
      setSuccess(undefined);
      setError(undefined);
      return;
    }

    setSuccess(undefined);
    setError(undefined);
    try {
      await revokeMutation.mutateAsync(provider.id);
      setSuccess("Chave revogada e provider desativado.");
      setConfirmRevoke(false);
    } catch (requestError) {
      setError(normalizeApiError(requestError).message);
    } finally {
      setReplacementKey("");
    }
  }

  return (
    <div className="rounded-control border border-app-border bg-app-bg p-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-sm font-medium text-app-text">
            {provider.has_api_key ? "Chave cadastrada" : "Sem chave"}
          </p>
          <p className="mt-1 text-xs text-app-muted">
            Substituir testa a nova chave antes de salvar. Revogar apaga a chave local e desativa o provider.
          </p>
        </div>
        {confirmRevoke ? (
          <p className="inline-flex items-center gap-2 text-xs text-amber-200">
            <WarningCircle size={16} />
            Confirme para revogar.
          </p>
        ) : null}
      </div>

      <form className="mt-3 flex flex-col gap-2 sm:flex-row" onSubmit={replaceCredentials}>
        <label className="sr-only" htmlFor={`replace-api-key-${provider.id}`}>
          Nova chave do provider
        </label>
        <input
          autoComplete="new-password"
          className="h-10 min-w-0 flex-1 rounded-control border border-app-border bg-app-surface px-3 text-sm text-app-text outline-none transition focus:border-app-primary focus:ring-4 focus:ring-app-primary/15"
          id={`replace-api-key-${provider.id}`}
          onChange={(event) => setReplacementKey(event.target.value)}
          placeholder="Nova chave"
          type="password"
          value={replacementKey}
        />
        <Button disabled={isLoading} icon={<Key size={16} />} type="submit">
          {replaceMutation.isPending ? "Validando..." : "Substituir chave"}
        </Button>
      </form>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          disabled={isLoading}
          icon={<Trash size={16} />}
          onClick={revokeCredentials}
          type="button"
          variant={confirmRevoke ? "primary" : "surface"}
        >
          {revokeMutation.isPending ? "Revogando..." : confirmRevoke ? "Confirmar revogacao" : "Revogar chave"}
        </Button>
        {confirmRevoke ? (
          <Button disabled={isLoading} onClick={() => setConfirmRevoke(false)} type="button" variant="ghost">
            Cancelar
          </Button>
        ) : null}
        <p className="text-xs text-app-muted">
          Desativar pausa o uso do provider. Revogar remove a credencial criptografada salva.
        </p>
      </div>

      {success ? <p className="mt-2 text-sm text-emerald-200">{success}</p> : null}
      {error ? (
        <p className="mt-2 text-sm text-red-200" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
