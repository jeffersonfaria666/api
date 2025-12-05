#!/usr/bin/env python3
"""
🚀 YOUTUBE/TIKTOK SERVER API - OPTIMIZADO PARA RENDER.COM
Versión: Render Ready 1.0
"""

import os
import sys
import json
import logging
import random
import time
import queue
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask, request, jsonify, send_file, Response, send_from_directory
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import yt_dlp
from werkzeug.middleware.proxy_fix import ProxyFix
from cachetools import TTLCache

# ==============================
# CONFIGURACIÓN PARA RENDER
# ==============================
class Config:
    # Configuración de Render
    PORT = int(os.environ.get('PORT', 10000))  # Render usa PORT automáticamente
    HOST = '0.0.0.0'
    DEBUG = os.environ.get('RENDER', 'False').lower() == 'false'  # False en producción
    
    # Directorio temporal (en Render usar /tmp/)
    TEMP_DIR = os.environ.get('TEMP_DIR', '/tmp/downloads')
    MAX_TEMP_FILES = int(os.environ.get('MAX_TEMP_FILES', 50))  # Menos archivos en Render
    MAX_FILE_SIZE = int(os.environ.get('MAX_FILE_SIZE', 500 * 1024 * 1024))  # 500MB para Render
    
    # Sistema de colas (optimizado para recursos limitados)
    MAX_WORKERS = int(os.environ.get('MAX_WORKERS', 2))  # Menos workers en free tier
    QUEUE_TIMEOUT = 180  # 3 minutos
    DOWNLOAD_TIMEOUT = 180  # 3 minutos
    
    # Cache
    INFO_CACHE_TTL = 180  # 3 minutos
    INFO_CACHE_MAXSIZE = 100
    
    # Rate limiting (más estricto en Render)
    RATE_LIMIT = os.environ.get('RATE_LIMIT', '30 per minute')
    
    # User-Agents
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ]

# ==============================
# SETUP DE LOGGING
# ==============================
def setup_logging():
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format))
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    
    return root_logger

logger = setup_logging()

