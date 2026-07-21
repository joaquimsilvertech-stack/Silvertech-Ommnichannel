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
outbound moderno usa a instancia persistida no canal da conversa. A configuracao
global de instancia permanece somente para compatibilidade com fluxos legados
fora desse caminho.

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
estados e backoff. `send_whatsapp_message` recebe explicitamente o
`WhatsAppChannel` validado e envia por `channel.instance_name`; ele nao consulta
`EVOLUTION_INSTANCE_NAME`. A factory `get_evolution_client` continua usando URL,
API key e timeout globais, sem resolver instancia ou tenant.

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
so chega a `WAITING_QR` quando as duas operacoes externas terminam. O outbound
moderno resolve a instancia pelo canal persistido na `Conversation`, sem fallback
para `EVOLUTION_INSTANCE_NAME`. A configuracao
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

Mensagens inbound textuais derivam o Workspace exclusivamente do
`WhatsAppChannel` bloqueado. A identidade WhatsApp de `Contact` e
`workspace + channel_id`, e `channel_id` recebe o telefone normalizado. Uma
constraint condicional impede identidades nao vazias duplicadas no mesmo
Workspace; contatos legados livres podem ser reivindicados, e uma corrida e
recuperada pelo vencedor da constraint depois de `IntegrityError`. Nenhum
Contact e global entre Workspaces.

O mesmo Contact pode participar de varios canais do mesmo Workspace, mas cada
canal usa sua propria `Conversation` aberta com o `WhatsAppChannel` exato.
Conversas de outro canal, fechadas ou legadas com `whatsapp_channel=null` nao sao
reutilizadas. Campos `workspace_id` e `instance` do payload nao controlam o
roteamento. A `Message` recebe `external_id` e uma `provider_message_key` SHA-256
composta pelo provider, ID tecnico do canal e ID externo.

Inbound direta exige `fromMe` booleano igual a `false`. Grupos, broadcast,
newsletter e sufixos desconhecidos sao ignorados; JIDs `@lid` exigem
`remoteJidAlt` individual em `@s.whatsapp.net` ou `@c.us`. Nomes recebidos sao
validados e atualizam apenas placeholders, sem substituir nomes curados por um
operador. Logs usam somente IDs tecnicos e codigos seguros, sem telefone, JID,
nome, corpo ou payload. O agendamento de IA continua em `transaction.on_commit`,
preservando handoff e idempotencia. A task de delivery recebe apenas os IDs da
mensagem e do canal esperado; nenhum token ou nome de instancia entra na fila.

O Redis continua sendo a primeira deduplicacao da entrada. O PostgreSQL mantem
um `EvolutionWebhookEvent` por canal e chave hashada para idempotencia duravel,
retry de falhas e reclaim de processamento stale. O recibo nao armazena payload,
mensagem, QR, telefone, headers ou credenciais. Eventos desconhecidos terminam
como `IGNORED` sem efeitos de dominio.

Atualizacoes outbound sao localizadas somente dentro do Workspace e canal da
conversa. As transicoes sao monotonicas de `PENDING` para `SENT`, `DELIVERED` e
`READ`; falhas tardias nao rebaixam mensagens entregues ou lidas. O roteamento
outbound usa exclusivamente o `WhatsAppChannel` da conversa. A Parte 23 expoe
QR/status, a Parte 25 endurece o roteamento inbound e a Parte 26 fixa o outbound
na instancia do canal.

### API de canais, QR Code e conexao

Usuarios autenticados com papel `OWNER` ou `ADMIN` no Workspace, alem de
superusers, podem usar os endpoints administrativos abaixo. Membros `AGENT` nao
possuem acesso, e todas as consultas resolvem Workspace e canal em conjunto para
preservar o isolamento entre tenants.

```text
GET  /api/workspaces/{workspace_id}/whatsapp-channels/
POST /api/workspaces/{workspace_id}/whatsapp-channels/
GET  /api/workspaces/{workspace_id}/whatsapp-channels/{channel_id}/
GET  /api/workspaces/{workspace_id}/whatsapp-channels/{channel_id}/status/
GET  /api/workspaces/{workspace_id}/whatsapp-channels/{channel_id}/qr/
```

