import { ArrowRight, DeviceMobile, WhatsappLogo } from "@phosphor-icons/react";
import { Button } from "../Button";
import type { WhatsAppChannel } from "../../lib/whatsappChannels";
import { getWhatsAppChannelStatusPresentation } from "./whatsappChannelStatusPresentation";

type Props = {
  channel: WhatsAppChannel;
  onOpen: (channel: WhatsAppChannel) => void;
};

function formatUpdatedAt(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Atualização indisponível";
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short"
  }).format(date);
}

function actionLabel(status: string) {
  if (status === "waiting_qr") return "Exibir QR Code";
  if (["provisioning", "connecting", "reconnecting"].includes(status)) {
    return "Acompanhar conexão";
  }
  if (status === "connected") return "Ver estado";
  if (["disconnected", "error"].includes(status)) return "Atualizar estado";
  return null;
}

export function WhatsAppChannelCard({ channel, onOpen }: Props) {
  const presentation = getWhatsAppChannelStatusPresentation(channel.status);
  const StatusIcon = presentation.icon;
  const action = actionLabel(channel.status);
  const cardDescription = channel.status === "error"
    ? "A conexão precisa de atenção."
    : presentation.description;

  return (
    <article className="flex min-h-[248px] flex-col rounded-card border border-app-border bg-app-surface p-5 shadow-soft">
      <div className="flex items-start justify-between gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-control bg-app-infoBg text-app-secondary">
          <WhatsappLogo size={22} weight="fill" />
        </span>
        <span className={`inline-flex min-h-8 items-center gap-2 rounded-pill border px-3 py-1 text-xs font-medium ${presentation.badgeClassName}`}>
          <StatusIcon className={presentation.isAnimated ? "animate-spin" : ""} size={15} />
          {presentation.label}
        </span>
      </div>

      <div className="mt-4 min-w-0">
        <h3 className="break-words text-base font-semibold text-white">{channel.name}</h3>
        <p className="mt-1 text-sm text-app-muted">WhatsApp</p>
        <p className="mt-3 text-sm leading-6 text-app-text">{cardDescription}</p>
      </div>

      <dl className="mt-4 grid gap-2 text-sm">
        {channel.phone_number_masked ? (
          <div className="flex items-center gap-2">
            <DeviceMobile className="text-app-muted" size={17} />
            <dt className="sr-only">Telefone</dt>
            <dd className="text-app-text">{channel.phone_number_masked}</dd>
          </div>
        ) : null}
        <div>
          <dt className="inline text-app-muted">Atualizado: </dt>
          <dd className="inline text-app-text">{formatUpdatedAt(channel.updated_at)}</dd>
        </div>
      </dl>

      <div className="mt-auto pt-5">
        {action ? (
          <Button
            className="w-full"
            icon={<ArrowRight size={17} />}
            onClick={() => onOpen(channel)}
            type="button"
            variant="surface"
          >
            {action}
          </Button>
        ) : (
          <p className="text-sm text-app-muted">
            {channel.status === "deleting" ? "Removendo conexão" : "Estado somente para leitura"}
          </p>
        )}
      </div>
    </article>
  );
}