# ==============================
# CLASE DE DESCARGA SIMPLIFICADA
# ==============================
class RenderDownloader:
    """Descargador optimizado para Render"""
    
    def __init__(self, url, download_type="best"):
        self.url = url
        self.download_type = download_type
        self.request_id = f"dl_{int(time.time())}_{random.randint(1000, 9999)}"
        self.temp_dir = Config.TEMP_DIR
        self.base_filename = f"render_{self.request_id}"
        
        # Crear directorio temporal si no existe
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Estado
        self.status = "pending"
        self.progress = 0
        self.error = None
        self.filename = None
        self.filepath = None
        
        logger.info(f"RenderDownloader creado para: {url[:50]}...")
    
    def sanitize_filename(self, filename):
        """Limpia nombre de archivo"""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename[:100]
    
    def get_video_info(self):
        """Obtiene información del video (con timeout)"""
        try:
            # Configuración rápida para info
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'socket_timeout': 15,
                'retries': 3,
                'ignoreerrors': True,
                'extract_flat': False,
                'http_headers': {
                    'User-Agent': random.choice(Config.USER_AGENTS),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                
                if not info:
                    return {'success': False, 'error': 'No se pudo obtener información'}
                
                # Extraer formatos disponibles
                formats = []
                for fmt in info.get('formats', []):
                    if fmt.get('url'):
                        format_info = {
                            'id': fmt.get('format_id', ''),
                            'ext': fmt.get('ext', ''),
                            'height': fmt.get('height'),
                            'filesize': fmt.get('filesize'),
                            'format_note': fmt.get('format_note', ''),
                        }
                        formats.append(format_info)
                
                # Ordenar por calidad
                formats.sort(key=lambda x: x.get('height') or 0, reverse=True)
                
                return {
                    'success': True,
                    'data': {
                        'id': info.get('id', ''),
                        'title': info.get('title', 'Sin título'),
                        'duration': info.get('duration', 0),
                        'thumbnail': info.get('thumbnail', ''),
                        'uploader': info.get('uploader', 'Desconocido'),
                        'formats': formats[:8],  # Limitar a 8 formatos
                        'best_quality': formats[0] if formats else None,
                    }
                }
                
        except Exception as e:
            logger.error(f"Error obteniendo info: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def _get_ydl_options(self):
        """Configuración de yt-dlp optimizada para Render"""
        user_agent = random.choice(Config.USER_AGENTS)
        
        base_opts = {
            'outtmpl': os.path.join(self.temp_dir, self.base_filename + '.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 30,
            'retries': 5,
            'fragment_retries': 5,
            'concurrent_fragment_downloads': 8,  # Menos fragmentos en Render
            'http_chunk_size': 5 * 1024 * 1024,  # 5MB chunks
            'ignoreerrors': True,
            'skip_unavailable_fragments': True,
            'no_check_certificate': True,
            'http_headers': {
                'User-Agent': user_agent,
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Connection': 'keep-alive',
            },
        }
        
        # Configurar según tipo
        if self.download_type == "audio":
            base_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            })
        elif self.download_type == "video":
            base_opts['format'] = 'best[height<=720]'  # Máximo 720p en Render
        else:
            base_opts['format'] = 'best[filesize<50M]'  # Limitar tamaño en modo best
        
        return base_opts
    
    def download(self, progress_callback=None):
        """Descarga el archivo"""
        self.status = "downloading"
        start_time = time.time()
        
        try:
            # Primero obtener información
            info_result = self.get_video_info()
            if not info_result['success']:
                self.status = "failed"
                self.error = info_result.get('error')
                return info_result
            
            # Configurar progreso
            if progress_callback:
                def progress_hook(d):
                    if d['status'] == 'downloading':
                        total = d.get('total_bytes', 0)
                        downloaded = d.get('downloaded_bytes', 0)
                        if total and downloaded:
                            self.progress = int((downloaded / total) * 100)
                            progress_callback(self.progress)
                    elif d['status'] == 'finished':
                        self.progress = 100
                        if progress_callback:
                            progress_callback(100)
                
                ydl_opts = self._get_ydl_options()
                ydl_opts['progress_hooks'] = [progress_hook]
            else:
                ydl_opts = self._get_ydl_options()
            
            # Descargar
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])
            
            # Buscar archivo descargado
            for file in os.listdir(self.temp_dir):
                if file.startswith(self.base_filename):
                    self.filename = file
                    self.filepath = os.path.join(self.temp_dir, file)
                    break
            
            if not self.filename or not os.path.exists(self.filepath):
                self.status = "failed"
                return {'success': False, 'error': 'Archivo no encontrado'}
            
            # Verificar tamaño
            file_size = os.path.getsize(self.filepath)
            if file_size > Config.MAX_FILE_SIZE:
                self.cleanup()
                self.status = "failed"
                return {
                    'success': False,
                    'error': f'Archivo demasiado grande ({file_size//1024//1024}MB > {Config.MAX_FILE_SIZE//1024//1024}MB)'
                }
            
            # Renombrar si es posible
            try:
                if info_result['success']:
                    title = info_result['data']['title']
                    safe_title = self.sanitize_filename(title)
                    file_ext = os.path.splitext(self.filename)[1]
                    new_filename = f"{safe_title}{file_ext}"
                    new_filepath = os.path.join(self.temp_dir, new_filename)
                    
                    # Evitar colisiones
                    counter = 1
                    while os.path.exists(new_filepath):
                        new_filename = f"{safe_title}_{counter}{file_ext}"
                        new_filepath = os.path.join(self.temp_dir, new_filename)
                        counter += 1
                    
                    os.rename(self.filepath, new_filepath)
                    self.filename = new_filename
                    self.filepath = new_filepath
            except:
                pass  # Si falla el renombrado, continuar con el nombre original
            
            self.status = "completed"
            download_time = time.time() - start_time
            
            return {
                'success': True,
                'filename': self.filename,
                'filepath': self.filepath,
                'filesize': file_size,
                'download_time': download_time,
                'original_url': self.url,
            }
            
        except Exception as e:
            self.status = "failed"
            self.error = str(e)
            logger.error(f"Error en descarga: {str(e)}")
            
            # Limpiar archivos parciales
            self.cleanup()
            
            return {
                'success': False,
                'error': f'Error en descarga: {str(e)}'
            }
    
    def cleanup(self):
        """Limpia archivos temporales"""
        try:
            if self.filename and os.path.exists(self.filepath):
                os.remove(self.filepath)
            # Limpiar otros archivos con el mismo base_filename
            for file in os.listdir(self.temp_dir):
                if file.startswith(self.base_filename):
                    try:
                        os.remove(os.path.join(self.temp_dir, file))
                    except:
                        pass
            return True
        except:
            return False