Listagem e detalhe retornam somente ID, nome, provider, estado, telefone
mascarado, disponibilidade de QR e timestamps publicos. O status retorna apenas
o estado local, telefone mascarado, disponibilidade de QR e timestamps. O
telefone usa mascara fixa e revela somente os quatro ultimos digitos; nomes de
instancia, IDs externos, tokens, segredos e codigos internos nunca sao expostos.

O endpoint de status usa o banco e o cache locais. `CONNECTION_UPDATE` recebido
pelo webhook e a fonte do estado, portanto o polling nao chama a Evolution. O QR
so pode ser exibido enquanto o canal estiver em `WAITING_QR`: a leitura consulta
primeiro o cache isolado por canal e, em caso de cache miss, faz uma unica chamada
controlada a `get_qr_code`. O estado e revalidado antes e depois da gravacao no
cache para impedir a entrega de QR antigo depois da conexao.

O QR permanece no cache por `EVOLUTION_QR_TTL_SECONDS` (120 segundos por padrao),
nunca no banco, e todas as respostas administrativas usam `no-store`. O frontend
nao deve salvar o QR em `localStorage`, session storage ou qualquer persistencia;
deve descarta-lo assim que o status deixar `WAITING_QR`. A Parte 24 implementara
a interface. O webhook legado permanece disponivel; o outbound moderno nao usa a
instancia global.

### Roteamento outbound por canal

Toda `Message` outbound entregue pela task segue a relacao persistida
`Message -> Conversation -> WhatsAppChannel`. O ID de canal recebido pela task e
apenas uma expectativa de integridade: ele precisa coincidir exatamente com
`conversation.whatsapp_channel_id` e nunca e usado para buscar ou redirecionar o
envio. Chamadas legadas contendo apenas `message_id` continuam aceitas, mas derivam
o canal da conversa e carregam esse mesmo ID nos retries seguintes.

Somente canais `CONNECTED`, do provider Evolution e do mesmo Workspace da
conversa podem chamar `send_text`. `PROVISIONING`, `WAITING_QR`, `CONNECTING` e
`RECONNECTING` mantem a mesma `Message` como `PENDING` e usam o backoff da task.
`DISCONNECTED`, `ERROR`, `DELETING`, estados desconhecidos, divergencias de
Workspace, Contact ou canal falham fechados sem chamada externa. Nao existe
fallback para `EVOLUTION_INSTANCE_NAME` nem selecao do primeiro canal do tenant.

O destinatario vem exclusivamente do `Contact` da conversa e a instancia vem de
`WhatsAppChannel.instance_name`. `instance_token` nao e descriptografado para o
envio, nao entra nos argumentos Celery e nao e registrado. Em sucesso, a mesma
mensagem recebe `external_id` quando disponivel e passa para `SENT`; `DELIVERED` e
`READ` continuam sendo aplicados somente pelos webhooks escopados ao mesmo canal.
Um retry nunca regenera IA, cria outra mensagem ou troca silenciosamente de
canal. Logs registram apenas IDs tecnicos, tentativas, status, codigos seguros e
latencia, sem telefone, corpo, instancia ou credenciais. O smoke test real da
Evolution sera executado posteriormente em ambiente controlado.

### Concorrencia e pipeline outbound

Cada entrega adquire um advisory lock PostgreSQL de sessao derivado somente do
UUID da `Message`. O lock permanece ativo durante a chamada HTTP e a persistencia
do resultado, e e liberado em `finally`. Assim, duas tasks concorrentes nao fazem
HTTP simultaneo para a mesma mensagem. Em contencao, a execucao perdedora
reagenda uma verificacao curta com os mesmos IDs, sem incrementar
`send_attempt_count` ou alterar o estado.

