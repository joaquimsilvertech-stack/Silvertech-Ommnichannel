from django.contrib import admin

from .models import (
    AIObservabilityEvent,
    AIProcessingRun,
    Conversation,
    EvolutionWebhookEvent,
    Message,
    WhatsAppChannel,
)
from .whatsapp_channel_read_service import mask_whatsapp_phone_number

_EMPTY_DISPLAY = '—'


@admin.register(WhatsAppChannel)
class WhatsAppChannelAdmin(admin.ModelAdmin):
    """Inspecao tecnica do canal, sem expor credencial, telefone completo ou QR."""

    list_display = (
        'name',
        'workspace',
        'provider',
        'instance_name',
        'status',
        'masked_phone_number',
        'connected_at',
        'last_connection_update_at',
        'created_at',
    )
    list_filter = ('provider', 'status', 'workspace', 'created_at', 'connected_at')
    search_fields = ('name', 'workspace__name', 'workspace__slug', 'instance_name')
    list_select_related = ('workspace',)
    ordering = ('workspace', 'name')
    fieldsets = (
        (
            'Identificacao',
            {'fields': ('id', 'workspace', 'name', 'provider', 'instance_name')},
        ),
        (
            'Conexao',
            {
                'fields': (
                    'status',
                    'masked_phone_number',
                    'connected_at',
                    'last_connection_update_at',
                    'last_error_code',
                ),
            },
        ),
        ('Webhook tecnico', {'fields': ('webhook_public_id',)}),
        ('Auditoria', {'fields': ('created_at', 'updated_at')}),
    )
    readonly_fields = (
        'id',
        'workspace',
        'name',
        'provider',
        'instance_name',
        'status',
        'masked_phone_number',
        'connected_at',
        'last_connection_update_at',
        'last_error_code',
        'webhook_public_id',
        'created_at',
        'updated_at',
    )

    @admin.display(description='Telefone')
    def masked_phone_number(self, obj):
        return mask_whatsapp_phone_number(obj.phone_number) or _EMPTY_DISPLAY

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj)


@admin.register(EvolutionWebhookEvent)
class EvolutionWebhookEventAdmin(admin.ModelAdmin):
    """Recibo tecnico do webhook para diagnostico, sem payload nem identificador de contato."""

    list_display = (
        'created_at',
        'workspace',
        'whatsapp_channel',
        'event_type',
        'status',
        'attempt_count',
        'error_code',
        'started_at',
        'finished_at',
    )
    list_filter = (
        'status',
        'event_type',
        'whatsapp_channel__workspace',
        'whatsapp_channel',
        'created_at',
    )
    search_fields = (
        'event_type',
        'error_code',
        'whatsapp_channel__name',
        'whatsapp_channel__workspace__name',
        'whatsapp_channel__workspace__slug',
    )
    list_select_related = ('whatsapp_channel', 'whatsapp_channel__workspace')
    fields = (
        'id',
        'whatsapp_channel',
        'event_type',
        'status',
        'attempt_count',
        'error_code',
        'started_at',
        'finished_at',
        'created_at',
        'updated_at',
    )
    readonly_fields = fields

    @admin.display(description='Workspace')
    def workspace(self, obj):
        return obj.whatsapp_channel.workspace

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = (
        'contact',
        'workspace',
        'channel',
        'whatsapp_channel_display',
        'status',
        'created_at',
    )
    list_filter = (
        'workspace',
        'channel',
        'whatsapp_channel',
        'status',
        'is_human_handoff',
        'created_at',
    )
    search_fields = ('contact__name', 'contact__email', 'contact__phone')
    list_select_related = ('contact', 'workspace', 'whatsapp_channel')
    readonly_fields = (
        'id',
        'workspace',
        'contact',
        'channel',
        'whatsapp_channel',
        'created_at',
        'updated_at',
    )

    @admin.display(description='Canal WhatsApp', ordering='whatsapp_channel')
    def whatsapp_channel_display(self, obj):
        if obj.whatsapp_channel_id is None:
            return 'Sem canal (legado)'
        return obj.whatsapp_channel


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    can_delete = False
    show_change_link = False
    fields = (
        'id',
        'direction',
        'status',
        'send_attempt_count',
        'send_error_code',
        'last_send_attempt_at',
        'next_send_retry_at',
        'body',
        'created_at',
        'updated_at',
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    """Inspecao somente leitura. O envio manual e exclusivo de POST /reply/."""

    list_display = (
        'conversation',
        'message_workspace',
        'message_whatsapp_channel',
        'direction',
        'status',
        'send_attempt_count',
        'send_error_code',
        'created_at',
    )
    list_filter = (
        'direction',
        'status',
        'conversation__workspace',
        'conversation__whatsapp_channel',
        'created_at',
    )
    search_fields = ('conversation__contact__name',)
    list_select_related = (
        'conversation',
        'conversation__contact',
        'conversation__workspace',
        'conversation__whatsapp_channel',
    )
    fields = (
        'id',
        'conversation',
        'direction',
        'status',
        'send_attempt_count',
        'send_error_code',
        'last_send_attempt_at',
        'next_send_retry_at',
        'body',
        'created_at',
        'updated_at',
    )
    readonly_fields = fields

    @admin.display(description='Workspace')
    def message_workspace(self, obj):
        return obj.conversation.workspace

    @admin.display(description='Canal WhatsApp')
    def message_whatsapp_channel(self, obj):
        if obj.conversation.whatsapp_channel_id is None:
            return 'Sem canal (legado)'
        return obj.conversation.whatsapp_channel

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AIProcessingRun)
class AIProcessingRunAdmin(admin.ModelAdmin):
    list_display = (
        'workspace',
        'conversation',
        'source_message',
        'status',
        'attempt_count',
        'created_at',
    )
    list_filter = ('status', 'workspace', 'created_at')
    list_select_related = (
        'workspace',
        'conversation',
        'source_message',
        'provider_config',
        'output_message',
    )
    readonly_fields = (
        'id',
        'workspace',
        'conversation',
        'source_message',
        'provider_config',
        'output_message',
        'status',
        'attempt_count',
        'error_code',
        'last_error_code',
        'last_attempt_at',
        'next_retry_at',
        'started_at',
        'finished_at',
        'created_at',
        'updated_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AIObservabilityEvent)
class AIObservabilityEventAdmin(admin.ModelAdmin):
    list_display = (
        'created_at',
        'workspace',
        'event_type',
        'status',
        'provider',
        'model_name',
        'error_code',
        'latency_ms',
        'attempt_count',
    )
    list_filter = ('event_type', 'status', 'provider', 'error_code', 'created_at')
    search_fields = ('workspace__name', 'provider', 'model_name', 'event_type', 'error_code')
    list_select_related = ('workspace', 'provider_config', 'conversation')
    readonly_fields = (
        'id',
        'workspace',
        'provider_config',
        'conversation',
        'source_message',
        'output_message',
        'ai_processing_run',
        'whatsapp_channel',
        'whatsapp_channel_id_snapshot',
        'event_type',
        'status',
        'provider',
        'model_name',
        'reason_code',
        'error_code',
        'latency_ms',
        'attempt_count',
        'metadata',
        'created_at',
        'updated_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False


ConversationAdmin.inlines = [MessageInline]
