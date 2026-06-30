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
