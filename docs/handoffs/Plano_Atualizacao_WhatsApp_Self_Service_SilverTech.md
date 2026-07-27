# SILVERTECH

## Plano de Atualização - WhatsApp Self-Service por Tenant

**Roadmap técnico das Partes 17 a 36**

Provisionamento automático de instâncias Evolution, QR Code, webhook seguro, roteamento por canal, onboarding SaaS, testes e produção.

**Documento de planejamento técnico**  
**Data:** 17 de julho de 2026

---

## Resumo executivo

**Objetivo:** Transformar a integração atual com a Evolution API em um fluxo self-service por Workspace, no qual o cliente conecta o próprio WhatsApp dentro do SilverTech sem copiar UUID, criar instância manualmente ou configurar webhook no painel da Evolution.

### Resultado esperado

O cliente cria a conta, recebe uma Workspace, acessa **Configurações > WhatsApp**, clica em **Conectar**, visualiza o QR Code dentro do SilverTech, escaneia pelo celular e passa a enviar e receber mensagens pela instância correta do seu tenant.

### Princípios da arquitetura

- Uma Workspace representa a empresa/tenant; o usuário inicial torna-se OWNER dessa Workspace.
- Cada conexão WhatsApp é representada por um `WhatsAppChannel` associado à Workspace.
- Cada canal possui sua própria instância Evolution e seu próprio webhook seguro.
- O frontend nunca acessa a Evolution diretamente nem recebe a API key global.
- A `Conversation` registra o canal responsável pelo recebimento e envio das mensagens.
- O Django Admin permanece disponível para inspeção técnica de canais, conversas, mensagens, IA e observabilidade.
- O desenvolvimento local continua possível; URL pública só é necessária quando a Evolution não alcança o backend pela rede local ou Docker.

### Fluxo final do cliente

```text
Cadastro do cliente
  -> cria User
  -> cria Workspace
  -> cria Member como OWNER
  -> cliente abre Configurações > WhatsApp
  -> clica em Conectar
  -> SilverTech cria instância Evolution
  -> SilverTech configura webhook seguro
  -> QR Code aparece no SilverTech
  -> cliente escaneia
  -> canal fica CONNECTED
  -> mensagens entram no CRM
  -> respostas usam a instância do canal correto
```

---

## Visão geral do roadmap

| Parte | Tema | Resultado principal |
|---:|---|---|
| 17 | Modelagem de canais WhatsApp por Workspace | Canal persistente e isolado por tenant |
| 18 | Migração do modelo atual para canais | Dados atuais preservados e associados a canal |
| 19 | Client/adapter central da Evolution API | Integração Evolution centralizada e testável |
| 20 | Provisionamento automático da instância | Instância e webhook criados pelo SilverTech |
| 21 | Webhook seguro por canal | Webhook autenticado e resolvido por canal |
| 22 | Processamento dos eventos da Evolution | Estados, mensagens e QR tratados por evento |
| 23 | API de QR Code e estado de conexão | QR e status expostos com segurança |
| 24 | Frontend de conexão do WhatsApp | Conexão realizada dentro do produto |
| 25 | Roteamento inbound por WhatsAppChannel | Inbound cai no tenant/canal correto |
| 26 | Roteamento outbound por WhatsAppChannel | Outbound usa a instância correta |
| 27 | Compatibilidade com Django Admin e testes manuais | Admin e testes manuais preservados |
| 28 | Criação automática de Workspace no cadastro | Conta cria Workspace e OWNER automaticamente |
| 29 | RBAC dos canais | Permissões claras para OWNER/ADMIN/AGENT |
| 30 | Desconectar, reconectar e excluir canal | Ciclo de vida completo da conexão |
| 31 | Observabilidade dos canais | Métricas e eventos operacionais por tenant |
| 32 | Segurança multi-tenant dos canais | Proteção contra IDOR, spoofing e vazamento |
| 33 | Testes de integração com Evolution simulada | Fluxo completo testado sem Evolution real |
| 34 | Configuração de desenvolvimento local | Testes locais documentados e reproduzíveis |
| 35 | Configuração de produção | Deploy seguro e observável |
| 36 | Remoção do fluxo legado | UUID no webhook e instância global removidos |

---

## Sumário detalhado

