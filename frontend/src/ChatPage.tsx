import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChatCircleText,
  Checks,
  Clock,
  FunnelSimple,
  MagnifyingGlass,
  PaperPlaneTilt,
  Plus,
  SlidersHorizontal,
  UserCircle
} from "@phosphor-icons/react";
import { clsx } from "clsx";
import { Button } from "./components/Button";
import { Conversation, getConversations } from "./lib/api";

type ConversationTab = "inbox" | "waiting" | "closed";

function contactName(conversation: Conversation) {
  if (conversation.contact_data?.name) return conversation.contact_data.name;
  if (typeof conversation.contact === "object") {
    return conversation.contact.name ?? `Contato #${conversation.contact.id}`;
  }
  return conversation.contact ? `Contato #${conversation.contact}` : "Contato sem nome";
}

function contactPhone(conversation: Conversation) {
  if (conversation.contact_data?.phone) return conversation.contact_data.phone;
  if (typeof conversation.contact === "object") return conversation.contact.phone;
  return undefined;
}

function statusLabel(status?: string) {
  if (!status) return "Entrada";
  const value = status.toLowerCase();
  if (["closed", "finished", "resolved", "finalizado"].includes(value)) return "Finalizado";
  if (["waiting", "pending", "esperando"].includes(value)) return "Esperando";
  return "Entrada";
}

function matchesTab(conversation: Conversation, tab: ConversationTab) {
  const label = statusLabel(conversation.status);
  if (tab === "closed") return label === "Finalizado";
  if (tab === "waiting") return label === "Esperando";
  return label === "Entrada";
}

