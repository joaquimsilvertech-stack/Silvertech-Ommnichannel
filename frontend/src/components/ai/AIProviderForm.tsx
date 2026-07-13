import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Button } from "../Button";
import { normalizeApiError } from "../../lib/apiErrors";
import type { AIProviderConfigInput, AIProviderName, WorkspaceAIProviderConfig } from "../../lib/aiProviders";
import { APIKeyField } from "./APIKeyField";
import { AIProviderSettingsEditor } from "./AIProviderSettingsEditor";
import { SystemPromptEditor } from "./SystemPromptEditor";

const DEFAULT_MODEL_BY_PROVIDER: Record<AIProviderName, string> = {
  openai: "gpt-4o-mini",
  anthropic: "claude-3-5-sonnet-latest",
  google: "gemini-1.5-flash"
};

type Props = {
  mode: "create" | "edit";
  provider?: WorkspaceAIProviderConfig;
  onSubmit: (payload: AIProviderConfigInput) => Promise<void>;
  onCancel?: () => void;
  isSubmitting?: boolean;
};

function safeSettingsText(settings: Record<string, unknown> | undefined) {
  return JSON.stringify(settings ?? {}, null, 2);
}

export function AIProviderForm({ mode, provider, onSubmit, onCancel, isSubmitting = false }: Props) {
  const [providerName, setProviderName] = useState<AIProviderName>(provider?.provider ?? "openai");
  const [modelName, setModelName] = useState(provider?.model_name ?? DEFAULT_MODEL_BY_PROVIDER.openai);
  const [systemPrompt, setSystemPrompt] = useState(provider?.system_prompt ?? "");
  const [settingsText, setSettingsText] = useState(safeSettingsText(provider?.settings));
  const [apiKey, setApiKey] = useState("");
  const [settingsError, setSettingsError] = useState<string>();
  const [formError, setFormError] = useState<string>();

  const hasApiKey = Boolean(provider?.has_api_key);

  useEffect(() => {
    if (!provider) return;
    setProviderName(provider.provider);
    setModelName(provider.model_name);
    setSystemPrompt(provider.system_prompt);
    setSettingsText(safeSettingsText(provider.settings));
    setApiKey("");
  }, [provider]);

  const title = useMemo(() => (mode === "create" ? "Novo provider" : `Editar ${provider?.provider ?? "provider"}`), [
    mode,
    provider?.provider
  ]);

  function parseSettings() {
    if (!settingsText.trim()) return {};
    const parsed = JSON.parse(settingsText) as unknown;
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
      throw new Error("Settings deve ser um objeto JSON.");
    }
    return parsed as Record<string, unknown>;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(undefined);
    setSettingsError(undefined);

    let settings: Record<string, unknown>;
    try {
      settings = parseSettings();
    } catch {
      setSettingsError("Informe um JSON valido no formato de objeto.");
      return;
    }

    const payload: AIProviderConfigInput = {
      model_name: modelName.trim(),
      system_prompt: systemPrompt,
      settings
    };
    if (mode === "create") payload.provider = providerName;
    if (apiKey.trim()) payload.api_key = apiKey.trim();

    try {
      await onSubmit(payload);
      setApiKey("");
      if (mode === "create") {
        setProviderName("openai");
        setModelName(DEFAULT_MODEL_BY_PROVIDER.openai);
        setSystemPrompt("");
        setSettingsText("{}");
      }
    } catch (error) {
      setFormError(normalizeApiError(error).message);
    }
  }

  return (
    <form className="rounded-card border border-app-border bg-app-surface p-5 shadow-soft" onSubmit={handleSubmit}>
      <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-base font-semibold text-white">{title}</h2>
          <p className="mt-1 text-sm text-app-muted">
            Configure o provider pelo backend. A chave e enviada somente no submit.
          </p>
        </div>
        {onCancel ? (
          <Button onClick={onCancel} type="button" variant="ghost">
            Cancelar
          </Button>
        ) : null}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <label className="mb-2 block text-sm font-medium text-app-text" htmlFor="ai-provider-name">
            Provider
          </label>
          <select
            className="h-11 w-full rounded-control border border-app-border bg-app-bg px-3 text-sm text-app-text outline-none transition focus:border-app-primary focus:ring-4 focus:ring-app-primary/15 disabled:opacity-70"
            disabled={mode === "edit"}
            id="ai-provider-name"
            onChange={(event) => {
              const nextProvider = event.target.value as AIProviderName;
              setProviderName(nextProvider);
              setModelName(DEFAULT_MODEL_BY_PROVIDER[nextProvider]);
            }}
            value={providerName}
          >
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="google">Google</option>
          </select>
        </div>

        <div>
          <label className="mb-2 block text-sm font-medium text-app-text" htmlFor="ai-provider-model">
            Modelo
          </label>
          <input
            className="h-11 w-full rounded-control border border-app-border bg-app-bg px-3 text-sm text-app-text outline-none transition focus:border-app-primary focus:ring-4 focus:ring-app-primary/15"
            id="ai-provider-model"
            onChange={(event) => setModelName(event.target.value)}
            required
            value={modelName}
          />
        </div>
      </div>

      <div className="mt-4 grid gap-4">
        <SystemPromptEditor onChange={setSystemPrompt} value={systemPrompt} />
        <AIProviderSettingsEditor error={settingsError} onChange={setSettingsText} value={settingsText} />
        <APIKeyField hasApiKey={hasApiKey} onChange={setApiKey} required={mode === "create" && !hasApiKey} value={apiKey} />
      </div>

      {formError ? (
        <div className="mt-4 rounded-control border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-100" role="alert">
          {formError}
        </div>
      ) : null}

      <div className="mt-5 flex justify-end">
        <Button disabled={isSubmitting} type="submit">
          {isSubmitting ? "Salvando..." : "Salvar provider"}
        </Button>
      </div>
    </form>
  );
}
