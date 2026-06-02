"""
Instância Celery do projeto SilverTech.

Carregada via silvertech/__init__.py para autodiscover de tasks nos apps Django.
"""
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'silvertech.settings')

app = Celery('silvertech')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
