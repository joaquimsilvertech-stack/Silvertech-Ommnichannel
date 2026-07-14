import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  activateAIProvider,
  createAIProvider,
  deactivateAIProvider,
  getAIProvider,
  getAIProviders,
  replaceAIProviderCredentials,
  revokeAIProviderCredentials,
  testAIProviderConnection,
  updateAIProvider,
  type AIProviderConfigInput
} from "../lib/aiProviders";

export const aiProvidersQueryKey = (workspaceId: string | number | undefined) => [
  "workspaces",
  workspaceId,
  "ai-providers"
];

export function useAIProviders(workspaceId: string | number | undefined) {
  return useQuery({
    queryKey: aiProvidersQueryKey(workspaceId),
    queryFn: () => getAIProviders(workspaceId!),
    enabled: Boolean(workspaceId)
  });
}

export function useAIProvider(workspaceId: string | number | undefined, providerConfigId: string | undefined) {
  return useQuery({
    queryKey: [...aiProvidersQueryKey(workspaceId), providerConfigId],
    queryFn: () => getAIProvider(workspaceId!, providerConfigId!),
    enabled: Boolean(workspaceId && providerConfigId)
  });
}

export function useCreateAIProvider(workspaceId: string | number | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: AIProviderConfigInput) => createAIProvider(workspaceId!, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: aiProvidersQueryKey(workspaceId) });
    }
  });
}

export function useUpdateAIProvider(workspaceId: string | number | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ providerConfigId, payload }: { providerConfigId: string; payload: AIProviderConfigInput }) =>
      updateAIProvider(workspaceId!, providerConfigId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: aiProvidersQueryKey(workspaceId) });
    }
  });
}

export function useTestAIProviderConnection(workspaceId: string | number | undefined) {
  const queryClient = useQueryClient();
  const transientApiKeyRef = useRef<string | undefined>(undefined);
  const mutation = useMutation({
    mutationFn: (providerConfigId: string) =>
      testAIProviderConnection(
        workspaceId!,
        providerConfigId,
        transientApiKeyRef.current ? { api_key: transientApiKeyRef.current } : undefined
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: aiProvidersQueryKey(workspaceId) });
    },
    onSettled: () => {
      transientApiKeyRef.current = undefined;
    }
  });

  return {
    ...mutation,
    testConnection: (providerConfigId: string, apiKey?: string) => {
      transientApiKeyRef.current = apiKey?.trim() || undefined;
      return mutation.mutateAsync(providerConfigId);
    }
  };
}

export function useActivateAIProvider(workspaceId: string | number | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (providerConfigId: string) => activateAIProvider(workspaceId!, providerConfigId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: aiProvidersQueryKey(workspaceId) });
    }
  });
}

export function useDeactivateAIProvider(workspaceId: string | number | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (providerConfigId: string) => deactivateAIProvider(workspaceId!, providerConfigId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: aiProvidersQueryKey(workspaceId) });
    }
  });
}

export function useReplaceAIProviderCredentials(workspaceId: string | number | undefined) {
  const queryClient = useQueryClient();
  const apiKeyRef = useRef<string | undefined>(undefined);
  const mutation = useMutation({
    mutationFn: (providerConfigId: string) =>
      replaceAIProviderCredentials(
        workspaceId!,
        providerConfigId,
        { api_key: apiKeyRef.current ?? "" }
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: aiProvidersQueryKey(workspaceId) });
    },
    onSettled: () => {
      apiKeyRef.current = undefined;
    }
  });

  return {
    ...mutation,
    replaceCredentials: (providerConfigId: string, apiKey: string) => {
      apiKeyRef.current = apiKey.trim();
      return mutation.mutateAsync(providerConfigId);
    }
  };
}

export function useRevokeAIProviderCredentials(workspaceId: string | number | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (providerConfigId: string) => revokeAIProviderCredentials(workspaceId!, providerConfigId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: aiProvidersQueryKey(workspaceId) });
    }
  });
}
