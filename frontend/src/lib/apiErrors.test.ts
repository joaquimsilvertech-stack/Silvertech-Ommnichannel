import { describe, expect, it } from "vitest";
import { normalizeApiError } from "./apiErrors";

const WHATSAPP_TERMS = ["canal", "whatsapp", "qr"];

function expectGenericMessage(message: string) {
  const normalizedMessage = message.toLocaleLowerCase("pt-BR");
  for (const term of WHATSAPP_TERMS) {
    expect(normalizedMessage).not.toContain(term);
  }
}

describe("normalizeApiError", () => {
  it("mantem a mensagem global de 403 neutra", () => {
    const normalized = normalizeApiError({
      response: { status: 403, data: {} }
    });

    expect(normalized.message).toBe(
      "Você não possui permissão para realizar esta ação."
    );
    expectGenericMessage(normalized.message);
  });

  it("mantem o fallback global de 503 neutro", () => {
    const normalized = normalizeApiError({
      response: { status: 503, data: {} }
    });

    expect(normalized.message).toBe(
      "O serviço está temporariamente indisponível. Tente novamente."
    );
    expectGenericMessage(normalized.message);
  });
});