1. Parte 17 - Modelagem de canais WhatsApp por Workspace
2. Parte 18 - Migração do modelo atual para canais
3. Parte 19 - Client/adapter central da Evolution API
4. Parte 20 - Provisionamento automático da instância
5. Parte 21 - Webhook seguro por canal
6. Parte 22 - Processamento dos eventos da Evolution
7. Parte 23 - API de QR Code e estado de conexão
8. Parte 24 - Frontend de conexão do WhatsApp
9. Parte 25 - Roteamento inbound por WhatsAppChannel
10. Parte 26 - Roteamento outbound por WhatsAppChannel
11. Parte 27 - Compatibilidade com Django Admin e testes manuais
12. Parte 28 - Criação automática de Workspace no cadastro
13. Parte 29 - RBAC dos canais
14. Parte 30 - Desconectar, reconectar e excluir canal
15. Parte 31 - Observabilidade dos canais
16. Parte 32 - Segurança multi-tenant dos canais
17. Parte 33 - Testes de integração com Evolution simulada
18. Parte 34 - Configuração de desenvolvimento local
19. Parte 35 - Configuração de produção
20. Parte 36 - Remoção do fluxo legado

---

## Fundação de domínio

### Parte 17 - Modelagem de canais WhatsApp por Workspace

**Objetivo:** Criar a entidade que representa uma conexão WhatsApp individual, persistente e vinculada a uma única Workspace.

#### Principais entregas

- Criar o model `WhatsAppChannel` com `workspace`, `provider`, `nome`, `instance_name`, `instance_id`, `instance_token` criptografado quando necessário, `webhook_public_id`, `webhook_secret` criptografado, `status`, telefone, `connected_at` e timestamps.
- Definir estados operacionais: `DISCONNECTED`, `PROVISIONING`, `WAITING_QR`, `CONNECTING`, `CONNECTED`, `RECONNECTING`, `ERROR` e `DELETING`.
- Adicionar relacionamento entre `Conversation` e `WhatsAppChannel` para que toda conversa saiba qual número/instância deve ser usado.
- Adicionar constraints para impedir nomes de instância duplicados e relações cruzadas entre tenants.
- Preparar o modelo para múltiplos números por Workspace, mesmo que o MVP permita apenas um canal inicialmente.

#### Critérios de conclusão

- Migration criada e reversível.
- Canal sempre pertence a uma Workspace.
- `Conversation` não pode apontar para canal de outro tenant.
- Campos sensíveis ficam criptografados e nunca aparecem em serializers públicos.

### Parte 18 - Migração do modelo atual para canais

**Objetivo:** Migrar com segurança o fluxo atual de instância global para o novo modelo por canal, sem perder conversas e mensagens existentes.

#### Principais entregas

- Criar um `WhatsAppChannel` para a configuração atual da Clínica A.
- Associar conversas existentes ao canal migrado.
- Manter compatibilidade temporária com `EVOLUTION_INSTANCE_NAME` por feature flag ou fallback controlado.
- Adicionar validações para identificar conversas antigas ainda sem canal.
- Criar estratégia de rollback e relatório de inconsistências antes de remover o legado.

#### Critérios de conclusão

- Nenhuma conversa ou mensagem é perdida.
- Todas as conversas ativas ficam associadas a canal válido.
- O código novo prioriza o canal e usa o legado apenas durante a transição.
- Testes cobrem migration forward e rollback.

---

## Integração com provider

### Parte 19 - Client/adapter central da Evolution API

**Objetivo:** Centralizar toda comunicação com a Evolution API em um client/adapter único, seguro e facilmente mockável.

#### Principais entregas

- Criar `omnichannel/evolution/client.py` ou módulo equivalente.
- Implementar `create_instance`, `configure_webhook`, `get_qr_code`, `get_connection_state`, `send_text`, `restart_instance`, `logout_instance` e `delete_instance`.
- Usar `EVOLUTION_API_URL` e `EVOLUTION_API_KEY` apenas no backend.
- Aplicar timeouts, validação de resposta, mapeamento de erros, retry seletivo e logs sanitizados.
- Não registrar API key, token, QR Code, payload bruto, headers ou corpo de mensagem.

#### Critérios de conclusão

