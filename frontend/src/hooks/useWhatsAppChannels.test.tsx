import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  create: vi.fn(),
  detail: vi.fn(),
  list: vi.fn(),
  qr: vi.fn(),
  status: vi.fn()
}));

vi.mock("../lib/whatsappChannels", () => ({
  createWhatsAppChannel: apiMocks.create,
  getWhatsAppChannel: apiMocks.detail,
  getWhatsAppChannelQRCode: apiMocks.qr,
  getWhatsAppChannels: apiMocks.list,
  getWhatsAppChannelStatus: apiMocks.status
}));

import {
  clearWhatsAppChannelQRCode,
  shouldRetryWhatsAppQuery,
  useCreateWhatsAppChannel,
  useWhatsAppChannelQRCode,
  useWhatsAppChannels,
  whatsappChannelQRCodeQueryBehavior,
  whatsappChannelQRCodeQueryKey,
  whatsappChannelQRCodeRefetchInterval,
  whatsappChannelsQueryKey,
  whatsappChannelStatusQueryKey,
  whatsappChannelStatusRefetchInterval,
  WHATSAPP_CHANNEL_QR_POLL_MS,
  WHATSAPP_CHANNEL_STATUS_POLL_MS
} from "./useWhatsAppChannels";

function createHarness() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  });
  function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  return { queryClient, Wrapper };
}

function qrRefetchInterval(status?: string, error: unknown = null) {
  return whatsappChannelQRCodeRefetchInterval({
    state: {
      data: status ? { status } : undefined,
      error
    }
  } as never);
}

