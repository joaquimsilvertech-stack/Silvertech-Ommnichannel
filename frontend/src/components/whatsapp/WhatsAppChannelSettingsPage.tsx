import {
  ArrowLeft,
  CheckCircle,
  Plus,
  QrCode,
  Robot,
  WarningCircle,
  WhatsappLogo
} from "@phosphor-icons/react";
import { useCallback, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Button } from "../Button";
import {
  useCreateWhatsAppChannel,
  useWhatsAppChannels
} from "../../hooks/useWhatsAppChannels";
import { normalizeApiError } from "../../lib/apiErrors";
import type { WhatsAppChannel } from "../../lib/whatsappChannels";
import { CreateWhatsAppChannelForm } from "./CreateWhatsAppChannelForm";
import { WhatsAppChannelCard } from "./WhatsAppChannelCard";
import { WhatsAppConnectionDialog } from "./WhatsAppConnectionDialog";

export function WhatsAppChannelSettingsPage() {
  const { workspaceId } = useParams();
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [selectedChannel, setSelectedChannel] = useState<WhatsAppChannel>();
  const channelsQuery = useWhatsAppChannels(workspaceId);
  const createMutation = useCreateWhatsAppChannel(workspaceId);

  const channels = useMemo(() => channelsQuery.data ?? [], [channelsQuery.data]);
  const summary = useMemo(
    () => ({
      total: channels.length,
      connected: channels.filter((channel) => channel.status === "connected").length,
      waitingQR: channels.filter((channel) => channel.status === "waiting_qr").length,
      issues: channels.filter((channel) => ["error", "disconnected"].includes(channel.status)).length
    }),
    [channels]
  );
  const currentSelectedChannel = selectedChannel
    ? channels.find((channel) => channel.id === selectedChannel.id) ?? selectedChannel
    : undefined;
  const closeConnectionDialog = useCallback(() => setSelectedChannel(undefined), []);

  if (!workspaceId) {
    return (
      <section className="rounded-card border border-red-500/30 bg-red-500/10 p-6 shadow-soft" role="alert">
        <div className="flex items-center gap-3 text-red-100">
          <WarningCircle size={22} />
          <h1 className="text-lg font-semibold">Workspace não informado</h1>
        </div>
        <p className="mt-3 text-sm text-app-muted">Acesse esta página pela lista de Workspaces.</p>
      </section>
    );
  }

  const normalizedError = channelsQuery.error ? normalizeApiError(channelsQuery.error) : undefined;
  const permissionDenied = normalizedError?.status === 403;

  async function createChannel(input: { name: string }) {
    const channel = await createMutation.mutateAsync(input);
    setShowCreateForm(false);
    setSelectedChannel(channel);
    return channel;
  }

  return (
    <div className="space-y-7">
      <header className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
        <div className="max-w-3xl">
          <nav aria-label="Configurações do workspace" className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
            <Link className="inline-flex items-center gap-2 text-app-muted transition hover:text-white" to="/workspaces">
              <ArrowLeft size={16} />
              Voltar para Workspaces
            </Link>
            <Link className="inline-flex items-center gap-2 text-app-secondary transition hover:text-white" to={`/workspaces/${workspaceId}/settings/ai`}>
              <Robot size={16} />
              Configuração de IA
            </Link>
          </nav>
          <div className="flex items-start gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-control bg-app-infoBg text-app-secondary">
              <WhatsappLogo size={24} weight="fill" />
            </span>
            <div>
              <h1 className="text-[28px] font-semibold leading-9 text-white">Canais do workspace</h1>
              <p className="mt-2 text-sm leading-6 text-app-muted">
                Gerencie as conexões WhatsApp usadas pela sua equipe no SilverTech.
              </p>
            </div>
          </div>
        </div>
        {!permissionDenied ? (
          <Button
            className="w-full sm:w-auto"
            icon={<Plus size={18} />}
            onClick={() => setShowCreateForm((current) => !current)}
            type="button"
          >
            Nova conexão
          </Button>
        ) : null}
      </header>

      {permissionDenied ? (
        <section className="rounded-card border border-amber-500/30 bg-amber-500/10 p-6 shadow-soft" role="alert">
          <WarningCircle className="text-amber-200" size={28} />
          <h2 className="mt-4 text-lg font-semibold text-white">
            Você não possui permissão para gerenciar conexões
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-app-muted">
            Somente proprietários e administradores do workspace podem acessar esta área.
          </p>
        </section>
      ) : (
        <>
          {showCreateForm ? (
            <CreateWhatsAppChannelForm
              isSubmitting={createMutation.isPending}
              onCancel={() => setShowCreateForm(false)}
              onSubmit={createChannel}
            />
          ) : null}

          <section aria-labelledby="whatsapp-summary-title">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold text-white" id="whatsapp-summary-title">WhatsApp</h2>
              {!channelsQuery.isLoading ? <span className="text-sm text-app-muted">Visão atual</span> : null}
            </div>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {[
                { label: "Total", value: summary.total, icon: WhatsappLogo, className: "text-app-secondary" },
                { label: "Conectados", value: summary.connected, icon: CheckCircle, className: "text-emerald-300" },
                { label: "Aguardando QR", value: summary.waitingQR, icon: QrCode, className: "text-blue-300" },
                { label: "Com problema", value: summary.issues, icon: WarningCircle, className: "text-red-300" }
              ].map(({ label, value, icon: Icon, className }) => (
                <div className="border-y border-app-border bg-app-surface px-4 py-4" key={label}>
                  <div className="flex items-center gap-2 text-sm text-app-muted">
                    <Icon className={className} size={18} />
                    {label}
                  </div>
                  <p className="mt-2 text-2xl font-semibold text-white">{value}</p>
                </div>
              ))}
            </div>
          </section>

          {channelsQuery.isLoading ? (
            <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="Carregando canais">
              {[0, 1, 2].map((item) => (
                <div className="h-[248px] animate-pulse rounded-card border border-app-border bg-app-surface" key={item} />
              ))}
            </section>
          ) : channelsQuery.isError ? (
            <section className="rounded-card border border-red-500/30 bg-red-500/10 p-6 shadow-soft" role="alert">
              <h2 className="text-base font-semibold text-red-100">Não foi possível carregar as conexões</h2>
              <p className="mt-2 text-sm text-app-muted">{normalizedError?.message}</p>
              {![401, 403, 404, 429].includes(normalizedError?.status ?? 0) ? (
                <Button className="mt-4" onClick={() => void channelsQuery.refetch()} type="button" variant="surface">
                  Tentar novamente
                </Button>
              ) : null}
            </section>
          ) : channels.length === 0 ? (
            <section className="flex min-h-[320px] flex-col items-center justify-center rounded-card border border-dashed border-app-border bg-app-surface px-6 text-center shadow-soft">
              <span className="flex h-14 w-14 items-center justify-center rounded-control bg-app-infoBg text-app-secondary">
                <WhatsappLogo size={30} weight="fill" />
              </span>
              <h2 className="mt-5 text-xl font-semibold text-white">Conecte seu primeiro WhatsApp</h2>
              <p className="mt-2 max-w-md text-sm leading-6 text-app-muted">
                Crie uma conexão para receber e enviar mensagens pelo workspace.
              </p>
              <Button className="mt-5" icon={<Plus size={18} />} onClick={() => setShowCreateForm(true)} type="button">
                Conectar WhatsApp
              </Button>
            </section>
          ) : (
            <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="Canais WhatsApp">
              {channels.map((channel) => (
                <WhatsAppChannelCard channel={channel} key={channel.id} onOpen={setSelectedChannel} />
              ))}
            </section>
          )}
        </>
      )}

      {currentSelectedChannel && !permissionDenied ? (
        <WhatsAppConnectionDialog
          channel={currentSelectedChannel}
          onClose={closeConnectionDialog}
          open
          workspaceId={workspaceId}
        />
      ) : null}
    </div>
  );
}
