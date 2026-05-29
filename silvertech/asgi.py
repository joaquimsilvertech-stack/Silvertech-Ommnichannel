"""
ASGI config for silvertech project.
HTTP: API REST, Django Admin e SSE (django-eventstream) gerenciados via Django ASGI.
"""
import os
from channels.routing import ProtocolTypeRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'silvertech.settings')


django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    
    'http': django_asgi_app,
})