import { clsx } from "clsx";

export type MessageDeliveryStatus = "pending" | "sent" | "delivered" | "read" | "failed" | null;

const STATUS_LABELS: Record<Exclude<MessageDeliveryStatus, null>, string> = {
  pending: "Pendente",
  sent: "Enviada",
  delivered: "Entregue",
  read: "Lida",
  failed: "Falhou"
};

type Props = {
  status: MessageDeliveryStatus;
};

export function MessageDeliveryStatusBadge({ status }: Props) {
  const label = status ? STATUS_LABELS[status] : "Sem status";

  return (
    <span
      className={clsx(
        "inline-flex min-h-7 items-center rounded-pill border px-3 text-xs font-medium",
        status === "pending" && "border-amber-500/30 bg-amber-500/10 text-amber-100",
        status === "sent" && "border-blue-500/30 bg-blue-500/10 text-blue-100",
        status === "delivered" && "border-emerald-500/30 bg-emerald-500/10 text-emerald-100",
        status === "read" && "border-app-primary/40 bg-app-primary/15 text-blue-100",
        status === "failed" && "border-red-500/30 bg-red-500/10 text-red-100",
        status === null && "border-app-border bg-app-menu text-app-muted"
      )}
    >
      {label}
    </span>
  );
}
