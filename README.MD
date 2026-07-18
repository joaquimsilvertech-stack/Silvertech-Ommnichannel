# SilverTech Omnichannel API

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg?logo=python)](https://www.python.org/downloads/)
[![Django](https://img.shields.io/badge/Django-5.0%2B-green.svg?logo=Django)](https://www.djangoproject.com/)
[![Redis](https://img.shields.io/badge/Redis-DC382D.svg?logo=redis&logoColor=white)](https://redis.io/)
[![Celery](https://img.shields.io/badge/Celery-37814A.svg?logo=celery&logoColor=white)](https://docs.celeryq.dev/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Sumário

- [Visão Geral](#visão-geral)
- [Problema que Resolve](#problema-que-resolve)
- [Objetivos Principais](#objetivos-principais)
- [Público-Alvo](#público-alvo)
- [Funcionalidades de Alto Nível](#funcionalidades-de-alto-nível)
- [Pacotes Utilizados](#pacotes-utilizados)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Diagrama de Banco de Dados](#diagrama-de-banco-de-dados)
- [Documentação da API](#documentação-da-api)
- [Configuração do Ambiente](#configuração-do-ambiente)


## Visão Geral
A **SilverTech Omnichannel API** é uma solução de backend robusta, assíncrona (ASGI) e multi-tenant (SaaS), projetada para centralizar a comunicação de empresas com seus clientes em múltiplos canais (como a API oficial do WhatsApp Business). O sistema integra um ecossistema completo de CRM à uma caixa de entrada unificada com atualização de dados em tempo real através de Server-Sent Events (SSE), garantindo alta performance na manipulação de grandes volumes de mensagens sem degradação do servidor.

## Problema que Resolve
Empresas sofrem com o atendimento descentralizado, onde múltiplos agentes utilizam diferentes contas ou dispositivos para interagir com clientes, gerando perda de histórico, falta de governança e dados isolados. Além disso, arquiteturas tradicionais enfrentam gargalos de concorrência e lentidão ao renderizar linhas do tempo de conversas extensas. A SilverTech API soluciona isso isolando dados de forma estrita por organização corporativa (Workspaces) e distribuindo atualizações de chat de maneira síncrona e fluida.

## Objetivos Principais

- **Isolamento Multi-Tenant Restrito:** Garantir segurança de dados absoluta através de queries escopadas por Workspace utilizando chaves UUID complexas.
- **Comunicação em Tempo Real Otimizada:** Fornecer atualizações instantâneas de eventos de mensagens para os atendentes através de streaming SSE baseado em camadas Redis Pub/Sub.
- **Alta Performance e Escalabilidade:** Mitigar problemas de consumo de recursos com paginação baseada em cursor (`CursorPagination`) para fluxos contínuos de mensagens e eliminação de gargalos N+1 via `select_related` e `prefetch_related`.
- **Autenticação Segura:** Proteção estrita de rotas operacionais via Tokens JWT de curta duração e controle de permissões baseado em atribuições de membros (`admin` e `agent`).

## Público-Alvo

- Empresas de médio e grande porte que buscam unificar canais de suporte e vendas, além de gestores de equipes de atendimento e desenvolvedores de interfaces front-end de chat.

## Funcionalidades de Alto Nível

- **Arquitetura Multi-Tenant & Convites:** Registro de workspaces corporativos isolados e sistema de convites para colaboradores com expiração automática de tokens (7 dias).
- **Core CRM B2B Avançado:** Cadastro de Contatos, Gerenciamento de Organizações e Funis de Leads com busca textual e filtros complexos de favoritos (`starred`).
- **Inbox Unificada (Omnichannel):** Endpoints otimizados para listagem de threads de conversas injetando metadados consolidados dos contatos (`_ContactInboxSerializer`).
- **Linha do Tempo em Tempo Real:** Canal contínuo de Server-Sent Events segmentado por empresa via `WorkspaceChannelManager`, impedindo interceptação de dados por agentes não autorizados.
- **Painel Administrativo customizado:** Painel administrativo estendido com inlines relacionais (`MessageInline`) para auditoria de fluxos de mensagens.

## Pacotes Utilizados

| Pacote                     | Versão       | Descrição                                                         |
|----------------------------|--------------|-------------------------------------------------------------------|
| django                     | >=5.0        | Framework web principal do ecossistema                            |
| djangorestframework        | latest       | Toolkit para construção das APIs RESTful                          |
| celery                     | >=5.5        | Motor de processamento de tarefas em background e filas           |
| django-channels            | 4.3.2        | Camada ASGI para suporte a protocolos assíncronos e tempo real    |
| django-eventstream         | 5.3.3        | Infraestrutura nativa para Server-Sent Events (SSE)               |
| channels-redis             | 4.3.0        | Driver de integração do Django Channels ao barramento Redis       |
| djangorestframework-jwt    | latest       | Autenticação robusta via JSON Web Tokens                          |
| uvicorn                    | latest       | Servidor de produção ASGI assíncrono ultrarrápido                 |

> **Nota:** Consulte o arquivo `requirements.txt` para conferir a árvore de dependências exata de desenvolvimento.

## Estrutura do Projeto

```text
projeto_api/
├── manage.py
├── requirements.txt
├── silvertech/
│   ├── celery.py          # Instância do motor de filas assíncronas
│   ├── settings.py
│   ├── asgi.py            # Roteamento ASGI HTTP e Tempo Real
│   └── wsgi.py
├── core/
│   └── models.py          # Implementação do BaseModel (UUID e Timestamps)
├── workspaces/
│   └── models.py          # Entidades Workspace e Member
├── crm/
│   ├── models.py          # Contact, Lead e Organization
│   ├── mixins.py          # Segurança Multi-tenant
│   └── pagination.py      # Rolagem infinita de alta performance
└── omnichannel/
    ├── models.py          # Conversation e Message
    ├── serializers.py     # Otimizações de payloads para a Inbox
    ├── signals.py         # Gatilho automático de SSE no banco
    ├── services.py        # Handlers de lógica de negócio e extração da Meta
    ├── tasks.py           # Tarefas do Celery para processamento de Webhooks
    ├── channelmanager.py  # Segurança de canais de tempo real
    └── views.py           # WebhookAPIView e ConversationViewSet

## Diagrama de Banco de Dados

![Diagrama de Banco de Dados](./docs/database_diagram.png)

> **Descrição:** Diagrama Entidade-Relacionamento (ER) ilustrando o isolamento multi-tenant a partir da entidade pai Workspace.

## Documentação da API

A documentação interativa e completa dos schemas pode ser consultada via Swagger UI localmente.

### Endpoints Principais

| Método | Endpoint                                    | Descrição                                         | Autenticação   |
|--------|---------------------------------------------|---------------------------------------------------|----------------|
| POST   | `/api/auth/token/`                          | Emissão de tokens de acesso JWT                   | Pública        |
| GET    | `/api/crm/contacts/`                        | Listagem paginada por cursor de contatos escopados| JWT Requerida  |
| GET    | `/api/crm/contacts/{id}/timeline/`         | Histórico estruturado de interações do contato    | JWT Requerida  |
| GET    | `/api/omnichannel/conversations/`           | Inbox unificada de conversas filtráveis           | JWT Requerida  |
| GET    | `/api/omnichannel/conversations/{id}/messages/` | Histórico paginado por cursor de mensagens da thread | JWT Requerida  |
| GET    | `/api/omnichannel/events/{workspace_id}/`   | Canal aberto de SSE para streaming em tempo real  | Sessão / Token |

## Configuração do Ambiente

Siga as etapas abaixo para configurar a arquitetura localmente.

1. **Clone o repositório:**
   
   git clone [https://github.com/SeuUsuario/SilverTech-Omnichannel.git](https://github.com/SeuUsuario/SilverTech-Omnichannel.git)
   cd SilverTech-Omnichannel

2. **Configure o ambiente virtual:**
  
        python -m venv venv
        source venv/bin/activate  # Linux/Mac
        venv\Scripts\activate     # Windows

3. **Instale as dependências necessárias:**
  
        pip install -r requirements.txt

4. **Inicialize o Servidor Redis (Obrigatório para o tempo real):**
  
        docker run -d -p 6379:6379 redis

5. **Execute as migrações estruturais do banco:**
    
        python manage.py migrate

6. **Inicie o servidor de desenvolvimento assíncrono (Uvicorn):**
   
        uvicorn silvertech.asgi:application --reload --host 0.0.0.0 --port 8000

  "Atenção: Como o projeto utiliza Django Channels e streaming ativo via protocolo ASGI, não utilize o comando python manage.py runserver, pois ele impossibilitará a execução do fluxo em tempo real (SSE)."

7. **Inicie o Background Worker do Celery (Terminal 2):**
   
    # Em sistemas Windows, utilize a flag -P solo:
        celery -A silvertech worker --loglevel=info --pool=solo

8. **Front-end React + Tailwind**
   
        cd frontend
        npm install
        npm run dev

    Rota do frontend
    http://127.0.0.1:5173

9. **Rotas do FrontEnd**

http://127.0.0.1:5173/
http://127.0.0.1:5173/contacts
http://127.0.0.1:5173/leads
http://127.0.0.1:5173/organizations
http://127.0.0.1:5173/conversations
http://127.0.0.1:5173/workspaces
http://127.0.0.1:5173/members
http://127.0.0.1:5173/invites

## Configuracao Segura de Secrets

Copie `.env.example` para `.env` apenas no ambiente local e preencha valores proprios. O arquivo `.env` nao deve ser versionado.

Variaveis obrigatorias para iniciar Django web, Celery worker e comandos administrativos:

- `SECRET_KEY`
- `FIELD_ENCRYPTION_KEY`
- `DJANGO_ENV`
- `DEBUG`
- `ALLOWED_HOSTS`
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` ou `DATABASE_URL`
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`, `REDIS_CACHE_URL`
- `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`
- `EVOLUTION_API_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCE_NAME`

Para gerar uma `SECRET_KEY` local segura:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Nunca troque `FIELD_ENCRYPTION_KEY` sem um plano de rotacao. Essa chave descriptografa campos sensiveis ja gravados no banco, incluindo `WorkspaceAIProviderConfig.api_key`; alterar o valor sem migracao controlada torna esses dados ilegíveis.

Em producao, forneca secrets por variaveis de ambiente do provedor, gerenciador de secrets ou mecanismo equivalente. Como evolucao recomendada, use AWS Secrets Manager ou Parameter Store para injetar `SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, credenciais PostgreSQL, Redis, Evolution API e Sentry sem gravar valores em arquivos versionados.

## System Prompt Source of Truth

`WorkspaceAIProviderConfig.system_prompt` é a fonte oficial do prompt de sistema usado pelo motor de IA.

`Workspace.ai_system_prompt` e `WorkspaceAIConfig` estão deprecated e permanecem apenas para compatibilidade historica, migrations e rollback. O fluxo funcional não usa esses campos antigos.

Prompts podem variar por provider, e a edição futura deve acontecer pela API self-service de configuração de provedores. O Django Admin continua apenas para observabilidade e não expõe nem edita credenciais ou prompts.

## Provider Adapters and Registry

`WorkspaceAIProviderConfig` define o provider ativo por workspace. A task de IA resolve esse provider pelo registry interno e chama o adapter correspondente, sem importar SDKs diretamente.

`build_conversation_context_for_ai` monta o contexto completo da conversa, incluindo a mensagem `system` com o prompt oficial. Os adapters recebem apenas `messages` normalizadas e prontas para o SDK do provider; eles nao conhecem `Workspace`, `WorkspaceAIProviderConfig` ou qualquer model de configuracao, e nao adicionam, removem ou deduplicam prompts.

Atualmente, somente `OpenAIAdapter` é funcional. `Anthropic` e `Google` permanecem apenas modelados e retornam provider não suportado até seus adapters serem implementados.

Para adicionar um novo provider, crie um adapter, registre no provider registry, adicione o SDK mínimo necessário e cubra o fluxo com testes unitários e de task. Não existe fallback automático entre providers, e cada adapter recebe exclusivamente a credencial criptografada do workspace da conversa.

No `OpenAIAdapter`, `max_tokens` e `max_completion_tokens` sao mutuamente exclusivos para evitar configuracoes ambiguas enviadas ao SDK.

## AI Provider Self-Service Serializer

`WorkspaceAIProviderConfigSerializer` prepara a futura API self-service de configuracao de provedores de IA sem expor credenciais. O campo `api_key` e aceito apenas como `write_only` em criacao e fluxos dedicados de credencial; respostas publicas usam somente `has_api_key` para indicar se existe credencial cadastrada.

O workspace da configuracao vem exclusivamente do contexto do serializer, nunca do payload enviado pelo cliente. Somente providers com adapter registrado no registry podem ser criados ou ativados pelo self-service. Neste momento, apenas OpenAI possui adapter funcional; Anthropic e Google continuam modelados, mas nao suportados no runtime.

As `settings` do provider sao validadas por allowlist e bloqueiam chaves sensiveis como credenciais, tokens, headers, proxies e parametros de cliente.

## AI Provider Self-Service API

Administradores do workspace podem gerenciar configuracoes de providers de IA pelos endpoints:

- `GET /api/workspaces/{workspace_id}/ai-providers/`
- `POST /api/workspaces/{workspace_id}/ai-providers/`
- `GET /api/workspaces/{workspace_id}/ai-providers/{id}/`
- `PUT /api/workspaces/{workspace_id}/ai-providers/{id}/`
- `PATCH /api/workspaces/{workspace_id}/ai-providers/{id}/`
- `POST /api/workspaces/{workspace_id}/ai-providers/{id}/test/`
- `POST /api/workspaces/{workspace_id}/ai-providers/{id}/activate/`
- `POST /api/workspaces/{workspace_id}/ai-providers/{id}/deactivate/`
- `POST /api/workspaces/{workspace_id}/ai-providers/{id}/credentials/replace/`
- `POST /api/workspaces/{workspace_id}/ai-providers/{id}/credentials/revoke/`

O `workspace_id` vem da URL e e repassado ao serializer pelo contexto; payloads com workspace sao rejeitados. `api_key` permanece apenas `write_only`, respostas usam `has_api_key` para indicar credencial cadastrada, e `PATCH`/`PUT` genericos rejeitam troca de chave. Apenas OpenAI esta funcional no runtime atual; Anthropic e Google continuam sem adapter e nao podem ser criados ou ativados pelo self-service.

O endpoint de teste de conexao tambem exige owner/admin do workspace. Ele pode usar a credencial salva ou uma `api_key` temporaria enviada no body; essa chave temporaria nao e salva, nao ativa automaticamente o provider e nunca aparece em resposta ou log. O teste faz uma chamada externa minima ao provider em runtime, com resposta sanitizada; os testes automatizados usam mocks.

### Gerenciamento de credenciais de IA

O endpoint `/credentials/replace/` recebe somente `api_key` write-only, valida o provider suportado e testa a nova chave com override temporario antes de salvar. Se o teste falhar, a credencial antiga permanece intacta e a resposta retorna apenas codigo e mensagem sanitizados. A substituicao nao altera `is_active`, `model_name`, `system_prompt` ou `settings`.

O endpoint `/credentials/revoke/` e idempotente, nao chama o provider externo e nao remove a configuracao. Ele apaga a credencial criptografada local (`api_key=""`) e desativa o provider (`is_active=false`), preservando provider, modelo, prompt e settings. Desativar pausa o uso do provider mantendo a chave; revogar remove a chave salva e tambem desativa o provider.

Ativacao e desativacao usam endpoints dedicados e tambem exigem owner/admin do workspace; agentes comuns nao podem executar essas acoes. O endpoint de ativacao valida a conexao usando somente a credencial salva antes de alterar o estado. Se o teste falhar, o provider permanece inativo e a resposta retorna apenas erro sanitizado, sem credenciais ou payload bruto do provider. Ao ativar um provider, os demais providers do mesmo workspace sao desativados atomicamente dentro de transacao PostgreSQL; providers de outros workspaces nao sao afetados.

O endpoint de desativacao nao chama provider externo, nao remove configuracao, nao apaga `api_key`, `settings`, `system_prompt` ou `model_name`. O campo `is_active` nao deve ser enviado em `POST`, `PUT` ou `PATCH` genericos; use exclusivamente `/activate/` e `/deactivate/` para mudar esse estado.

### Observabilidade e metricas por tenant

O backend registra eventos seguros de observabilidade por Workspace para acompanhar webhook -> IA -> delivery sem armazenar conteudo sensivel. Os eventos ficam em `AIObservabilityEvent` e carregam apenas metadados permitidos, como `source`, `action`, `message_type`, `direction`, `provider_supported`, `has_api_key`, `retry_countdown`, `is_retryable`, `http_status` e `delivery_status`.

Endpoints read-only para owner/admin:

- `GET /api/workspaces/{workspace_id}/ai-observability/summary/`
- `GET /api/workspaces/{workspace_id}/ai-observability/timeseries/`
- `GET /api/workspaces/{workspace_id}/ai-observability/events/`

Filtros aceitos: `period` (`24h`, `7d`, `30d`), `provider`, `event_type`, `status`, `error_code` e `limit` nos eventos recentes. O summary retorna totais de IA agendada, skips, tentativas, sucessos, falhas, retries, medias de latencia e erros agregados por provider/modelo. O timeseries retorna buckets simples por hora ou dia. O endpoint de events retorna eventos recentes ordenados por `created_at`.

A observabilidade nao armazena `api_key`, Authorization, headers, payload bruto, prompt, `message.body`, resposta da IA, telefone ou e-mail completo. Falhas ao registrar observabilidade usam helper safe, geram apenas log sanitizado e nao quebram webhook, task de IA, delivery ou operacoes administrativas de provider.

O frontend exibe a secao "Observabilidade da IA" na tela de configuracao de IA do workspace com filtro de periodo, cards de resumo, buckets recentes e tabela de eventos. Nao ha Prometheus, Grafana, dashboard avancado, exportacao CSV, alertas externos, billing, custo por token nem retry manual nesta parte.

### Testes de seguranca multi-tenant

A suite automatizada possui testes dedicados contra IDOR/BOLA e regressao de isolamento por Workspace. Os cenarios cobrem Workspaces, memberships, convites, CRM, Omnichannel, Tickets, Automations, AI providers, credenciais de IA, observabilidade e tasks Celery.

Os testes validam que owner/admin atuam apenas dentro dos proprios workspaces, agent e nao membro sao bloqueados em endpoints administrativos, IDs validos de outro tenant retornam 403/404, payloads com `workspace`, `workspace_id`, `contact_id`, `conversation_id` ou relacoes cruzadas nao criam vinculos entre tenants, e query params como `?workspace=<outro_workspace_id>` ou searches com dados de outro tenant nao vazam entidades.

Tambem ha cobertura para garantir que `api_key`, payload bruto, body de mensagem, prompt, resposta da IA, headers, telefone/e-mail de outro tenant e segredos fake `sk-...` nao aparecam em responses ou logs criticos. Chamadas reais para OpenAI/Evolution sao mockadas nos testes.

Comandos uteis:

```bash
python manage.py check
python manage.py makemigrations --check
pytest workspaces/tests/test_multi_tenant_security.py workspaces/tests/test_ai_provider_multi_tenant_security.py -q
pytest omnichannel/tests/test_multi_tenant_security.py omnichannel/tests/test_ai_observability_multi_tenant_security.py -q
pytest crm/tests/test_multi_tenant_security.py tickets/tests/test_multi_tenant_security.py automations/tests/test_multi_tenant_security.py core/tests/test_idor_security.py -q
pytest -q
```

### Canais WhatsApp por Workspace

`WhatsAppChannel` representa uma conexao WhatsApp isolada por Workspace. Um
Workspace pode possuir multiplos canais, cada um preparado para usar sua propria
instancia da Evolution API, e `Conversation` possui uma referencia opcional ao
canal que preserva a compatibilidade com conversas antigas.

Tokens da instancia, segredos do webhook e numeros de telefone sao armazenados
em campos criptografados. QR Code nao e persistido. O provisionamento de novos
canais e feito pelo endpoint administrativo descrito abaixo, enquanto o fluxo
legado da Evolution continua usando temporariamente a configuracao global
existente.

A migracao da instancia global para o modelo de canais e uma operacao explicita:
nao existe migration automatica nem tentativa de localizar um Workspace por nome.
O operador deve informar `--workspace-id`; `--instance-name` e opcional e, quando
omitido, utiliza `EVOLUTION_INSTANCE_NAME`.

```powershell
.\venv\Scripts\python.exe manage.py migrate_legacy_whatsapp_channel --workspace-id <UUID> --dry-run
.\venv\Scripts\python.exe manage.py migrate_legacy_whatsapp_channel --workspace-id <UUID>
.\venv\Scripts\python.exe manage.py migrate_legacy_whatsapp_channel --workspace-id <UUID> --rollback --dry-run
.\venv\Scripts\python.exe manage.py migrate_legacy_whatsapp_channel --workspace-id <UUID> --rollback
```

O canal e criado localmente como `DISCONNECTED`; o estado real sera sincronizado
em uma parte futura. A API key global nunca e copiada para o canal, e o comando
nao chama a Evolution, nao configura webhook e nao gera QR Code. Dry-run nao
persiste alteracoes. O rollback remove somente a associacao das conversas
WhatsApp com o canal, preservando canal, contatos, conversas e mensagens. O
webhook e o envio legados permanecem ativos durante esta transicao.

### Client central da Evolution API

Todas as chamadas HTTP para a Evolution passam pelo adapter em
`omnichannel/evolution`. URL base, header `apikey`, timeout, parsing das respostas
e exceptions proprias ficam centralizados. O client suporta criar instancia,
configurar webhook, obter QR Code, consultar conexao, enviar texto, reiniciar,
encerrar sessao e excluir instancia, mas nesta parte somente o envio de texto foi
ligado ao runtime existente.

O client faz exatamente uma tentativa por operacao e nao possui retry interno.
O retry do envio outbound continua sob controle da task Celery, com os mesmos
estados e backoff. `send_whatsapp_message` permanece como wrapper compativel e
continua escolhendo a instancia por `EVOLUTION_INSTANCE_NAME`; o roteamento por
`WhatsAppChannel` ainda nao foi ativado.

O adapter nao persiste QR Code ou qualquer resposta, nao provisiona instancias,
nao configura webhooks automaticamente e nao registra payloads, telefones,
mensagens, headers ou credenciais. O contrato de referencia e a Evolution API v2,
validado contra a imagem local v2.2.3 e a
[documentacao oficial](https://doc.evolution-api.com/v2/api-reference). Como o
`docker-compose.yml` ainda usa uma tag dinamica, a versao e o contrato devem ser
conferidos novamente antes de cada deploy.

### Provisionamento de canais WhatsApp

OWNERs e ADMINs do Workspace podem provisionar um canal por meio de
`POST /api/workspaces/{workspace_id}/whatsapp-channels/`, enviando somente:

```json
{
  "name": "WhatsApp principal"
}
```

O backend gera um `instance_name` tecnico, imprevisivel e sem dados pessoais,
reserva o canal como `PROVISIONING` e cria automaticamente a instancia na
Evolution. O provisionamento e sincrono nesta parte e o client realiza uma unica
tentativa. Em caso de sucesso, o canal passa para `WAITING_QR`; em caso de falha,
permanece registrado como `ERROR` com um codigo sanitizado.

As chamadas externas ocorrem fora das transacoes que bloqueiam Workspace ou
canal. A operacao e idempotente por Workspace e nome normalizado: repetir a mesma
solicitacao reutiliza o canal existente e nao cria uma segunda instancia. Se a
criacao remota tiver resultado ambiguo ou a finalizacao local falhar, o backend
tenta remover a instancia remota uma unica vez, sem apagar o canal local.

O endpoint nao retorna nem persiste QR Code. Para canais novos, o webhook seguro
por canal e configurado automaticamente depois da criacao da instancia; o canal
so chega a `WAITING_QR` quando as duas operacoes externas terminam. Inbound e
outbound continuam no roteamento legado, incluindo o uso temporario de
`EVOLUTION_INSTANCE_NAME`. A configuracao
`CONFIG_SESSION_PHONE_VERSION=2.3000.1041652166` permanece inalterada. Operacoes
reais, sobretudo as destrutivas, devem usar exclusivamente uma instancia de
teste da Evolution.

### Webhook seguro por canal

Cada canal novo recebe uma URL publica exclusiva:

```text
POST /api/omnichannel/webhooks/evolution/{webhook_public_id}/
```

O UUID publico identifica o canal, mas nao autentica a chamada. A Evolution envia
o segredo individual no header `X-SilverTech-Webhook-Secret`; o backend armazena
esse segredo criptografado e compara digests SHA-256 com `compare_digest`. Canal
inexistente, segredo ausente e segredo incorreto recebem a mesma resposta.

Durante o provisionamento, o backend registra os eventos `QRCODE_UPDATED`,
`CONNECTION_UPDATE`, `MESSAGES_UPSERT`, `MESSAGES_UPDATE` e `SEND_MESSAGE`. A URL
e criada somente a partir de `EVOLUTION_WEBHOOK_PUBLIC_BASE_URL`, nunca do Host
enviado por uma requisicao.

O endpoint aceita apenas objeto JSON, limita o corpo a 512 KiB por padrao e usa
throttle de 300 requisicoes por minuto, separado por canal e IP. Entregas iguais
sao deduplicadas por 24 horas com uma chave Redis composta somente pelo ID
tecnico do canal e pelo SHA-256 do JSON canonico. A task recebe `channel_id` e
payload; qualquer Workspace e derivado do `WhatsAppChannel`, nunca de query,
header ou campo recebido.

Depois da fila, a task processa os eventos de forma idempotente conforme descrito
na secao seguinte. O webhook legado em
`/api/omnichannel/webhooks/whatsapp/?workspace=<UUID>` permanece disponivel.

Exemplos de configuracao local:

```dotenv
# Django no host e Evolution no Docker
EVOLUTION_WEBHOOK_PUBLIC_BASE_URL=http://host.docker.internal:8000

# Django e Evolution no mesmo compose
EVOLUTION_WEBHOOK_PUBLIC_BASE_URL=http://backend:8000

# Evolution remota ou producao
EVOLUTION_WEBHOOK_PUBLIC_BASE_URL=https://api.seu-dominio.com

EVOLUTION_WEBHOOK_MAX_BODY_BYTES=524288
EVOLUTION_WEBHOOK_DEDUP_TTL_SECONDS=86400
EVOLUTION_QR_TTL_SECONDS=120
EVOLUTION_EVENT_PROCESSING_STALE_SECONDS=300
```

Em producao, a URL publica deve utilizar HTTPS. Nenhum segredo, token, QR ou
payload deve ser registrado na documentacao ou nos logs.

### Processamento de eventos da Evolution

A task segura recebe somente `channel_id` e payload. O Workspace e sempre
derivado do `WhatsAppChannel`; nenhum identificador de tenant recebido no JSON ou
na query controla o roteamento. Sao processados `QRCODE_UPDATED`,
`CONNECTION_UPDATE`, `MESSAGES_UPSERT`, `MESSAGES_UPDATE`, `SEND_MESSAGE` e,
defensivamente, `SEND_MESSAGE_UPDATE`. Este ultimo nao foi adicionado a lista de
eventos configurados remotamente porque o contrato usado no repositorio ainda
precisa de smoke test real para confirmar seu registro.

O QR validado fica exclusivamente no cache por `EVOLUTION_QR_TTL_SECONDS` (120
segundos por padrao), separado pelo ID tecnico do canal. Ele nunca e salvo no
banco, eventstream, logs ou observabilidade. Eventos de conexao atualizam os
estados `WAITING_QR`, `CONNECTING`, `CONNECTED`, `RECONNECTING`, `DISCONNECTED` e
`ERROR`; QR e connecting atrasados nao rebaixam um canal conectado.

Mensagens inbound textuais criam ou reutilizam `Contact` no Workspace do canal e
uma `Conversation` aberta vinculada ao proprio `WhatsAppChannel`. A `Message`
recebe `external_id` e uma `provider_message_key` SHA-256 composta pelo provider,
ID tecnico do canal e ID externo. O agendamento de IA continua ocorrendo apenas
em `transaction.on_commit`, preservando handoff e as regras atuais.

O Redis continua sendo a primeira deduplicacao da entrada. O PostgreSQL mantem
um `EvolutionWebhookEvent` por canal e chave hashada para idempotencia duravel,
retry de falhas e reclaim de processamento stale. O recibo nao armazena payload,
mensagem, QR, telefone, headers ou credenciais. Eventos desconhecidos terminam
como `IGNORED` sem efeitos de dominio.

Atualizacoes outbound sao localizadas somente dentro do Workspace e canal da
conversa. As transicoes sao monotonicas de `PENDING` para `SENT`, `DELIVERED` e
`READ`; falhas tardias nao rebaixam mensagens entregues ou lidas. O roteamento
outbound ainda usa `EVOLUTION_INSTANCE_NAME`. A Parte 23 exposera QR/status, a
Parte 25 concluira o hardening inbound e a Parte 26 migrara o outbound para a
instancia do canal.

## Blocos frontend de IA

O frontend Vite/React possui blocos reutilizaveis para gerenciar providers de IA por workspace na rota `/workspaces/:workspaceId/settings/ai`. A tela consome os endpoints `/api/workspaces/{workspace_id}/ai-providers/`, `/test/`, `/activate/`, `/deactivate/`, `/credentials/replace/` e `/credentials/revoke/`, sempre usando o backend como fonte de verdade para permissao, provider suportado, ativacao, credenciais e teste de conexao.

`api_key` e tratada como write-only: o formulario de criacao usa campo de senha, o teste de conexao aceita uma chave temporaria e a substituicao usa o endpoint dedicado `/credentials/replace/`. Campos de chave sao limpos em sucesso e erro. O frontend usa `has_api_key` apenas para indicar se ha chave cadastrada, nunca renderiza a chave real e nao salva credenciais em `localStorage` ou `sessionStorage`.

`is_active` nao e enviado em create/update/patch genericos. Ativacao e desativacao usam somente os endpoints dedicados; o teste de conexao nao ativa provider automaticamente. O frontend nao chama OpenAI, Evolution ou qualquer provider externo diretamente.

Os componentes de status outbound exibem `PENDING`, `SENT`, `FAILED`, `DELIVERED`, `READ` e informacoes de retry (`send_attempt_count`, `send_error_code`, `last_send_attempt_at`, `next_send_retry_at`) apenas para leitura. Retry manual, dashboard avancado, metricas e graficos ficam fora desta parte.

## Ligacao Automatica Webhook -> IA

Mensagens inbound validas recebidas pelo webhook da Evolution API podem agendar uma resposta automatica de IA. O agendamento acontece com `transaction.on_commit`, depois que a mensagem inbound foi persistida com sucesso; o webhook nao chama OpenAI, nao chama adapter de provider e nao envia resposta diretamente pela Evolution API.

A IA nao e agendada para mensagens `fromMe`, grupos nao suportados, mensagens vazias ou sem conteudo textual processavel, conversas em handoff humano ou workspaces sem provider ativo. Para disparar automaticamente, o workspace precisa ter um `WorkspaceAIProviderConfig` ativo, suportado no runtime e com `api_key` salva. Nenhuma credencial e incluida em resposta ou log.

### Idempotencia por mensagem

Cada mensagem inbound processada automaticamente com `source_message_id` pode ter no maximo um `AIProcessingRun`. A relacao unica com `source_message` impede duas respostas de IA para a mesma mensagem, inclusive em execucoes repetidas da task ou disputas concorrentes entre workers protegidas por `transaction.atomic`, `select_for_update` e constraint no banco.

Chamadas retrocompativeis com `source_message_id=None` continuam funcionando sem idempotencia persistente. `AIProcessingRun` nao armazena credenciais, payload bruto do webhook, corpo completo da mensagem nem resposta bruta do provider.

### Estados da mensagem outbound

Respostas geradas pela IA criam uma `Message` outbound inicialmente como `PENDING`. Quando a Evolution API confirma o envio, a mensagem passa para `SENT` e o `external_id` e salvo quando o provider retorna um identificador. Se o envio falhar, a mesma mensagem passa para `FAILED` com `send_error_code` sanitizado.

`AIProcessingRun.SUCCEEDED` indica que a IA gerou uma resposta e que uma `output_message` foi persistida. Erros de envio pelo WhatsApp pertencem a `Message`, nao ao `AIProcessingRun`, preservando a idempotencia por `source_message` e evitando uma segunda resposta automatica. Nenhuma credencial, payload bruto da Evolution ou resposta bruta do provider e armazenada no run.

### Retry, backoff e tratamento de falhas

Falhas transitorias do provider de IA (`rate limit`, timeout e indisponibilidade) sao retryadas com backoff deterministico antes de criar `output_message`. Enquanto aguarda nova tentativa, o `AIProcessingRun` fica como `RETRYING`, com `last_error_code`, `last_attempt_at` e `next_retry_at` preenchidos de forma sanitizada. Falhas permanentes do provider, como autenticacao, request invalido, provider sem suporte ou resposta invalida, marcam o `AIProcessingRun` como `FAILED` sem retry.

Depois que a `output_message` existe, falhas da Evolution retryam apenas o envio da mesma `Message` outbound. O reenvio nao regenera IA e nao cria uma nova mensagem; a `Message` permanece `PENDING` enquanto aguarda retry, com `send_attempt_count`, `send_error_code`, `last_send_attempt_at` e `next_send_retry_at` atualizados. Apos o limite de tentativas, a `Message` vira `FAILED` com `send_error_code` sanitizado, enquanto `AIProcessingRun.SUCCEEDED` continua indicando que a resposta da IA foi gerada e persistida.

Nenhuma credencial, payload bruto, header, resposta bruta da Evolution, prompt completo ou resposta completa da IA e armazenada ou logada nesse fluxo. Frontend, observabilidade avancada, retry manual e metricas de custo ficam para evolucoes futuras.

Antes de deploy:

```bash
python manage.py check
python manage.py check --deploy
pytest core/tests/ workspaces/tests/ omnichannel/tests/ -q
```
