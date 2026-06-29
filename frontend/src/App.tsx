import { useMemo, useState } from "react";
import { QueryClient, QueryClientProvider, useQueries } from "@tanstack/react-query";
import {
  AddressBook,
  ChatCircleText,
  CheckCircle,
  Kanban,
  Plus,
  Robot,
  UsersThree,
  WarningCircle
} from "@phosphor-icons/react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Button } from "./components/Button";
import { LoginPanel } from "./components/LoginPanel";
import { MetricCard } from "./components/MetricCard";
import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";
import { ResourcePage } from "./pages/ResourcePage";
import {
  Contact,
  Conversation,
  Lead,
  Member,
  Organization,
  Workspace,
  WorkspaceInvite,
  getContacts,
  getConversations,
  getInvites,
  getLeads,
  getMembers,
  getOrganizations,
  getWorkspaces,
  tokenStore
} from "./lib/api";

const queryClient = new QueryClient();

function DashboardPage({ isAuthenticated, onLoggedIn }: { isAuthenticated: boolean; onLoggedIn: () => void }) {
  const [workspacesQuery, contactsQuery, conversationsQuery] = useQueries({
    queries: [
      { queryKey: ["workspaces"], queryFn: getWorkspaces, enabled: isAuthenticated },
      { queryKey: ["contacts"], queryFn: getContacts, enabled: isAuthenticated },
      { queryKey: ["conversations"], queryFn: getConversations, enabled: isAuthenticated }
    ]
  });

  const contacts = contactsQuery.data ?? [];
  const conversations = conversationsQuery.data ?? [];
  const workspaces = workspacesQuery.data ?? [];
  const activeConversations = useMemo(
    () => conversations.filter((conversation) => conversation.status !== "closed").length,
    [conversations]
  );

  return (
    <>
      <div className="mb-8 flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="max-w-3xl">
          <h1 className="text-[30px] font-semibold leading-[38px] text-app-text">Dashboard Omnichannel</h1>
          <p className="mt-2 text-sm leading-[22px] text-app-muted">
            Este frontend agora aponta para as rotas reais do Django/DRF e aplica o design system extraído da Umbler.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="surface" icon={<Robot size={18} />}>Agentes</Button>
          <Button icon={<Plus size={18} />}>Novo contato</Button>
        </div>
      </div>

      <div className="mb-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Conversas abertas" value={activeConversations} detail="/api/omnichannel/conversations/" icon={ChatCircleText} tone="blue" />
        <MetricCard label="Contatos" value={contacts.length} detail="/api/crm/contacts/" icon={AddressBook} />
        <MetricCard label="Workspaces" value={workspaces.length} detail="/api/workspaces/workspaces/" icon={UsersThree} tone="green" />
        <MetricCard label="Status da API" value={isAuthenticated ? "JWT" : "Login"} detail={isAuthenticated ? "Token ativo no cliente." : "Entre para carregar dados."} icon={CheckCircle} tone={isAuthenticated ? "green" : "neutral"} />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_380px]">
        <section className="rounded-card border border-app-border bg-app-surface p-6 shadow-soft">
          <h2 className="text-base font-semibold leading-6 text-white">Mapa de rotas do front para o back</h2>
          <div className="mt-4 overflow-x-auto rounded-card border border-app-border">
            <table className="w-full min-w-[640px] border-collapse text-left text-sm">
              <thead className="bg-app-menu text-white">
                <tr>
                  <th className="px-4 py-3">Tela React</th>
                  <th className="px-4 py-3">Endpoint Django/DRF</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ["/contacts", "/api/crm/contacts/"],
                  ["/leads", "/api/crm/leads/"],
                  ["/organizations", "/api/crm/organizations/"],
                  ["/conversations", "/api/omnichannel/conversations/"],
                  ["/workspaces", "/api/workspaces/workspaces/"],
                  ["/members", "/api/workspaces/members/"],
                  ["/invites", "/api/workspaces/invites/"]
                ].map(([front, api]) => (
                  <tr className="border-t border-app-border hover:bg-app-hover" key={front}>
                    <td className="px-4 py-3 text-app-text">{front}</td>
                    <td className="px-4 py-3 text-app-muted">{api}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <aside className="space-y-6">
          {!isAuthenticated ? <LoginPanel onLoggedIn={onLoggedIn} /> : null}
          <section className="rounded-card border border-app-border bg-app-surface p-6 shadow-soft">
            <div className="mb-4 flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-app-infoBg text-app-secondary">
                <WarningCircle size={22} weight="bold" />
              </span>
              <div>
                <h2 className="text-base font-semibold leading-6 text-white">Importante</h2>
                <p className="text-sm leading-[22px] text-app-muted">O `/` do Django continua sendo API/back-end.</p>
              </div>
            </div>
            <p className="text-sm leading-[22px] text-app-muted">
              Em desenvolvimento, acesse as telas pelo Vite em `5173`. O Vite encaminha `/api` para o Django em `8000`.
            </p>
          </section>
        </aside>
      </div>
    </>
  );
}