- Nenhuma chamada Evolution permanece espalhada pelos módulos de negócio.
- Client possui testes unitários com respostas simuladas.
- Erros da Evolution são convertidos em códigos internos previsíveis.
- Frontend nunca conhece credenciais da Evolution.

---

## Provisionamento automático

### Parte 20 - Provisionamento automático da instância

**Objetivo:** Permitir que owner/admin crie um canal e receba o QR Code sem acessar o painel da Evolution.

#### Principais entregas

- Criar endpoint `POST /api/workspaces/{workspace_id}/whatsapp-channels/`.
- Criar o canal local com status `PROVISIONING` e gerar `instance_name` único e não previsível.
- Chamar a Evolution para criar a instância, configurar o webhook e solicitar o QR.
- Atualizar o status para `WAITING_QR` quando o QR estiver disponível.
- Tratar cliques duplicados, timeouts e falhas parciais sem deixar instâncias órfãs ou canais inconsistentes.
- Aplicar idempotência ou lock transacional durante o provisionamento.

#### Critérios de conclusão

- Um único clique cria canal, instância e webhook.
- Falha parcial resulta em estado recuperável e erro sanitizado.
- Duas requisições simultâneas não criam duas instâncias acidentalmente.
- Somente owner/admin pode provisionar.

---

## Segurança de entrada

### Parte 21 - Webhook seguro por canal

**Objetivo:** Substituir o webhook baseado em `?workspace=UUID` por um endpoint seguro identificado por canal.

#### Principais entregas

- Criar rota `/api/omnichannel/webhooks/evolution/{webhook_public_id}/`.
- Resolver `WhatsAppChannel` pelo `webhook_public_id` e, a partir dele, obter a Workspace.
- Configurar um segredo por canal em header, por exemplo `X-SilverTech-Webhook-Secret`.
- Validar o segredo com comparação constante usando `secrets.compare_digest`.
- Rejeitar canal inexistente ou segredo inválido antes de criar `Contact`, `Conversation` ou `Message`.
- Aplicar limite de payload, rate limit apropriado, idempotência e logs sanitizados.

#### Critérios de conclusão

- UUID público sozinho não autentica o webhook.
- Webhook inválido não causa side effects.
- Nenhuma mensagem pode ser direcionada manualmente a outro tenant.
- O endpoint não revela se um canal existe.

---

## Eventos e sincronização

### Parte 22 - Processamento dos eventos da Evolution

**Objetivo:** Processar de forma explícita os eventos de QR, conexão, mensagens e status enviados pela Evolution.

#### Principais entregas

- Tratar `QRCODE_UPDATED` para disponibilizar QR temporário e marcar `WAITING_QR`.
- Tratar `CONNECTION_UPDATE` para atualizar `CONNECTED`, `DISCONNECTED`, `RECONNECTING` ou `ERROR`.
- Tratar `MESSAGES_UPSERT` para criar `Contact`, `Conversation` e `Message` inbound no Workspace do canal.
- Tratar `MESSAGES_UPDATE` e `SEND_MESSAGE_UPDATE` para atualizar `SENT`, `DELIVERED`, `READ` e `FAILED`.
- Usar `external_id` e constraints para evitar duplicidade.
- Não armazenar payload bruto, QR permanente ou dados sensíveis desnecessários.

#### Critérios de conclusão

- Cada evento possui handler testado.
- Mensagens duplicadas não criam registros duplicados.
- Estados de conexão e delivery são consistentes.
- Eventos desconhecidos são ignorados com segurança.

---

## API de conexão

### Parte 23 - API de QR Code e estado de conexão

**Objetivo:** Expor QR Code, status e dados seguros do canal para o frontend.

#### Principais entregas

- Criar endpoints de list, detail, QR e status para canais do Workspace.
- Retornar somente campos públicos: `id`, nome, `provider`, `status`, telefone mascarado, `has_qr_code` e timestamps.
- QR disponível somente para owner/admin e com expiração curta.
- Não retornar `instance_token`, `webhook_secret`, API key global ou `instance_name` técnico sem necessidade.
- Possibilitar polling ou atualização em tempo real do status.

#### Critérios de conclusão

- Agent não acessa QR.
- QR não aparece em logs nem `localStorage`.
- Canal de outro Workspace retorna 403/404.
- Resposta não contém segredos.

