import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import {
  createWhatsAppChannel,
  getWhatsAppChannel,
  getWhatsAppChannelQRCode,
  getWhatsAppChannels,
  getWhatsAppChannelStatus,
  WhatsAppChannelApiError
} from "./whatsappChannels";

const channel = {
  id: "channel-1",
  name: "WhatsApp principal",
  provider: "evolution" as const,
  status: "waiting_qr" as const,
  phone_number_masked: null,
  has_qr_code: true,
  connected_at: null,
  last_connection_update_at: null,
  created_at: "2026-07-18T12:00:00Z",
  updated_at: "2026-07-18T12:00:00Z"
};

describe("whatsappChannels API client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lista canais no endpoint tenant-scoped", async () => {
    const spy = vi.spyOn(api, "get").mockResolvedValueOnce({ data: [channel] });
    await expect(getWhatsAppChannels("workspace-1")).resolves.toEqual([channel]);
    expect(spy).toHaveBeenCalledWith("/api/workspaces/workspace-1/whatsapp-channels/");
  });

  it("cria canal enviando somente name", async () => {
    const spy = vi.spyOn(api, "post").mockResolvedValueOnce({ data: channel });
    await createWhatsAppChannel("workspace-1", {
      name: "WhatsApp principal",
      workspace_id: "workspace-2",
      instance_name: "private-instance",
      instance_token: "private-token",
      webhook_secret: "private-secret"
    } as never);
    expect(spy).toHaveBeenCalledWith("/api/workspaces/workspace-1/whatsapp-channels/", {
      name: "WhatsApp principal"
    });
  });

  it("consulta detalhe usando Workspace e canal", async () => {
    const spy = vi.spyOn(api, "get").mockResolvedValueOnce({ data: channel });
    await getWhatsAppChannel("workspace-1", "channel-1");
    expect(spy).toHaveBeenCalledWith(
      "/api/workspaces/workspace-1/whatsapp-channels/channel-1/"
    );
  });

  it("consulta status no endpoint local", async () => {
    const spy = vi.spyOn(api, "get").mockResolvedValueOnce({ data: channel });
    await getWhatsAppChannelStatus("workspace-1", "channel-1");
    expect(spy).toHaveBeenCalledWith(
      "/api/workspaces/workspace-1/whatsapp-channels/channel-1/status/"
    );
  });

  it("consulta QR somente no endpoint dedicado", async () => {
    const qr = { id: "channel-1", status: "waiting_qr", has_qr_code: true, qr_code: "encoded", format: "base64" };
    const spy = vi.spyOn(api, "get").mockResolvedValueOnce({ data: qr });
    await expect(getWhatsAppChannelQRCode("workspace-1", "channel-1")).resolves.toEqual(qr);
    expect(spy).toHaveBeenCalledWith(
      "/api/workspaces/workspace-1/whatsapp-channels/channel-1/qr/"
    );
  });

  it("nao possui URL externa nem credenciais no client", () => {
    const source = [
      getWhatsAppChannels,
      createWhatsAppChannel,
      getWhatsAppChannel,
      getWhatsAppChannelStatus,
      getWhatsAppChannelQRCode
    ].map((fn) => fn.toString()).join(" ");
    expect(source).not.toContain("EVOLUTION_API_URL");
    expect(source).not.toContain("EVOLUTION_API_KEY");
    expect(source).not.toContain("instance_token");
    expect(source).not.toContain("webhook_secret");
    expect(source).not.toContain("fetch(");
  });

  it.each([
    [403, "Você não possui permissão para gerenciar os canais deste workspace."],
    [429, "Muitas atualizações em pouco tempo. Aguarde alguns segundos."]
  ])("normaliza status HTTP %s", async (status, message) => {
    vi.spyOn(api, "get").mockRejectedValueOnce({ response: { status, data: {} } });
    const error = await getWhatsAppChannels("workspace-1").catch((value) => value);
    expect(error).toBeInstanceOf(WhatsAppChannelApiError);
    expect(error.normalized.status).toBe(status);
    expect(error.message).toBe(message);
  });

  it("normaliza erro de QR sem expor corpo remoto", async () => {
    vi.spyOn(api, "get").mockRejectedValueOnce({
      response: {
        status: 503,
        data: {
          error_code: "QR_CACHE_UNAVAILABLE",
          detail: "private-token https://private.example/qr"
        }
      }
    });
    const error = await getWhatsAppChannelQRCode("workspace-1", "channel-1").catch((value) => value);
    expect(error.message).toBe("QR Code temporariamente indisponível. Tente novamente em instantes.");
    expect(error.message).not.toContain("private-token");
    expect(error.message).not.toContain("private.example");
  });

  it("nao grava respostas em storage", async () => {
    const local = vi.spyOn(Storage.prototype, "setItem");
    vi.spyOn(api, "get").mockResolvedValueOnce({ data: [channel] });
    await getWhatsAppChannels("workspace-1");
    expect(local).not.toHaveBeenCalled();
  });
});