Depois do lock, a task rele a `Message`; um claim curto com `select_for_update`
incrementa a tentativa apenas se ela ainda estiver `PENDING`. Nenhuma transacao
fica aberta durante o HTTP. As atualizacoes finais sao monotonicas: `SENT`,
`DELIVERED` e `READ` nao sao rebaixados por falhas, retries ou conclusoes tardias.

Reply manual, IA e `FlowEngine` compartilham a mesma pipeline: persistem uma
unica `Message OUTBOUND PENDING` e, em `transaction.on_commit`, enfileiram somente
`message_id` e o ID tecnico do canal esperado. Apenas
`send_outbound_whatsapp_message` chama a Evolution. Body, telefone, nome de
instancia, tokens, chaves e segredos nao entram nos argumentos Celery nem nos
logs; tambem nao existe fallback para uma instancia global.

O advisory lock impede envios HTTP concorrentes, mas nao oferece exactly-once
absoluto: se a Evolution aceitar o envio e o worker morrer antes de persistir
`SENT`, uma redelivery ainda pode repetir a tentativa porque o provider nao
fornece uma chave de idempotencia para esse fluxo. O smoke test real continua
reservado para uma etapa posterior em ambiente controlado.

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

### Cadastro self-service

`POST /api/auth/register/` e o unico endpoint publico de escrita alem do login.
Ele cria o **tenant minimo** de forma atomica: `User` + `Workspace` +
`Member` com papel `OWNER`.

Entrada:

| Campo | Regra |
| --- | --- |
| `full_name` | obrigatorio, nao vazio apos trim; dividido em `first_name`/`last_name` |
| `company_name` | obrigatorio, nao vazio apos trim; vira o `name` do Workspace |
| `email` | obrigatorio, normalizado; unicidade case-insensitive |
| `password` | obrigatorio, `write_only`, validado por `AUTH_PASSWORD_VALIDATORS` |

`slug` e `role` **nao** sao aceitos no payload. O slug e derivado do nome da
empresa por `slugify`; nome sem caracteres slugificaveis cai no fallback
`workspace`, e colisao recebe um sufixo hexadecimal curto. O papel no tenant e
sempre `OWNER`, e o `role` de plataforma do `CustomUser` permanece no default —
o cadastro nao cria admin de plataforma.

Resposta `201 Created`:

```json
{
  "user": {"id": "<uuid>", "email": "<email>", "first_name": "...", "last_name": "...", "full_name": "..."},
  "workspace": {"id": "<uuid>", "name": "<empresa>", "slug": "<gerado>"},
  "membership": {"id": "<uuid>", "role": "owner"},
  "tokens": {"access": "<jwt>", "refresh": "<jwt>"}
}
```

Os tokens sao emitidos **apos o commit**, para logar o cliente imediatamente e
evitar um segundo round-trip de login. `password` nunca aparece na resposta nem
em log. E-mail duplicado retorna `400` com erro no campo `email`, nunca `500`.
O endpoint tem throttle dedicado no escopo `auth_register` (`5/minute`).

Qualquer falha em qualquer etapa desfaz **toda** a transacao: nao resta `User`,
`Workspace` nem `Member` parcial.

**Nenhuma instancia Evolution e provisionada no cadastro** e nenhum
`WhatsAppChannel` e criado. A conexao do WhatsApp continua sendo um passo
separado e explicito, via
`POST /api/workspaces/{workspace_id}/whatsapp-channels/`.

O superuser continua criando `Workspace` manualmente pelo Django Admin (com
`prepopulated_fields` de slug) e associando um `Member` OWNER para suporte. Essa
excecao e deliberada: a invariante "Workspace sempre com OWNER" e garantida no
fluxo de cadastro, nao por constraint global no model — o que preservaria o
caminho manual, as factories e os dados existentes. Um Workspace criado assim
tambem pode conectar canal depois pelo mesmo endpoint de provisionamento.

A tela de cadastro em React fica para uma parte futura; aqui o contrato e
validado por Swagger e testes.

### Django Admin e testes manuais do WhatsApp