---

## Experiência do usuário

### Parte 24 - Frontend de conexão do WhatsApp

**Objetivo:** Criar a interface onde o cliente conecta e gerencia o WhatsApp dentro do SilverTech.

#### Principais entregas

- Criar rota `/workspaces/:workspaceId/settings/channels` ou `/settings/whatsapp`.
- Exibir lista de canais, status, número mascarado e ações permitidas.
- Adicionar botão **Conectar WhatsApp** e modal/card com QR Code e instruções.
- Exibir estados: preparando, aguardando QR, conectando, conectado, reconectando, desconectado e erro.
- Adicionar ações de atualizar QR, reiniciar, desconectar e remover.
- Frontend chama apenas a API SilverTech; nunca chama a Evolution diretamente.

#### Critérios de conclusão

- Cliente conecta o número sem conhecer UUID, webhook ou painel Evolution.
- QR é limpo da memória quando modal fecha ou expira.
- Erros são sanitizados.
- Componentes possuem testes de loading, erro e permissões.

---

## Roteamento por canal

### Parte 25 - Roteamento inbound por WhatsAppChannel

**Objetivo:** Garantir que toda mensagem inbound seja criada no tenant e no canal corretos.

#### Principais entregas

- Fluxo: `webhook_public_id -> WhatsAppChannel -> Workspace -> Contact -> Conversation -> Message`.
- Contato deve pertencer à Workspace do canal.
- `Conversation` deve pertencer ao mesmo Workspace e registrar o `WhatsAppChannel`.
- O mesmo telefone pode existir em Workspaces diferentes sem colisão.
- Definir regra para um mesmo contato usando mais de um número/canal dentro da mesma Workspace.
- Preservar o agendamento automático da IA após o commit da mensagem.

#### Critérios de conclusão

- Inbound da Clínica A nunca aparece na Loja B.
- Search e filtros continuam escopados por Workspace.
- Contato/conversa não podem usar canal de outro tenant.
- Fluxo IA continua funcional.

### Parte 26 - Roteamento outbound por WhatsAppChannel

**Objetivo:** Enviar cada resposta pela instância Evolution associada ao canal da conversa.

#### Principais entregas

- Alterar `send_whatsapp_message` para receber o canal ou resolver o canal pela `Conversation`.
- Usar `channel.instance_name` e credenciais apropriadas ao chamar `EvolutionClient.send_text`.
- Validar canal `CONNECTED`, `Message OUTBOUND/PENDING` e consistência de Workspace.
- Retry deve reutilizar a mesma `Message` e o mesmo canal.
- Falha de delivery não deve regenerar a resposta de IA.
- Impedir envio pela instância de outro tenant mesmo com IDs manipulados.

#### Critérios de conclusão

- Clínica A sempre envia pelo WhatsApp da Clínica A.
- Retry não troca canal.
- Mensagens não são duplicadas.
- Códigos de erro continuam sanitizados e observáveis.

---

## Operação e suporte

### Parte 27 - Compatibilidade com Django Admin e testes manuais

**Objetivo:** Preservar inspeção técnica pelo Django Admin e os testes manuais já usados durante o desenvolvimento.

#### Principais entregas

- Registrar `WhatsAppChannel` no admin com Workspace, `provider`, instância, status, telefone mascarado e timestamps.
- Não mostrar API key, `instance_token`, `webhook_secret`, QR Code ou payload bruto.
- Manter visualização de `Contact`, `Conversation`, `Message`, `AIProcessingRun` e `AIObservabilityEvent`.
- Preservar endpoint `/api/omnichannel/conversations/{id}/reply/` para envio manual.
- Criar, se desejado, ação segura no admin que agenda o envio em vez de apenas criar uma linha no banco.
- Documentar como criar Workspace + Member OWNER + canal para testes.

#### Critérios de conclusão

- Mensagens continuam visíveis no Django Admin.
- Envio pelo endpoint `/reply/` continua funcionando.
- Criar `Message` manualmente não envia sem passar pelo fluxo controlado.
- Admin não expõe segredos.

---

## Onboarding SaaS

### Parte 28 - Criação automática de Workspace no cadastro

**Objetivo:** Criar automaticamente a estrutura mínima do tenant quando um cliente abre uma conta.

