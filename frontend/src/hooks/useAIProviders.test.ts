import { describe, expect, it } from "vitest";
import { aiProvidersQueryKey } from "./useAIProviders";

describe("aiProvidersQueryKey", () => {
  it("usa apenas workspaceId e nao carrega credenciais", () => {
    const key = aiProvidersQueryKey("workspace-1");

    expect(JSON.stringify(key)).toContain("workspace-1");
    expect(JSON.stringify(key)).not.toContain("api_key");
    expect(JSON.stringify(key)).not.toContain("sk-");
  });
});