function AppLayout() {
  const [isAuthenticated, setIsAuthenticated] = useState(Boolean(tokenStore.getAccess()));
  const onLoggedIn = () => setIsAuthenticated(true);

  return (
    <div className="min-h-screen bg-app-bg text-app-text">
      <div className="flex min-h-screen">
        <Sidebar />
        <div className="min-w-0 flex-1">
          <Topbar />
          <main className="px-4 py-8 lg:px-9">
            <Routes>
              <Route path="/" element={<DashboardPage isAuthenticated={isAuthenticated} onLoggedIn={onLoggedIn} />} />
              <Route
                path="/contacts"
                element={<ResourcePage<Contact> title="Contatos" description="Design aplicado à rota existente de contatos." endpoint="/api/crm/contacts/" icon={AddressBook} queryKey="contacts" queryFn={getContacts} columns={[
                  { header: "Nome", render: (item) => item.name },
                  { header: "Telefone", render: (item) => item.phone },
                  { header: "E-mail", render: (item) => item.email },
                  { header: "Canal", render: (item) => item.channel_id },
                  { header: "Favorito", render: (item) => item.starred ? "Sim" : "Não" }
                ]} />}
              />
              <Route
                path="/leads"
                element={<ResourcePage<Lead> title="Leads" description="Design aplicado à rota existente de leads." endpoint="/api/crm/leads/" icon={Kanban} queryKey="leads" queryFn={getLeads} columns={[
                  { header: "Contato", render: (item) => item.contact_name ?? item.contact },
                  { header: "Status", render: (item) => item.status },
                  { header: "Score", render: (item) => item.score },
                  { header: "Origem", render: (item) => item.source }
                ]} />}
              />
              <Route
                path="/organizations"
                element={<ResourcePage<Organization> title="Organizações" description="Design aplicado à rota existente de organizações." endpoint="/api/crm/organizations/" icon={Robot} queryKey="organizations" queryFn={getOrganizations} columns={[
                  { header: "Nome", render: (item) => item.name },
                  { header: "Workspace", render: (item) => item.workspace?.name },
                  { header: "Contatos", render: (item) => item.contacts?.length ?? 0 }
                ]} />}
              />
              <Route
                path="/conversations"
                element={<ResourcePage<Conversation> title="Conversas" description="Design aplicado à rota existente de conversas." endpoint="/api/omnichannel/conversations/" icon={ChatCircleText} queryKey="conversations" queryFn={getConversations} columns={[
                  {
                    header: "Contato",
                    render: (item) =>
                      item.contact_data?.name ??
                      (typeof item.contact === "object" ? item.contact.name ?? item.contact.id : item.contact)
                  },
                  { header: "Telefone", render: (item) => item.contact_data?.phone },
                  { header: "Canal", render: (item) => item.channel ?? item.channel_name },
                  { header: "Status", render: (item) => item.status }
                ]} />}
              />
              <Route
                path="/workspaces"
                element={<ResourcePage<Workspace> title="Workspaces" description="Design aplicado à rota existente de workspaces." endpoint="/api/workspaces/workspaces/" icon={UsersThree} queryKey="workspaces" queryFn={getWorkspaces} columns={[
                  { header: "Nome", render: (item) => item.name },
                  { header: "Slug", render: (item) => item.slug },
                  { header: "ID", render: (item) => item.id }
                ]} />}
              />
              <Route
                path="/members"
                element={<ResourcePage<Member> title="Membros" description="Design aplicado à rota existente de membros." endpoint="/api/workspaces/members/" icon={UsersThree} queryKey="members" queryFn={getMembers} columns={[
                  { header: "Usuário", render: (item) => item.user?.email },
                  { header: "Workspace", render: (item) => item.workspace?.name },
                  { header: "Papel", render: (item) => item.role }
                ]} />}
              />
              <Route
                path="/invites"
                element={<ResourcePage<WorkspaceInvite> title="Convites" description="Design aplicado à rota existente de convites." endpoint="/api/workspaces/invites/" icon={UsersThree} queryKey="invites" queryFn={getInvites} columns={[
                  { header: "E-mail", render: (item) => item.email },
                  { header: "Workspace", render: (item) => item.workspace?.name },
                  { header: "Papel", render: (item) => item.role },
                  { header: "Aceito", render: (item) => item.accepted ? "Sim" : "Não" }
                ]} />}
              />
            </Routes>
          </main>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppLayout />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