O Django Admin e uma ferramenta de **inspecao operacional**, nunca de operacao.
Ele le apenas o PostgreSQL: nao chama a Evolution, nao consulta Redis, nao
enfileira Celery e nao consulta QR Code.

#### Onde encontrar cada modelo

Em `/admin/`, dentro da aplicacao **Omnichannel**:

| Modelo | Uso | Permissoes |
| --- | --- | --- |
| `canais WhatsApp` (`WhatsAppChannel`) | conferir a qual Workspace o canal pertence, provider, `instance_name` tecnico, status e timestamps de conexao | somente leitura |
| `eventos de webhook Evolution` (`EvolutionWebhookEvent`) | diagnosticar recebimento e processamento idempotente dos eventos | somente leitura |
| `conversas` (`Conversation`) | ver o `whatsapp_channel` associado e as mensagens da thread | tenant e canal somente leitura |
| `mensagens` (`Message`) | inspecionar direcao, status, tentativas de envio e `body` | somente leitura |
| `AIProcessingRun` / `AIObservabilityEvent` | diagnostico da IA | somente leitura |

#### Campos exibidos e campos deliberadamente ocultos

`WhatsAppChannel` exibe `name`, `workspace`, `provider`, `instance_name`,
`status`, telefone **mascarado**, `connected_at`, `last_connection_update_at`,
`last_error_code`, `webhook_public_id`, `created_at` e `updated_at`.

Nunca sao exibidos, nem mesmo como campos somente leitura: `instance_token`,
`webhook_secret`, `phone_number` completo, `instance_id`, `EVOLUTION_API_KEY`,
chave de criptografia, QR Code, payload bruto, headers e resposta bruta da
Evolution. Esses campos tambem estao fora de `list_display`, `list_filter`,
`search_fields`, `readonly_fields`, `fieldsets`, `autocomplete_fields` e
`raw_id_fields`, porque `EncryptedCharField` descriptografa o valor no momento
em que o model o acessa.

O telefone e renderizado pelo mesmo helper usado pelos serializers de status e
listagem (`mask_whatsapp_phone_number`), no formato `********1234`. Telefone
vazio, curto ou formatado aparece como `—`. O Admin nao loga telefone, `body`,
`instance_id`, token, segredo, QR, payload, `external_id` nem headers.

`EvolutionWebhookEvent` exibe `created_at`, Workspace derivado do canal,
`whatsapp_channel`, `event_type`, `status`, `attempt_count`, `error_code`,
`started_at` e `finished_at`. `deduplication_key` e `external_id` ficam ocultos,
e o model nao armazena payload bruto.

Conversas legadas sem canal aparecem como `Sem canal (legado)` e nao quebram a
renderizacao. Workspace, Contact, canal logico e `whatsapp_channel` sao somente
leitura: uma Conversation nao pode ser movida entre tenants ou canais pelo Admin.

#### Message e o envio manual

`Message` e o inline de mensagens sao **view-only**. Criar `Message` pelo Admin
**nao envia nada**: o pipeline duravel comeca no endpoint, que cria a mensagem
`OUTBOUND/PENDING`, registra `transaction.on_commit` e so entao agenda
`send_outbound_whatsapp_message` no Celery. Uma linha inserida a mao pula
roteamento por canal, validacao multi-tenant, controle de status e retry.

O unico mecanismo de envio manual e:

```
POST /api/omnichannel/conversations/{conversation_id}/reply/
{"body": "Mensagem de teste"}
```

#### Roteiro de teste manual pelo Swagger

1. Ative o virtualenv do projeto.
2. `python manage.py migrate`.
3. Suba PostgreSQL e Redis.
4. Suba o Django/Uvicorn.
5. Suba o worker Celery.
6. Suba a Evolution API.
7. Crie a conta em `POST /api/auth/register/` — o cadastro ja devolve `User`,
   `Workspace`, a membership `OWNER` e o par de tokens JWT. Como alternativa de
   suporte, o Admin do superuser continua permitindo criar os tres a mao.
