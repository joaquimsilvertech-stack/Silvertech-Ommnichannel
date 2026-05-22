from rest_framework.pagination import CursorPagination


class CRMCursorPagination(CursorPagination):
    page_size = 20
    ordering = '-created_at'
