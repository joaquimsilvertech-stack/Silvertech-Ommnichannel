from django.contrib import admin

from .models import Conversation, Message


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
    readonly_fields = ('id', 'created_at', 'updated_at')
    fields = ('direction', 'status', 'body', 'created_at')


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'direction', 'status', 'created_at')
    list_filter = ('direction', 'status', 'created_at')
    search_fields = ('body', 'conversation__contact__name')
    list_select_related = ('conversation', 'conversation__contact')
    readonly_fields = ('id', 'created_at', 'updated_at')


ConversationAdmin.inlines = [MessageInline]