export function ConversationsPage() {
  const [activeTab, setActiveTab] = useState<ConversationTab>("inbox");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | number | null>(null);

  const query = useQuery({
    queryKey: ["conversations"],
    queryFn: getConversations
  });

  const conversations = query.data ?? [];
  const selectedConversation = conversations.find((conversation) => conversation.id === selectedId);

  const counts = useMemo(
    () => ({
      inbox: conversations.filter((conversation) => matchesTab(conversation, "inbox")).length,
      waiting: conversations.filter((conversation) => matchesTab(conversation, "waiting")).length,
      closed: conversations.filter((conversation) => matchesTab(conversation, "closed")).length
    }),
    [conversations]
  );

  const filteredConversations = conversations.filter((conversation) => {
    const haystack = `${contactName(conversation)} ${contactPhone(conversation) ?? ""} ${conversation.channel ?? ""} ${conversation.status ?? ""}`.toLowerCase();
    return matchesTab(conversation, activeTab) && haystack.includes(search.toLowerCase());
  });

  return (
    <section className="h-[calc(100vh-126px)] min-h-[640px] overflow-hidden rounded-[0_32px_0_0] border border-app-border bg-app-bg shadow-soft">
      <div className="grid h-full grid-cols-1 xl:grid-cols-[377px_minmax(0,1fr)]">
        <aside className="flex min-h-0 flex-col border-r border-app-border bg-app-bg">
          <header className="border-b border-app-border px-4 pb-4 pt-3">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h1 className="text-xl font-semibold leading-6 text-app-text">Conversas</h1>
              <div className="flex items-center gap-2">
                <Button className="h-[46px] w-[46px] rounded-full p-0 text-app-muted" variant="ghost" aria-label="Filtros" icon={<SlidersHorizontal size={20} />} />
                <Button className="h-[38px] w-[38px] rounded-full p-0" aria-label="Nova conversa" icon={<Plus size={18} />} />
              </div>
            </div>

            <div className="mb-4 flex items-center">
              <Button className="h-[37px] rounded-[16px_0_0_16px] border-[#dee2e6] px-3 text-[#dee2e6]" variant="surface" aria-label="Buscar" icon={<MagnifyingGlass size={17} />} />
              <input
                className="h-[37px] min-w-0 flex-1 border-y border-app-border bg-transparent px-3 text-sm text-app-text outline-none placeholder:text-app-muted focus:border-app-secondary"
                placeholder="Buscar por nome ou telefone"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              <Button className="h-[37px] rounded-[0_16px_16px_0] border-[#dee2e6] px-3 text-[#dee2e6]" variant="surface" aria-label="Limpar busca" onClick={() => setSearch("")} icon={<FunnelSimple size={17} />} />
            </div>

            <div className="flex gap-0 overflow-x-auto">
              {[
                { id: "inbox", label: "Entrada", count: counts.inbox },
                { id: "waiting", label: "Esperando", count: counts.waiting },
                { id: "closed", label: "Finalizados", count: counts.closed }
              ].map((tab) => (
                <button
                  className={clsx(
                    "flex h-[33px] shrink-0 items-center gap-2 rounded-pill px-2 py-1 text-sm leading-[22px] transition",
                    activeTab === tab.id ? "bg-app-primary text-white" : "text-app-text hover:bg-app-hover"
                  )}
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as ConversationTab)}
                >
                  <span>{tab.label}</span>
                  <span className={clsx("rounded-pill px-2 text-xs", activeTab === tab.id ? "bg-white/15 text-white" : "bg-app-menu text-app-muted")}>
                    {tab.count}
                  </span>
                </button>
              ))}
            </div>
          </header>

          <div className="border-b border-[#07553b] bg-app-successBg px-4 py-3 text-sm leading-[21px] text-app-text">
            <div className="flex items-start gap-3">
              <Checks className="mt-0.5 shrink-0 text-[#52C41A]" size={22} weight="fill" />
              <p>
                Comunicacao em tempo real ativa para conversas omnichannel.
                <span className="ml-1 rounded-pill bg-[#389e0d] px-3 py-1 text-white">Online</span>
              </p>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {query.isLoading ? (
              <div className="p-6 text-sm text-app-muted">Carregando conversas...</div>
            ) : query.isError ? (
              <div className="m-4 rounded-card border border-[#9C2F27] bg-[#401923] p-4 text-sm text-[#ffb3b3]">
                Nao foi possivel carregar /api/omnichannel/conversations/.
              </div>
            ) : filteredConversations.length ? (
              <div className="divide-y divide-app-border">
                {filteredConversations.map((conversation) => {
                  const selected = selectedId === conversation.id;
                  return (
                    <button
                      className={clsx("flex w-full gap-3 px-4 py-4 text-left transition hover:bg-app-hover", selected && "bg-app-menu")}
                      key={conversation.id}
                      onClick={() => setSelectedId(conversation.id)}
                    >
                      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-app-menu text-app-muted">
                        <UserCircle size={28} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center justify-between gap-3">
                          <strong className="truncate text-sm font-semibold leading-[22px] text-app-text">{contactName(conversation)}</strong>
                          <span className="shrink-0 text-[12px] leading-[18px] text-app-muted">
                            {conversation.updated_at ? new Date(conversation.updated_at).toLocaleDateString("pt-BR") : "agora"}
                          </span>
                        </span>
                        <span className="mt-1 block truncate text-sm leading-[22px] text-app-muted">
                          {contactPhone(conversation) ?? conversation.channel ?? "Sem telefone vinculado"}
                        </span>
                        <span className="mt-2 inline-flex rounded-pill bg-app-infoBg px-2 py-0.5 text-[12px] text-app-secondary">
                          {statusLabel(conversation.status)}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="flex h-full min-h-[280px] items-center justify-center p-6 text-center text-sm text-app-muted">
                Nenhuma conversa encontrada
              </div>
            )}
          </div>
        </aside>

        <main className="relative hidden min-h-0 bg-app-bg xl:block">
          {selectedConversation ? (
            <div className="flex h-full flex-col">
              <header className="flex min-h-[72px] items-center justify-between border-b border-app-border px-6">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-app-menu text-app-muted">
                    <UserCircle size={28} />
                  </span>
                  <div className="min-w-0">
                    <h2 className="truncate text-base font-semibold leading-6 text-white">{contactName(selectedConversation)}</h2>
                    <p className="truncate text-sm leading-[22px] text-app-muted">{contactPhone(selectedConversation) ?? selectedConversation.channel ?? "Canal nao informado"}</p>
                  </div>
                </div>
                <span className="rounded-pill bg-app-successBg px-3 py-1 text-sm text-[#8ad27a]">{statusLabel(selectedConversation.status)}</span>
              </header>
              <div className="flex flex-1 items-center justify-center px-6">
                <div className="max-w-md text-center">
                  <ChatCircleText className="mx-auto text-app-muted" size={64} />
                  <h3 className="mt-4 text-2xl font-semibold leading-[28.8px] text-app-text">Historico da conversa</h3>
                  <p className="mt-2 text-sm leading-[22px] text-app-muted">
                    Este painel esta preparado para receber mensagens quando o endpoint de mensagens for exposto no back-end.
                  </p>
                </div>
              </div>
              <footer className="border-t border-app-border p-4">
                <div className="flex items-center gap-3 rounded-[32px] border border-app-border bg-app-surface px-4 py-3">
                  <input className="min-w-0 flex-1 bg-transparent text-sm text-app-text outline-none placeholder:text-app-muted" placeholder="Escreva uma mensagem..." />
                  <Button className="h-10 w-10 rounded-full p-0" aria-label="Enviar mensagem" icon={<PaperPlaneTilt size={18} weight="fill" />} />
                </div>
              </footer>
            </div>
          ) : (
            <div className="flex h-full items-center justify-center px-8 text-center">
              <div>
                <div className="mx-auto flex h-[168px] w-[168px] items-center justify-center rounded-full border border-app-border bg-app-surface">
                  <ChatCircleText size={72} className="text-app-muted" />
                </div>
                <h3 className="mt-4 text-2xl font-semibold leading-[28.8px] text-app-text">Selecione uma conversa</h3>
                <p className="mt-2 flex items-center justify-center gap-2 text-sm leading-[22px] text-app-muted">
                  <Clock size={16} />
                  Estabelecendo comunicacao em tempo real...
                </p>
              </div>
            </div>
          )}
        </main>
      </div>
    </section>
  );
}
