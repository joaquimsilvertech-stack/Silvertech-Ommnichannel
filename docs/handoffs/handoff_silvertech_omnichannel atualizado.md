# Handoff — SilverTech CRM Omnichannel

> **Como usar este documento.** Cole-o no início de um chat novo para restaurar o contexto do projeto. Ele registra o estado atual, as decisões tomadas (e seus porquês), o backlog aberto e as premissas de código já verificadas. **O código-fonte é a fonte de verdade**; este documento cobre o que o código *não* conta: decisões não-escritas, itens adiados e onde paramos. Destinado a qualquer assistente de IA (incluindo Claude Code em chat limpo, que só enxerga o repositório local).
>
> **Última atualização:** após o micro-fix do Swagger UI (commit `a11e8c2`). Ver §3 para o estado por parte e §8 para itens em aberto.

---

## 0. Papel do assistente e fluxo de trabalho

O assistente atua como **arquiteto técnico**. O trabalho avança por "partes" do roadmap, uma de cada vez, cada uma isolada e com commit próprio. Fluxo por parte:

1. O usuário descreve a próxima parte.
2. O assistente **clona o repo e valida as premissas no código real** antes de escrever qualquer prompt (nunca presume nomes de campo, arquivos de teste, assinaturas).
3. O assistente entrega um **prompt completo em `.md`** para o usuário colar no **Claude Code Desktop** (chat limpo por parte).
4. Claude Code implementa, roda a suíte e devolve um **relatório**.
5. O usuário cola o relatório de volta; o assistente **clona a master, valida cada afirmação no código** (rodando os testes quando possível) e monta um **checklist de follow-ups**.
6. Se não houver fix urgente, o usuário commita/`push`, confirma o CI, e dá `/clear` no Claude Code para a próxima parte.

**Regras invariantes de qualquer prompt/entrega:** arquitetura limpa · API First · multi-tenant por Workspace · segurança · escalabilidade · compatibilidade retroativa quando possível · idempotência · isolamento entre Workspaces · observabilidade · testes (nunca remover existentes; sempre adicionar para novas regras) · sem "quick fix" quando há solução arquitetural melhor · sem mudanças grandes sem justificar.

**Preferências de prompt (manter):** persona de engenheiro sênior; contexto de roadmap curto no topo (o chat do Claude Code é limpo e não vê PDFs nem este handoff); **PASSO 1 de inspeção obrigatória** com verificações explícitas; guardrails de "não implemente parte futura"; `manage.py check` + `makemigrations --check` (esperado `No changes detected` quando a parte não toca models); rodar suíte focada + completa; `git diff --check`; **não criar commit**; reportar com saída real.

**Ambiente:** Windows/PowerShell. Interpreter do venv: `.\venv\Scripts\python.exe`. Servir com **ASGI/uvicorn** (`silvertech.asgi:application`), não `runserver`.

**Checklist de follow-up (formato por item):** Severidade 🔴 bug/segurança (agora) · 🟡 dívida/inconsistência (depois) · 🟢 opcional/estético — **O quê** · **Onde** (arquivo/símbolo) · **Prompt sugerido**.

**Lição de processo aprendida:** houve casos de commit/push **antes** do CI passar; numa ocasião a master ficou com build vermelho (ver §8, item do `requirements.txt`). Preferir **CI verde antes do push**, ou ao menos antes da validação do arquiteto. "Verde local" ≠ "verde no CI" (o pipeline é mais estrito que o `pip` no Windows local).

---

## 1. O que é o sistema

CRM Omnichannel SaaS **multi-tenant por Workspace**. Objetivo do trilho atual: transformar a integração com a **Evolution API v2 (WhatsApp)** num fluxo **self-service por Workspace** — o cliente conecta o próprio WhatsApp dentro do SilverTech (sem copiar UUID, criar instância manual ou configurar webhook no painel da Evolution).

**Stack:** Python 3.12 · Django 6.0.5 · DRF 3.17 · PostgreSQL · Redis · Celery 5.5 · Evolution API v2 · Channels/django-eventstream (SSE). Auth por **JWT (SimpleJWT)**. `drf-spectacular` (Swagger). `django-csp` (CSP estrita). Front-end React/Vite (estado em §7).

**Repo:** https://github.com/joaquimsilvertech-stack/Silvertech-Ommnichannel (branch `master`).

**Apps Django:** `core` (usuário/auth/segurança/middleware), `workspaces` (tenant + membership + permissões), `crm` (contatos/leads/orgs + mixin de scoping), `omnichannel` (WhatsApp/Evolution/conversas/mensagens), `tickets`, `automations`.

