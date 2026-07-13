import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MessageDeliveryStatusBadge } from "./MessageDeliveryStatusBadge";
import { MessageRetryInfo } from "./MessageRetryInfo";

describe("MessageDeliveryStatusBadge", () => {
  it.each([
    ["pending", "Pendente"],
    ["sent", "Enviada"],
    ["delivered", "Entregue"],
    ["read", "Lida"],
    ["failed", "Falhou"],
    [null, "Sem status"]
  ] as const)("renderiza status %s", (status, label) => {
    render(<MessageDeliveryStatusBadge status={status} />);

    expect(screen.getByText(label)).toBeInTheDocument();
  });
});

describe("MessageRetryInfo", () => {
  it("mostra tentativa e proximo retry para mensagem pending", () => {
    render(
      <MessageRetryInfo
        message={{
          id: "message-1",
          direction: "outbound",
          status: "pending",
          send_attempt_count: 2,
          last_send_attempt_at: "2026-07-13T12:00:00Z",
          next_send_retry_at: "2026-07-13T12:05:00Z"
        }}
      />
    );

    expect(screen.getByText("Tentativas de envio")).toBeInTheDocument();
    expect(screen.getByText("Nova tentativa")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("mostra codigo sanitizado quando mensagem falhou", () => {
    render(
      <MessageRetryInfo
        message={{
          id: "message-1",
          direction: "outbound",
          status: "failed",
          send_error_code: "EVOLUTION_TIMEOUT"
        }}
      />
    );

    expect(screen.getByText("EVOLUTION_TIMEOUT")).toBeInTheDocument();
  });
});
