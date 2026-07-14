from django.contrib import admin

from .models import AIObservabilityEvent, AIProcessingRun, Conversation, Message


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('contact', 'workspace', 'channel', 'status', 'created_at')
    list_filter = ('status', 'channel', 'workspace', 'created_at')
    search_fields = ('contact__name', 'contact__email', 'contact__phone')
    list_select_related = ('contact', 'workspace')
    readonly_fields = ('id', 'created_at', 'updated_at')


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = (
        'id',
        'send_attempt_count',
        'send_error_code',
        'last_send_attempt_at',
        'next_send_retry_at',
        'created_at',
        'updated_at',
    )
    fields = (
        'direction',
        'status',
        'send_attempt_count',
        'send_error_code',
        'last_send_attempt_at',
        'next_send_retry_at',
        'body',
        'created_at',
    )


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        'conversation',
        'direction',
        'status',
        'send_attempt_count',
        'send_error_code',
        'created_at',
    )
    list_filter = ('direction', 'status', 'created_at')
    search_fields = ('body', 'conversation__contact__name')
    list_select_related = ('conversation', 'conversation__contact')
    readonly_fields = (
        'id',
        'send_attempt_count',
        'send_error_code',
        'last_send_attempt_at',
        'next_send_retry_at',
        'created_at',
        'updated_at',
    )


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
