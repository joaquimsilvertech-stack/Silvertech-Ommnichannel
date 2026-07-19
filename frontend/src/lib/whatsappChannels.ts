import { api } from "./api";
import { normalizeApiError, type NormalizedApiError } from "./apiErrors";

export type WhatsAppChannelStatus =
  | "disconnected"
  | "provisioning"
  | "waiting_qr"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "error"
  | "deleting";

export type WhatsAppChannel = {
  id: string;
  name: string;
  provider: "evolution";
  status: WhatsAppChannelStatus;
  phone_number_masked: string | null;
  has_qr_code: boolean;
  connected_at: string | null;
  last_connection_update_at: string | null;
  created_at: string;
  updated_at: string;
};

export type WhatsAppChannelConnectionStatus = {
  id: string;
  status: WhatsAppChannelStatus;
  phone_number_masked: string | null;
  has_qr_code: boolean;
  connected_at: string | null;
  last_connection_update_at: string | null;
  updated_at: string;
};

export type WhatsAppChannelQRCode = {
  id: string;
  status: WhatsAppChannelStatus;
  has_qr_code: boolean;
  qr_code: string | null;
  format: "base64" | "data_uri" | null;
};

export type CreateWhatsAppChannelInput = {
  name: string;
};

const WHATSAPP_HTTP_STATUS_MESSAGES: Record<number, string> = {
  401: "Sua sessão expirou. Entre novamente.",
  403: "Você não possui permissão para gerenciar os canais deste workspace.",
  404: "Workspace ou canal não encontrado.",
  429: "Muitas atualizações em pouco tempo. Aguarde alguns segundos."
};

const KNOWN_WHATSAPP_ERROR_CODES = new Set([
  "QR_CACHE_UNAVAILABLE",
  "EVOLUTION_TIMEOUT",
  "EVOLUTION_AUTHENTICATION_ERROR",
  "EVOLUTION_CONFIGURATION_ERROR",
  "EVOLUTION_CONNECTION_ERROR",
  "EVOLUTION_UNAVAILABLE",
  "EVOLUTION_RATE_LIMIT",
  "EVOLUTION_INVALID_RESPONSE",
  "EVOLUTION_INVALID_REQUEST",
  "EVOLUTION_NOT_FOUND",
  "EVOLUTION_CONFLICT",
  "EVOLUTION_UNEXPECTED_RESPONSE",
  "EVOLUTION_REQUEST_ERROR"
]);

export function normalizeWhatsAppChannelApiError(error: unknown): NormalizedApiError {
  const normalized = normalizeApiError(error);
  const status = normalized.status ?? 0;
  const statusMessage = WHATSAPP_HTTP_STATUS_MESSAGES[status];

  if (statusMessage) {
    return { ...normalized, message: statusMessage };
  }

  if (
    [502, 503, 504].includes(status) &&
    !KNOWN_WHATSAPP_ERROR_CODES.has(normalized.errorCode ?? "")
  ) {
    return {
      ...normalized,
      message: "O serviço de conexão está temporariamente indisponível. Tente novamente."
    };
  }

  return normalized;
}

export class WhatsAppChannelApiError extends Error {
  normalized: NormalizedApiError;

  constructor(error: unknown) {
    const normalized = normalizeWhatsAppChannelApiError(error);
    super(normalized.message);
    this.name = "WhatsAppChannelApiError";
    this.normalized = normalized;
  }
}

function channelBaseUrl(workspaceId: string | number) {
  return `/api/workspaces/${encodeURIComponent(String(workspaceId))}/whatsapp-channels/`;
}

async function wrapChannelRequest<T>(request: Promise<{ data: T }>): Promise<T> {
  try {
    const { data } = await request;
    return data;
  } catch (error) {
    throw new WhatsAppChannelApiError(error);
  }
}

export async function getWhatsAppChannels(workspaceId: string | number) {
  return wrapChannelRequest<WhatsAppChannel[]>(api.get(channelBaseUrl(workspaceId)));
}

export async function createWhatsAppChannel(
  workspaceId: string | number,
  input: CreateWhatsAppChannelInput
) {
  return wrapChannelRequest<WhatsAppChannel>(
    api.post(channelBaseUrl(workspaceId), { name: input.name })
  );
}

export async function getWhatsAppChannel(workspaceId: string | number, channelId: string) {
  return wrapChannelRequest<WhatsAppChannel>(
    api.get(`${channelBaseUrl(workspaceId)}${encodeURIComponent(channelId)}/`)
  );
}

export async function getWhatsAppChannelStatus(
  workspaceId: string | number,
  channelId: string
) {
  return wrapChannelRequest<WhatsAppChannelConnectionStatus>(
    api.get(`${channelBaseUrl(workspaceId)}${encodeURIComponent(channelId)}/status/`)
  );
}

export async function getWhatsAppChannelQRCode(
  workspaceId: string | number,
  channelId: string
) {
  return wrapChannelRequest<WhatsAppChannelQRCode>(
    api.get(`${channelBaseUrl(workspaceId)}${encodeURIComponent(channelId)}/qr/`)
  );
}
