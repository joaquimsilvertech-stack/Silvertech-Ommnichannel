type Props = {
  value: string;
  onChange: (value: string) => void;
};

export function SystemPromptEditor({ value, onChange }: Props) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-app-text" htmlFor="ai-provider-system-prompt">
        System prompt
      </label>
      <textarea
        className="min-h-32 w-full resize-y rounded-control border border-app-border bg-app-bg px-3 py-3 text-sm leading-6 text-app-text outline-none transition focus:border-app-primary focus:ring-4 focus:ring-app-primary/15"
        id="ai-provider-system-prompt"
        onChange={(event) => onChange(event.target.value)}
        value={value}
      />
    </div>
  );
}
