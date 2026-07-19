import {
  CheckCircle,
  CircleNotch,
  Info,
  WarningCircle,
  X
} from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState
} from "react";
import { Button } from "../Button";
import {
  clearWhatsAppChannelQRCode,
  useWhatsAppChannelQRCode,
  useWhatsAppChannelStatus,
  whatsappChannelDetailQueryKey,
  whatsappChannelsQueryKey
} from "../../hooks/useWhatsAppChannels";
import { normalizeApiError } from "../../lib/apiErrors";
import {
  createQRCodeObjectURL,
  QR_IMAGE_ERROR_MESSAGE,
  revokeQRCodeObjectURL
} from "../../lib/qrImage";
import type {
  WhatsAppChannel
} from "../../lib/whatsappChannels";
import { WhatsAppQRCode } from "./WhatsAppQRCode";
import { getWhatsAppChannelStatusPresentation } from "./whatsappChannelStatusPresentation";

const QR_REFRESH_COOLDOWN_MS = 6_000;

type Props = {
  channel: WhatsAppChannel;
  open: boolean;
  workspaceId: string | number;
  onClose: () => void;
};

export function WhatsAppConnectionDialog({ channel, open, workspaceId, onClose }: Props) {
  const queryClient = useQueryClient();
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const objectUrlRef = useRef<string | null>(null);
  const previousStatusRef = useRef(channel.status);
  const closeInProgressRef = useRef(false);
  const cooldownTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [qrImageError, setQrImageError] = useState<string>();
  const [qrCooldown, setQrCooldown] = useState(false);

  const statusQuery = useWhatsAppChannelStatus(workspaceId, channel.id, open);
  const statusBeforeQR = statusQuery.data?.status ?? channel.status;
  const qrQuery = useWhatsAppChannelQRCode(
    workspaceId,
    channel.id,
    open && statusBeforeQR === "waiting_qr"
  );
  const effectiveStatus =
    qrQuery.data?.status && qrQuery.data.status !== "waiting_qr"
      ? qrQuery.data.status
      : statusBeforeQR;
  const currentPhone = statusQuery.data?.phone_number_masked ?? channel.phone_number_masked;
  const presentation = getWhatsAppChannelStatusPresentation(effectiveStatus);
  const StatusIcon = presentation.icon;

  const replaceObjectUrl = useCallback((nextObjectUrl: string | null) => {
    if (objectUrlRef.current && objectUrlRef.current !== nextObjectUrl) {
      revokeQRCodeObjectURL(objectUrlRef.current);
    }
    objectUrlRef.current = nextObjectUrl;
    setObjectUrl(nextObjectUrl);
  }, []);

  const clearSensitiveQRCode = useCallback(async () => {
    await clearWhatsAppChannelQRCode(queryClient, workspaceId, channel.id);
    replaceObjectUrl(null);
    setQrImageError(undefined);
  }, [channel.id, queryClient, replaceObjectUrl, workspaceId]);

  const handleClose = useCallback(() => {
    if (closeInProgressRef.current) return;
    closeInProgressRef.current = true;
    if (cooldownTimerRef.current) clearTimeout(cooldownTimerRef.current);
    void clearSensitiveQRCode().finally(() => {
      setQrCooldown(false);
      closeInProgressRef.current = false;
      onClose();
    });
  }, [clearSensitiveQRCode, onClose]);

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();

    function handleDocumentKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        handleClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleDocumentKeyDown);
    return () => {
      document.removeEventListener("keydown", handleDocumentKeyDown);
      document.body.style.overflow = previousOverflow;
      opener?.focus();
    };
  }, [handleClose, open]);

  useEffect(() => {
    const qr = qrQuery.data;
    if (effectiveStatus !== "waiting_qr" || qrQuery.isFetching) return;

    if (qr && (!qr.has_qr_code || !qr.qr_code || !qr.format)) {
      replaceObjectUrl(null);
      setQrImageError(undefined);
      return;
    }

    if (!qr?.has_qr_code || !qr.qr_code || !qr.format) return;

    try {
      const nextObjectUrl = createQRCodeObjectURL(qr.qr_code, qr.format);
      replaceObjectUrl(nextObjectUrl);
      setQrImageError(undefined);
    } catch {
      setQrImageError(QR_IMAGE_ERROR_MESSAGE);
    }
  }, [effectiveStatus, qrQuery.data, qrQuery.isFetching, replaceObjectUrl]);

  useEffect(() => {
    if (effectiveStatus === "waiting_qr") return;
    void clearSensitiveQRCode();
  }, [clearSensitiveQRCode, effectiveStatus]);

  useEffect(() => {
    const latest = statusQuery.data;
    if (!latest) return;
    queryClient.setQueryData<WhatsAppChannel[]>(
      whatsappChannelsQueryKey(workspaceId),
      (channels) => channels?.map((item) => (item.id === channel.id ? { ...item, ...latest } : item))
    );
    queryClient.setQueryData<WhatsAppChannel>(
      whatsappChannelDetailQueryKey(workspaceId, channel.id),
      (detail) => (detail ? { ...detail, ...latest } : detail)
    );
    if (latest.status === "connected" && previousStatusRef.current !== "connected") {
      void queryClient.invalidateQueries({ queryKey: whatsappChannelsQueryKey(workspaceId) });
    }
    previousStatusRef.current = latest.status;
  }, [channel.id, queryClient, statusQuery.data, workspaceId]);

  useEffect(() => {
    return () => {
      if (cooldownTimerRef.current) clearTimeout(cooldownTimerRef.current);
      revokeQRCodeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
      void clearWhatsAppChannelQRCode(queryClient, workspaceId, channel.id);
    };
  }, [channel.id, queryClient, workspaceId]);

  function refreshQRCode() {
    if (qrCooldown || qrQuery.isFetching) return;
    setQrCooldown(true);
    void qrQuery.refetch();
    cooldownTimerRef.current = setTimeout(() => setQrCooldown(false), QR_REFRESH_COOLDOWN_MS);
  }

  if (!open) return null;

  const requestError = statusQuery.error
    ? normalizeApiError(statusQuery.error).message
    : undefined;
  const qrError = qrImageError ?? (qrQuery.error ? normalizeApiError(qrQuery.error).message : undefined);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 p-0 sm:items-center sm:p-6"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) handleClose();
      }}
    >
      <div
        aria-labelledby={titleId}
        aria-modal="true"
        className="max-h-[94vh] w-full overflow-y-auto rounded-t-card border border-app-border bg-app-surface shadow-soft sm:max-w-4xl sm:rounded-card"
        ref={dialogRef}
        role="dialog"
      >
        <header className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-app-border bg-app-surface px-5 py-4 sm:px-6">
          <div className="min-w-0">
            <p className="text-sm text-app-muted">Conexão WhatsApp</p>
            <h2 className="mt-1 break-words text-xl font-semibold text-white" id={titleId} tabIndex={-1}>
              {channel.name}
            </h2>
          </div>
          <button
            aria-label="Fechar acompanhamento da conexão"
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-app-text transition hover:bg-app-hover hover:text-white focus:outline-none focus:ring-4 focus:ring-app-primary/20"
            onClick={handleClose}
            ref={closeButtonRef}
            type="button"
          >
            <X size={19} />
          </button>
        </header>

        <div className="px-5 py-6 sm:px-6">
          <div className="flex items-start gap-3" aria-live="polite">
            <span className={`mt-0.5 ${presentation.iconClassName}`}>
              <StatusIcon className={presentation.isAnimated ? "animate-spin" : ""} size={24} />
            </span>
            <div>
              <p className="font-semibold text-white">{presentation.label}</p>
              <p className="mt-1 text-sm leading-6 text-app-muted">{presentation.description}</p>
            </div>
          </div>

          {requestError ? (
            <p className="mt-5 rounded-control border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-100" role="alert">
              {requestError}
            </p>
          ) : null}

          {effectiveStatus === "provisioning" ? (
            <section className="mt-8 flex min-h-[250px] flex-col items-center justify-center text-center">
              <CircleNotch className="animate-spin text-app-secondary" size={46} />
              <h3 className="mt-5 text-lg font-semibold text-white">Preparando sua conexão</h3>
              <p className="mt-2 text-sm text-app-muted">Isso pode levar alguns segundos.</p>
            </section>
          ) : null}

          {effectiveStatus === "waiting_qr" ? (
            <section className="mt-7 grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
              <div>
                <h3 className="text-lg font-semibold text-white">Leia o QR Code</h3>
                <ol className="mt-4 space-y-3 text-sm leading-6 text-app-text">
                  {[
                    "Abra o WhatsApp no celular.",
                    "Acesse aparelhos conectados.",
                    "Escolha conectar um aparelho.",
                    "Leia o código exibido."
                  ].map((instruction, index) => (
                    <li className="flex gap-3" key={instruction}>
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-app-infoBg text-xs font-semibold text-app-secondary">
                        {index + 1}
                      </span>
                      <span>{instruction}</span>
                    </li>
                  ))}
                </ol>
                <div className="mt-5 flex gap-2 rounded-control border border-app-border bg-app-bg p-3 text-sm leading-6 text-app-muted">
                  <Info className="mt-0.5 shrink-0" size={18} />
                  O código é temporário e desaparece assim que a conexão for confirmada.
                </div>
              </div>
              <WhatsAppQRCode
                error={qrError}
                loading={qrQuery.isFetching || qrCooldown}
                objectUrl={objectUrl}
                onRefresh={refreshQRCode}
              />
            </section>
          ) : null}

          {effectiveStatus === "connecting" ? (
            <section className="mt-8 flex min-h-[250px] flex-col items-center justify-center text-center">
              <CircleNotch className="animate-spin text-app-secondary" size={46} />
              <h3 className="mt-5 text-lg font-semibold text-white">Confirmando conexão</h3>
              <p className="mt-2 text-sm text-app-muted">QR Code lido. Confirmando conexão.</p>
            </section>
          ) : null}

          {effectiveStatus === "connected" ? (
            <section className="mt-8 flex min-h-[250px] flex-col items-center justify-center text-center">
              <CheckCircle className="text-emerald-300" size={56} weight="fill" />
              <h3 className="mt-5 text-xl font-semibold text-white">WhatsApp conectado</h3>
              <p className="mt-2 text-sm text-app-muted">Sua conexão está pronta para uso.</p>
              {currentPhone ? <p className="mt-4 font-medium text-app-text">{currentPhone}</p> : null}
            </section>
          ) : null}

          {effectiveStatus === "reconnecting" ? (
            <section className="mt-8 flex min-h-[250px] flex-col items-center justify-center text-center">
              <CircleNotch className="animate-spin text-amber-300" size={46} />
              <h3 className="mt-5 text-lg font-semibold text-white">Reconectando</h3>
              <p className="mt-2 text-sm text-app-muted">Tentando restaurar a conexão.</p>
            </section>
          ) : null}

          {["disconnected", "error"].includes(effectiveStatus) ? (
            <section className="mt-8 flex min-h-[230px] flex-col items-center justify-center text-center">
              <WarningCircle className={effectiveStatus === "error" ? "text-red-300" : "text-app-muted"} size={48} />
              <h3 className="mt-5 text-lg font-semibold text-white">
                {effectiveStatus === "error" ? "A conexão precisa de atenção" : "WhatsApp desconectado"}
              </h3>
              <p className="mt-2 max-w-md text-sm leading-6 text-app-muted">
                Atualize o estado para consultar novamente. Nenhuma alteração remota será executada.
              </p>
              <Button className="mt-5" onClick={() => void statusQuery.refetch()} type="button" variant="surface">
                {statusQuery.isFetching ? "Atualizando..." : "Tentar atualizar estado"}
              </Button>
            </section>
          ) : null}

          {effectiveStatus === "deleting" ? (
            <section className="mt-8 flex min-h-[230px] flex-col items-center justify-center text-center">
              <p className="text-lg font-semibold text-white">Removendo conexão</p>
              <p className="mt-2 text-sm text-app-muted">Este estado está disponível somente para leitura.</p>
            </section>
          ) : null}

          {![
            "provisioning",
            "waiting_qr",
            "connecting",
            "connected",
            "reconnecting",
            "disconnected",
            "error",
            "deleting"
          ].includes(effectiveStatus) ? (
            <section className="mt-8 min-h-[200px] text-center">
              <p className="text-lg font-semibold text-white">Estado indisponível</p>
              <p className="mt-2 text-sm text-app-muted">Não foi possível consultar o estado agora.</p>
            </section>
          ) : null}
        </div>

        <footer className="flex justify-end border-t border-app-border px-5 py-4 sm:px-6">
          <Button onClick={handleClose} type="button">
            {effectiveStatus === "connected" ? "Concluir" : "Fechar"}
          </Button>
        </footer>
      </div>
    </div>
  );
}
