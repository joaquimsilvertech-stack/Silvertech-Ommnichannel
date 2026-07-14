import { describe, expect, it } from "vitest";
import { aiObservabilityQueryKey } from "./useAIObservability";

describe("aiObservabilityQueryKey", () => {
  it("nao inclui campos sensiveis mesmo quando recebidos por acidente", () => {
    const key = aiObservabilityQueryKey("workspace-1", {
      period: "24h",
      provider: "openai",
      api_key: "sk-secret",
      body: "conteudo",
      prompt: "prompt sensivel",
      payload: "raw"
    } as never);

    expect(JSON.stringify(key)).toContain("workspace-1");
    expect(JSON.stringify(key)).toContain("openai");
    expect(JSON.stringify(key)).not.toContain("sk-secret");
    expect(JSON.stringify(key)).not.toContain("conteudo");
    expect(JSON.stringify(key)).not.toContain("prompt sensivel");
    expect(JSON.stringify(key)).not.toContain("raw");
  });
});