#### Principais entregas

- No cadastro, criar `User`, `Workspace` e `Member` com role `OWNER` em uma única transação.
- Solicitar nome do usuário, nome da empresa, e-mail e senha.
- Gerar slug único e garantir que nenhuma Workspace seja criada sem OWNER.
- Não provisionar instância Evolution automaticamente no cadastro.
- Criar a instância apenas quando o owner clicar em **Conectar WhatsApp**.
- Permitir que superuser continue criando Workspaces manualmente pelo admin para suporte/testes.

#### Critérios de conclusão

- Cadastro concluído sempre resulta em tenant válido.
- Falha em qualquer etapa desfaz toda a transação.
- Usuário inicial vira OWNER.
- Workspace manual do admin também pode conectar canal posteriormente.

---

## Controle de acesso

### Parte 29 - RBAC dos canais

**Objetivo:** Definir quem pode conectar, visualizar QR e administrar canais.

#### Principais entregas

- OWNER: criar, consultar, reiniciar, desconectar e remover canais.
- ADMIN: mesmas ações, caso a política do produto permita.
- AGENT: utilizar conversas e responder clientes, sem gerenciar conexão ou segredos.
- SUPERUSER: diagnóstico interno no Django Admin, sem exibir credenciais em texto puro.
- Aplicar permissões no backend; esconder botões no frontend é apenas conveniência visual.
- Retornar 403/404 sem revelar objetos de outro tenant.

#### Critérios de conclusão

- Agent não acessa QR nem ações administrativas.
- Owner/admin atuam apenas no próprio Workspace.
- Testes cobrem todos os endpoints e roles.
- Superuser tem comportamento explícito e documentado.

---

## Ciclo de vida

### Parte 30 - Desconectar, reconectar e excluir canal

**Objetivo:** Permitir recuperar, pausar e remover conexões sem perder o histórico do CRM.

#### Principais entregas

- Criar endpoints `restart`, `disconnect`, `refresh-qr` e `delete/archive`.
- Restart reinicia a instância sem remover configuração.
- Disconnect faz logout e marca o canal como desconectado.
- Refresh QR solicita novo QR para instância desconectada.
- Delete remove a instância remota e arquiva o canal local.
- Preservar conversas e mensagens; preferir soft delete/arquivamento.
- Tratar falha remota com estados intermediários e reconciliação.

#### Critérios de conclusão

- Nenhuma ação apaga histórico.
- Delete parcial não deixa canal em estado enganoso.
- Ações são idempotentes quando possível.
- Somente owner/admin pode executar.

---

## Operação e métricas

### Parte 31 - Observabilidade dos canais

**Objetivo:** Adicionar observabilidade específica para provisionamento, conexão e tráfego de canais.

#### Principais entregas

- Registrar eventos de canal criado, instância provisionada, webhook configurado, QR gerado, conectado, desconectado, reconectando, erro e removido.
- Registrar inbound recebido e outbound enviado por canal sem armazenar body ou telefone completo.
- Adicionar métricas: canais conectados, desconectados, falhas de provisionamento, tempo até conexão, volume inbound/outbound e falhas de envio.
- Integrar ao painel de observabilidade por Workspace.
- Definir retenção futura para eventos de alto volume.

#### Critérios de conclusão

- Eventos sempre carregam workspace/canal corretos.
- Nenhum QR, segredo, payload bruto ou telefone completo é armazenado.
- Falha da observabilidade não quebra o fluxo principal.
- Painel não agrega dados de outro tenant.

---

## Segurança e isolamento

### Parte 32 - Segurança multi-tenant dos canais

**Objetivo:** Cobrir o novo domínio de canais contra IDOR/BOLA, spoofing de webhook e vínculos cross-tenant.

#### Principais entregas

- Testar Workspace A tentando acessar canal do Workspace B.
- Testar owner/admin/agent/não membro em todas as ações.
- Testar webhook com segredo incorreto, canal inexistente e payload malicioso.
- Testar `Conversation`/`Message` usando canal de outro tenant.
- Testar envio tentando usar `instance_name` ou `channel_id` de outro Workspace.
- Testar que QR, `webhook_secret`, token e API key não aparecem em response, log, admin ou frontend.
- Mockar todas as chamadas externas.