---

## 2. Premissas de código já verificadas (não reinvestigar do zero)

**Auth e usuários**
- `AUTH_USER_MODEL = 'core.CustomUser'`: login por **e-mail** (`USERNAME_FIELD='email'`), PK UUID, herda `AbstractUser` (`username=None`). `CustomUserManager.create_user(email, password=None, **extra)`. Campo `role` de **plataforma** (`admin`/`agent`/`viewer`, default `VIEWER`) — **distinto** de `Member.Role`.
- Login usa `ModelBackend` padrão → match exato de e-mail (não há `AUTHENTICATION_BACKENDS` custom). O cadastro grava e-mail em caixa baixa canônica (`normalize_email(...).lower()`), então login com a forma canônica funciona.
- Auth existente: `POST /api/auth/token/` e `/api/auth/token/refresh/` (throttle scope `auth = 5/minute`). Cadastro: `POST /api/auth/register/` (público, `AllowAny`, `authentication_classes=[]`, throttle `auth_register = 5/minute`).
- **JWT:** `ACCESS_TOKEN_LIFETIME = 60 min`, `REFRESH_TOKEN_LIFETIME = 7 dias` (valores cravados em `settings.py`; ver §8 para a sugestão de parametrizar por env).

**Workspaces e permissões**
- `workspaces.Workspace`: `name` + `slug` (`SlugField(max_length=128, unique=True)`, obrigatório, derivado do nome da empresa no cadastro — não enviado pelo cliente). M2M com users via `Member`.
- `workspaces.Member.Role`: `OWNER`/`ADMIN`/`AGENT` (default `AGENT`); constraint única `(workspace, user)`.
- **Fonte única de checagem de membership:** `workspaces/authorization.py::user_has_workspace_role(user, workspace_id, allowed_roles)` — bypass de superuser + query `Member`. Reutilizada por `workspaces/permissions.py::IsWorkspaceAdminMember` (`{OWNER, ADMIN}`) e pela política de canais. **Direção de dependência: omnichannel → workspaces.**
- `WorkspaceScopedQuerysetMixin` (`crm/mixins.py`): escopa querysets aos workspaces em que o usuário é **membro de qualquer role**. É o que dá acesso de AGENT às conversas.

**Omnichannel / WhatsApp**
- `WhatsAppChannel` (canal por workspace; campos criptografados `instance_token`/`webhook_secret`/`phone_number`; `instance_name` unique; `Status`: `DISCONNECTED`/`PROVISIONING`/`WAITING_QR`/`CONNECTING`/`CONNECTED`/`RECONNECTING`/`ERROR`/`DELETING`).
- `EvolutionWebhookEvent`: recibo técnico idempotente. **Guarda só metadados** (`event_type`, `status` [`PROCESSING`/`PROCESSED`/`IGNORED`/`FAILED`], `deduplication_key`, `attempt_count`, `error_code`) — **não armazena payload bruto** (decisão de segurança). Consequência operacional: para capturar payloads reais da Evolution é preciso um inspetor de túnel (ex.: ngrok `http://127.0.0.1:4040`).
- Helper **`mask_whatsapp_phone_number`** em `omnichannel/whatsapp_channel_read_service.py` (retorna `********`+4 dígitos, ou `None` para vazio/curto) — **fonte de verdade de mascaramento; reutilizar sempre**.
- **Envio de mensagem é durável/assíncrono:** `POST /api/omnichannel/conversations/{id}/reply/` (payload `{"body": "..."}`, campo do `MessageCreateSerializer`) cria `Message OUTBOUND/PENDING` → `transaction.on_commit` → task Celery `send_outbound_whatsapp_message` → Evolution. Criar `Message` na mão **não** dispara isso.
- **SSE:** `omnichannel/signals.py` publica eventos `message` e `message_status` no canal `workspace-{id}` (django-eventstream) no `post_save` de `Message`. Requer ASGI/uvicorn.
- **Client Evolution:** `omnichannel/evolution/base.py::BaseEvolutionClient` (ABC) com `create_instance`, `configure_webhook`, `get_qr_code`, `get_connection_state`, `send_text`, `restart_instance`, `logout_instance`, `delete_instance`. **Injeção de dependência via `client=None`** em todos os serviços (facilita fake/testes).
- **Erro seguro:** padrão `WhatsAppChannelProvisioningError`/`SAFE_*` sanitiza `error_code` e nunca vaza detalhe da Evolution. **Nota:** `_sanitize_error_code` está **duplicado em 4 módulos** (`provisioning`, `qr_service`, `outbound_routing`, `evolution_event_processing`) — dívida em §8.
- **FKs relevantes ao remover canal:** `Conversation.whatsapp_channel = SET_NULL` (conversa vira legado, não some); `EvolutionWebhookEvent.whatsapp_channel = CASCADE`.
- **URL de webhook:** `build_evolution_channel_webhook_url` valida `EVOLUTION_WEBHOOK_PUBLIC_BASE_URL` (sem espaço/query/fragmento/credencial; HTTPS obrigatório só se `IS_PRODUCTION`). Header de autenticação do webhook: `X-SilverTech-Webhook-Secret`. **Segredo inválido → resposta 404** (não 401/403), por design de não-vazamento.
- **Provisionamento é síncrono no request** (dívida de escalabilidade — ver §8/Parte 35). As ações restart/disconnect/remove também são síncronas, por coerência.

