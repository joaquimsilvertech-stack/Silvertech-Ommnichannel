"""
ASGI config for silvertech project.
HTTP: API REST, Django Admin e SSE gerenciados via Django ASGI com suporte a Static Files.
"""
import os
from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler  # <-- IMPORTANTE
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'silvertech.settings')

# Inicializa o app ASGI nativo do Django
django_asgi_app = get_asgi_application()

# Se estiver em modo de desenvolvimento (DEBUG = True), intercepta e serve os arquivos estáticos
if settings.DEBUG:
    django_asgi_app = ASGIStaticFilesHandler(django_asgi_app)

application = ProtocolTypeRouter({
    # Agora o Django resolve o HTTP comum e também entrega os CSS/JS do Admin
    'http': django_asgi_app,
})