describe("WhatsApp channel query hooks", () => {
  beforeEach(() => {
    Object.values(apiMocks).forEach((mock) => mock.mockReset());
    apiMocks.list.mockResolvedValue([]);
    apiMocks.qr.mockResolvedValue({ has_qr_code: false });
    apiMocks.create.mockResolvedValue({ id: "channel-1" });
  });

  it("inclui workspace e canal em todas as query keys", () => {
    expect(whatsappChannelsQueryKey("workspace-1")).toEqual([
      "workspaces", "workspace-1", "whatsapp-channels"
    ]);
    expect(whatsappChannelStatusQueryKey("workspace-1", "channel-1")).toContain("channel-1");
    expect(whatsappChannelQRCodeQueryKey("workspace-1", "channel-1")).toContain("workspace-1");
    expect(whatsappChannelsQueryKey("workspace-1")).not.toEqual(whatsappChannelsQueryKey("workspace-2"));
  });

  it("desabilita listagem sem Workspace", () => {
    const { Wrapper } = createHarness();
    renderHook(() => useWhatsAppChannels(undefined), { wrapper: Wrapper });
    expect(apiMocks.list).not.toHaveBeenCalled();
  });

  it.each([
    [false, "waiting_qr"],
    [true, "connected"],
    [true, "error"]
  ])("desabilita QR quando enabled=%s e status externo=%s", (enabled) => {
    const { Wrapper } = createHarness();
    renderHook(() => useWhatsAppChannelQRCode("workspace-1", "channel-1", enabled), {
      wrapper: Wrapper
    });
    if (enabled) expect(apiMocks.qr).toHaveBeenCalledOnce();
    else expect(apiMocks.qr).not.toHaveBeenCalled();
  });

  it("desabilita QR sem canal", () => {
    const { Wrapper } = createHarness();
    renderHook(() => useWhatsAppChannelQRCode("workspace-1", undefined, true), { wrapper: Wrapper });
    expect(apiMocks.qr).not.toHaveBeenCalled();
  });

  it("configura QR sem retry, sem foco, gc zero e polling de dez segundos", () => {
    const { queryClient, Wrapper } = createHarness();
    renderHook(() => useWhatsAppChannelQRCode("workspace-1", "channel-1", true), { wrapper: Wrapper });
    const query = queryClient.getQueryCache().find({
      queryKey: whatsappChannelQRCodeQueryKey("workspace-1", "channel-1")
    });
    expect(query?.options.gcTime).toBe(0);
    expect(whatsappChannelQRCodeQueryBehavior.retry).toBe(false);
    expect(whatsappChannelQRCodeQueryBehavior.refetchOnWindowFocus).toBe(false);
    expect(whatsappChannelQRCodeQueryBehavior.refetchOnReconnect).toBe(false);
    expect(whatsappChannelQRCodeQueryBehavior.refetchInterval).toBe(
      whatsappChannelQRCodeRefetchInterval
    );
    expect(qrRefetchInterval()).toBe(WHATSAPP_CHANNEL_QR_POLL_MS);
    expect(60_000 / WHATSAPP_CHANNEL_QR_POLL_MS).toBeLessThan(10);
  });

  it("desabilita refetch automatico do QR ao reconectar a rede", () => {
    expect(whatsappChannelQRCodeQueryBehavior.refetchOnReconnect).toBe(false);
  });

  it("mantem polling de QR em waiting_qr sem erro", () => {
    expect(qrRefetchInterval("waiting_qr")).toBe(WHATSAPP_CHANNEL_QR_POLL_MS);
  });

  it.each(["connected", "connecting", "error"])(
    "para polling de QR quando resposta informa %s",
    (status) => {
      expect(qrRefetchInterval(status)).toBe(false);
    }
  );

  it.each([401, 403, 404, 429, 502, 503, 504])(
    "para polling de QR depois do erro HTTP %s",
    (status) => {
      expect(qrRefetchInterval("waiting_qr", { response: { status, data: {} } })).toBe(false);
    }
  );

  it("para polling de QR depois de erro de rede", () => {
    expect(qrRefetchInterval("waiting_qr", new Error("Network Error"))).toBe(false);
  });

  it("retoma intervalo normal depois de tentativa manual bem-sucedida", () => {
    expect(qrRefetchInterval("waiting_qr", new Error("Network Error"))).toBe(false);
    expect(qrRefetchInterval("waiting_qr")).toBe(WHATSAPP_CHANNEL_QR_POLL_MS);
  });

  it.each(["provisioning", "waiting_qr", "connecting", "reconnecting"])(
    "mantem polling de status em %s",
    (status) => {
      const interval = whatsappChannelStatusRefetchInterval({
        state: { data: { status }, error: null }
      } as never);
      expect(interval).toBe(WHATSAPP_CHANNEL_STATUS_POLL_MS);
    }
  );

  it.each(["connected", "disconnected", "error", "deleting"])(
    "para polling de status em %s",
    (status) => {
      const interval = whatsappChannelStatusRefetchInterval({
        state: { data: { status }, error: null }
      } as never);
      expect(interval).toBe(false);
    }
  );

  it.each([401, 403, 404, 429])("nao repete erro HTTP %s", (status) => {
    expect(shouldRetryWhatsAppQuery(0, { response: { status, data: {} } })).toBe(false);
  });

  it("invalida a listagem depois da criacao", async () => {
    const { queryClient, Wrapper } = createHarness();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useCreateWhatsAppChannel("workspace-1"), { wrapper: Wrapper });
    await result.current.mutateAsync({ name: "Principal" });
    expect(apiMocks.create).toHaveBeenCalledWith("workspace-1", { name: "Principal" });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: whatsappChannelsQueryKey("workspace-1") });
  });

  it("cancela e remove somente a query sensivel do QR", async () => {
    const queryClient = new QueryClient();
    const cancel = vi.spyOn(queryClient, "cancelQueries");
    const remove = vi.spyOn(queryClient, "removeQueries");
    await clearWhatsAppChannelQRCode(queryClient, "workspace-1", "channel-1");
    const expected = {
      queryKey: whatsappChannelQRCodeQueryKey("workspace-1", "channel-1"),
      exact: true
    };
    expect(cancel).toHaveBeenCalledWith(expected);
    expect(remove).toHaveBeenCalledWith(expected);
  });

  it("remove query QR ao desmontar por gcTime zero", async () => {
    const { queryClient, Wrapper } = createHarness();
    const key = whatsappChannelQRCodeQueryKey("workspace-1", "channel-1");
    const view = renderHook(() => useWhatsAppChannelQRCode("workspace-1", "channel-1", true), {
      wrapper: Wrapper
    });
    await waitFor(() => expect(apiMocks.qr).toHaveBeenCalled());
    view.unmount();
    await waitFor(() => expect(queryClient.getQueryState(key)).toBeUndefined());
  });
});