**Admin**
- **Django Admin NÃO é tenant-scoped:** qualquer staff/superuser vê linhas de todos os tenants (isolamento fino é a Parte 32). Admin é view-only para canais/eventos/mensagens e mascara telefone/segredos (Parte 27).

**Infra de documentação e segurança**
- **CSP estrita** (`django-csp`): `default-src 'none'`, `script-src`/`style-src` = `'self' 'unsafe-inline'`, `img-src 'self' data:`. **Não afrouxar para CDNs.**
- **Swagger UI** serve assets **localmente via `drf-spectacular-sidecar`** (não CDN), e `/static/` é servido sob ASGI em `DEBUG` via `staticfiles_urlpatterns()` nas urls. Isso mantém a CSP intacta.

---

## 3. Roadmap — estado por parte

**Concluídas e validadas no código (master):**

- **Partes 17–26:** canais, migração legada, client Evolution, provisionamento self-service, webhook seguro por canal, processamento de eventos, QR/status API, roteamento inbound/outbound.
- **Parte 27 — Django Admin (view-only, mascarado).** `WhatsAppChannel`/`EvolutionWebhookEvent` view-only; telefone mascarado reutilizando `mask_whatsapp_phone_number`; nenhum segredo/QR/payload exposto; `Conversation` mostra canal (legado → "Sem canal (legado)"); envio manual só por `/reply/`.
- **Parte 28 — Cadastro self-service.** `POST /api/auth/register/` cria **User + Workspace + Member(OWNER)** num `transaction.atomic` (savepoints para e-mail duplicado → 400; retry de slug à prova de corrida). Emite JWT na resposta 201. Micro-fix de e-mail: grava caixa baixa canônica (`3a9991f`).
- **Parte 29 — RBAC + superfície de gestão dos canais.** Commit `2556e35` + micro-fix `a044ac2`. Detalhes em §4.

**Micro-fixes de infra pós-Parte 29:**
- **Swagger UI local + CSP preservada** (`a11e8c2`): sidecar + serving de estáticos sob ASGI. Ver §4.
- **Correção de contrato da Evolution — inbound `@lid` + status `keyId`** (`d1f92eb`, validado, na master). Descoberto em smoke real. Dois bugs 🔴 que descartavam todo inbound e todo status: (1) `messages.upsert` com `remoteJid @lid` sem `remoteJidAlt` → agora usa `payload.sender` como fallback (contato nasce com o número real, nunca com o `@lid`); (2) `messages.update` com id em `data.keyId`/`messageId` → paths adicionados a `_extract_external_id`. Compat retroativa preservada (`@s.whatsapp.net`, `remoteJidAlt`, `key.id`). +13 testes com os payloads reais como fixtures; suíte 1516→1529. **Validação do arquiteto executada:** check limpo, sem migration, omnichannel 1149 passed, sem regressão. **Descoberta de escopo (ver §8):** o Fix 2 resolve o rastreio de status das mensagens **outbound** (o caso de produto principal); marcar *leitura de mensagens inbound* ficou deliberadamente fora (o `_update_outbound_message` filtra `direction=OUTBOUND`, blindado por `test_inbound_message_is_never_updated`) — é decisão de produto, não bug.

**Próxima parte planejada: ainda a decidir** entre as candidatas de §5 (recomendação de ordem lá).

**Baseline de testes atual:** suíte completa **1516 passed** (após o micro-fix do Swagger; 85 arquivos de teste). Nas partes anteriores: 1512 (Parte 29) → 1516 (Swagger, +4).

---

## 4. Detalhe das entregas recentes (para validação/continuidade)

