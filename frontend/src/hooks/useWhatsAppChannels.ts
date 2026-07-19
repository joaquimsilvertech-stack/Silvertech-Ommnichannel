import {
  useMutation,
  useQuery,
  useQueryClient,
  type Query,
  type QueryClient
} from "@tanstack/react-query";
import { normalizeApiError } from "../lib/apiErrors";
import {
  createWhatsAppChannel,
  getWhatsAppChannel,
  getWhatsAppChannelQRCode,
  getWhatsAppChannels,
  getWhatsAppChannelStatus,
  type CreateWhatsAppChannelInput,
  type WhatsAppChannel,
  type WhatsAppChannelConnectionStatus,
  type WhatsAppChannelQRCode
} from "../lib/whatsappChannels";

export const WHATSAPP_CHANNEL_LIST_POLL_MS = 5_000;
export const WHATSAPP_CHANNEL_STATUS_POLL_MS = 3_000;
export const WHATSAPP_CHANNEL_QR_POLL_MS = 10_000;

export function whatsappChannelQRCodeRefetchInterval(
  query: Query<WhatsAppChannelQRCode, Error>
) {
  if (query.state.error) return false;

  const status = query.state.data?.status;
  if (status && status !== "waiting_qr") return false;

  return WHATSAPP_CHANNEL_QR_POLL_MS;
}

export const whatsappChannelQRCodeQueryBehavior = {
  refetchInterval: whatsappChannelQRCodeRefetchInterval,
  refetchIntervalInBackground: false,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
  retry: false,
  gcTime: 0
} as const;

const STATUS_POLLING_STATES = new Set([
  "provisioning",
  "waiting_qr",
  "connecting",
  "reconnecting"
]);

export const whatsappChannelsQueryKey = (workspaceId: string | number | undefined) => [
  "workspaces",
  workspaceId,
  "whatsapp-channels"
];

export const whatsappChannelDetailQueryKey = (
  workspaceId: string | number | undefined,
  channelId: string | undefined
) => [...whatsappChannelsQueryKey(workspaceId), channelId, "detail"];

export const whatsappChannelStatusQueryKey = (
  workspaceId: string | number | undefined,
  channelId: string | undefined
) => [...whatsappChannelsQueryKey(workspaceId), channelId, "status"];

export const whatsappChannelQRCodeQueryKey = (
  workspaceId: string | number | undefined,
  channelId: string | undefined
) => [...whatsappChannelsQueryKey(workspaceId), channelId, "qr"];

export function shouldRetryWhatsAppQuery(failureCount: number, error: unknown) {
  if (failureCount >= 2) return false;
  const status = normalizeApiError(error).status;
  if ([401, 403, 404, 429].includes(status ?? 0)) return false;
  return status === undefined || status >= 500;
}

export function whatsappChannelStatusRefetchInterval(
  query: Query<WhatsAppChannelConnectionStatus, Error>
) {
  const status = query.state.data?.status;
  if (query.state.error && !shouldRetryWhatsAppQuery(0, query.state.error)) return false;
  return !status || STATUS_POLLING_STATES.has(status)
    ? WHATSAPP_CHANNEL_STATUS_POLL_MS
    : false;
}

function whatsappChannelsRefetchInterval(query: Query<WhatsAppChannel[], Error>) {
  if (query.state.error && !shouldRetryWhatsAppQuery(0, query.state.error)) return false;
  return WHATSAPP_CHANNEL_LIST_POLL_MS;
}

export function useWhatsAppChannels(workspaceId: string | number | undefined) {
  return useQuery({
    queryKey: whatsappChannelsQueryKey(workspaceId),
    queryFn: () => getWhatsAppChannels(workspaceId!),
    enabled: Boolean(workspaceId),
    refetchInterval: whatsappChannelsRefetchInterval,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: shouldRetryWhatsAppQuery
  });
}

export function useWhatsAppChannel(
  workspaceId: string | number | undefined,
  channelId: string | undefined
) {
  return useQuery({
    queryKey: whatsappChannelDetailQueryKey(workspaceId, channelId),
    queryFn: () => getWhatsAppChannel(workspaceId!, channelId!),
    enabled: Boolean(workspaceId && channelId),
    retry: shouldRetryWhatsAppQuery
  });
}

export function useWhatsAppChannelStatus(
  workspaceId: string | number | undefined,
  channelId: string | undefined,
  enabled: boolean
) {
  return useQuery({
    queryKey: whatsappChannelStatusQueryKey(workspaceId, channelId),
    queryFn: () => getWhatsAppChannelStatus(workspaceId!, channelId!),
    enabled: Boolean(enabled && workspaceId && channelId),
    refetchInterval: whatsappChannelStatusRefetchInterval,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: shouldRetryWhatsAppQuery
  });
}

export function useWhatsAppChannelQRCode(
  workspaceId: string | number | undefined,
  channelId: string | undefined,
  enabled: boolean
) {
  return useQuery({
    queryKey: whatsappChannelQRCodeQueryKey(workspaceId, channelId),
    queryFn: () => getWhatsAppChannelQRCode(workspaceId!, channelId!),
    enabled: Boolean(enabled && workspaceId && channelId),
    ...whatsappChannelQRCodeQueryBehavior
  });
}

export function useCreateWhatsAppChannel(workspaceId: string | number | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateWhatsAppChannelInput) =>
      createWhatsAppChannel(workspaceId!, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: whatsappChannelsQueryKey(workspaceId) });
    }
  });
}

export async function clearWhatsAppChannelQRCode(
  queryClient: QueryClient,
  workspaceId: string | number | undefined,
  channelId: string | undefined
) {
  const queryKey = whatsappChannelQRCodeQueryKey(workspaceId, channelId);
  await queryClient.cancelQueries({ queryKey, exact: true });
  queryClient.removeQueries({ queryKey, exact: true });
}
