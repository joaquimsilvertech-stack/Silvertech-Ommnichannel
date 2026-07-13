type Props = {
  value: string;
  onChange: (value: string) => void;
  hasApiKey?: boolean;
  required?: boolean;
};

export function APIKeyField({ value, onChange, hasApiKey = false, required = false }: Props) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-app-text" htmlFor="ai-provider-api-key">
        API key
      </label>
      <input
        autoComplete="new-password"
        className="h-11 w-full rounded-control border border-app-border bg-app-bg px-3 text-sm text-app-text outline-none transition focus:border-app-primary focus:ring-4 focus:ring-app-primary/15"
        id="ai-provider-api-key"
        name="api-key"
        onChange={(event) => onChange(event.target.value)}
        placeholder={hasApiKey ? "Deixe em branco para manter a chave atual" : "Cole a chave do provider"}
        required={required}
        type="password"
        value={value}
      />
      <p className="mt-2 text-xs text-app-muted">
        {hasApiKey ? "Chave cadastrada. A chave real nunca e exibida." : "Nenhuma chave cadastrada."}
      </p>
    </div>
  );
}
