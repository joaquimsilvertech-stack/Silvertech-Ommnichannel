from django.contrib import admin

from .models import Flow


@admin.register(Flow)
class FlowAdmin(admin.ModelAdmin):
    list_display = ('name', 'workspace', 'is_active', 'created_at')
    list_filter = ('is_active', 'workspace')
    search_fields = ('name', 'workspace__name')
    autocomplete_fields = ('workspace',)
