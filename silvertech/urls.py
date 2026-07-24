"""
URL configuration for silvertech project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.conf import settings
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from core.auth_views import RegisterView


class ThrottledTokenObtainPairView(TokenObtainPairView):
    throttle_scope = 'auth'


class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_scope = 'auth'


urlpatterns = [
    path('admin/', admin.site.urls),
    # Documentação da API (Swagger UI)
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    # Cadastro self-service: cria User + Workspace + Member OWNER atomicamente.
    path('api/auth/register/', RegisterView.as_view(), name='auth-register'),
    # Autenticação JWT (par access + refresh) para consumo pela API REST.
    path('api/auth/token/', ThrottledTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', ThrottledTokenRefreshView.as_view(), name='token_refresh'),
    path('api/', include('core.urls')),
    path('api/crm/', include('crm.urls')),
    path('api/workspaces/', include('workspaces.urls')),
    path('api/omnichannel/', include('omnichannel.urls')),
    path('api/tickets/', include('tickets.urls')),
    path('api/automations/', include('automations.urls')),
]

if settings.DEBUG:
    # Serve /static/ via finders sob ASGI/uvicorn (o auto-serving do runserver não
    # existe aqui). Necessário para os assets locais do Swagger UI (sidecar) e para
    # o CSS/JS do Django Debug Toolbar. Produção é assunto separado (WhiteNoise/nginx).
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += [
        path('__debug__/', include('debug_toolbar.urls')),
    ]
