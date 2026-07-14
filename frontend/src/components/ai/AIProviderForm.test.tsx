import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AIProviderForm } from "./AIProviderForm";
import type { WorkspaceAIProviderConfig } from "../../lib/aiProviders";

const provider: WorkspaceAIProviderConfig = {
  id: "provider-1",
  provider: "openai",
  model_name: "gpt-4o-mini",
  system_prompt: "Prompt existente",
  settings: { temperature: 0.2 },
  is_active: true,
  has_api_key: true,
  is_supported: true,
  created_at: "2026-07-13T00:00:00Z",
  updated_at: "2026-07-13T00:00:00Z"
};

describe("AIProviderForm", () => {
  it("form de criacao envia payload seguro e limpa api_key apos sucesso", async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockResolvedValue(undefined);

    render(<AIProviderForm mode="create" onSubmit={submit} />);

    await user.clear(screen.getByLabelText("Modelo"));
    await user.type(screen.getByLabelText("Modelo"), "gpt-4o-mini");
    await user.type(screen.getByLabelText("System prompt"), "Seja conciso.");
    fireEvent.change(screen.getByLabelText("Settings JSON"), { target: { value: "{\"temperature\":0.1}" } });
    await user.type(screen.getByLabelText("API key"), "sk-create-key");
    await user.click(screen.getByRole("button", { name: /salvar provider/i }));

    expect(submit).toHaveBeenCalledWith({
      provider: "openai",
      model_name: "gpt-4o-mini",
      system_prompt: "Seja conciso.",
      settings: { temperature: 0.1 },
      api_key: "sk-create-key"
    });
    expect(screen.getByLabelText("API key")).toHaveValue("");
  });

  it("form de edicao preserva chave quando api_key fica vazia", async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockResolvedValue(undefined);

    render(<AIProviderForm mode="edit" onSubmit={submit} provider={provider} />);

    await user.clear(screen.getByLabelText("Modelo"));
    await user.type(screen.getByLabelText("Modelo"), "gpt-4.1-mini");
    await user.click(screen.getByRole("button", { name: /salvar provider/i }));

    expect(submit).toHaveBeenCalledWith({
      model_name: "gpt-4.1-mini",
      system_prompt: "Prompt existente",
      settings: { temperature: 0.2 }
    });
  });

  it("settings JSON invalido mostra erro local e nao chama API", async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockResolvedValue(undefined);

    render(<AIProviderForm mode="edit" onSubmit={submit} provider={provider} />);

    fireEvent.change(screen.getByLabelText("Settings JSON"), { target: { value: "{invalid" } });
    await user.click(screen.getByRole("button", { name: /salvar provider/i }));

    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByText(/json valido/i)).toBeInTheDocument();
  });

  it("nao renderiza campo de chave no modo edicao", () => {
    render(<AIProviderForm mode="edit" onSubmit={vi.fn()} provider={provider} />);

    expect(screen.queryByLabelText("API key")).not.toBeInTheDocument();
    expect(screen.queryByText(/sk-/i)).not.toBeInTheDocument();
  });
});
