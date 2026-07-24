# Handoff — SilverTech CRM Omnichannel



## 0. Como trabalhamos (papel e fluxo)

O assistente atua como **arquiteto técnico** do projeto. Fluxo por parte do roadmap:

1. O usuário descreve a próxima parte.
2. O assistente **clona o repo e valida as premissas no código real** antes de escrever qualquer prompt (nunca presume nomes de campo, arquivos de teste, etc.).
3. O assistente entrega um **prompt completo em `.md`** para o usuário colar no **Claude Code Desktop** (chat limpo por parte).
4. Claude Code implementa, roda a suíte e devolve um relatório **sem commit**.
5. O usuário cola o relatório aqui; o assistente **clona a master e valida no código** cada afirmação e monta um **checklist de follow-ups**.
6. Se não houver fix a fazer agora, o usuário commita/`push` e dá `/clear` no Claude Code.

Formato do checklist de follow-ups (por item): **Severidade** 🔴 bug/segurança (agora) · 🟡 dívida/inconsistência (depois) · 🟢 opcional/estético — **O quê** · **Onde** (arquivo/símbolo) · **Prompt sugerido** (texto escopado pronto para colar).

Preferências de prompt do usuário (padrão a manter): persona de engenheiro sênior; contexto de roadmap curto no topo (o chat do Claude Code é limzo e não vê os PDFs); PASSO 1 de inspeção obrigatória com verificações explícitas; guardrails de "não implemente parte futura"; `manage.py check` + `makemigrations --check` (esperado `No changes detected`); rodar suíte focada + completa; `git diff --check`; **não criar commit**; reportar tudo com saída real. Ambiente Windows/PowerShell: `.\venv\Scripts\python.exe`.

## 1. O que é o sistema

CRM Omnichannel SaaS **multi-tenant por Workspace**. Objetivo do trilho atual: transformar a integração com a **Evolution API v2 (WhatsApp)** num fluxo **self-service por Workspace** — o cliente conecta o próprio WhatsApp dentro do SilverTech (sem copiar UUID, criar instância manual ou configurar webhook no painel da Evolution).

**Stack:** Python 3.12 · Django 6 · DRF · PostgreSQL · Redis · Celery · Evolution API v2. Auth por **JWT (SimpleJWT)**. `drf-spectacular` (Swagger). Servir com **ASGI/uvicorn** (`silvertech.asgi:application`), não `runserver`.

**Repo:** https://github.com/joaquimsilvertech-stack/Silvertech-Ommnichannel (branch `master`).

## 2. Premissas de código já verificadas (não reinvestigar do zero)

- `AUTH_USER_MODEL = 'core.CustomUser'`: login por **e-mail** (`USERNAME_FIELD='email'`), PK UUID, herda `AbstractUser` (tem `first_name`/`last_name`; `username=None`). `CustomUserManager.create_user(email, password=None, **extra)`. Campo `role` de **plataforma** (`admin`/`agent`/`viewer`, default `VIEWER`) — **distinto** de `Member.Role`.
- `workspaces.Workspace`: `name` + `slug` (`SlugField(max_length=128, unique=True)`, obrigatório). M2M com users via `Member`.
- `workspaces.Member.Role`: `OWNER`/`ADMIN`/`AGENT` (default `AGENT`); constraint única `(workspace, user)`.
- `WorkspaceViewSet`: `ModelViewSet` com `WorkspaceScopedQuerysetMixin`; `create` **não** cria OWNER e exige `slug` no payload → não serve como cadastro (workspace ficaria órfão/invisível).
- Auth existente: `POST /api/auth/token/` e `/api/auth/token/refresh/` (throttle scope `auth = 5/minute`). **Login usa `ModelBackend` padrão → match exato de e-mail** (não há `AUTHENTICATION_BACKENDS` custom).
- Cadastro: `POST /api/auth/register/` (criado na Parte 28 — ver abaixo).
- Throttle: `DEFAULT_THROTTLE_CLASSES` inclui `ScopedRateThrottle` (por isso `throttle_scope` nas views funciona). Scopes: `auth`, `auth_register` (ambos `5/minute`).
- WhatsApp/omnichannel: `WhatsAppChannel` (canal por workspace, campos criptografados `instance_token`/`webhook_secret`/`phone_number`), `EvolutionWebhookEvent` (sem payload bruto). Helper **`mask_whatsapp_phone_number`** em `omnichannel/whatsapp_channel_read_service.py` (retorna `********`+4 dígitos, ou `None` para vazio/curto/formatado) — **é a fonte de verdade de mascaramento; reutilizar sempre**.
- Envio de mensagem é **durável/assíncrono**: `POST /api/omnichannel/conversations/{id}/reply/` cria `Message OUTBOUND/PENDING` → `transaction.on_commit` → task Celery `send_outbound_whatsapp_message` → Evolution. Criar `Message` na mão **não** dispara isso.
- **Django Admin não é tenant-scoped**: qualquer staff/superuser vê linhas de todos os tenants (isolamento fino é a Parte 29).
- Provisionamento de instância Evolution é **síncrono** dentro do request hoje (dívida de escalabilidade — ver §5).

## 3. Roadmap — onde paramos

Partes **17–26** concluídas (canais, migração legada, client Evolution, provisionamento self-service, webhook seguro por canal, processamento de eventos, QR/status API, roteamento inbound/outbound).

