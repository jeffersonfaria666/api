"""
CONFIGURACIÓN GUNICORN PARA RENDER.COM - CORREGIDA
"""

import os
import multiprocessing

# Configuración básica
bind = "0.0.0.0:" + str(os.environ.get("PORT", "10000"))
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE", "5"))

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")

# Worker class
worker_class = "sync"

# Max requests (para prevenir fugas de memoria)
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "50"))

# Configuración adicional para Render
preload_app = True
reload = os.environ.get("GUNICORN_RELOAD", "False").lower() == "true"
