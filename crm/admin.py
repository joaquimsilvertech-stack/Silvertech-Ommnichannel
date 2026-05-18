from django.contrib import admin

from .models import Contact, Lead, Organization


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'workspace', 'starred', 'created_at')
    list_filter = ('workspace', 'starred', 'created_at')
    search_fields = ('name', 'email', 'phone')


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('contact', 'status', 'score', 'assigned_to', 'created_at')
    list_filter = ('status', 'assigned_to', 'created_at')
    search_fields = ('contact__name', 'contact__email')


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'workspace', 'created_at')
    list_filter = ('workspace',)
    search_fields = ('name',)
