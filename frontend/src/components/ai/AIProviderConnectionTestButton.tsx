import { useState } from "react";
import { Flask } from "@phosphor-icons/react";
import { Button } from "../Button";
import { normalizeApiError } from "../../lib/apiErrors";
import { useTestAIProviderConnection } from "../../hooks/useAIProviders";

type Props = {
  workspaceId: string | number;
  providerConfigId: string;
};

export function AIProviderConnectionTestButton({ workspaceId, providerConfigId }: Props) {
  const [temporaryKey, setTemporaryKey] = useState("");
  const [message, setMessage] = useState<string>();
  const [error, setError] = useState<string>();
  const mutation = useTestAIProviderConnection(workspaceId);

  async function handleTest() {
    setMessage(undefined);
    setError(undefined);
    try {
      const result = await mutation.testConnection(providerConfigId, temporaryKey.trim() || undefined);
      setMessage(result.message || "Conexao testada com sucesso.");
    } catch (requestError) {
      const normalized = normalizeApiError(requestError);
      setError(normalized.errorCode ? `${normalized.message} (${normalized.errorCode})` : normalized.message);
    } finally {
      setTemporaryKey("");
    }
  }

  return (
    <div className="rounded-control border border-app-border bg-app-bg p-3">
      <label className="mb-2 block text-xs font-medium text-app-muted" htmlFor={`temporary-api-key-${providerConfigId}`}>
        Chave temporaria para teste
      </label>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          autoComplete="new-password"
          className="h-10 min-w-0 flex-1 rounded-control border border-app-border bg-app-surface px-3 text-sm text-app-text outline-none transition focus:border-app-primary focus:ring-4 focus:ring-app-primary/15"
          id={`temporary-api-key-${providerConfigId}`}
          onChange={(event) => setTemporaryKey(event.target.value)}
          placeholder="Opcional, nao sera salva"
          type="password"
          value={temporaryKey}
        />
        <Button disabled={mutation.isPending} icon={<Flask size={16} />} onClick={handleTest} type="button" variant="surface">
          {mutation.isPending ? "Testando..." : "Testar conexao"}
        </Button>
      </div>
      {message ? <p className="mt-2 text-sm text-emerald-200">{message}</p> : null}
      {error ? (
        <p className="mt-2 text-sm text-red-200" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
