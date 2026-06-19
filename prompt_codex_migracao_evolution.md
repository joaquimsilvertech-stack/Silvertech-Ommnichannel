# Contexto do projeto

Você está trabalhando no back-end de um **CRM Omnichannel** chamado LOØR,
construído em **Python + Django 5 + Django REST Framework (DRF)**, com
**PostgreSQL**, **Celery + Redis** para tarefas assíncronas, e
**django-eventstream** (SSE via Redis pub-sub) para atualizações em tempo
real no front-end.

O sistema centraliza conversas de WhatsApp em uma inbox única por
**workspace** (multi-tenant: cada cliente da plataforma é um Workspace
isolado, com seus próprios Contacts, Conversations e Messages). Quando uma
mensagem chega no WhatsApp, um webhook recebe o payload, uma task Celery
processa em background (cria/atualiza Contact e Conversation, salva a
Message, dispara um evento SSE), e o front-end React atualiza a tela do
agente em tempo real. Quando um agente responde pela interface, a API chama
o provedor de WhatsApp para entregar a mensagem no celular do cliente final.

Apps Django relevantes para esta tarefa:
- `omnichannel/`: models `Conversation` e `Message`, `services.py` (regras
  de negócio e integração com o provedor de WhatsApp), `views.py`
  (`WebhookAPIView` para receber payloads e `ConversationViewSet` com a
  action `reply` para enviar mensagens), `tasks.py` (Celery), `serializers.py`.
- `crm/`: model `Contact` (cada contato tem `workspace`, `name`, `phone`,
  `channel_id`).
- `silvertech/settings.py`: configurações globais do projeto, incluindo
  variáveis de ambiente do provedor de WhatsApp.

# O que já existe e funciona (não mexer)

- `Conversation` e `Message` (em `omnichannel/models.py`) já têm os campos
  necessários: `Message.Direction` (INBOUND/OUTBOUND), `Message.Status`
  (SENT/DELIVERED/READ/FAILED), `Message.external_id` (ID da mensagem no
  provedor externo).
- O pipeline assíncrono (`WebhookAPIView.post` → Celery
  `process_whatsapp_webhook_task` → `services.process_whatsapp_payload`) já
  funciona e está testado — POST chega, task é enfileirada, processamento
  acontece em background.
- O SSE (tempo real) já funciona e não precisa de nenhuma alteração.
- A action `reply` do `ConversationViewSet` (em `views.py`) já existe e
  funciona — ela valida o body recebido, busca o telefone do contato da
  conversa, chama uma função `send_whatsapp_message(phone, text)` de
  `services.py`, e cria a `Message` outbound no banco.

# O que está mudando: motivo da tarefa

O projeto usava a **WhatsApp Cloud API oficial da Meta** como provedor. Por
limitações da sandbox de desenvolvimento da Meta (mensagens não chegavam ao
celular real mesmo com a API retornando sucesso), o projeto está migrando
para a **Evolution API** — um servidor open-source self-hosted que expõe uma
API REST sobre o protocolo do WhatsApp Web (Baileys).

A Evolution API **já está rodando e configurada** via Docker (não é parte
desta tarefa mexer em infraestrutura):
- Disponível em `http://localhost:8080`.
- Autenticação via header `apikey`.
- Uma instância chamada `silvertech_whatsapp` já está criada e **conectada**
  a um número de WhatsApp real (QR code já escaneado).
- O webhook da instância já foi cadastrado na Evolution apontando para
  `http://host.docker.internal:8000/api/omnichannel/webhooks/whatsapp/?workspace={workspace_id}`,
  assinando os eventos `MESSAGES_UPSERT` e `CONNECTION_UPDATE`.

**Sua tarefa é exclusivamente no código Django**: trocar a integração que
hoje fala com a Graph API da Meta para falar com a Evolution API, nos dois
sentidos (enviar mensagem e processar mensagem recebida).

# Referência: como a Evolution API se comporta

**Enviar mensagem de texto** — `POST {EVOLUTION_API_URL}/message/sendText/{instance}`
```
Headers: apikey: <EVOLUTION_API_KEY>, Content-Type: application/json
Body: {"number": "5561983788392", "text": "conteúdo da mensagem"}
```
Resposta inclui `key.id` — o ID único da mensagem no WhatsApp (equivalente
ao `wamid` que a Meta usava), que deve ser salvo no campo `external_id` da
`Message`.

**Webhook de mensagem recebida** — evento `messages.upsert`, payload:
```json
{
  "event": "messages.upsert",
  "instance": "silvertech_whatsapp",
  "data": {
    "key": {
      "remoteJid": "5561983788392@s.whatsapp.net",
      "fromMe": false,
      "id": "3EB0C767D26A1D8B0F1D"
    },
    "pushName": "Nome do Contato",
    "message": { "conversation": "texto da mensagem recebida" }
  }
}
```
Observações importantes sobre esse payload:
- `data` pode vir como objeto único ou como lista — trate os dois casos.
- Quando `key.fromMe` é `true`, é eco de uma mensagem que a própria
  instância enviou — deve ser **ignorado** (já criamos a Message outbound
  no momento do envio, via `/reply/`).
- `remoteJid` terminando em `@g.us` é mensagem de **grupo** — fora de
  escopo do CRM (que é 1:1), deve ser ignorado.
