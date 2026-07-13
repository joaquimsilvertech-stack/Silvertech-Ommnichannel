import { MessageDeliveryStatusBadge, type MessageDeliveryStatus } from "./MessageDeliveryStatusBadge";

export type MessageDeliveryInfo = {
  id: string;
  direction: "inbound" | "outbound";
  status: MessageDeliveryStatus;
  external_id?: string | null;
  send_error_code?: string;
  send_attempt_count?: number;
  last_send_attempt_at?: string | null;
  next_send_retry_at?: string | null;
};

function formatDateTime(value?: string | null) {
  if (!value) return undefined;
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short"
  }).format(new Date(value));
}

export function MessageRetryInfo({ message }: { message: MessageDeliveryInfo }) {
  const nextRetryAt = formatDateTime(message.next_send_retry_at);
  const lastAttemptAt = formatDateTime(message.last_send_attempt_at);
  const attempts = message.send_attempt_count ?? 0;

  return (
    <div className="rounded-control border border-app-border bg-app-bg p-3 text-sm">
      <div className="mb-2">
        <MessageDeliveryStatusBadge status={message.status} />
      </div>
      <dl className="grid gap-2 text-app-muted">
        {attempts > 0 ? (
          <div className="flex items-center justify-between gap-4">
            <dt>Tentativas de envio</dt>
            <dd className="text-app-text">{attempts}</dd>
          </div>
        ) : null}
        {lastAttemptAt ? (
          <div className="flex items-center justify-between gap-4">
            <dt>Ultima tentativa</dt>
            <dd className="text-app-text">{lastAttemptAt}</dd>
          </div>
        ) : null}
        {message.status === "pending" && nextRetryAt ? (
          <div className="flex items-center justify-between gap-4">
            <dt>Nova tentativa</dt>
            <dd className="text-app-text">{nextRetryAt}</dd>
          </div>
        ) : null}
        {message.status === "failed" && message.send_error_code ? (
          <div className="flex items-center justify-between gap-4">
            <dt>Erro</dt>
            <dd className="font-mono text-red-100">{message.send_error_code}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
}