# ==============================
# GESTOR DE DESCARGA PARA RENDER
# ==============================
class RenderDownloadManager:
    """Gestor simple para Render"""
    
    def __init__(self):
        self.downloads = {}
        self.cache = TTLCache(maxsize=Config.INFO_CACHE_MAXSIZE, ttl=Config.INFO_CACHE_TTL)
        self.executor = ThreadPoolExecutor(max_workers=Config.MAX_WORKERS)
        self.queue = queue.Queue()
        
        # Iniciar limpiador
        self.cleanup_thread = threading.Thread(target=self._cleanup_worker, daemon=True)
        self.cleanup_thread.start()
        
        # Crear directorio temporal
        os.makedirs(Config.TEMP_DIR, exist_ok=True)
        
        logger.info(f"RenderDownloadManager iniciado en {Config.TEMP_DIR}")
    
    def _cleanup_worker(self):
        """Limpia archivos antiguos"""
        while True:
            try:
                time.sleep(300)  # Cada 5 minutos
                
                if not os.path.exists(Config.TEMP_DIR):
                    continue
                
                cutoff_time = time.time() - 1800  # 30 minutos
                files_deleted = 0
                
                for filename in os.listdir(Config.TEMP_DIR):
                    filepath = os.path.join(Config.TEMP_DIR, filename)
                    try:
                        if os.path.isfile(filepath):
                            file_time = os.path.getmtime(filepath)
                            if file_time < cutoff_time:
                                os.remove(filepath)
                                files_deleted += 1
                    except Exception as e:
                        logger.error(f"Error limpiando {filename}: {e}")
                
                # Limitar número de archivos
                files = os.listdir(Config.TEMP_DIR)
                if len(files) > Config.MAX_TEMP_FILES:
                    files.sort(key=lambda x: os.path.getmtime(os.path.join(Config.TEMP_DIR, x)))
                    for filename in files[:len(files) - Config.MAX_TEMP_FILES]:
                        try:
                            os.remove(os.path.join(Config.TEMP_DIR, filename))
                            files_deleted += 1
                        except:
                            pass
                
                if files_deleted > 0:
                    logger.info(f"Limpieza: {files_deleted} archivos eliminados")
                    
            except Exception as e:
                logger.error(f"Error en cleanup worker: {e}")
    
    def submit_download(self, url, download_type="best", callback_url=None):
        """Envía una descarga"""
        download_id = f"render_{int(time.time())}_{random.randint(1000, 9999)}"
        
        # Crear objeto de descarga
        downloader = RenderDownloader(url, download_type)
        
        # Guardar en el diccionario
        self.downloads[download_id] = {
            'id': download_id,
            'url': url,
            'type': download_type,
            'status': 'queued',
            'progress': 0,
            'downloader': downloader,
            'created_at': datetime.now().isoformat(),
            'callback_url': callback_url,
        }
        
        # Ejecutar en el thread pool
        def download_task():
            download_data = self.downloads[download_id]
            downloader = download_data['downloader']
            
            def progress_callback(progress):
                download_data['progress'] = progress
            
            # Actualizar estado
            download_data['status'] = 'downloading'
            
            # Ejecutar descarga
            result = downloader.download(progress_callback)
            
            # Actualizar resultado
            download_data['result'] = result
            download_data['status'] = 'completed' if result['success'] else 'failed'
            download_data['completed_at'] = datetime.now().isoformat()
            
            # Notificar si hay callback URL
            if callback_url and result['success']:
                try:
                    import requests
                    requests.post(callback_url, json={
                        'download_id': download_id,
                        'status': 'completed',
                        'filename': result.get('filename'),
                        'filesize': result.get('filesize'),
                    }, timeout=5)
                except:
                    pass
        
        self.executor.submit(download_task)
        
        return download_id
    
    def get_download(self, download_id):
        """Obtiene información de una descarga"""
        return self.downloads.get(download_id)
    
    def get_file(self, download_id):
        """Obtiene el archivo de una descarga"""
        download_data = self.downloads.get(download_id)
        if not download_data or download_data['status'] != 'completed':
            return None
        
        result = download_data.get('result')
        if not result or not result['success']:
            return None
        
        return result['filepath']
    
    def cleanup_download(self, download_id):
        """Limpia una descarga"""
        download_data = self.downloads.get(download_id)
        if download_data and 'downloader' in download_data:
            return download_data['downloader'].cleanup()
        return False
    
    def get_stats(self):
        """Obtiene estadísticas"""
        stats = {
            'total_downloads': len(self.downloads),
            'active_downloads': sum(1 for d in self.downloads.values() if d['status'] in ['queued', 'downloading']),
            'completed_downloads': sum(1 for d in self.downloads.values() if d['status'] == 'completed'),
            'failed_downloads': sum(1 for d in self.downloads.values() if d['status'] == 'failed'),
        }
        
        # Espacio en disco
        if os.path.exists(Config.TEMP_DIR):
            temp_files = os.listdir(Config.TEMP_DIR)
            stats['temp_files'] = len(temp_files)
            
            total_size = 0
            for file in temp_files:
                try:
                    total_size += os.path.getsize(os.path.join(Config.TEMP_DIR, file))
                except:
                    pass
            
            stats['temp_size_mb'] = total_size / (1024 * 1024)
        
        return stats