### Parte 29 — RBAC e gestão dos canais (`2556e35`, micro-fix `a044ac2`)

**Contexto:** a RBAC dos endpoints de canal **existentes** (list/create/detail/status/qr) já estava implementada e testada (OWNER/ADMIN→200, AGENT→403, não-membro→403, superuser→200, cross-tenant→404). O gap real eram as **ações de gestão sem endpoint** e a centralização da política.

**Fonte única de autorização:** `omnichannel/channel_authorization.py` com `CHANNEL_CAPABILITY_ROLES` (matriz capability→roles), `roles_for_capability`, `user_has_channel_capability`, `resolve_workspace_for_capability` (retorna 404 sem vazar objeto de outro tenant), e a permission parametrizável `HasChannelCapability` (a view declara `required_channel_capability`).

**Matriz efetiva:**

| Capability | Roles | Endpoint |
|---|---|---|
| VIEW | OWNER, ADMIN | list / detail(GET) / status / qr |
| CONNECT | OWNER, ADMIN | POST (provisionar) |
| RESTART | OWNER, ADMIN | `POST …/{id}/restart/` |
| DISCONNECT | OWNER, ADMIN | `POST …/{id}/disconnect/` |
| REMOVE | **OWNER** | `DELETE …/{id}/` |
| superuser | bypass de todas | — |

REMOVE é **OWNER-only** por ser destrutiva/irreversível (default seguro; ajustável num único ponto). Rotas em `workspaces/urls.py`.

**Serviços** (`omnichannel/whatsapp_channel_management.py`, síncronos, `client=None`):
- `restart`: guarda de estado (409 em `PROVISIONING`/`DELETING`); chama `restart_instance`; status transitório; 200 com `WhatsAppChannelStatusSerializer`.
- `disconnect`: **idempotente** (já `DISCONNECTED` → 200 no-op sem tocar Evolution); senão `logout_instance` + limpa `phone_number`/`connected_at`; 409 no ciclo de vida; 200.
- `remove`: **best-effort** — falha remota é logada e a remoção local prossegue (nunca prende o canal em `DELETING`); conversa vira legado (SET_NULL), webhook events caem (CASCADE); 204. Repetir/inexistente → 404.
- Erros da Evolution em restart/disconnect → **502 seguro** (`error_code` sanitizado).

**Throttle:** escopo `whatsapp_channel_management = 6/minute` (DELETE usa esse, não o read).

**Micro-fix `a044ac2`:** moveu `user_has_workspace_role` para `workspaces/authorization.py` (eliminou import local adiado que contornava ciclo; direção omnichannel→workspaces); removeu o `try/except` inalcançável e o `502` do `@extend_schema` **do DELETE** (remove é best-effort; restart/disconnect mantêm o 502 legítimo).

**Validação do arquiteto (executada):** `manage.py check` limpo, `No changes detected`, 1512 passed (omnichannel+workspaces 1400), cross-tenant/no-leak/idempotência conferidos nos testes reais.

### Micro-fix Swagger UI (`a11e8c2`)

Assets do Swagger passaram a ser servidos **localmente** via `drf-spectacular-sidecar==2026.7.1` (`SWAGGER_UI_DIST: 'SIDECAR'`, `SWAGGER_UI_FAVICON_HREF: 'SIDECAR'`), e `staticfiles_urlpatterns()` foi adicionado sob `if settings.DEBUG:` para servir `/static/` em ASGI. Motivo: a CSP estrita bloqueava o CDN (`cdn.jsdelivr.net`) e a página abria em branco. **CSP não foi afrouxada.** 4 testes novos (sem CDN externo, aponta para `/static/`, CSP segue estrita, assets resolvem pelo finder). Confirmado funcionando no navegador pelo usuário. Efeito colateral positivo: o Django Debug Toolbar voltou a ter estilo.

> ⚠️ **Pendência ligada a este commit:** o `requirements.txt` está em **UTF-16 com BOM duplicado** e **quebrou o CI** (`Invalid requirement: '\ufeffasgiref==3.11.1'`). Ver §8. O usuário removeu o BOM **localmente**, mas na master `a11e8c2` os dois `\ufeff` ainda estão presentes; a conversão definitiva para UTF-8 foi adiada. **Enquanto não subir a correção, o CI da master pode estar vermelho.**

---

## 5. Recomendações arquiteturais de médio prazo (registradas)