- O texto pode vir em `message.conversation` (texto simples) ou em
  `message.extendedTextMessage.text` (texto com link/preview/citação) —
  trate os dois casos; se nenhum existir (mensagem de mídia: imagem, áudio,
  documento), ignore por enquanto (fora de escopo desta tarefa).
- `remoteJid` precisa ser normalizado removendo o sufixo
  (`"5561983788392@s.whatsapp.net"` → `"5561983788392"`) antes de salvar
  como `Contact.phone`.

**Webhook de status de conexão** — evento `connection.update`, payload:
```json
{
  "event": "connection.update",
  "instance": "silvertech_whatsapp",
  "data": { "state": "open" }
}
```
`state` pode ser `"open"` (conectado), `"close"` (desconectado/sessão
caiu) ou `"connecting"`. Por enquanto, apenas logar — sem persistir no
banco ainda.

# Tarefa: aplicar as 4 mudanças abaixo

## 1. `silvertech/settings.py`

Localize as variáveis de ambiente do provedor de WhatsApp (atualmente
nomeadas algo como `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
`WHATSAPP_VERIFY_TOKEN`, lidas via `django-environ`). Substitua por três
novas variáveis, seguindo o mesmo padrão de validação no boot (sem
`default=`, para o Django exigir essas chaves obrigatoriamente):

```python
EVOLUTION_API_URL = env('EVOLUTION_API_URL')
EVOLUTION_API_KEY = env('EVOLUTION_API_KEY')
EVOLUTION_INSTANCE_NAME = env('EVOLUTION_INSTANCE_NAME')
```

## 2. `.env`

Remova as variáveis antigas do provedor Meta (se existirem no arquivo) e
adicione:
```
EVOLUTION_API_URL=http://localhost:8080
EVOLUTION_API_KEY=silvertech_chave_secreta_123
EVOLUTION_INSTANCE_NAME=silvertech_whatsapp
```

## 3. `omnichannel/services.py`

Reescreva a função responsável por enviar mensagens (atualmente integrada
com a Graph API da Meta) para usar o endpoint `sendText` da Evolution,
conforme a especificação acima. Mantenha tratamento de exceção via
`requests.exceptions.RequestException`, com log do corpo da resposta de
erro quando disponível (`exc.response.text`).

Reescreva também o parser do payload de webhook: hoje provavelmente navega
uma estrutura `entry → changes → value` (formato da Meta) — substitua por
um roteador que lê o campo `event` do payload Evolution e despacha para:
- `messages.upsert` → lógica de upsert de Contact/Conversation/Message
  inbound (aplicando os filtros de `fromMe`, grupos, e os dois formatos de
  texto descritos acima).
- `connection.update` → apenas log (WARNING se `state == 'close'`, INFO
  caso contrário).
- qualquer outro evento → log informativo, sem erro.

Mantenha a assinatura pública da função principal de processamento de
webhook compatível com o que `tasks.py` já chama (mesmo nome de função,
recebendo `payload: dict` e `workspace_id: str`) — não altere `tasks.py`.

A função de upsert de mensagem inbound deve continuar usando
`transaction.atomic()`, `Contact.objects.get_or_create` (chave:
`workspace_id` + `phone`), e buscar/criar `Conversation` com
`status=Conversation.Status.OPEN` antes de criar a `Message` com
`direction=Message.Direction.INBOUND`. Adicione o campo `external_id` da
mensagem (vindo de `key.id`) ao criar a `Message`.

## 4. `omnichannel/views.py`

Na `WebhookAPIView`:
- O método `get` provavelmente implementa um handshake de verificação
  específico da Meta (parâmetros `hub.mode`, `hub.verify_token`,
  `hub.challenge`). A Evolution API **não exige handshake de verificação de
  URL** — substitua o corpo do método por um simples retorno HTTP 200 vazio
  (health-check).
- O método `post` deve continuar igual: loga o payload, extrai
  `workspace_id` da query string, enfileira a task Celery, responde 200
  imediatamente. Não altere essa parte.

Na action `reply` do `ConversationViewSet`:
- A função de envio agora retorna o payload de resposta da Evolution (não
  mais da Meta). Ajuste a extração do ID da mensagem enviada: em vez de ler
  de uma lista `messages[0].id` (formato Meta), leia de `key.id` (formato
  Evolution) — algo como `response.get('key', {}).get('id')`.
- O resto da lógica (validação do serializer, busca da conversa, criação da
  `Message` outbound, resposta 201) permanece igual.

# Regras gerais

- Mantenha tipagem (type hints) e o estilo de código já presente no projeto
  (snake_case, docstrings curtas em português, `from __future__ import
  annotations` no topo dos arquivos que já o usam).
- Não modifique `models.py`, `tasks.py`, `urls.py`, `serializers.py` —
  estão fora do escopo desta tarefa e já funcionam corretamente.
- Não adicione suporte a mensagens de mídia (imagem, áudio, documento)
  nesta tarefa — está fora de escopo, é um card futuro do backlog.
- Não implemente validação de assinatura de webhook nesta tarefa — também
  é um card futuro, separado.
- Ao final, rode (ou descreva o comando para rodar) `python manage.py
  check` para confirmar que não há erro de import ou de variável de
  ambiente ausente.
- Retorne um resumo claro do que foi alterado em cada um dos 4 arquivos.
