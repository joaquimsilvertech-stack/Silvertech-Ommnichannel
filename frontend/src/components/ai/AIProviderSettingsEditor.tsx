type Props = {
  value: string;
  onChange: (value: string) => void;
  error?: string;
};

export function AIProviderSettingsEditor({ value, onChange, error }: Props) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-app-text" htmlFor="ai-provider-settings">
        Settings JSON
      </label>
      <textarea
        aria-invalid={Boolean(error)}
        aria-describedby={error ? "ai-provider-settings-error" : undefined}
        className="min-h-28 w-full resize-y rounded-control border border-app-border bg-app-bg px-3 py-3 font-mono text-sm leading-6 text-app-text outline-none transition focus:border-app-primary focus:ring-4 focus:ring-app-primary/15"
        id="ai-provider-settings"
        onChange={(event) => onChange(event.target.value)}
        spellCheck={false}
        value={value}
      />
      {error ? (
        <p className="mt-2 text-xs text-red-200" id="ai-provider-settings-error">
          {error}
        </p>
      ) : (
        <p className="mt-2 text-xs text-app-muted">Use um objeto JSON. Deixe vazio para enviar {"{}"}.</p>
      )}
    </div>
  );
}