- **Evolution fake / testes de integração determinísticos (candidata a Parte 33):** um dublê com estado que implementa `BaseEvolutionClient` e dispara webhooks de volta, em dois níveis: (a) in-process para pytest; (b) servidor HTTP fake local para rodar a stack inteira sem celular. Serve para exercitar `provisioning→waiting_qr→connecting→connected`, caminhos de erro (timeout, 502, payload malformado, **webhook perdido**) e inbound/outbound. **Só é confiável se calibrado com payloads reais capturados no smoke** (senão espelha suposições). A DI via `client=None` já deixa isso barato. **Prioridade elevada:** o smoke real provou 2 bugs 🔴 de contrato (`@lid` inbound e `keyId` no update — ver §8) que os mocks atuais escondem; o fake **deve** reproduzir esses formatos reais (`@lid` sem `remoteJidAlt`, `update` com `keyId`, número em `sender`) senão os fixes regridem silenciosamente. Payloads reais já capturados no smoke de 26/07 (upsert `@lid` + update `keyId`).
- **Provisionamento assíncrono (Parte 35):** mover criação de instância/webhook (e as ações restart/disconnect/remove) para task Celery com o frontend fazendo polling de `/status/`. Hoje é síncrono no request (risco de timeout). A máquina de estados (`DELETING`/`RECONNECTING`) já foi desenhada para isso.
- **Reconciliação periódica de estado (Parte 35):** status vem de webhook; um webhook perdido causa divergência silenciosa. Task de conciliação.
- **Isolamento multi-tenant do Django Admin (Parte 32):** é a única lacuna real de isolamento que resta; revisitar `contact__phone` em `ConversationAdmin.search_fields` e `has_delete_permission` de `Conversation`.
- **Remoção do fluxo legado (`?workspace=UUID`, instância global) — Parte 36:** manter fallback + métrica até nenhum tenant usar mais.
- **Cliente TS gerado do OpenAPI** (openapi-typescript/orval) para o frontend — mata o drift front↔back na raiz.

---

## 6. Fluxo de smoke test manual (validação real end-to-end)

Objetivo: confrontar as premissas do código com a Evolution **real** (primeira vez) e **capturar payloads reais** para calibrar o fake (Parte 33).

**Pré-requisitos:** túnel público (ngrok) apontado em `EVOLUTION_WEBHOOK_PUBLIC_BASE_URL`; **domínio do túnel no `ALLOWED_HOSTS`** (enforçado mesmo com `DEBUG=True` → senão webhook vira 400 DisallowedHost); uvicorn no ar; **worker Celery no ar** (senão outbound trava em `PENDING`). `EVOLUTION_API_KEY` do Django deve ser idêntica à `EVOLUTION_AUTHENTICATION_API_KEY` do container.

**Sequência:** register → descobrir workspace → provisionar canal (só `{name}`) → `GET /qr/` (renderizável como `data:image/...;base64,<qr_code>` no navegador, dispensa frontend) → escanear → `GET /status/` até `connected` → inbound (mensagem de outro número) → `POST /reply/` outbound (`PENDING`→`SENT`→`DELIVERED`) → ações de gestão (restart/disconnect/idempotência/delete) por último.

**Captura de payloads (o entregável mais valioso):** aba `http://127.0.0.1:4040` do ngrok (corpo completo de cada webhook) + `EvolutionWebhookEvent` no banco (metadados; anotar `IGNORED`/`FAILED` e os `event_type` observados).

**Diagnóstico "travou em waiting_qr":** ver se o webhook chegou (4040); `404`=segredo inválido; `400`=divergência de contrato (salvar payload); `200`=problema no processamento (checar `EvolutionWebhookEvent`).

> Config Docker relevante (`docker-compose.yml`): `CONFIG_SESSION_PHONE_VERSION` **expira 17/08/2026** — se a conexão falhar de forma estranha no QR, é suspeita legítima (não é bug do código). Redis dbs separados: **db 0** Celery/Channels, **db 1** Evolution, **db 2** cache do Django (não apontar cache para db 0, senão `cache.clear()` apaga a fila do Celery).

---

## 7. Estado do frontend (React/Vite) — importante

**Ilhas prontas (código de produção, com testes):** `lib/` (JWT, erros, clients tipados, `qrImage`), hooks com polling adaptativo (lista 5s, status 3s, QR 10s), 13 componentes de `ai/` (providers + observabilidade) e 6 de `whatsapp/` (settings page, form de criação, card, `WhatsAppConnectionDialog`, `WhatsAppQRCode`).

**Andaime / não-produto:** Dashboard é uma tabela "mapa de rotas front→back" (documentação virada UI); botões sem `onClick`; `ResourcePage` é tabela **somente-leitura** genérica para contacts/leads/orgs/members/invites.

