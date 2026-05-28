"""
ASGI config for silvertech project.
HTTP: API REST, Django Admin e SSE (django-eventstream) gerenciados via Django ASGI.
"""
import os
from channels.routing import ProtocolTypeRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'silvertech.settings')

# Inicializa o app ASGI do Django para carregar as rotas do urls.py
django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    # Deixa o próprio Django resolver todo o ecossistema HTTP (incluindo /admin e as APIs)
    'http': django_asgi_app,
})