**Parte 27 — Django Admin (CONCLUÍDA e validada no código, na master).**
`WhatsAppChannel` e `EvolutionWebhookEvent` registrados **view-only**; telefone mascarado **reutilizando** `mask_whatsapp_phone_number`; nenhum segredo/QR/payload exposto em nenhuma opção do admin; `Conversation` mostra `whatsapp_channel` (legado → "Sem canal (legado)"); `Message`/`MessageInline` view-only; envio manual só por `/reply/`. `has_view_permission` delega ao padrão do Django. Suíte verde. Commit isolado.

**Parte 28 — Cadastro self-service (CONCLUÍDA e validada, incl. micro-fix, na master).**
`POST /api/auth/register/` público (`AllowAny`, `authentication_classes=[]` → sem CSRF), throttle `auth_register`. Cria **User + Workspace + Member(OWNER)** num único `transaction.atomic` (savepoints internos para e-mail duplicado → 400, e retry de slug à prova de corrida). Slug único gerado do nome da empresa (`workspaces/slug_service.py`), **não** enviado pelo cliente. Senha validada por `validate_password`, nunca exposta. Emite **JWT (access/refresh) na resposta 201** (decisão tomada: melhor UX self-service; emitido após o commit, fora do atomic). `CustomUser.role` permanece `VIEWER`. Admin manual do superuser preservado (invariante "workspace sempre com OWNER" é **transacional no cadastro**, não constraint global). Arquivos: `workspaces/slug_service.py`, `workspaces/registration_service.py`, `core/serializers.py`, `core/auth_views.py`, `silvertech/urls.py` (+rota), `silvertech/settings.py` (+throttle), testes. Suíte 1470 verde.

**Micro-fix do e-mail (CONCLUÍDO e validado, na master, commit `3a9991f`).**
`register_owner_account` e `RegistrationSerializer.validate_email` passaram a gravar o e-mail em **caixa baixa completa** (`normalize_email(...).lower()`), mantendo `email__iexact` na checagem de duplicidade. Resolve o cenário: cadastra `Joao@Empresa.com` → loga com `joao@empresa.com`. 3 testes novos; diff de 3 arquivos.

**Próxima parte: 29 — RBAC OWNER/ADMIN/AGENT dos canais** (ainda não iniciada).

## 4. Backlog aberto (vive só aqui — não está no código)

- **🟡 `contact__phone` no `ConversationAdmin.search_fields`** — como o admin não é tenant-scoped, buscar telefone completo localiza conversas de qualquer tenant. Decisão atual: manter (é dado de CRM do Contact, e a Parte 27 manda preservar o `ContactAdmin`). **Revisitar na Parte 32** (segurança multi-tenant dos canais).
- **🟢 Delete de `Conversation` no admin** — `ConversationAdmin` não sobrescreve `has_delete_permission`, então superuser ainda deleta Conversation. Não foi pedido bloquear; opcional. Fix trivial: `has_delete_permission = False`.
- **Decisão parkada — login case-insensitive de verdade no `/token/`** — hoje o cadastro grava e-mail canônico minúsculo, então login com a forma canônica funciona. Aceitar **qualquer caixa digitada** no login exige mexer no auth. **NÃO** usar o meio-fix ingênuo de baixar só a caixa do input (quebraria usuários criados via admin/factory com e-mail em caixa mista). Se for fechar: preferir (a) baixar a caixa no **formulário de login do frontend** (mais barato, zero risco), ou (b) lookup **`email__iexact`** no backend de auth. Não bloqueia a Parte 29 — encaixa quando chegar no frontend de login.

## 5. Recomendações arquiteturais de médio prazo (registradas, não urgentes)

- **Provisionamento assíncrono:** mover a criação de instância/webhook Evolution para task Celery com o frontend fazendo polling de `/status/` — hoje é síncrono no request (risco de timeout/escalabilidade). A máquina de estados do canal já foi desenhada para isso. (Alinhado à Parte 35.)
- **Reconciliação periódica de estado dos canais:** status vem de webhook; um webhook perdido causa divergência silenciosa. Task de conciliação simples. (Parte 35.)
- **Cliente TS gerado do OpenAPI** (openapi-typescript/orval) para o frontend — mata na raiz o drift frontend↔backend, em vez de corrigir tela por tela.
- **Evolution fake / testes de integração simulados (Parte 33) antes do smoke manual** — para exercitar QR/inbound/outbound de forma determinística, sem celular real.
- Remoção do fluxo legado (`?workspace=UUID`, instância global) é a **Parte 36** — manter fallback + métrica até nenhum tenant usar mais.

## 6. Documentação a corrigir

- Roteiro de smoke test no README: o passo de obter JWT **já foi corrigido** de `{"username": ...}` para `{"email": ...}` (a Parte 28 arrumou). Confirmado resolvido.

## 7. Notas operacionais

- Testar cadastro/login: Swagger em `/api/schema/swagger-ui/`; token com corpo `{"email": ..., "password": ...}` (campo é **email**). Ver efeito no Django admin (User/Workspace/Member OWNER). Throttle `auth_register`/`auth` = 5/min pode dar **429 esperado** durante testes manuais — esperar 1 min ou limpar cache.
- **Migrations:** só rodar `migrate` ao subir ambiente do zero ou quando uma parte **de fato** criar migration. Nas partes recentes, `makemigrations --check` = `No changes detected` → **não** rodar migrate. `makemigrations` (sem `--check`) não deve ser usado nas partes que não tocam models.
- Rollback/atomicidade e casos de corrida só se validam por **pytest**, não à mão pelo Swagger.