**Lacunas reais:**
- 🔴 **Conflito de rota `/conversations`:** `main.tsx` faz `window.location.pathname === "/conversations" ? <ConversationsRoute/> : <App/>`, criando **duas árvores React** (dois `QueryClient`, dois `BrowserRouter`) e definindo a mesma rota com telas diferentes — tabela via navegação SPA, chat via URL direta. Precisa unificar.
- **Chat não funcional:** `ChatPage` tem `<input>` sem handler; **sem mutation `/reply/`**; **sem consumo de SSE** (backend emite, front não abre `EventSource`).
- **Sem UI para ações da Parte 29** (restart/disconnect/remove) nem gating visual por role (lembrar: esconder botão é conveniência; backend já barra).
- **Sem tela de cadastro** (endpoint existe; a promessa self-service quebra na porta de entrada), sem guarda de auth nas rotas, sem seletor/contexto de workspace.

**Decisão registrada:** o frontend pode ser adiado (coerente com API First), preferencialmente construído **depois** de a API estabilizar (pós Partes 35/36) e com **cliente TS gerado do OpenAPI**. Mas "depois" deve ter fronteira definida (ex.: pós-36), pois o self-service é uma promessa de UX. O conflito de `/conversations` é barato de resolver e piora quanto mais tela encostar nele.

---

## 8. Backlog aberto (vive aqui — não está no código)

**🔴 / prioritário**
- **[DESCOBERTO no smoke 27/07 — GRAVE, corrige premissa do fix `@lid`] `sender` é a própria linha, não o remetente.** O fix `d1f92eb` assumiu que, para `remoteJid @lid`, o número real do contato vinha em `payload.sender`. **ERRADO.** O `sender` é o número da **instância conectada** (o dono da linha), não quem enviou a mensagem — confirmado porque TODOS os inbounds (marlucia, Ramilla, Arthur) trazem o mesmo `sender: 556183788392` (o número do próprio usuário do teste). Efeito: **todo contato inbound `@lid` é criado com o número da própria linha**; `outbound_routing` usa `recipient = contact.phone` (linha 125), então responder envia a mensagem **de volta para a própria linha** e vários contatos colapsam no mesmo telefone. Reproduzido: resposta ao "Arthur Ximenes" chegou no próprio número do testador. O número real do remetente está ofuscado no `@lid` e **não aparece em campo utilizável** nos payloads capturados. **Correção não é óbvia — precisa investigação:** (a) a Evolution tem endpoint para resolver `@lid`→número? (b) algum cenário traz `remoteJidAlt`/participante com número real? (c) **mais promissor:** persistir o `@lid`/`remoteJid` original e usá-lo como destinatário do outbound (responder pelo mesmo identificador que recebeu, sem tentar extrair telefone que o WhatsApp esconde). Requer prompt de correção dedicado + teste contra Evolution real. **NOTA:** isto rebaixa a validação anterior do `@lid` — inbound cria conversa/mensagem, mas com identidade de contato incorreta; o fix `d1f92eb` resolveu o `INVALID_REMOTE_JID` mas introduziu identidade errada. A lógica de `@s.whatsapp.net` normal (número no próprio `remoteJid`) permanece correta.
- **[CORRIGIDO em `d1f92eb`] Status por `keyId` (`INVALID_EXTERNAL_ID`).** `_extract_external_id` ganhou os paths `data.keyId`/`data.messageId`; validado no smoke (o `messages.update` real com `keyId` deixou de dar `INVALID_EXTERNAL_ID`). Nota de escopo: status de leitura só se aplica a mensagens OUTBOUND — ver decisão em aberto abaixo.
- **[RESOLVIDO em `66de7d2`, confirmar CI verde] `requirements.txt` → UTF-8.** Era UTF-16 com BOM e quebrava o CI. `66de7d2` converteu para UTF-8 sem BOM (lista byte-idêntica) e removeu o passo `Normalize requirements encoding` do `ci.yml`. Validado no código pelo arquiteto. **Pendente:** confirmar visualmente o run verde na aba Actions de `66de7d2`.
- **[DECISÃO EM ABERTO] Status de leitura em mensagens inbound.** O Fix 2 corrigiu a extração do `keyId`, mas `_update_outbound_message` filtra `direction=OUTBOUND` (com teste-guarda `test_inbound_message_is_never_updated`). Logo, o `messages.update` de uma mensagem que o cliente enviou resulta em `OUTBOUND_MESSAGE_NOT_FOUND` — por design. O caso de produto que importa (status/tique-azul das mensagens que o agente envia) funciona. Marcar leitura de mensagens inbound é decisão de produto separada (mudar filtro de direção + o teste-guarda). Registrado, aguardando decisão.

