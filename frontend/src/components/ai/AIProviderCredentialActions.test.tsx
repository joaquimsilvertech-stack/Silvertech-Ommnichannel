import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AIProviderCredentialActions } from "./AIProviderCredentialActions";
import type { WorkspaceAIProviderConfig } from "../../lib/aiProviders";

const replaceCredentialsMock = vi.fn();
const revokeCredentialsMock = vi.fn();

vi.mock("../../hooks/useAIProviders", () => ({
  useReplaceAIProviderCredentials: () => ({
    isPending: false,
    replaceCredentials: replaceCredentialsMock
  }),
  useRevokeAIProviderCredentials: () => ({
    isPending: false,
    mutateAsync: revokeCredentialsMock
  })
}));

const provider: WorkspaceAIProviderConfig = {
  id: "provider-1",
  provider: "openai",
  model_name: "gpt-4o-mini",
  system_prompt: "Prompt",
  settings: {},
  is_active: true,
  has_api_key: true,
  is_supported: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z"
};

describe("AIProviderCredentialActions", () => {
  beforeEach(() => {
    replaceCredentialsMock.mockReset();
    revokeCredentialsMock.mockReset();
  });

  it("substitui credencial e limpa o campo sem renderizar a chave", async () => {
    const user = userEvent.setup();
    replaceCredentialsMock.mockResolvedValueOnce({ ...provider, has_api_key: true });

    render(<AIProviderCredentialActions provider={provider} workspaceId="workspace-1" />);

    const input = screen.getByLabelText("Nova chave do provider");
    await user.type(input, "sk-new-provider-secret");
    await user.click(screen.getByRole("button", { name: /substituir chave/i }));

    await screen.findByText("Chave substituida com sucesso.");
    expect(replaceCredentialsMock).toHaveBeenCalledWith("provider-1", "sk-new-provider-secret");
    await waitFor(() => expect(input).toHaveValue(""));
    expect(screen.queryByText("sk-new-provider-secret")).not.toBeInTheDocument();
  });

  it("limpa o campo apos erro de substituicao e exibe erro sanitizado", async () => {
    const user = userEvent.setup();
    replaceCredentialsMock.mockRejectedValueOnce({
      normalized: {
        message: "Credencial invalida. Verifique a chave informada.",
        errorCode: "INVALID_CREDENTIALS",
        fieldErrors: {}
      }
    });

    render(<AIProviderCredentialActions provider={provider} workspaceId="workspace-1" />);

    const input = screen.getByLabelText("Nova chave do provider");
    await user.type(input, "sk-invalid-provider-secret");
    await user.click(screen.getByRole("button", { name: /substituir chave/i }));

    await screen.findByText("Credencial invalida. Verifique a chave informada. (INVALID_CREDENTIALS)");
    expect(replaceCredentialsMock).toHaveBeenCalledWith("provider-1", "sk-invalid-provider-secret");
    await waitFor(() => expect(input).toHaveValue(""));
    expect(screen.queryByText("sk-invalid-provider-secret")).not.toBeInTheDocument();
  });

  it("revoga credencial apenas depois de confirmacao", async () => {
    const user = userEvent.setup();
    revokeCredentialsMock.mockResolvedValueOnce({ ...provider, has_api_key: false, is_active: false });

    render(<AIProviderCredentialActions provider={provider} workspaceId="workspace-1" />);

    expect(screen.getByText("Chave cadastrada")).toBeInTheDocument();
    expect(screen.getByText(/Desativar pausa o uso do provider/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /revogar chave/i }));
    expect(revokeCredentialsMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /confirmar revogacao/i }));

    await screen.findByText("Chave revogada e provider desativado.");
    expect(revokeCredentialsMock).toHaveBeenCalledWith("provider-1");
  });
});
