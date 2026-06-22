📘 Runbook: Queda e Reconexão de Sessão do WhatsApp (Evolution API)
Visão Geral
Este documento descreve o procedimento operacional padrão (SOP) para reestabelecer a conexão do WhatsApp com o CRM Silvertech caso a sessão expire, o aparelho seja desconectado remotamente ou perca a sincronia.

🚨 Sintomas de Queda

O sistema para de receber novas mensagens de clientes (Inbound falhando).

Mensagens enviadas pelo painel do CRM não chegam ao destino (Outbound falhando).

O terminal do backend (Django/Celery) exibe logs de erro em connection.update informando status close ou connecting travado.

🛡️ Impacto nos Dados

Risco de perda de dados históricos: ZERO. Todo o histórico de conversas e contatos fica salvo no PostgreSQL do nosso back-end.

O servidor Django não precisa ser reiniciado.

O Docker Compose não precisa ser derrubado.

🛠️ Passo a Passo para Reconexão
Passo 1: Acessar o Gerenciador da Evolution API

Acesse o painel visual (Evolution Manager) ou a interface do Swagger local apontando para a porta 8080.

Localize a instância atual de produção (ex: silvertech_whatsapp).

Passo 2: Limpar a Sessão "Morta" (CRÍTICO)

Não delete a instância! Se você deletar, perderemos a configuração do Webhook.

Clique no botão de Desconectar / Logout na instância.

Por que fazer isso? Isso obriga o container do Docker a apagar os tokens criptografados antigos e corrompidos que ficaram salvos na pasta /evolution_store. A instância voltará para o estado "em branco".

Passo 3: Gerar e Ler o Novo QR Code

Com a instância limpa, clique no botão para Gerar QR Code (Connect).

Pegue o aparelho celular dedicado ao CRM.

Abra o WhatsApp > Configurações > Aparelhos Conectados > Conectar um Aparelho.

Aponte a câmera para a tela e escaneie o código.

Passo 4: Validação (Health Check)

Aguarde alguns segundos. O status da instância no Manager deve mudar para open ou connected.

Faça um teste de ponta a ponta (E2E):

Mande uma mensagem do seu celular pessoal para o número do CRM.

Verifique se ela aparece imediatamente na aba de Mensagens do Django Admin.

💡 Dica de Ouro: Se a empresa decidir trocar o "Chip" (número de telefone) no futuro, o procedimento é exatamente este. Basta deslogar o chip antigo e ler o QR Code com o chip novo. O nosso código entende a troca instantaneamen