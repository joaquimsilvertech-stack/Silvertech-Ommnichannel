## 📝 O que foi feito
- Implementação do endpoint de Timeline mockada no `ContactViewSet` (`GET /api/crm/contacts/{id}/timeline/`).
- O endpoint retorna uma lista cronológica fictícia de eventos (mensagens, mudanças de status e notas) para liberar o desenvolvimento do Front-end antes da conclusão do app Omnichannel.
- Fechamento oficial do Card #019-N e conclusão da Sprint 2.

## 🏗️ App Django afetado
- [ ] `core`
- [ ] `workspaces`
- [x] `crm`
- [ ] `omnichannel`
- [ ] `automations`
- [ ] Outro / Configurações globais

## 🔄 Tipo de mudança
- [ ] 🐛 Bug fix (correção de erro)
- [x] ✨ Nova feature (nova funcionalidade / mock preparatório)
- [ ] ♻️ Refactor (melhoria de código/performance)
- [ ] 🗄️ Migration (alteração estrutural no banco de dados)
- [ ] 🔒 Segurança (CORS, JWT, permissões)

## ✅ Checklist obrigatório (Qualidade Sênior)
- [x] A Migration foi criada com nome descritivo (Não aplicável nesta PR, apenas lógica de View)
- [x] O Serializer possui validação adequada para os dados de entrada
- [x] O Queryset possui filtro de `workspace` (Garantia de isolamento Multi-tenant / herdado via Mixin)
- [x] Foram usados `select_related` ou `prefetch_related` onde necessário 
- [x] O código não possui `print()` soltos ou comentários de debug esquecidos