# ==============================
# INICIALIZAR FLASK APP
# ==============================
app = Flask(__name__)

# Configurar para Render
if 'RENDER' in os.environ:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Configurar CORS
CORS(app)

# Configurar rate limiting
try:
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=[Config.RATE_LIMIT],
        storage_uri="memory://",
        strategy="fixed-window"
    )
except:
    limiter = Limiter(app=app, key_func=get_remote_address)

# Inicializar manager
download_manager = RenderDownloadManager()

# ==============================
# ENDPOINTS DE LA API
# ==============================

@app.route('/')
@limiter.exempt
def home():
    return jsonify({
        'service': 'YouTube/TikTok Downloader API',
        'version': 'Render Ready 1.0',
        'status': 'online',
        'timestamp': datetime.now().isoformat(),
        'endpoints': {
            '/': 'Esta página (GET)',
            '/health': 'Health check (GET)',
            '/api/info': 'Obtener información (POST)',
            '/api/download': 'Descargar video (POST)',
            '/api/status/<id>': 'Estado de descarga (GET)',
            '/api/file/<id>': 'Descargar archivo (GET)',
            '/api/stats': 'Estadísticas (GET)',
        },
        'limits': {
            'max_file_size': f"{Config.MAX_FILE_SIZE // 1024 // 1024}MB",
            'max_workers': Config.MAX_WORKERS,
            'rate_limit': Config.RATE_LIMIT,
        },
        'render': 'RENDER' in os.environ
    })

@app.route('/health')
@limiter.exempt
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'stats': download_manager.get_stats()
    })

@app.route('/api/info', methods=['POST'])
def get_info():
    """Obtiene información de un video"""
    try:
        data = request.get_json(silent=True) or {}
        url = data.get('url')
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        # Validar URL
        valid_domains = ['youtube.com', 'youtu.be', 'tiktok.com', 'vm.tiktok.com']
        if not any(domain in url for domain in valid_domains):
            return jsonify({'success': False, 'error': 'URL no soportada'}), 400
        
        # Obtener información
        downloader = RenderDownloader(url)
        result = downloader.get_video_info()
        
        return jsonify(result), 200 if result['success'] else 400
        
    except Exception as e:
        logger.error(f"Error en /api/info: {e}")
        return jsonify({'success': False, 'error': 'Error interno'}), 500

@app.route('/api/download', methods=['POST'])
def start_download():
    """Inicia una descarga"""
    try:
        data = request.get_json(silent=True) or {}
        url = data.get('url')
        download_type = data.get('type', 'best')
        callback_url = data.get('callback_url')
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        # Validar tipo
        if download_type not in ['video', 'audio', 'best']:
            return jsonify({'success': False, 'error': 'Tipo debe ser: video, audio, o best'}), 400
        
        # Enviar descarga
        download_id = download_manager.submit_download(url, download_type, callback_url)
        
        return jsonify({
            'success': True,
            'download_id': download_id,
            'status_url': f'/api/status/{download_id}',
            'message': 'Descarga iniciada'
        }), 202
        
    except Exception as e:
        logger.error(f"Error en /api/download: {e}")
        return jsonify({'success': False, 'error': 'Error interno'}), 500