8. Se preferir logar de novo (ou tiver usado o caminho manual do Admin), obtenha
   o JWT em `POST /api/auth/token/` com
   `{"email": "<email>", "password": "<password>"}`. Vindo do cadastro, o
   `access` ja veio no passo 7 e este passo e dispensavel.
9. Autorize o Swagger com `Bearer <access_token>`.
10. Liste ou crie o canal em
    `GET`/`POST /api/workspaces/{workspace_id}/whatsapp-channels/`.
11. Acompanhe `.../{channel_id}/status/` e `.../{channel_id}/qr/`.
12. Inspecione no Admin: `WhatsAppChannel`, `EvolutionWebhookEvent`, `Contact`,
    `Conversation`, `Message`, `AIProcessingRun` e `AIObservabilityEvent`.
13. Liste mensagens em
    `GET /api/omnichannel/conversations/{conversation_id}/messages/`.
14. Responda em `POST /api/omnichannel/conversations/{conversation_id}/reply/`.
15. Confirme que a `Message` nasce `OUTBOUND/PENDING`, que o Celery a processa,
    que o status avanca para `SENT` e que os webhooks podem avanca-la para
    `DELIVERED` e `READ`.

Nunca: criar `Message` no Admin para enviar; chamar a Evolution diretamente;
copiar a API key da Evolution para o Swagger; colocar segredo no frontend; testar
com o numero principal do negocio; ou fazer chamada real a Evolution dentro da
suite automatizada. O Evolution Manager serve apenas para diagnostico
controlado, nunca como caminho de operacao do produto.

#### Migracao de instancia legada

Uma instancia legada (criada antes do provisionamento self-service) pode ser
associada a uma Workspace pelo comando existente:

```
python manage.py migrate_legacy_whatsapp_channel --workspace-id <UUID> --dry-run
python manage.py migrate_legacy_whatsapp_channel --workspace-id <UUID>
```

O comando cria ou reutiliza o canal local e o vincula a Workspace informada. Ele
**nao** configura um webhook novo, **nao** gera QR e **nao** chama a Evolution.
Ele nao substitui o provisionamento self-service: um canal provisionado nasce
com `webhook_public_id`, `webhook_secret` e ciclo de QR proprios, enquanto a
instancia legada apenas ganha um registro local correspondente. Rode sempre o
`--dry-run` antes.

O smoke test real de ponta a ponta ocorrera depois da Parte 28, quando o cadastro
criar Workspace e Member automaticamente.

### Frontend de conexao do WhatsApp

A pagina `/workspaces/:workspaceId/settings/channels` permite que `OWNER` e
`ADMIN` listem canais, criem uma conexao e acompanhem seu estado usando somente
os endpoints SilverTech em `/api/workspaces/{workspace_id}/whatsapp-channels/`.
O backend continua sendo a autoridade de autorizacao; membros `AGENT` recebem a
interface de permissao negada e nenhum dado parcial e exibido.

A listagem consulta o backend em intervalo moderado, e o painel acompanha o
status local durante `provisioning`, `waiting_qr`, `connecting` e `reconnecting`.
O QR e consultado somente em `waiting_qr`, no maximo a cada dez segundos. O
frontend nunca chama a Evolution diretamente.

O valor do QR existe apenas em memoria enquanto o painel esta aberto. A imagem e
criada em uma Blob URL temporaria depois da validacao de MIME e magic bytes; a
URL e revogada ao substituir o QR, mudar de estado, fechar ou desmontar o painel.
A query sensivel tambem e cancelada e removida do TanStack Query. O QR nao e
gravado em `localStorage`, `sessionStorage`, logs, URLs, arquivos ou analytics.

Operacoes de lifecycle ainda nao possuem controles na interface. Restart,
disconnect e delete serao implementados na Parte 30, depois dos respectivos
contratos seguros de backend.

Antes de deploy:

```bash
python manage.py check
python manage.py check --deploy
pytest core/tests/ workspaces/tests/ omnichannel/tests/ -q
```
