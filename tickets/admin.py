from django.contrib import admin

from .models import Ticket


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('title', 'workspace', 'status', 'assigned_to', 'due_at', 'created_at')
    list_filter = ('status', 'workspace', 'assigned_to')
    search_fields = ('title', 'contact__name', 'contact__phone', 'assigned_to__email')
    autocomplete_fields = ('workspace', 'contact', 'conversation', 'assigned_to')