#### Critérios de conclusão

- ID válido de outro tenant não produz vazamento nem side effect.
- Webhook sem segredo válido é rejeitado.
- Nenhum teste chama Evolution real.
- Suíte completa permanece verde.

---

## Qualidade de integração

### Parte 33 - Testes de integração com Evolution simulada

**Objetivo:** Validar o fluxo completo usando mocks ou uma Evolution fake, sem depender de serviço externo real.

#### Principais entregas

- Testar criar canal -> criar instância -> configurar webhook -> receber QR -> conectar -> receber mensagem -> enviar resposta -> atualizar status.
- Simular Evolution offline, timeout, 401/403, instância duplicada e resposta inválida.
- Simular QR expirado, desconexão durante envio, falha de delete e retry do provisionamento.
- Validar idempotência e compensação de falhas parciais.
- Validar que OpenAI/Evolution reais não são chamadas na suíte.

#### Critérios de conclusão

- Fluxo feliz e principais falhas possuem teste.
- Testes são determinísticos.
- Nenhum recurso externo é obrigatório.
- Cobertura protege regressões do onboarding e roteamento.

---

## Ambiente local

### Parte 34 - Configuração de desenvolvimento local

**Objetivo:** Manter o desenvolvimento local simples e documentar como a Evolution alcança o Django em diferentes topologias.

#### Principais entregas

- Adicionar `EVOLUTION_API_URL`, `EVOLUTION_API_KEY`, `SILVERTECH_PUBLIC_URL` e nome do header do webhook.
- Documentar tudo em Docker Compose: Evolution usa `http://backend:8000`.
- Documentar Evolution em Docker e Django no Windows: usar `http://host.docker.internal:8000`.
- Documentar Evolution remota e Django local: usar túnel HTTPS temporário.
- Documentar comandos para Django, Redis, Celery, frontend e Evolution.
- Documentar teste completo com QR, mensagem inbound, reply e inspeção no admin.

#### Critérios de conclusão

- Desenvolvedor consegue reproduzir o fluxo local.
- Não é obrigatório deploy quando os serviços compartilham rede.
- Túnel é usado apenas quando a Evolution remota precisa acessar localhost.
- README contém troubleshooting básico.

---

## Produção

### Parte 35 - Configuração de produção

**Objetivo:** Preparar a infraestrutura para conexões reais com URL pública estável, segurança e operação contínua.

#### Principais entregas

- Configurar domínio HTTPS para backend e frontend.
- Fixar uma versão validada da Evolution em vez de usar `latest` indiscriminadamente.
- Armazenar API keys e encryption keys em secret manager ou variáveis protegidas.
- Executar PostgreSQL, Redis, Celery worker, backups e health checks.
- Configurar `ALLOWED_HOSTS`, CORS, rate limits, timeouts e retry.
- Rotacionar webhook secrets e criar reconciliação periódica de estado das instâncias.
- Monitorar filas, falhas de webhook, conexões e delivery.

#### Critérios de conclusão

- Evolution alcança a URL pública do webhook.
- Secrets não estão versionados.
- Backups e health checks estão ativos.
- Deploy suporta reinício sem perder estado.

---

## Finalização da migração

### Parte 36 - Remoção do fluxo legado

**Objetivo:** Remover o fluxo legado somente após comprovar que todos os tenants usam `WhatsAppChannel`.

#### Principais entregas

- Remover `?workspace=UUID` do webhook.
- Remover dependência funcional de `EVOLUTION_INSTANCE_NAME`.
- Remover código antigo de instância global.
- Rejeitar webhooks legados após período de transição.
- Atualizar testes, documentação, variáveis de ambiente e deploy.
- Confirmar que nenhuma `Conversation` ativa está sem canal.
- Usar feature flag durante a transição e executar checklist de rollback.

#### Critérios de conclusão

- Todos os canais funcionam pelo modelo novo.
- Nenhuma conversa ativa depende do legado.
- Suíte completa e testes manuais ficam verdes.
- Documentação não orienta mais copiar UUID para webhook.

---

## Apêndice A - Como ficará o teste local

**Sem deploy obrigatório:** O fluxo pode ser testado localmente desde que a Evolution consiga alcançar o backend Django pela mesma rede, pelo Docker Compose ou por `host.docker.internal`. Quando a Evolution estiver em servidor remoto, use uma URL pública temporária de túnel.

