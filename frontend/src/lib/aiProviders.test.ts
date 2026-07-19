import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import {
  activateAIProvider,
  AIProviderApiError,
  createAIProvider,
  deactivateAIProvider,
  getAIProviders,
  replaceAIProviderCredentials,
  revokeAIProviderCredentials,
  testAIProviderConnection,
  updateAIProvider
} from "./aiProviders";
import { normalizeApiError } from "./apiErrors";

describe("aiProviders API client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("getAIProviders chama a URL correta", async () => {
    const spy = vi.spyOn(api, "get").mockResolvedValueOnce({ data: [] });

    await getAIProviders("workspace-1");

    expect(spy).toHaveBeenCalledWith("/api/workspaces/workspace-1/ai-providers/");
  });

  it("createAIProvider nao envia workspace nem is_active", async () => {
    const spy = vi.spyOn(api, "post").mockResolvedValueOnce({ data: { id: "provider-1" } });

    await createAIProvider("workspace-1", {
      provider: "openai",
      model_name: "gpt-4o-mini",
      system_prompt: "Prompt",
      settings: {},
      api_key: "sk-test-key",
      workspace: "workspace-2",
      is_active: true
    } as never);

    expect(spy).toHaveBeenCalledWith("/api/workspaces/workspace-1/ai-providers/", {
      provider: "openai",
      model_name: "gpt-4o-mini",
      system_prompt: "Prompt",
      settings: {},
      api_key: "sk-test-key"
    });
  });

  it("createAIProvider nao envia workspace_id mesmo se recebido por acidente", async () => {
    const spy = vi.spyOn(api, "post").mockResolvedValueOnce({ data: { id: "provider-1" } });

    await createAIProvider("workspace-1", {
      provider: "openai",
      model_name: "gpt-4o-mini",
      settings: {},
      api_key: "sk-test-key",
      workspace_id: "workspace-2"
    } as never);

    expect(spy).toHaveBeenCalledWith("/api/workspaces/workspace-1/ai-providers/", {
      provider: "openai",
      model_name: "gpt-4o-mini",
      settings: {},
      api_key: "sk-test-key"
    });
  });

  it("updateAIProvider nao envia api_key pelo endpoint generico", async () => {
    const spy = vi.spyOn(api, "patch").mockResolvedValueOnce({ data: { id: "provider-1" } });

    await updateAIProvider("workspace-1", "provider-1", {
      model_name: "gpt-4o-mini",
      api_key: "sk-should-use-replace-endpoint"
    });

    expect(spy).toHaveBeenCalledWith("/api/workspaces/workspace-1/ai-providers/provider-1/", {
      model_name: "gpt-4o-mini"
    });
  });

  it("testAIProviderConnection envia chave temporaria apenas quando preenchida", async () => {
    const spy = vi.spyOn(api, "post").mockResolvedValue({ data: { success: true } });

    await testAIProviderConnection("workspace-1", "provider-1", { api_key: "sk-temp-key" });
    await testAIProviderConnection("workspace-1", "provider-1", { api_key: "" });

    expect(spy).toHaveBeenNthCalledWith(1, "/api/workspaces/workspace-1/ai-providers/provider-1/test/", {
      api_key: "sk-temp-key"
    });
    expect(spy).toHaveBeenNthCalledWith(2, "/api/workspaces/workspace-1/ai-providers/provider-1/test/", {});
  });

  it("activate e deactivate usam endpoints dedicados sem api_key", async () => {
    const spy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "provider-1" } });

    await activateAIProvider("workspace-1", "provider-1");
    await deactivateAIProvider("workspace-1", "provider-1");

    expect(spy).toHaveBeenNthCalledWith(1, "/api/workspaces/workspace-1/ai-providers/provider-1/activate/", {});
    expect(spy).toHaveBeenNthCalledWith(2, "/api/workspaces/workspace-1/ai-providers/provider-1/deactivate/", {});
  });

  it("replace e revoke usam endpoints dedicados de credenciais", async () => {
    const spy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "provider-1" } });

    await replaceAIProviderCredentials("workspace-1", "provider-1", { api_key: " sk-new-key " });
    await revokeAIProviderCredentials("workspace-1", "provider-1");

    expect(spy).toHaveBeenNthCalledWith(
      1,
      "/api/workspaces/workspace-1/ai-providers/provider-1/credentials/replace/",
      { api_key: "sk-new-key" }
    );
    expect(spy).toHaveBeenNthCalledWith(
      2,
      "/api/workspaces/workspace-1/ai-providers/provider-1/credentials/revoke/",
      {}
    );
  });

  it("replaceAIProviderCredentials omite chave vazia para backend retornar MISSING_API_KEY", async () => {
    const spy = vi.spyOn(api, "post").mockResolvedValueOnce({ data: { id: "provider-1" } });

    await replaceAIProviderCredentials("workspace-1", "provider-1", { api_key: " " });

    expect(spy).toHaveBeenCalledWith(
      "/api/workspaces/workspace-1/ai-providers/provider-1/credentials/replace/",
      {}
    );
  });

  it("normalizeApiError remove dados sensiveis da mensagem", () => {
    const error = normalizeApiError({
      response: {
        status: 400,
        data: {
          error_code: "MISSING_API_KEY",
          detail: "api_key sk-secret Authorization"
        }
      },
      isAxiosError: true
    });

    expect(error.message).toBe("Informe uma chave antes de continuar.");
    expect(error.errorCode).toBe("MISSING_API_KEY");
  });

  it("erro 403 de IA nao menciona canais WhatsApp", async () => {
    vi.spyOn(api, "get").mockRejectedValueOnce({
      response: { status: 403, data: {} }
    });

    const error = await getAIProviders("workspace-1").catch((value) => value);
    expect(error).toBeInstanceOf(AIProviderApiError);
    expect(error.message).toBe(
      "Você não possui permissão para realizar esta ação."
    );
    expect(error.message.toLocaleLowerCase("pt-BR")).not.toContain("canal");
    expect(error.message.toLocaleLowerCase("pt-BR")).not.toContain("whatsapp");
  });

  it("erro 503 de IA usa fallback generico", async () => {
    vi.spyOn(api, "get").mockRejectedValueOnce({
      response: { status: 503, data: {} }
    });

    const error = await getAIProviders("workspace-1").catch((value) => value);
    expect(error).toBeInstanceOf(AIProviderApiError);
    expect(error.message).toBe(
      "O serviço está temporariamente indisponível. Tente novamente."
    );
    expect(error.message.toLocaleLowerCase("pt-BR")).not.toContain("conexão");
    expect(error.message.toLocaleLowerCase("pt-BR")).not.toContain("qr");
  });
});
