import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AIProviderConnectionTestButton } from "./AIProviderConnectionTestButton";

const testConnectionMock = vi.fn();

vi.mock("../../hooks/useAIProviders", () => ({
  useTestAIProviderConnection: () => ({
    isPending: false,
    testConnection: testConnectionMock
  })
}));

describe("AIProviderConnectionTestButton", () => {
  beforeEach(() => {
    testConnectionMock.mockReset();
  });

  it("limpa a chave temporaria apos teste bem-sucedido e envia antes de limpar", async () => {
    const user = userEvent.setup();
    testConnectionMock.mockResolvedValueOnce({
      success: true,
      message: "Conexao testada com sucesso.",
      provider: "openai",
      model_name: "gpt-4o-mini"
    });

    render(<AIProviderConnectionTestButton providerConfigId="provider-1" workspaceId="workspace-1" />);

    const input = screen.getByLabelText("Chave temporaria para teste");
    await user.type(input, "sk-temporary-secret");
    await user.click(screen.getByRole("button", { name: /testar conexao/i }));

    await screen.findByText("Conexao testada com sucesso.");
    expect(testConnectionMock).toHaveBeenCalledWith("provider-1", "sk-temporary-secret");
    await waitFor(() => expect(input).toHaveValue(""));
  });

  it("limpa a chave temporaria apos erro e nao renderiza a chave em mensagens", async () => {
    const user = userEvent.setup();
    testConnectionMock.mockRejectedValueOnce({
      normalized: {
        message: "Credencial invalida. Verifique a chave cadastrada.",
        errorCode: "INVALID_CREDENTIALS",
        fieldErrors: {}
      }
    });

    render(<AIProviderConnectionTestButton providerConfigId="provider-1" workspaceId="workspace-1" />);

    const input = screen.getByLabelText("Chave temporaria para teste");
    await user.type(input, "sk-temporary-secret");
    await user.click(screen.getByRole("button", { name: /testar conexao/i }));

    await screen.findByText("Credencial invalida. Verifique a chave cadastrada. (INVALID_CREDENTIALS)");
    expect(testConnectionMock).toHaveBeenCalledWith("provider-1", "sk-temporary-secret");
    await waitFor(() => expect(input).toHaveValue(""));
    expect(screen.queryByText("sk-temporary-secret")).not.toBeInTheDocument();
  });
});
