import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { api, tokenStore } from "./lib/api";

vi.mock("./components/whatsapp/WhatsAppChannelSettingsPage", () => ({
  WhatsAppChannelSettingsPage: () => <div>Canais WhatsApp route</div>
}));

vi.mock("./components/ai/AIProviderSettingsPage", () => ({
  AIProviderSettingsPage: () => <div>IA route</div>
}));

describe("App workspace settings routes", () => {
  beforeEach(() => {
    vi.spyOn(tokenStore, "getAccess").mockReturnValue(null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.history.pushState({}, "", "/");
  });

  it("renderiza pagina de canais na rota tenant-scoped", () => {
    window.history.pushState({}, "", "/workspaces/workspace-1/settings/channels");
    render(<App />);
    expect(screen.getByText("Canais WhatsApp route")).toBeInTheDocument();
  });

  it("adiciona links de IA e WhatsApp para o Workspace correto", async () => {
    vi.spyOn(api, "get").mockResolvedValue({
      data: [{ id: "workspace-1", name: "Workspace teste", slug: "workspace-teste" }]
    });
    window.history.pushState({}, "", "/workspaces");
    render(<App />);
    await waitFor(() => expect(screen.getByText("Workspace teste")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Configurar IA" })).toHaveAttribute(
      "href",
      "/workspaces/workspace-1/settings/ai"
    );
    expect(screen.getByRole("link", { name: "Configurar WhatsApp" })).toHaveAttribute(
      "href",
      "/workspaces/workspace-1/settings/channels"
    );
  });

  it("preserva a rota de configuracao de IA e o Sidebar", () => {
    window.history.pushState({}, "", "/workspaces/workspace-1/settings/ai");
    render(<App />);
    expect(screen.getByText("IA route")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Workspaces" })).toHaveAttribute("href", "/workspaces");
    expect(screen.queryByRole("link", { name: "Configurar WhatsApp" })).not.toBeInTheDocument();
  });
});
