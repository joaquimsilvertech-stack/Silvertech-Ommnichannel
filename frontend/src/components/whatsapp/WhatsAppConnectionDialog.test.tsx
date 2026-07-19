import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { WhatsAppChannel } from "../../lib/whatsappChannels";
import { WhatsAppConnectionDialog } from "./WhatsAppConnectionDialog";

const hookMocks = vi.hoisted(() => ({
  clear: vi.fn(),
  qr: vi.fn(),
  status: vi.fn()
}));
const imageMocks = vi.hoisted(() => ({
  create: vi.fn((qrCode: string, format: string) => {
    void qrCode;
    void format;
    return "blob:secure-qr";
  }),
  revoke: vi.fn((objectUrl: string) => {
    void objectUrl;
  })
}));

vi.mock("../../hooks/useWhatsAppChannels", () => ({
  clearWhatsAppChannelQRCode: (...args: unknown[]) => hookMocks.clear(...args),
  useWhatsAppChannelQRCode: (...args: unknown[]) => hookMocks.qr(...args),
  useWhatsAppChannelStatus: (...args: unknown[]) => hookMocks.status(...args),
  whatsappChannelDetailQueryKey: (workspaceId: string, channelId: string) => [workspaceId, channelId, "detail"],
  whatsappChannelsQueryKey: (workspaceId: string) => [workspaceId, "channels"]
}));

vi.mock("../../lib/qrImage", () => ({
  createQRCodeObjectURL: (qrCode: string, format: string) => imageMocks.create(qrCode, format),
  QR_IMAGE_ERROR_MESSAGE: "Erro seguro de imagem.",
  revokeQRCodeObjectURL: (objectUrl: string) => imageMocks.revoke(objectUrl)
}));

const RAW_QR = "private-raw-qr-sentinel";
const channel: WhatsAppChannel = {
  id: "channel-private-id",
  name: "WhatsApp principal",
  provider: "evolution",
  status: "waiting_qr",
  phone_number_masked: "********1234",
  has_qr_code: true,
  connected_at: null,
  last_connection_update_at: null,
  created_at: "2026-07-18T12:00:00Z",
  updated_at: "2026-07-18T12:00:00Z"
};

function statusState(status = "waiting_qr", overrides: Record<string, unknown> = {}) {
  return {
    data: { ...channel, status },
    error: undefined,
    isFetching: false,
    refetch: vi.fn(),
    ...overrides
  };
}

function qrState(overrides: Record<string, unknown> = {}) {
  return {
    data: {
      id: channel.id,
      status: "waiting_qr",
      has_qr_code: true,
      qr_code: RAW_QR,
      format: "base64"
    },
    error: undefined,
    isFetching: false,
    refetch: vi.fn().mockResolvedValue({}),
    ...overrides
  };
}

function renderDialog(overrides: Partial<React.ComponentProps<typeof WhatsAppConnectionDialog>> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const props = {
    channel,
    onClose: vi.fn(),
    open: true,
    workspaceId: "workspace-private-id",
    ...overrides
  };
  return {
    ...render(
      <QueryClientProvider client={queryClient}>
        <WhatsAppConnectionDialog {...props} />
      </QueryClientProvider>
    ),
    props,
    queryClient
  };
}

