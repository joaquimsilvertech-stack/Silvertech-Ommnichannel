import axios from "axios";

export type NormalizedApiError = {
  status?: number;
  message: string;
  errorCode?: string;
  fieldErrors: Record<string, string[]>;
};

const ERROR_MESSAGES: Record<string, string> = {
  INVALID_CREDENTIALS: "Credencial invalida. Verifique a chave cadastrada.",
  RATE_LIMITED: "Provider limitou as requisicoes. Tente novamente em instantes.",
  PROVIDER_TIMEOUT: "O provider demorou para responder.",
  AI_PROVIDER_TIMEOUT: "O provider demorou para responder.",
  UNSUPPORTED_PROVIDER: "Este provider ainda nao esta disponivel no runtime.",
  MISSING_API_KEY: "Cadastre uma chave antes de ativar."
};

function sanitizeText(value: unknown): string {
  if (typeof value !== "string") return "";
  return value
    .replace(/sk-[A-Za-z0-9_-]+/g, "[redacted]")
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
      ...normalized
    };
  }

  if (axios.isAxiosError(error)) {
    const normalized = payloadToError(error.response?.data);
    return {
      status: error.response?.status,
      ...normalized
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
