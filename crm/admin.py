from django.contrib import admin

from .models import Contact, Lead


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('name', 'workspace', 'email', 'phone', 'contact_type')
    list_filter = ('contact_type', 'workspace')
    search_fields = ('name', 'email', 'phone')


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('id', 'contact', 'status', 'score', 'source')
    list_filter = ('status', 'source')
    search_fields = ('contact__name', 'contact__email')
