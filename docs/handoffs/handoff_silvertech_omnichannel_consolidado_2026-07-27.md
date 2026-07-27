# Handoff consolidado - SilverTech CRM Omnichannel

> Atualizado em 27/07/2026, após o smoke real com Evolution API v2.2.3 e os testes dirigidos de identidade `@lid`.
>
> Repositório de referência: [joaquimsilvertech-stack/Silvertech-Ommnichannel](https://github.com/joaquimsilvertech-stack/Silvertech-Ommnichannel), branch `master`.
>
> Estado em uma frase: o cadastro self-service, o provisionamento, o QR e a conexão do canal funcionaram de ponta a ponta, mas o fluxo inbound/outbound está bloqueado por um bug crítico de identidade: a `master` ainda trata `payload.sender` como telefone do contato em eventos `@lid`, embora o smoke tenha provado que esse campo representa a própria linha conectada.

## 0. Como usar este handoff

Este documento substitui as conclusões antigas quando houver conflito. A ordem de confiança é:

1. Código atual da `master`.
2. Payloads e respostas reais obtidos no smoke.
3. Plano técnico das Partes 17 a 36.
4. Handoffs e análises anteriores.

Regras para qualquer retomada:

- Não presumir que `payload.sender` identifica o remetente.
- Não executar `/reply/` em conversa criada pelo fallback incorreto.
- Não usar o telefone gravado no contato Arthur como destino.
- Não reutilizar tokens, senhas, API keys ou segredos compartilhados em conversas.
- Não reverter integralmente o commit `d1f92eb`: a correção de `keyId` continua válida; somente o tratamento de identidade por `sender` está invalidado.
- Confirmar nomes de arquivos, funções e contratos no código antes de implementar.

## 1. Visão do produto

O SilverTech é um CRM omnichannel SaaS multi-tenant por `Workspace`. O trilho atual transforma a integração com a Evolution API em um fluxo WhatsApp self-service:

```text
Cadastro
  -> User + Workspace + Member OWNER
  -> owner/admin cria um WhatsAppChannel
  -> SilverTech cria a instância Evolution
  -> SilverTech configura webhook seguro por canal
  -> QR é exibido pelo SilverTech
  -> cliente escaneia e conecta
  -> inbound entra no Workspace/canal correto
  -> outbound sai pela instância vinculada à conversa
```

### Stack confirmada

- Python 3.12
- Django 6.0.5
- Django REST Framework 3.17
- PostgreSQL
- Redis
- Celery 5.5
- Evolution API v2.2.3 no smoke
- JWT com SimpleJWT
- ASGI/uvicorn
- Channels/django-eventstream para SSE
- Swagger/OpenAPI com `drf-spectacular`
- CSP estrita com `django-csp`
- Frontend React/Vite

### Invariantes arquiteturais

- `Workspace` é a fronteira do tenant.
- `Member.Role` (`OWNER`, `ADMIN`, `AGENT`) é diferente do `role` de plataforma do usuário.
- Cada `WhatsAppChannel` pertence a um único Workspace.
- Cada conversa WhatsApp registra o canal responsável pelo inbound e outbound.
- O frontend nunca acessa a Evolution diretamente.
- Segredos, tokens, QR e payload bruto não devem aparecer em response, log, admin ou frontend.
- Qualquer identidade não resolvida deve falhar de forma segura; nunca deve ser convertida em telefone por inferência.

## 2. Estado atual do repositório

### Referência verificada

- Branch padrão: `master`.
- HEAD observado: `66de7d2882ebeedac6baa05a6194dcaee864968a` - `fix utf 16 to utf 8`.
- Commit relevante ao bug: `d1f92eba29d336b4f834fb378ff1df4331806a76` - `fix evolution lid inbound`.

### Commits de referência

| Commit | Entrega | Situação |
|---|---|---|
| `074c212` | Parte 28 - cadastro cria Workspace e OWNER | Válido |
| `3a9991f` | Normalização do e-mail no cadastro | Válido |
| `2556e35` | Parte 29 - RBAC dos canais | Válido |
| `a044ac2` | Higiene de autorização e contrato do DELETE | Válido |
| `0ad3ed5` | Ajuste do `.env.example` | Válido |
| `a11e8c2` | Swagger local com CSP estrita | Válido |
| `d1f92eb` | Suporte a `keyId` e fallback de LID por `sender` | Parcialmente inválido |
| `66de7d2` | `requirements.txt` convertido para UTF-8 | Válido; confirmar CI verde |

No `d1f92eb`:

- A extração de IDs de status em `data.keyId` e `data.messageId` deve ser preservada.
- O comentário e a lógica que afirmam que o número do contato chega em `sender` devem ser removidos/substituídos.
- Os testes adicionados precisam ser separados entre os que validam `keyId` e os que cristalizam o fallback incorreto.

### Evidência direta no código atual

Em `omnichannel/evolution_event_processing.py`, `_parse_inbound_message` ainda faz:

```text
remoteJid termina em @lid
  -> tenta remoteJidAlt
  -> se não houver telefone, normaliza event_sender
```

Em `omnichannel/outbound_routing.py`, `resolve_outbound_whatsapp_route` ainda faz:

```text
recipient = contact.phone
```

Em `omnichannel/inbound_routing.py`, o fluxo atual grava o mesmo valor como:

```text
Contact.phone = phone
Contact.channel_id = phone
```

A combinação dessas três regras explica o incidente:

```text
remoteJid do Arthur = @lid
  -> fallback usa sender da linha SilverTech
  -> contato Arthur recebe o telefone da própria linha
  -> /reply/ lê Contact.phone
  -> mensagem sai para a própria linha
```

## 3. Estado do roadmap das Partes 17 a 36

| Parte | Tema | Estado consolidado |
|---|---|---|
| 17 | Modelagem de `WhatsAppChannel` | Implementada |
| 18 | Migração do legado para canais | Implementada com fallback legado ainda existente |
| 19 | Client/adapter Evolution | Implementado e injetável por `client=None` |
| 20 | Provisionamento automático | Implementado; smoke real aprovado |
| 21 | Webhook seguro por canal | Implementado; cadeia real aprovada |
| 22 | Processamento de eventos | Implementado, mas parsing de inbound `@lid` contém bug crítico |
| 23 | APIs de QR e status | Implementadas; smoke aprovado |
| 24 | Frontend de conexão | Parcial: componentes existem, produto integrado ainda incompleto |
| 25 | Roteamento inbound por canal | Tenant/canal implementados; identidade `@lid` não está correta |
| 26 | Roteamento outbound por canal | Instância/canal corretos; destinatário pode estar contaminado |
| 27 | Django Admin seguro e testes manuais | Implementada |
| 28 | Cadastro self-service | Implementada; smoke aprovado |
| 29 | RBAC dos canais | Implementada |
| 30 | Gestão do ciclo de vida | Restart, disconnect idempotente e delete implementados; revisar aderência total ao plano |
| 31 | Observabilidade dos canais | Parcial; há recibos e observabilidade, mas o pacote completo do roadmap não foi encerrado |
| 32 | Segurança multi-tenant | Parcial; APIs possuem proteção, mas Django Admin ainda não é tenant-scoped |
| 33 | Evolution simulada | Não concluída; prioridade aumentou após o bug real |
| 34 | Desenvolvimento local | Roteiro manual existe; smoke ainda não terminou |
| 35 | Produção | Não concluída |
| 36 | Remoção do legado | Não iniciada/concluída |

### Baseline de testes

- Registro histórico após Swagger: `1516 passed`.
- Relato após `d1f92eb`: `1529 passed`, com 13 testes adicionais.
- Esse verde não comprova o comportamento correto de LID, pois parte dos testes foi construída sobre a premissa errada de que `sender` era o contato.
- A suíte precisa ser alterada e executada novamente após o fix.

## 4. Ambiente operacional usado no smoke

### Ambiente local

- Windows/PowerShell.
- Projeto local sob `C:\Users\Administrator\Downloads\API-Silvertech-Ommni-channel\API-Silvertech-Ommni-channel-main`.
- Backend em `http://127.0.0.1:8000`.
- Evolution em `http://localhost:8080`.
- Redis em `6379`.
- PostgreSQL em `5432`.
- Inspetor ngrok em `http://127.0.0.1:4040`.
- Celery no Windows com `--pool=solo`.

### Comandos-base

```powershell
.\venv\Scripts\python.exe -m uvicorn silvertech.asgi:application --port 8000 --reload

.\venv\Scripts\celery.exe -A silvertech worker -l info --pool=solo
```

Não usar `runserver` como referência para SSE.

### Redis

- DB 0: Celery/Channels.
- DB 1: Evolution.
- DB 2: cache Django.
- Não apontar o cache Django para DB 0; `cache.clear()` poderia apagar a fila do Celery.

### Identificadores atuais de validação

| Recurso | Valor |
|---|---|
| Conta de validação | `homologacao@silvertech.com` |
| User ID | `b34c3417-810e-4dd6-a02a-5b39e935bde3` |
| Workspace | `SilverTech Validação` |
| Workspace ID | `efc4e9d4-b854-404b-a8b4-702b45bfdec8` |
| Workspace slug | `silvertech-validacao` |
| Membership ID | `6647ab3a-3063-4065-a873-1eea5abbacbe` |
| Role | `owner` |
| Canal | `Atendimento Principal` |
| Channel ID | `aad2891e-fe81-4a79-a296-c5bf942ede0f` |
| Provider | `evolution` |
| Status comprovado | `connected` |
| Linha conectada | `********8392` |
| Conectado em | `2026-07-27T18:39:42.617248Z` |
| Instância usada nos testes dirigidos | `st_2e492824ea3c4e3797f79a04dc2d01b8` |

Credenciais foram deliberadamente omitidas. A senha da conta, JWTs e API key da Evolution apareceram em conversas e devem ser tratados como comprometidos.

### Recursos antigos/superseded

Não reutilizar como estado atual:

| Recurso antigo | ID |
|---|---|
| Workspace do primeiro smoke | `7ee042c2-0ef9-449c-8d4e-7d4dbd137702` |
| Canal do primeiro smoke | `a38675fa-323e-4268-ab4b-68d0bd7bee54` |

O canal atual é `aad2891e-fe81-4a79-a296-c5bf942ede0f`.

## 5. Smoke test: o que foi comprovado

| Fase | Resultado | Estado |
|---|---|---|
| Pré-requisitos | Backend, Evolution, Redis e PostgreSQL acessíveis | Aprovado |
| Cadastro | `POST /api/auth/register/` retornou `201` | Aprovado |
| Tenant | User + Workspace + Member OWNER criados | Aprovado |
| Provisionamento | Canal criado somente com `{"name":"Atendimento Principal"}` | Aprovado |
| QR | Canal chegou a `waiting_qr` e o QR foi pareado | Aprovado |
| Status | `GET .../status/` retornou `connected` | Aprovado |
| Webhook de conexão | Evolution alcançou e atualizou o backend | Aprovado |
| Inbound | Evento real `messages.upsert` chegou | Chegou, mas identidade foi processada incorretamente |
| Contato/conversa | Arthur foi criado com telefone da própria linha | Reprovado |
| Outbound por `/reply/` | Enviou para a própria linha | Reprovado e bloqueado |
| Envio direto por LID | Evolution retornou `400 / exists:false` | Não suportado nesta versão/sessão |
| Consulta do LID | `findContacts` retornou LID, nome e ID interno, sem telefone | Sem resolução |
| Envio pelo ID interno | Evolution retornou `400 / exists:false` | ID não enviável |
| Ações restart/disconnect/delete | Não concluídas neste ciclo novo | Pendente |
| Captura completa dos payloads | Parte capturada no ngrok | Preservar e completar após o fix |

Chegar a `connected` comprova:

- instância criada;
- webhook configurado;
- URL pública alcançável;
- segredo aceito;
- evento de conexão processado;
- canal e status vinculados ao tenant correto.

Isso não comprova identidade correta do contato nem destinatário correto do outbound.

## 6. Diagnóstico final do bug `@lid`

### Semântica comprovada do payload

No caso real:

```text
data.key.remoteJid = 119215877054656@lid
  -> identidade disponível do contato/remetente Arthur

payload.sender = número da linha conectada SilverTech
  -> não é o telefone do Arthur
```

O telefone contaminado do contato termina em `8392`, igual à linha conectada.

### Testes dirigidos

#### Teste A - envio direto para o LID

Destino:

```text
119215877054656@lid
```

Resposta:

```json
{
  "status": 400,
  "error": "Bad Request",
  "response": {
    "message": [
      {
        "exists": false,
        "jid": "119215877054656@lid",
        "name": "Arthur Ximenes de Oliveir",
        "number": "119215877054656@lid"
      }
    ]
  }
}
```

Conclusão: a Evolution reconhece metadados do LID, mas não o aceitou como destinatário enviável nessa versão/sessão.

#### Teste D - `findContacts` filtrado pelo LID

Retornou somente:

- ID interno `cms3kr786085nqz5wuv4m9yrt`;
- `remoteJid = 119215877054656@lid`;
- nome/pushName do Arthur.

Não retornou:

- telefone;
- `remoteJidAlt`;
- JID `@s.whatsapp.net`;
- campo equivalente de número verificado.

Conclusão: o endpoint consultado não expõe o mapeamento LID para telefone.

#### Teste C - envio pelo ID interno

Destino:

```text
cms3kr786085nqz5wuv4m9yrt
```

Resposta:

```json
{
  "status": 400,
  "error": "Bad Request",
  "response": {
    "message": [
      {
        "exists": false,
        "jid": "3786085549@s.whatsapp.net",
        "number": "cms3kr786085nqz5wuv4m9yrt"
      }
    ]
  }
}
```

Conclusão: a Evolution removeu os caracteres não numéricos do ID e interpretou o resíduo `3786085549` como telefone. Ela não resolveu o ID interno como contato.

### Matriz de identidade

| Campo/valor | O que representa | Pode identificar o contato? | Pode ser usado no outbound atual? |
|---|---|---:|---:|
| `payload.sender` | Linha conectada SilverTech | Não | Não |
| `remoteJid @lid` | Identidade WhatsApp observada do contato | Sim, como identidade de provedor | Não nesta versão/sessão |
| `remoteJidAlt @s.whatsapp.net` | JID telefônico alternativo, quando presente | Sim | Sim, após validação |
| `Contact.phone` contaminado | Própria linha conectada | Não | Deve ser bloqueado |
| ID `cms...` | ID de registro interno da Evolution | Não como JID | Não |
| Telefone verificado `55...` | Número real resolvido por fonte confiável | Sim | Sim |

### Conclusões invalidadas

- "`sender` é o telefone do remetente."
- "O commit `d1f92eb` resolveu completamente o inbound `@lid`."
- "O contato criado com final `8392` pode ser usado no `/reply/`."
- "O SilverTech não deve armazenar o LID."
- "O fluxo outbound da Parte 26 está aprovado para qualquer inbound real."

### Conclusões preservadas

- O `@lid` é uma identidade relevante e deve ser armazenado.
- `remoteJidAlt @s.whatsapp.net`, quando realmente presente e validado, pode fornecer um telefone/JID direto.
- `keyId`/`messageId` são caminhos válidos para correlacionar atualizações de status.
- O canal e a instância de saída continuam sendo resolvidos corretamente pela conversa.
- Na ausência de destinatário resolvido, o sistema deve falhar fechado.

## 7. Correção recomendada

### 7.1 Hotfix obrigatório

1. Remover o fallback `@lid -> event_sender` de `_parse_inbound_message`.
2. Preservar `remote_jid` como identidade do provedor.
3. Nunca copiar `payload.sender` para `Contact.phone` ou `Contact.channel_id`.
4. Permitir que o inbound seja armazenado mesmo quando o telefone não estiver resolvido.
5. Bloquear outbound quando não houver telefone/JID direto verificado.
6. Bloquear explicitamente destinatário igual à linha do próprio canal, como defesa contra dados já contaminados.
7. Garantir que nenhuma chamada à Evolution ocorra nos casos bloqueados.

### 7.2 Caminho de menor impacto no modelo atual

O model `Contact` já suporta:

- `phone` vazio;
- `channel_id` como identificador do contato no canal.

Portanto, um hotfix pode evitar migration:

```text
Inbound com @lid sem número resolvido
  -> Contact.channel_id = remoteJid @lid
  -> Contact.phone = ""
  -> Contact.name = pushName seguro
  -> Conversation e Message inbound são preservadas
  -> outbound falha com RECIPIENT_UNRESOLVED
```

Esse caminho exige ajustar `resolve_inbound_whatsapp_route`, pois hoje ele recebe um `phone` obrigatório e usa esse valor em `phone` e `channel_id`.

Cuidados:

- Definir se a unicidade de `channel_id` deve ser somente por Workspace ou por Workspace + WhatsAppChannel. O schema atual é único por `(workspace, channel_id)`.
- Se um telefone confiável aparecer posteriormente, atualizar o contato do LID sem criar duplicata.
- Não substituir silenciosamente um telefone existente sem comprovar que as identidades pertencem à mesma pessoa.

### 7.3 Arquitetura de longo prazo

Separar "contato CRM" de "identidade no provedor" por uma entidade dedicada, por exemplo:

```text
Contact
  -> ChannelIdentity
       workspace
       whatsapp_channel
       provider
       provider_jid
       phone nullable
       resolution_status
       resolution_source
       verified_at
```

Vantagens:

- um contato pode possuir LID e telefone sem misturar semânticas;
- a origem da resolução fica auditável;
- múltiplos canais e provedores deixam de competir por `Contact.channel_id`;
- outbound pode exigir uma identidade `VERIFIED`;
- é possível reconciliar LID e telefone depois sem perder inbound.

O hotfix não precisa esperar essa modelagem, mas não deve impedir sua adoção.

### 7.4 Comportamento da API

Para conversa com somente LID:

- não criar envio para a Evolution;
- não permanecer indefinidamente em `PENDING`;
- responder/registrar erro controlado, por exemplo:

```text
HTTP 409
error_code = OUTBOUND_RECIPIENT_UNRESOLVED
```

Recomenda-se:

- preflight no `/reply/` para evitar criar uma mensagem impossível;
- validação redundante na task Celery para impedir bypass ou corrida;
- erro sanitizado, sem telefone, LID ou payload no log público.

## 8. Dados contaminados

O contato Arthur criado no Workspace atual está contaminado:

- nome do contato: Arthur Ximenes de Oliveir;
- identidade real observada: `119215877054656@lid`;
- telefone gravado: número da própria linha, final `8392`;
- ID interno observado na Evolution: `cms3kr786085nqz5wuv4m9yrt`.

Até a correção:

- não usar a conversa para `/reply/`;
- não usar `Contact.phone` como fonte confiável;
- não executar automação ou IA que possa responder por essa conversa;
- preservar o payload bruto capturado fora do banco para fixture de regressão.

Após o hotfix:

1. Fazer backup/registrar IDs do contato, conversa e mensagens de teste.
2. Corrigir o contato para `channel_id = 119215877054656@lid` e `phone = ""`, ou recriá-lo no workspace de teste.
3. Garantir que a conversa continue vinculada ao canal atual.
4. Confirmar que o próprio número do canal não aparece como telefone de contatos criados por LID.
5. Só remover dados antigos depois de validar a nova fixture e o histórico necessário.

## 9. Testes obrigatórios para o fix

### Parsing e inbound

- `@lid` sem `remoteJidAlt`, com `sender` igual à linha conectada: nunca usar `sender`.
- `@lid` sem telefone: preservar LID, contato com `phone` vazio e inbound criado.
- `@lid` com `remoteJidAlt @s.whatsapp.net`: aceitar somente após normalização e validação.
- JID direto `@s.whatsapp.net`: manter compatibilidade.
- Grupo `@g.us`: continuar rejeitado/ignorado conforme contrato.
- Evento duplicado: não duplicar contato, conversa ou mensagem.
- Dois inbounds concorrentes do mesmo LID: manter idempotência.

### Outbound

- Contato com `phone` vazio: erro seguro, zero chamadas Evolution.
- Contato com telefone igual ao `WhatsAppChannel.phone_number`: bloquear.
- Contato contaminado histórico: bloquear.
- Contato com telefone confiável: enviar pela instância do canal correto.
- Manipulação cross-tenant: continuar 403/404 ou erro de roteamento seguro.
- Retry: manter a mesma Message e o mesmo canal.

### Status

- Preservar testes de `data.keyId`.
- Preservar testes de `data.messageId`.
- Preservar compatibilidade com `key.id`.
- Atualizar somente mensagens outbound, conforme decisão atual do produto.

### Integração/fake

O Evolution fake da Parte 33 deve reproduzir o payload real:

```text
remoteJid = ...@lid
remoteJidAlt ausente
sender = linha conectada
messages.update com keyId
```

Se o fake fornecer telefone em `sender`, ele esconderá novamente o bug.

### Critérios de aceite

- Nenhuma mensagem chega à própria linha por erro de identidade.
- Inbound `@lid` não é perdido.
- O LID fica persistido separadamente do telefone.
- Outbound sem destinatário resolvido falha fechado.
- A Evolution não é chamada em rota não resolvida.
- `keyId` continua correlacionando status.
- Suíte focada e completa ficam verdes.
- `manage.py check`, `makemigrations --check` e `git diff --check` ficam limpos.

## 10. Próximas ações, em ordem

### Prioridade 0 - Segurança

1. Rotacionar a API key global da Evolution exposta.
2. Alterar a senha da conta de validação ou recriar a conta.
3. Não reutilizar o access/refresh JWT exibido.
4. Confirmar que `.env` permanece fora do Git.
5. Atualizar a configuração do Django e da Evolution com as novas credenciais.

### Prioridade 1 - Preservar evidência

1. Exportar o JSON bruto do `messages.upsert` pelo inspetor do ngrok.
2. Exportar o `messages.update` que usa `keyId`.
3. Salvar as respostas dos testes LID, `findContacts` e ID interno como fixtures sanitizadas.
4. Não salvar API key, JWT, webhook secret, QR ou corpo sensível desnecessário.

### Prioridade 2 - Implementar o hotfix

Escopo mínimo:

- `omnichannel/evolution_event_processing.py`;
- `omnichannel/inbound_routing.py`;
- `omnichannel/outbound_routing.py`;
- camada do endpoint `/reply/` e task de envio, se necessário para o `409`;
- testes relacionados ao commit `d1f92eb`;
- fixtures reais sanitizadas.

Não alterar a extração de `keyId` que já foi validada.

### Prioridade 3 - Reparar dados de teste

- Quarentenar/corrigir Arthur e a conversa contaminada.
- Procurar outros contatos do Workspace cujo telefone seja igual ao número do canal.
- Não fazer limpeza destrutiva sem confirmar o alvo e preservar evidência.

### Prioridade 4 - Repetir o smoke

1. Gerar token novo.
2. Confirmar canal `connected`.
3. Enviar inbound de outro aparelho.
4. Confirmar:
   - LID persistido;
   - `phone` vazio ou número realmente verificado;
   - contato não recebe a linha SilverTech.
5. Tentar `/reply/`:
   - se não houver número resolvido, esperar `409`/erro seguro e zero envio;
   - se houver JID telefônico confiável, confirmar entrega ao aparelho correto.
6. Validar `PENDING -> SENT -> DELIVERED` somente no caso enviável.
7. Executar restart, disconnect, idempotência e delete por último.
8. Confirmar que a conversa sobrevive ao delete conforme `SET_NULL`.

### Prioridade 5 - Decisão de produto/provider

Se a Evolution v2.2.3 continuar sem fornecer LID -> telefone:

- investigar versão fixada mais recente em ambiente isolado;
- validar se algum evento oficial entrega `remoteJidAlt`, `senderPn`, `participantAlt` ou equivalente;
- não depender de endpoint interno sem contrato;
- considerar limitação operacional explícita ou outro provider se outbound confiável não puder ser garantido.

Upgrade da Evolution não deve ocorrer diretamente no ambiente atual. Primeiro reproduzir em ambiente de teste, fixar versão e repetir as fixtures.

## 11. Endpoints relevantes

| Finalidade | Endpoint |
|---|---|
| Cadastro | `POST /api/auth/register/` |
| Login | `POST /api/auth/token/` |
| Refresh | `POST /api/auth/token/refresh/` |
| Workspaces do usuário | `GET /api/workspaces/workspaces/` |
| Listar/criar canais | `GET/POST /api/workspaces/{workspace_id}/whatsapp-channels/` |
| QR | `GET /api/workspaces/{workspace_id}/whatsapp-channels/{channel_id}/qr/` |
| Status | `GET /api/workspaces/{workspace_id}/whatsapp-channels/{channel_id}/status/` |
| Reiniciar | `POST /api/workspaces/{workspace_id}/whatsapp-channels/{channel_id}/restart/` |
| Desconectar | `POST /api/workspaces/{workspace_id}/whatsapp-channels/{channel_id}/disconnect/` |
| Remover | `DELETE /api/workspaces/{workspace_id}/whatsapp-channels/{channel_id}/` |
| Conversas | `GET /api/omnichannel/conversations/` |
| Mensagens | `GET /api/omnichannel/conversations/{conversation_id}/messages/` |
| Responder | `POST /api/omnichannel/conversations/{conversation_id}/reply/` |
| Webhook atual | `POST /api/omnichannel/webhooks/evolution/{webhook_public_id}/` |

O fluxo legado com `?workspace=UUID` permanece transitório e deve ser removido somente na Parte 36.

## 12. RBAC consolidada

| Ação | OWNER | ADMIN | AGENT | SUPERUSER |
|---|---:|---:|---:|---:|
| Ver canais/status/QR | Sim | Sim | Não | Bypass explícito |
| Criar canal | Sim | Sim | Não | Bypass explícito |
| Reiniciar | Sim | Sim | Não | Bypass explícito |
| Desconectar | Sim | Sim | Não | Bypass explícito |
| Remover | Sim | Não | Não | Bypass explícito |
| Responder conversa | Sim | Sim | Sim | Técnico |

O backend é a fonte de verdade; esconder botões no frontend não substitui autorização.

## 13. Frontend

### Pronto/parcial

- clientes JWT e de erro;
- helpers de QR;
- polling adaptativo;
- componentes de WhatsApp;
- componentes de IA/observabilidade.

### Lacunas

- conflito de rota `/conversations`, com duas árvores React;
- chat sem mutation real para `/reply/`;
- ausência de consumo SSE;
- ausência de UI para restart/disconnect/remove;
- ausência de gating visual por role;
- ausência de tela de cadastro e guarda de autenticação;
- ausência de seletor/contexto de Workspace;
- dashboard ainda funciona como mapa de rotas, não como produto final.

Não implementar o envio do frontend antes de o backend bloquear destinatários não resolvidos.

## 14. Backlog restante

### Crítico

- Corrigir identidade `@lid` sem `sender`.
- Corrigir dados contaminados.
- Rotacionar segredos expostos.
- Confirmar CI verde no HEAD `66de7d2`.

### Importante

- Saneamento estrutural do OpenAPI:
  - serializers aninhados com nomes colididos;
  - `APIView` sem schema explícito;
  - enums de status colididos;
  - `operationId` duplicado;
  - schema incorreto do `/reply/`, que deve aceitar somente `{"body":"..."}`.
- Isolamento multi-tenant do Django Admin.
- Consolidar `_sanitize_error_code`, hoje duplicado.
- Provisionamento e gestão assíncronos.
- Reconciliação periódica de status.
- Parametrizar tempos de JWT por ambiente.
- Fixar versão de produção da Evolution em vez de `latest`.
- Definir serving de `/static/` em produção.

### Produto/decisões

- Status de leitura de mensagens inbound continua fora de escopo.
- Definir fronteira para concluir o frontend.
- Gerar cliente TypeScript a partir do OpenAPI após saneamento.
- Remover fluxo legado somente após telemetria provar que não há tenants dependentes.

## 15. Fluxo de trabalho com Claude Code

Para cada parte/fix:

1. Abrir chat limpo.
2. Informar contexto curto, commit base e escopo exato.
3. Exigir inspeção do código real antes de editar.
4. Não misturar parte futura.
5. Não criar commit automaticamente.
6. Rodar:

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py makemigrations --check
.\venv\Scripts\python.exe -m pytest <suíte focada>
.\venv\Scripts\python.exe -m pytest
git diff --check
```

7. Entregar relatório com:
   - arquivos alterados;
   - decisões;
   - testes e saída real;
   - riscos;
   - itens deliberadamente fora de escopo.
8. O arquiteto deve validar as afirmações contra a `master` antes de aceitar o trabalho.

## 16. Prompt curto para retomar em outro chat

```text
Use o repositório joaquimsilvertech-stack/Silvertech-Ommnichannel, branch master, como fonte de verdade.

O self-service já criou e conectou o canal aad2891e-fe81-4a79-a296-c5bf942ede0f no Workspace efc4e9d4-b854-404b-a8b4-702b45bfdec8. O smoke provou um bug crítico no commit d1f92eb:

- data.key.remoteJid = 119215877054656@lid identifica o contato Arthur;
- payload.sender identifica a própria linha conectada, final 8392;
- a master usa sender como fallback e grava a própria linha em Contact.phone;
- outbound lê Contact.phone e enviou para a própria linha;
- sendText para o LID retornou 400 exists:false;
- findContacts pelo LID retornou somente LID, nome e id cms..., sem telefone;
- sendText para o id cms... também retornou 400 exists:false;
- a extração de status por keyId no mesmo commit continua válida.

Não execute /reply/ nessa conversa. Primeiro inspecione evolution_event_processing.py, inbound_routing.py, outbound_routing.py e os testes do d1f92eb. Implemente um hotfix que preserve o LID, permita phone vazio, nunca use sender como contato, bloqueie destinatário não resolvido e bloqueie envio para o número do próprio canal. Preserve inbound, keyId, isolamento multi-tenant e idempotência. Use o payload real como fixture e rode a suíte focada e completa.
```

## 17. Referências

- [Repositório SilverTech Omnichannel](https://github.com/joaquimsilvertech-stack/Silvertech-Ommnichannel)
- [Commit `d1f92eb` - fix Evolution LID inbound](https://github.com/joaquimsilvertech-stack/Silvertech-Ommnichannel/commit/d1f92eba29d336b4f834fb378ff1df4331806a76)
- [Commit `66de7d2` - requirements UTF-8](https://github.com/joaquimsilvertech-stack/Silvertech-Ommnichannel/commit/66de7d2882ebeedac6baa05a6194dcaee864968a)
- [Evolution API issue #1872 - contexto de eventos `@lid`](https://github.com/evolution-foundation/evolution-api/issues/1872)
- [Evolution API issue #2547 - reprodução de envio por `@lid`](https://github.com/evolution-foundation/evolution-api/issues/2547)

## 18. Estado exato de parada

O último trabalho concluído foi o diagnóstico, não o fix.

Ponto de retomada:

```text
Diagnóstico fechado
  -> sender descartado como identidade do contato
  -> LID direto não enviável na v2.2.3/sessão testada
  -> findContacts não revelou telefone
  -> id cms... não é destinatário
  -> master ainda contém fallback inseguro
  -> próximo passo = hotfix + testes + reparo dos dados
```

Até isso ser entregue, o canal pode permanecer conectado para observação, mas o outbound de conversas originadas apenas por LID deve ficar bloqueado.
