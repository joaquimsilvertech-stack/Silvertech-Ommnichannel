import {
  CheckCircle,
  CircleNotch,
  ClockCountdown,
  Plugs,
  QrCode,
  Trash,
  WarningCircle,
  type Icon
} from "@phosphor-icons/react";
import type { WhatsAppChannelStatus } from "../../lib/whatsappChannels";

export type WhatsAppChannelStatusPresentation = {
  label: string;
  description: string;
  icon: Icon;
  iconClassName: string;
  badgeClassName: string;
  isAnimated?: boolean;
};

export const whatsappChannelStatusPresentation: Record<
  WhatsAppChannelStatus,
  WhatsAppChannelStatusPresentation
> = {
  provisioning: {
    label: "Preparando",
    description: "Criando a conexão segura.",
    icon: CircleNotch,
    iconClassName: "text-app-secondary",
    badgeClassName: "border-app-primary/30 bg-app-infoBg text-blue-100",
    isAnimated: true
  },
  waiting_qr: {
    label: "Aguardando QR Code",
    description: "Leia o QR Code com o WhatsApp.",
    icon: QrCode,
    iconClassName: "text-app-secondary",
    badgeClassName: "border-app-primary/30 bg-app-infoBg text-blue-100"
  },
  connecting: {
    label: "Conectando",
    description: "Confirmando a conexão do aparelho.",
    icon: CircleNotch,
    iconClassName: "text-app-secondary",
    badgeClassName: "border-app-primary/30 bg-app-infoBg text-blue-100",
    isAnimated: true
  },
  connected: {
    label: "Conectado",
    description: "WhatsApp pronto para uso.",
    icon: CheckCircle,
    iconClassName: "text-emerald-300",
    badgeClassName: "border-emerald-500/30 bg-emerald-500/10 text-emerald-100"
  },
  reconnecting: {
    label: "Reconectando",
    description: "Tentando restaurar a conexão.",
    icon: CircleNotch,
    iconClassName: "text-amber-300",
    badgeClassName: "border-amber-500/30 bg-amber-500/10 text-amber-100",
    isAnimated: true
  },
  disconnected: {
    label: "Desconectado",
    description: "O aparelho não está conectado.",
    icon: Plugs,
    iconClassName: "text-app-muted",
    badgeClassName: "border-app-border bg-app-bg text-app-muted"
  },
  error: {
    label: "Problema na conexão",
    description: "Não foi possível concluir a conexão.",
    icon: WarningCircle,
    iconClassName: "text-red-300",
    badgeClassName: "border-red-500/30 bg-red-500/10 text-red-100"
  },
  deleting: {
    label: "Removendo",
    description: "A conexão está sendo removida.",
    icon: Trash,
    iconClassName: "text-app-muted",
    badgeClassName: "border-app-border bg-app-bg text-app-muted"
  }
};

const UNKNOWN_STATUS: WhatsAppChannelStatusPresentation = {
  label: "Estado indisponível",
  description: "Não foi possível consultar o estado agora.",
  icon: ClockCountdown,
  iconClassName: "text-app-muted",
  badgeClassName: "border-app-border bg-app-bg text-app-muted"
};

export function getWhatsAppChannelStatusPresentation(status: string) {
  return whatsappChannelStatusPresentation[status as WhatsAppChannelStatus] ?? UNKNOWN_STATUS;
}