**🟡 dívida**
- **[DESCOBERTO no smoke 27/07] Dessincronização SilverTech ↔ Evolution: instância fantasma.** Após recriar o container da Evolution (troca de `CONFIG_SESSION_PHONE_VERSION`) e/ou `disconnect`/`logout`, a instância deixou de existir na Evolution, mas o `WhatsAppChannel` continua no banco do SilverTech apontando para ela. Sintoma: `POST /restart/` → `502 EVOLUTION_NOT_FOUND` (a Evolution responde 404 = instância inexistente). Nenhuma ação do usuário (restart/qr) se recupera, porque todas dependem de uma instância que evaporou; o canal fica preso em `disconnected` apontando para o nada. O código lida com o erro de forma segura (502 sanitizado, sem corromper estado), mas **falta um caminho de recuperação** (re-provisionar/recriar instância). Evidência real e concreta de que a **reconciliação periódica da Parte 35** é necessária, não teórica. Relaciona-se com a lacuna de reconexão abaixo — ambas apontam para "o canal precisa de uma ação que o traga de volta a um estado conectável a partir de `disconnected`/instância-ausente". Workaround no smoke: re-provisionar (criar canal novo). **A validar/decidir junto com a Parte 35.**
- **[A VALIDAR] Lacuna de reconexão: canal `DISCONNECTED` não volta a `WAITING_QR` pelo SilverTech.** Sintoma observado no smoke: após `disconnect` (que deixa o canal `DISCONNECTED`), chamar `GET /qr/` retorna vazio e o QR não pareia — porque `get_whatsapp_channel_qr_code` só busca/retorna QR quando `channel.status == WAITING_QR` (guarda na entrada do serviço) e **nada** transiciona `DISCONNECTED → WAITING_QR`. Hoje só funciona clicando "gerar QR" no painel da Evolution (que reabre a sessão e emite o webhook que põe o canal em `WAITING_QR`). Falta uma ação de **reconectar** no SilverTech. Hipótese a testar: sequência `disconnect → restart → qr` (o `restart_instance` reabriria a sessão). Decisão de design pendente: (a) `/qr/` disparar reconnect/restart quando `DISCONNECTED` em vez de retornar vazio, ou (b) endpoint explícito de "reconnect", ou (c) o frontend orquestrar `restart` antes do `qr`. Impacto direto no frontend: o botão "Conectar WhatsApp" precisa funcionar a partir de qualquer estado, não só do primeiro provisionamento. Conecta com a máquina de estados do canal e com a Parte 35 (async). **Ainda não corrigido — registrado durante o smoke, a validar.**
- **Saneamento do schema OpenAPI (candidata a parte própria, antes do cliente TS).** Ao abrir o Swagger, o `drf-spectacular` emite avisos que indicam schema incorreto — o que contaminaria o cliente TS gerado. Não são erros de runtime (a API responde; `/api/schema/` = 200). Agrupar num único trabalho: (a) **serializers aninhados duplicados com nomes colididos** — `_WorkspaceNestedSerializer` existe em `crm`/`workspaces`/`tickets`/`automations` e `_AssignedToNestedSerializer` em `crm`/`tickets`; nomes iguais + shapes diferentes fazem o OpenAPI fundir/sobrescrever componentes → unificar num componente compartilhado (provável `core`/`workspaces`), o que também mata duplicação de código; (b) `@extend_schema`/`serializer_class` nas `APIView` puras hoje ignoradas (`unable to guess serializer`): `DashboardAnalyticsView`, `WebhookAPIView`, `EvolutionChannelWebhookView`, `AIObservability{Events,Summary,Timeseries}View`, e as views de canal antigas `WorkspaceWhatsAppChannel{Collection,Detail,QRCode,Status}View` (as ações novas da P29 já têm `@extend_schema`); (c) `ENUM_NAME_OVERRIDES` para os campos `status` colididos (`StatusC1cEnum`); (d) `operationId` únicos (colisão `workspaces_whatsapp_channels_retrieve` entre list e detail). Fazer picado, warning a warning, é o "quick fix" a evitar; é trabalho estrutural único. **Evidência adicional do smoke:** no Swagger, o `POST /conversations/{id}/reply/` exibe um "Example Value" **errado** (mostra `workspace`/`channel`/`status`/`is_human_handoff` — schema de outro serializer), quando o corpo real aceito é apenas `{"body": "..."}` (`MessageCreateSerializer`). O endpoint funciona; a doc engana. Incluir na correção do schema.
- **Isolamento multi-tenant do Django Admin** (Parte 32): admin não é tenant-scoped; `contact__phone` em `ConversationAdmin.search_fields` acha conversas de qualquer tenant; `ConversationAdmin` não sobrescreve `has_delete_permission` (superuser deleta Conversation).
- **`_sanitize_error_code` duplicado em 4 módulos** (`provisioning`, `qr_service`, `outbound_routing`, `evolution_event_processing`) + import cross-module do símbolo privado em `management`. Consolidar num helper público compartilhado (parte de limpeza própria).
- **Provisionamento/gestão síncronos no request** → assíncrono + reconciliação (Parte 35).
- **JWT com tempos cravados** em `settings.py`. Sugestão: parametrizar por env (`JWT_ACCESS_TOKEN_LIFETIME_MINUTES`, `JWT_REFRESH_TOKEN_LIFETIME_DAYS`) com defaults 60/7 e guarda em produção contra valores absurdos (mesmo padrão já usado no `CORS_ALLOW_ALL_ORIGINS`). Não subir o valor cravado (access longo é risco). Não bloqueia nada.