1. Iniciar PostgreSQL, Redis, Django, Celery, frontend e Evolution.
2. Criar uma Workspace pelo cadastro real ou pelo Django Admin.
3. Criar/associar um Member OWNER à Workspace.
4. Abrir **Configurações > WhatsApp** e clicar em **Conectar**.
5. Escanear o QR Code exibido no SilverTech.
6. Enviar uma mensagem de outro WhatsApp para o número conectado.
7. Confirmar `Contact`, `Conversation` e `Message` no Django Admin.
8. Responder pelo frontend ou pelo endpoint `/api/omnichannel/conversations/{id}/reply/`.
9. Confirmar a mensagem recebida no WhatsApp e os eventos de observabilidade.

### Django Admin continuará útil

O admin continuará exibindo conversas, mensagens, status, tentativas, runs de IA e eventos de observabilidade. Criar uma linha `Message` manualmente não deve ser o mecanismo principal de envio; o envio deve passar pelo endpoint/task controlado para aplicar canal, status, retry e segurança.

---

## Apêndice B - Matriz de responsabilidades

| Ação | OWNER | ADMIN | AGENT | SUPERUSER |
|---|---|---|---|---|
| Criar Workspace | Cadastro inicial / permitido | Normalmente não | Não | Sim, suporte |
| Criar canal WhatsApp | Sim | Conforme política | Não | Diagnóstico |
| Visualizar QR | Sim | Conforme política | Não | Não expor segredo |
| Reiniciar/desconectar | Sim | Conforme política | Não | Suporte controlado |
| Responder conversas | Sim | Sim | Sim | Técnico |
| Configurar IA | Sim | Sim | Não | Diagnóstico |
| Ver observabilidade | Sim | Sim | Não | Sim |
| Ver segredos em texto puro | Não | Não | Não | Não |

---

## Apêndice C - Configuração de infraestrutura

```dotenv
EVOLUTION_API_URL=https://evolution.exemplo.com
EVOLUTION_API_KEY=<segredo-global-do-backend>
SILVERTECH_PUBLIC_URL=https://api.exemplo.com
EVOLUTION_WEBHOOK_HEADER_NAME=X-SilverTech-Webhook-Secret
```

- A API key global pertence ao backend SilverTech e nunca ao cliente final.
- Cada canal possui identificador público e segredo de webhook próprios.
- O QR Code é temporário e não deve ser persistido permanentemente.
- Em produção, o backend precisa de URL HTTPS pública estável.
- Em ambiente local compartilhando rede/Docker, uma URL pública externa pode ser desnecessária.

---

## Checklist de conclusão da atualização

- [ ] Workspace e OWNER são criados automaticamente no cadastro real.
- [ ] `WhatsAppChannel` existe e isola cada conexão por tenant.
- [ ] `EvolutionClient` centraliza todas as chamadas externas.
- [ ] Owner/admin conecta WhatsApp pelo painel do SilverTech.
- [ ] Instância, webhook e QR são provisionados automaticamente.
- [ ] Webhook valida segredo e resolve Workspace pelo canal.
- [ ] Inbound e outbound utilizam o `WhatsAppChannel` correto.
- [ ] `Conversation` e `Message` permanecem visíveis no Django Admin.
- [ ] Testes locais continuam possíveis sem deploy quando a rede permite.
- [ ] Agent não administra canais, QR ou credenciais.
- [ ] Restart, disconnect, refresh QR e remoção são seguros.
- [ ] Observabilidade registra conexão e tráfego sem conteúdo sensível.
- [ ] Testes cobrem multi-tenancy, IDOR/BOLA, spoofing e falhas externas.
- [ ] A produção usa HTTPS, secrets protegidos, backups e health checks.
- [ ] O fluxo legado com `?workspace=UUID` e instância global foi removido com segurança.

### Estado final do produto

O SilverTech passa a oferecer onboarding de WhatsApp self-service por tenant: o cliente cria a conta, conecta o número por QR dentro do produto, recebe e envia mensagens pela instância correta, configura IA por Workspace e mantém histórico, segurança, retry, observabilidade e suporte técnico pelo Django Admin.