describe("WhatsAppConnectionDialog", () => {
  beforeEach(() => {
    hookMocks.clear.mockReset().mockResolvedValue(undefined);
    hookMocks.status.mockReset().mockReturnValue(statusState());
    hookMocks.qr.mockReset().mockReturnValue(qrState());
    imageMocks.create.mockClear();
    imageMocks.revoke.mockClear();
  });

  it("renderiza dialog acessivel com titulo e botao de fechar", () => {
    renderDialog();
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("dialog")).toHaveAccessibleName("WhatsApp principal");
    expect(screen.getByRole("button", { name: "Fechar acompanhamento da conexão" })).toBeInTheDocument();
  });

  it("converte QR em Blob URL sem renderizar valor bruto", async () => {
    renderDialog();
    const image = await screen.findByRole("img", { name: "QR Code para conectar o WhatsApp" });
    expect(image).toHaveAttribute("src", "blob:secure-qr");
    expect(image).toHaveAttribute("draggable", "false");
    expect(imageMocks.create).toHaveBeenCalledWith(RAW_QR, "base64");
    expect(document.body).not.toHaveTextContent(RAW_QR);
    for (const element of Array.from(document.querySelectorAll("*"))) {
      for (const attribute of Array.from(element.attributes)) {
        expect(attribute.value).not.toContain(RAW_QR);
      }
    }
  });

  it.each(["provisioning", "connecting", "connected", "reconnecting", "error", "deleting"])(
    "desabilita consulta de QR em %s",
    (status) => {
      hookMocks.status.mockReturnValue(statusState(status));
      hookMocks.qr.mockReturnValue(qrState({ data: undefined }));
      renderDialog({ channel: { ...channel, status: status as never } });
      expect(hookMocks.qr).toHaveBeenCalledWith("workspace-private-id", channel.id, false);
    }
  );

  it("revoga Blob e remove query quando status deixa waiting_qr", async () => {
    let currentStatus = "waiting_qr";
    hookMocks.status.mockImplementation(() => statusState(currentStatus));
    const view = renderDialog();
    await waitFor(() => expect(imageMocks.create).toHaveBeenCalled());
    currentStatus = "connecting";
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <WhatsAppConnectionDialog {...view.props} />
      </QueryClientProvider>
    );
    await waitFor(() => expect(imageMocks.revoke).toHaveBeenCalledWith("blob:secure-qr"));
    expect(hookMocks.clear).toHaveBeenCalled();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("QR Code lido. Confirmando conexão.")).toBeInTheDocument();
  });

  it("remove e revoga QR antigo depois de resposta concluida sem QR", async () => {
    let currentQR = qrState();
    hookMocks.qr.mockImplementation(() => currentQR);
    const view = renderDialog();
    await screen.findByRole("img", { name: "QR Code para conectar o WhatsApp" });

    currentQR = qrState({
      data: {
        id: channel.id,
        status: "waiting_qr",
        has_qr_code: false,
        qr_code: null,
        format: null
      },
      isFetching: false
    });
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <WhatsAppConnectionDialog {...view.props} />
      </QueryClientProvider>
    );

    await waitFor(() => expect(imageMocks.revoke).toHaveBeenCalledWith("blob:secure-qr"));
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("O QR Code ainda não está disponível.")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(hookMocks.clear).not.toHaveBeenCalled();
  });

  it("preserva QR antigo durante loading e remove somente ao concluir sem QR", async () => {
    let currentQR = qrState();
    hookMocks.qr.mockImplementation(() => currentQR);
    const view = renderDialog();
    await screen.findByRole("img", { name: "QR Code para conectar o WhatsApp" });

    const unavailableQR = {
      id: channel.id,
      status: "waiting_qr",
      has_qr_code: false,
      qr_code: null,
      format: null
    };
    currentQR = qrState({ data: unavailableQR, isFetching: true });
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <WhatsAppConnectionDialog {...view.props} />
      </QueryClientProvider>
    );

    expect(screen.getByRole("img", { name: "QR Code para conectar o WhatsApp" })).toHaveAttribute(
      "src",
      "blob:secure-qr"
    );
    expect(imageMocks.revoke).not.toHaveBeenCalled();

    currentQR = qrState({ data: unavailableQR, isFetching: false });
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <WhatsAppConnectionDialog {...view.props} />
      </QueryClientProvider>
    );

    await waitFor(() => expect(imageMocks.revoke).toHaveBeenCalledWith("blob:secure-qr"));
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("fecha com Escape, limpa QR e chama onClose", async () => {
    const user = userEvent.setup();
    const { props } = renderDialog();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(hookMocks.clear).toHaveBeenCalled());
    expect(props.onClose).toHaveBeenCalledOnce();
  });

  it("bloqueia scroll e restaura foco ao fechar", async () => {
    const user = userEvent.setup();
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    const { unmount } = renderDialog();
    expect(document.body.style.overflow).toBe("hidden");
    await user.click(screen.getByRole("button", { name: "Fechar acompanhamento da conexão" }));
    unmount();
    expect(document.body.style.overflow).toBe("");
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it("mostra telefone mascarado conectado sem telefone completo", () => {
    hookMocks.status.mockReturnValue(statusState("connected"));
    hookMocks.qr.mockReturnValue(qrState({ data: undefined }));
    renderDialog({ channel: { ...channel, status: "connected" } });
    expect(screen.getByText("WhatsApp conectado")).toBeInTheDocument();
    expect(screen.getByText("********1234")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("5511999991234");
  });

  it("atualiza QR manualmente e aplica cooldown contra spam", async () => {
    vi.useFakeTimers();
    const refetch = vi.fn().mockResolvedValue({});
    hookMocks.qr.mockReturnValue(qrState({ refetch }));
    renderDialog();
    const button = screen.getByRole("button", { name: "Atualizar QR Code" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(refetch).toHaveBeenCalledOnce();
    expect(button).toBeDisabled();
    act(() => vi.advanceTimersByTime(6_000));
    expect(button).not.toBeDisabled();
    vi.useRealTimers();
  });

  it.each([
    [429, "Muitas atualizações em pouco tempo. Aguarde alguns segundos."],
    [503, "QR Code temporariamente indisponível. Tente novamente em instantes."]
  ])("mostra erro amigavel HTTP %s", (status, message) => {
    hookMocks.qr.mockReturnValue(qrState({
      data: undefined,
      error: {
        normalized: { status, message, fieldErrors: {} }
      }
    }));
    renderDialog();
    expect(screen.getByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByText(String(status))).not.toBeInTheDocument();
  });

  it("nao oferece acoes de lifecycle sem endpoint", () => {
    hookMocks.status.mockReturnValue(statusState("error"));
    hookMocks.qr.mockReturnValue(qrState({ data: undefined }));
    renderDialog({ channel: { ...channel, status: "error" } });
    expect(screen.queryByRole("button", { name: /reiniciar/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /desconectar/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /excluir/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tentar atualizar estado" })).toBeInTheDocument();
  });

  it("nao grava nem registra o QR", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem");
    const consoleLog = vi.spyOn(console, "log").mockImplementation(() => undefined);
    renderDialog();
    await waitFor(() => expect(imageMocks.create).toHaveBeenCalled());
    expect(storage).not.toHaveBeenCalled();
    expect(consoleLog).not.toHaveBeenCalled();
  });
});