**🟢 opcional / documentação**
- **Status de leitura em mensagens inbound (decisão de produto, não bug).** Após o fix `d1f92eb`, o `messages.update` da Evolution atualiza corretamente o status das mensagens **outbound** (entrega/leitura das mensagens que o workspace envia — o caso principal). Marcar que o operador *leu* uma mensagem **inbound** do cliente ficou fora: `_update_outbound_message` filtra `direction=OUTBOUND` de propósito, blindado por `test_inbound_message_is_never_updated`. Se o produto quiser esse recurso, é escopo novo (mudar o filtro de direção + o teste-guarda) — alinhar antes de implementar. Baixa prioridade; a maioria dos CRMs não expõe isso.
- **Serving de `/static/` em produção:** hoje `staticfiles_urlpatterns()` é guardado por `DEBUG`; com `DEBUG=False` o Swagger UI ficaria sem assets. Precisa WhiteNoise (+`collectstatic`) ou nginx servindo `STATIC_ROOT`.
- **Login case-insensitive "de verdade" no `/token/`:** hoje o cadastro grava e-mail canônico minúsculo, então login com a forma canônica funciona. Aceitar qualquer caixa no input exige (a) baixar a caixa no **form de login do frontend** (mais barato) ou (b) lookup `email__iexact` no backend de auth. **Não** usar o meio-fix ingênuo de baixar só a caixa do input (quebra usuários criados via admin/factory com caixa mista).
- **`ALLOWED_HOSTS` com entradas duplicadas** no `.env` local do usuário (inofensivo; limpar quando conveniente).
- **`.env.example`:** já corrigido (remoção de chave `EVOLUTION_WEBHOOK_PUBLIC_BASE_URL` duplicada e de domínio pessoal de ngrok que havia vazado). Garantir que `.env` está no `.gitignore` (contém `FIELD_ENCRYPTION_KEY`, que protege tokens/telefones criptografados).

---

## 9. Notas operacionais

- **Migrations:** só rodar `migrate` ao subir ambiente do zero ou quando uma parte **de fato** criar migration. Nas partes recentes, `makemigrations --check` = `No changes detected` → **não** rodar migrate.
- **Rollback/atomicidade e corrida** só se validam por **pytest**, não à mão pelo Swagger.
- **Throttles** relevantes: `auth`/`auth_register` = 5/min; `whatsapp_channel_provisioning` = 3/min; `whatsapp_channel_read` = 120/min; `whatsapp_channel_qr` = 10/min; `whatsapp_channel_management` = 6/min. `429` durante teste manual é esperado — esperar 1 min.
- **Testar cadastro/login/QR:** Swagger em `/api/schema/swagger-ui/` (agora funcional após o sidecar). Corpo do token: `{"email": ..., "password": ...}`. Se o access expirar no meio do smoke, use `/api/auth/token/refresh/` em vez de relogar (evita `429`).
- **Commit hashes de referência:** `074c212` P28 · `3a9991f` micro-fix e-mail · `2556e35` P29 · `a044ac2` micro-fix P29 · `0ad3ed5` `.env.example` · `a11e8c2` Swagger · `d1f92eb` fix Evolution `@lid`+`keyId` · `66de7d2` requirements UTF-8/CI.