@app.route('/api/status/<download_id>', methods=['GET'])
def get_status(download_id):
    """Obtiene el estado de una descarga"""
    try:
        download_data = download_manager.get_download(download_id)
        
        if not download_data:
            return jsonify({'success': False, 'error': 'Descarga no encontrada'}), 404
        
        # Preparar respuesta
        response = {
            'id': download_data['id'],
            'url': download_data['url'][:100] + ('...' if len(download_data['url']) > 100 else ''),
            'type': download_data['type'],
            'status': download_data['status'],
            'progress': download_data['progress'],
            'created_at': download_data['created_at'],
        }
        
        if 'completed_at' in download_data:
            response['completed_at'] = download_data['completed_at']
        
        if 'result' in download_data:
            result = download_data['result']
            if result and 'success' in result:
                response['result'] = {
                    'success': result['success'],
                    'error': result.get('error'),
                    'filename': result.get('filename'),
                    'filesize': result.get('filesize'),
                }
        
        return jsonify({'success': True, 'data': response}), 200
        
    except Exception as e:
        logger.error(f"Error en /api/status: {e}")
        return jsonify({'success': False, 'error': 'Error interno'}), 500

@app.route('/api/file/<download_id>', methods=['GET'])
def download_file(download_id):
    """Descarga el archivo"""
    try:
        filepath = download_manager.get_file(download_id)
        
        if not filepath or not os.path.exists(filepath):
            return jsonify({'success': False, 'error': 'Archivo no disponible'}), 404
        
        # Obtener nombre del archivo
        filename = os.path.basename(filepath)
        
        # Enviar archivo
        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
            mimetype='application/octet-stream'
        )
        
    except Exception as e:
        logger.error(f"Error en /api/file: {e}")
        return jsonify({'success': False, 'error': 'Error interno'}), 500

@app.route('/api/stats', methods=['GET'])
@limiter.exempt
def get_stats():
    """Obtiene estadísticas del sistema"""
    try:
        stats = download_manager.get_stats()
        
        return jsonify({
            'success': True,
            'timestamp': datetime.now().isoformat(),
            'stats': stats,
            'config': {
                'temp_dir': Config.TEMP_DIR,
                'max_file_size_mb': Config.MAX_FILE_SIZE // 1024 // 1024,
                'max_workers': Config.MAX_WORKERS,
                'is_render': 'RENDER' in os.environ,
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error en /api/stats: {e}")
        return jsonify({'success': False, 'error': 'Error interno'}), 500

@app.route('/favicon.ico')
def favicon():
    return '', 204

# ==============================
# MANEJO DE ERRORES
# ==============================
@app.errorhandler(404)
def not_found(e):
    return jsonify({'success': False, 'error': 'Endpoint no encontrado'}), 404

@app.errorhandler(429)
def ratelimit_exceeded(e):
    return jsonify({'success': False, 'error': 'Demasiadas solicitudes. Intenta más tarde.'}), 429

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Error 500: {e}")
    return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

# ==============================
# INICIALIZACIÓN
# ==============================
if __name__ == '__main__':
    # Mostrar información de inicio
    print("\n" + "="*60)
    print("🚀 SERVER PARA RENDER.COM - READY TO DEPLOY")
    print("="*60)
    print(f"📡 Host: {Config.HOST}")
    print(f"🔌 Puerto: {Config.PORT}")
    print(f"💾 Temp Dir: {Config.TEMP_DIR}")
    print(f"👷 Workers: {Config.MAX_WORKERS}")
    print(f"📦 Max File Size: {Config.MAX_FILE_SIZE//1024//1024}MB")
    print(f"📊 Rate Limit: {Config.RATE_LIMIT}")
    print("="*60)
    print("✅ Optimizado para Render Free Tier")
    print("✅ Sistema de colas con limpieza automática")
    print("✅ Límites de tamaño para evitar problemas")
    print("="*60)
    
    # Iniciar servidor
    if Config.DEBUG:
        # Modo desarrollo
        app.run(
            host=Config.HOST,
            port=Config.PORT,
            debug=True,
            threaded=True
        )
    else:
        # Modo producción (Render)
        try:
            from waitress import serve
            print("⚡ Usando Waitress para producción")
            serve(
                app,
                host=Config.HOST,
                port=Config.PORT,
                threads=4,
                channel_timeout=300
            )
        except ImportError:
            print("⚠️ Waitress no disponible, usando Flask server")
            app.run(
                host=Config.HOST,
                port=Config.PORT,
                debug=False,
                threaded=True
            )
