import axios from "axios";

export type NormalizedApiError = {
  status?: number;
  message: string;
  errorCode?: string;
  fieldErrors: Record<string, string[]>;
};

const ERROR_MESSAGES: Record<string, string> = {
  INVALID_CREDENTIALS: "Credencial invalida. Verifique a chave informada.",
  RATE_LIMITED: "Provider limitou as requisicoes. Tente novamente em instantes.",
  PROVIDER_TIMEOUT: "O provider demorou para responder. Tente novamente.",
  AI_PROVIDER_TIMEOUT: "O provider demorou para responder.",
  PROVIDER_UNAVAILABLE: "O provider esta indisponivel no momento.",
  PROVIDER_ERROR: "Nao foi possivel validar a credencial agora.",
  UNSUPPORTED_PROVIDER: "Este provider ainda nao esta disponivel no runtime.",
  MISSING_API_KEY: "Informe uma chave antes de continuar.",
  QR_CACHE_UNAVAILABLE: "QR Code temporariamente indisponível. Tente novamente em instantes.",
  EVOLUTION_TIMEOUT: "A conexão demorou para responder. Tente novamente.",
  EVOLUTION_AUTHENTICATION_ERROR: "Não foi possível consultar a conexão agora.",
  EVOLUTION_CONFIGURATION_ERROR: "Não foi possível consultar a conexão agora.",
  EVOLUTION_CONNECTION_ERROR: "O serviço de conexão está temporariamente indisponível.",
  EVOLUTION_UNAVAILABLE: "O serviço de conexão está temporariamente indisponível.",
  EVOLUTION_RATE_LIMIT: "O serviço de conexão está temporariamente indisponível.",
  EVOLUTION_INVALID_RESPONSE: "O serviço retornou uma resposta inválida.",
  EVOLUTION_INVALID_REQUEST: "Não foi possível obter o QR Code.",
  EVOLUTION_NOT_FOUND: "Não foi possível obter o QR Code.",
  EVOLUTION_CONFLICT: "Não foi possível obter o QR Code.",
  EVOLUTION_UNEXPECTED_RESPONSE: "Não foi possível obter o QR Code.",
  EVOLUTION_REQUEST_ERROR: "Não foi possível obter o QR Code."
};

const HTTP_STATUS_MESSAGES: Record<number, string> = {
  401: "Sua sessão expirou. Entre novamente.",
  403: "Você não possui permissão para realizar esta ação.",
  404: "Recurso não encontrado.",
  429: "Muitas solicitações em pouco tempo. Aguarde alguns segundos."
};

function sanitizeText(value: unknown): string {
  if (typeof value !== "string") return "";
  return value
    .replace(/sk-[A-Za-z0-9_-]+/g, "[redacted]")
    .replace(/Bearer\s+\S+/gi, "[redacted]")
    .replace(/https?:\/\/\S+/gi, "[redacted]")
    .replace(/api_key/gi, "credencial")
    .replace(/authorization/gi, "autorizacao")
    .slice(0, 240);
}

function firstString(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return firstString(value[0]);
  return "";
}

function sanitizeErrorCode(value: unknown): string | undefined {
  const raw = firstString(value);
  if (!raw) return undefined;
  return raw
    .replace(/[^A-Za-z0-9_]/g, "_")
    .slice(0, 80)
    .toUpperCase();
}

function payloadToError(payload: unknown): Pick<NormalizedApiError, "message" | "errorCode" | "fieldErrors"> {
  const fieldErrors: Record<string, string[]> = {};
  if (!payload || typeof payload !== "object") {
    return { message: "Nao foi possivel concluir a acao.", fieldErrors };
  }

  const record = payload as Record<string, unknown>;
  const errorCode = sanitizeErrorCode(record.error_code || record.code);
  const detail = sanitizeText(firstString(record.detail));
  const nonFieldError = sanitizeText(firstString(record.non_field_errors));

  for (const [field, value] of Object.entries(record)) {
    if (["detail", "non_field_errors", "error_code", "code"].includes(field)) continue;
    const error = sanitizeText(firstString(value));
    if (error) fieldErrors[field] = [error];
  }

  const friendly = errorCode ? ERROR_MESSAGES[errorCode] : undefined;
  return {
    message: friendly || detail || nonFieldError || "Nao foi possivel concluir a acao.",
    errorCode,
    fieldErrors
  };
}

export function normalizeApiError(error: unknown): NormalizedApiError {
  if (error && typeof error === "object" && "normalized" in error) {
    const normalized = (error as { normalized?: NormalizedApiError }).normalized;
    if (normalized) return normalized;
  }

  if (error && typeof error === "object" && "response" in error) {
    const response = (error as { response?: { status?: number; data?: unknown } }).response;
    const normalized = payloadToError(response?.data);
    return {
      status: response?.status,
      ...normalized,
      message: normalizeHttpStatusMessage(response?.status, normalized)
    };
  }

  if (axios.isAxiosError(error)) {
    const normalized = payloadToError(error.response?.data);
    return {
      status: error.response?.status,
      ...normalized,
      message: normalizeHttpStatusMessage(error.response?.status, normalized)
    };
  }

  if (error instanceof Error) {
    return {
      message: sanitizeText(error.message) || "Erro inesperado.",
      fieldErrors: {}
    };
  }

  return {
    message: "Erro inesperado.",
    fieldErrors: {}
  };
}

function normalizeHttpStatusMessage(
  status: number | undefined,
  normalized: Pick<NormalizedApiError, "message" | "errorCode">
): string {
  if (!status) return normalized.message;
  if (HTTP_STATUS_MESSAGES[status]) return HTTP_STATUS_MESSAGES[status];
  if ([502, 503, 504].includes(status)) {
    if (normalized.errorCode && ERROR_MESSAGES[normalized.errorCode]) {
      return ERROR_MESSAGES[normalized.errorCode];
    }
    return "O serviço está temporariamente indisponível. Tente novamente.";
  }
  return normalized.message;
}
