import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { WhatsAppChannel } from "../../lib/whatsappChannels";
import { WhatsAppChannelSettingsPage } from "./WhatsAppChannelSettingsPage";

const hookMocks = vi.hoisted(() => ({
  create: vi.fn(),
  list: vi.fn()
}));

vi.mock("../../hooks/useWhatsAppChannels", () => ({
  useCreateWhatsAppChannel: (...args: unknown[]) => hookMocks.create(...args),
  useWhatsAppChannels: (...args: unknown[]) => hookMocks.list(...args)
}));

vi.mock("./WhatsAppConnectionDialog", () => ({
  WhatsAppConnectionDialog: ({ channel }: { channel: WhatsAppChannel }) => (
    <div role="dialog">Painel de {channel.name}</div>
  )
}));

const channel: WhatsAppChannel = {
  id: "channel-private-id",
  name: "WhatsApp principal",
  provider: "evolution",
  status: "connected",
  phone_number_masked: "********1234",
  has_qr_code: false,
  connected_at: "2026-07-18T12:00:00Z",
  last_connection_update_at: "2026-07-18T12:00:00Z",
  created_at: "2026-07-18T12:00:00Z",
  updated_at: "2026-07-18T12:00:00Z"
};

function listState(overrides: Record<string, unknown> = {}) {
  return {
    data: [channel],
    error: undefined,
    isError: false,
    isLoading: false,
    refetch: vi.fn(),
    ...overrides
  };
}

function renderPage(path = "/workspaces/workspace-private-id/settings/channels") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/workspaces/:workspaceId/settings/channels" element={<WhatsAppChannelSettingsPage />} />
        <Route path="/settings/channels" element={<WhatsAppChannelSettingsPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("WhatsAppChannelSettingsPage", () => {
  const mutateAsync = vi.fn();

  beforeEach(() => {
    hookMocks.list.mockReset();
    hookMocks.create.mockReset();
    mutateAsync.mockReset();
    hookMocks.list.mockReturnValue(listState());
    hookMocks.create.mockReturnValue({ isPending: false, mutateAsync });
    mutateAsync.mockResolvedValue(channel);
  });

  it("mostra erro seguro quando Workspace esta ausente", () => {
    renderPage("/settings/channels");
    expect(screen.getByRole("alert")).toHaveTextContent("Workspace não informado");
    expect(screen.queryByText("workspace-private-id")).not.toBeInTheDocument();
  });

  it("renderiza loading inicial", () => {
    hookMocks.list.mockReturnValue(listState({ data: undefined, isLoading: true }));
    renderPage();
    expect(screen.getByLabelText("Carregando canais")).toBeInTheDocument();
  });

  it("renderiza estado vazio e CTA", () => {
    hookMocks.list.mockReturnValue(listState({ data: [] }));
    renderPage();
    expect(screen.getByText("Conecte seu primeiro WhatsApp")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Conectar WhatsApp" })).toBeInTheDocument();
  });

  it("lista dados publicos sem exibir identificadores ou campos tecnicos", () => {
    renderPage();
    expect(screen.getByText("WhatsApp principal")).toBeInTheDocument();
    expect(screen.getByText("********1234")).toBeInTheDocument();
    expect(screen.getByText("Conectado")).toBeInTheDocument();
    expect(screen.queryByText("channel-private-id")).not.toBeInTheDocument();
    expect(screen.queryByText("workspace-private-id")).not.toBeInTheDocument();
    expect(screen.queryByText("evolution")).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("5511999991234");
    expect(document.body).not.toHaveTextContent("instance_name");
    expect(document.body).not.toHaveTextContent("instance_token");
  });

  it("mostra acao correta para waiting QR e erro generico", () => {
    hookMocks.list.mockReturnValue(listState({
      data: [
        { ...channel, id: "waiting", name: "Com QR", status: "waiting_qr" },
        { ...channel, id: "error", name: "Com erro", status: "error" }
      ]
    }));
    renderPage();
    expect(screen.getByRole("button", { name: "Exibir QR Code" })).toBeInTheDocument();
    expect(screen.getByText("A conexão precisa de atenção.")).toBeInTheDocument();
    expect(screen.queryByText("last_error_code")).not.toBeInTheDocument();
  });

  it("status desconhecido nao quebra a pagina", () => {
    hookMocks.list.mockReturnValue(listState({ data: [{ ...channel, status: "future_status" }] }));
    renderPage();
    expect(screen.getByText("Estado indisponível")).toBeInTheDocument();
    expect(screen.getByText("Estado somente para leitura")).toBeInTheDocument();
  });

  it("403 mostra permissao negada sem formulario ou dados", () => {
    hookMocks.list.mockReturnValue(listState({
      data: undefined,
      error: { normalized: { status: 403, message: "proibido", fieldErrors: {} } },
      isError: true
    }));
    renderPage();
    expect(screen.getByText("Você não possui permissão para gerenciar conexões")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Nova conexão" })).not.toBeInTheDocument();
    expect(screen.queryByText("WhatsApp principal")).not.toBeInTheDocument();
  });

  it("normaliza nome, envia somente name e abre acompanhamento", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Nova conexão" }));
    await user.type(screen.getByLabelText("Nome da conexão"), "  WhatsApp   vendas  ");
    await user.click(screen.getByRole("button", { name: "Criar conexão" }));
    expect(mutateAsync).toHaveBeenCalledWith({ name: "WhatsApp vendas" });
    expect(await screen.findByRole("dialog")).toHaveTextContent("Painel de WhatsApp principal");
  });

  it("impede submit duplicado enquanto a primeira chamada aguarda", async () => {
    mutateAsync.mockReturnValue(new Promise(() => undefined));
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Nova conexão" }));
    await user.type(screen.getByLabelText("Nome da conexão"), "Principal");
    const form = screen.getByLabelText("Nome da conexão").closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(mutateAsync).toHaveBeenCalledOnce();
  });

  it("preserva nome quando a criacao falha", async () => {
    mutateAsync.mockRejectedValue({
      normalized: { status: 503, message: "Erro seguro.", fieldErrors: {} }
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Nova conexão" }));
    const input = screen.getByLabelText("Nome da conexão");
    await user.type(input, "WhatsApp vendas");
    await user.click(screen.getByRole("button", { name: "Criar conexão" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Erro seguro.");
    expect(input).toHaveValue("WhatsApp vendas");
  });

  it("mantem links de retorno e configuracao de IA", () => {
    renderPage();
    expect(screen.getByRole("link", { name: "Voltar para Workspaces" })).toHaveAttribute("href", "/workspaces");
    expect(screen.getByRole("link", { name: "Configuração de IA" })).toHaveAttribute(
      "href",
      "/workspaces/workspace-private-id/settings/ai"
    );
  });

  it("usa os tokens centrais do design system", async () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Canais do workspace" })).toHaveClass("text-white");
    await waitFor(() => expect(document.querySelector(".bg-app-surface")).toBeInTheDocument());
  });
});
