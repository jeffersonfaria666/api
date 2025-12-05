# Configuración de Gunicorn para Render
import multiprocessing

# Configuración básica
bind = "0.0.0.0:" + str(int(os.environ.get("PORT", 10000)))
workers = 2
threads = 4
timeout = 300
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Worker class
worker_class = "sync"

# Max requests
max_requests = 1000
max_requests_jitter = 50
