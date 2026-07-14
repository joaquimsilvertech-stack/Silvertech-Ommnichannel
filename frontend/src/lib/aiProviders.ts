import { api } from "./api";
import { normalizeApiError, type NormalizedApiError } from "./apiErrors";

export type AIProviderName = "openai" | "anthropic" | "google";

export type WorkspaceAIProviderConfig = {
  id: string;
  provider: AIProviderName;
  model_name: string;
  system_prompt: string;
  settings: Record<string, unknown>;
  is_active: boolean;
  has_api_key: boolean;
  is_supported: boolean;
  created_at: string;
  updated_at: string;
};

export type AIProviderConfigInput = {
  provider?: AIProviderName;
  model_name?: string;
  system_prompt?: string;
  settings?: Record<string, unknown>;
  api_key?: string;
};

export type AIProviderCredentialsInput = {
  api_key: string;
};

export type AIProviderConnectionTestResult = {
  success: boolean;
  provider: AIProviderName;
  model_name: string;
  message?: string;
  error_code?: string;
};

export class AIProviderApiError extends Error {
  normalized: NormalizedApiError;

  constructor(error: unknown) {
    const normalized = normalizeApiError(error);
    super(normalized.message);
    this.name = "AIProviderApiError";
    this.normalized = normalized;
  }
}

function providerBaseUrl(workspaceId: string | number) {
  return `/api/workspaces/${workspaceId}/ai-providers/`;
}

function sanitizeProviderPayload(input: AIProviderConfigInput, options: { includeApiKey?: boolean } = {}): AIProviderConfigInput {
  const { provider, model_name, system_prompt, settings, api_key } = input;
  const includeApiKey = options.includeApiKey ?? true;
  const payload: AIProviderConfigInput = {};

  if (provider) payload.provider = provider;
  if (model_name !== undefined) payload.model_name = model_name;
  if (system_prompt !== undefined) payload.system_prompt = system_prompt;
  if (settings !== undefined) payload.settings = settings;
  if (includeApiKey && api_key && api_key.trim()) payload.api_key = api_key.trim();

  return payload;
}

async function wrapProviderRequest<T>(request: Promise<{ data: T }>): Promise<T> {
  try {
    const { data } = await request;
    return data;
  } catch (error) {
    throw new AIProviderApiError(error);
  }
}

export async function getAIProviders(workspaceId: string | number) {
  return wrapProviderRequest<WorkspaceAIProviderConfig[]>(
    api.get(providerBaseUrl(workspaceId))
  );
}

export async function getAIProvider(workspaceId: string | number, providerConfigId: string) {
  return wrapProviderRequest<WorkspaceAIProviderConfig>(
    api.get(`${providerBaseUrl(workspaceId)}${providerConfigId}/`)
  );
}

export async function createAIProvider(workspaceId: string | number, input: AIProviderConfigInput) {
  return wrapProviderRequest<WorkspaceAIProviderConfig>(
    api.post(providerBaseUrl(workspaceId), sanitizeProviderPayload(input))
  );
}

export async function updateAIProvider(
  workspaceId: string | number,
  providerConfigId: string,
  input: AIProviderConfigInput
) {
  return wrapProviderRequest<WorkspaceAIProviderConfig>(
    api.patch(`${providerBaseUrl(workspaceId)}${providerConfigId}/`, sanitizeProviderPayload(input, { includeApiKey: false }))
  );
}

export async function testAIProviderConnection(
  workspaceId: string | number,
  providerConfigId: string,
  input?: Pick<AIProviderConfigInput, "api_key">
) {
  const payload = input?.api_key?.trim() ? { api_key: input.api_key.trim() } : {};
  return wrapProviderRequest<AIProviderConnectionTestResult>(
    api.post(`${providerBaseUrl(workspaceId)}${providerConfigId}/test/`, payload)
  );
}

export async function activateAIProvider(workspaceId: string | number, providerConfigId: string) {
  return wrapProviderRequest<WorkspaceAIProviderConfig>(
    api.post(`${providerBaseUrl(workspaceId)}${providerConfigId}/activate/`, {})
  );
}

export async function deactivateAIProvider(workspaceId: string | number, providerConfigId: string) {
  return wrapProviderRequest<WorkspaceAIProviderConfig>(
    api.post(`${providerBaseUrl(workspaceId)}${providerConfigId}/deactivate/`, {})
  );
}

export async function replaceAIProviderCredentials(
  workspaceId: string | number,
  providerConfigId: string,
  input: AIProviderCredentialsInput
) {
  const payload = input.api_key.trim() ? { api_key: input.api_key.trim() } : {};
  return wrapProviderRequest<WorkspaceAIProviderConfig>(
    api.post(`${providerBaseUrl(workspaceId)}${providerConfigId}/credentials/replace/`, payload)
  );
}

export async function revokeAIProviderCredentials(workspaceId: string | number, providerConfigId: string) {
  return wrapProviderRequest<WorkspaceAIProviderConfig>(
    api.post(`${providerBaseUrl(workspaceId)}${providerConfigId}/credentials/revoke/`, {})
  );
}
