#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE/TIKTOK PARA RENDER.COM - VERSIÓN MEJORADA
Versión: 2.2 - Corregido problemas de descarga y dependencias
"""

import os
import sys
import json
import logging
import random
import time
import threading
import tempfile
import shutil
import signal
from datetime import datetime
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp

# ==============================
# CONFIGURACIÓN PARA RENDER
# ==============================
class Config:
    PORT = int(os.environ.get('PORT', 10000))
    HOST = '0.0.0.0'
    TEMP_DIR = '/tmp/youtube_downloads'
    MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB
    TIMEOUT = 120
    MAX_WORKERS = 3
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ]
    FORMATS = {
        'audio': 'bestaudio/best',
        'video': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
        'best': 'bestvideo+bestaudio/best'
    }

# ==============================
# SETUP DE LOGGING
# ==============================
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(threadName)s] - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    return logging.getLogger(__name__)

logger = setup_logging()

# ==============================
# UTILIDADES
# ==============================
class DownloadUtils:
    @staticmethod
    def clean_filename(name: str) -> str:
        if not name:
            return "video"
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        if len(name) > 80:
            name = name[:77] + "..."
        return name

    @staticmethod
    def format_duration(seconds: int) -> str:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"

# ==============================
# GESTOR DE DESCARGA ASÍNCRONA
# ==============================
class AsyncDownloader:
    def __init__(self, max_workers: int = Config.MAX_WORKERS):
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="Downloader")
        self.active_tasks: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.RLock()
        logger.info(f"Inicializado ThreadPoolExecutor con {max_workers} workers")

    def submit_download(self, download_func, *args, **kwargs) -> str:
        import uuid
        task_id = str(uuid.uuid4())

        def task_wrapper():
            try:
                result = download_func(*args, **kwargs)
                with self.lock:
                    self.active_tasks[task_id]['result'] = result
                    self.active_tasks[task_id]['status'] = 'completed'
                return result
            except Exception as e:
                with self.lock:
                    self.active_tasks[task_id]['error'] = str(e)
                    self.active_tasks[task_id]['status'] = 'failed'
                raise

        with self.lock:
            self.active_tasks[task_id] = {
                'status': 'running',
                'start_time': time.time(),
                'result': None,
                'error': None
            }

        self.executor.submit(task_wrapper)
        return task_id

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            return self.active_tasks.get(task_id)

    def cleanup_old_tasks(self, max_age_seconds: int = 300):
        current_time = time.time()
        with self.lock:
            to_remove = []
            for task_id, task_info in self.active_tasks.items():
                if current_time - task_info['start_time'] > max_age_seconds:
                    to_remove.append(task_id)
            for task_id in to_remove:
                del self.active_tasks[task_id]
            if to_remove:
                logger.info(f"Limpiadas {len(to_remove)} tareas antiguas")

    def shutdown(self):
        logger.info("Cerrando ThreadPoolExecutor...")
        self.executor.shutdown(wait=False)

# ==============================
# CLASE DE DESCARGA PRINCIPAL - MEJORADA
# ==============================
class DownloadManager:
    def __init__(self, url: str, download_type: str = "best"):
        self.url = url
        self.download_type = download_type
        self.download_id = None
        self.temp_dir = tempfile.mkdtemp(prefix=f"ytdl_{int(time.time())}_", dir="/tmp")
        self.output_path = None
        self.status = "pending"
        self.progress = 0
        self.error = None
        self.metadata = {}
        logger.info(f"Iniciando descarga: {url[:50]}... en {self.temp_dir}")

    def __del__(self):
        self.cleanup()

    def cleanup(self):
        try:
            if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                logger.info(f"Limpiado directorio temporal: {self.temp_dir}")
        except Exception as e:
            logger.error(f"Error limpiando directorio temporal: {e}")

    def get_info(self) -> Dict[str, Any]:
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'ignoreerrors': True,
                'no_check_certificate': True,
                'socket_timeout': 10,
                'retries': 3,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web']
                    }
                },
                'http_headers': {
                    'User-Agent': random.choice(Config.USER_AGENTS),
                }
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=False)

                if not info:
                    return {'success': False, 'error': 'Video no encontrado o URL inválida'}

                self.metadata = {
                    'title': info.get('title', 'Video sin título'),
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'uploader': info.get('uploader', 'Desconocido'),
                    'view_count': info.get('view_count', 0),
                    'webpage_url': info.get('webpage_url', self.url)
                }

                formats = []
                for fmt in info.get('formats', []):
                    if fmt.get('url') and fmt.get('ext') in ['mp4', 'webm', 'm4a', 'mp3']:
                        formats.append({
                            'format_id': fmt.get('format_id', ''),
                            'ext': fmt.get('ext', ''),
                            'resolution': f"{fmt.get('height', 'N/A')}p" if fmt.get('height') else 'Audio',
                            'filesize_mb': fmt.get('filesize', 0) / (1024 * 1024) if fmt.get('filesize') else 0,
                            'format_note': fmt.get('format_note', ''),
                        })

                unique_formats = []
                seen = set()
                for fmt in sorted(formats, key=lambda x: x.get('filesize_mb', 0), reverse=True):
                    key = (fmt.get('resolution'), fmt.get('ext'))
                    if key not in seen:
                        seen.add(key)
                        unique_formats.append(fmt)

                return {
                    'success': True,
                    'title': self.metadata['title'],
                    'duration': DownloadUtils.format_duration(self.metadata['duration']),
                    'duration_seconds': self.metadata['duration'],
                    'thumbnail': self.metadata['thumbnail'],
                    'uploader': self.metadata['uploader'],
                    'view_count': self.metadata['view_count'],
                    'formats': unique_formats[:10],
                    'webpage_url': self.metadata['webpage_url']
                }

        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            if 'Private video' in error_msg:
                return {'success': False, 'error': 'Video privado o no disponible'}
            elif 'Video unavailable' in error_msg:
                return {'success': False, 'error': 'Video no disponible en tu región'}
            else:
                return {'success': False, 'error': f'Error de descarga: {error_msg}'}
        except Exception as e:
            logger.error(f"Error obteniendo info: {e}")
            return {'success': False, 'error': f'Error procesando video: {str(e)}'}

    def download(self) -> Dict[str, Any]:
        self.status = "downloading"
        start_time = time.time()

        try:
            ydl_opts = {
                'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,
                'no_check_certificate': True,
                'socket_timeout': 15,
                'retries': 5,
                'fragment_retries': 5,
                'concurrent_fragment_downloads': 2,
                'http_headers': {
                    'User-Agent': random.choice(Config.USER_AGENTS),
                    'Accept': '*/*',
                },
                'progress_hooks': [self._progress_hook],
            }

            if self.download_type == "audio":
                ydl_opts.update({
                    'format': Config.FORMATS['audio'],
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'extractaudio': True,
                })
            elif self.download_type == "video":
                ydl_opts['format'] = Config.FORMATS['video']
            else:
                ydl_opts['format'] = Config.FORMATS['best']

            # Ejecutar descarga
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=True)

                if not info:
                    self.status = "failed"
                    return {'success': False, 'error': 'No se pudo extraer información del video'}

                # Buscar archivo descargado en el directorio temporal
                downloaded_files = []
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        # Ignorar archivos parciales
                        if not file.endswith(('.part', '.ytdl')):
                            if file.endswith(('.mp4', '.webm', '.mp3', '.m4a', '.mkv', '.flv', '.avi')):
                                downloaded_files.append(os.path.join(root, file))

                if not downloaded_files:
                    self.status = "failed"
                    return {'success': False, 'error': 'No se generó ningún archivo (solo archivos parciales)'}

                self.output_path = downloaded_files[0]

                # Verificar archivo
                if not os.path.exists(self.output_path):
                    self.status = "failed"
                    return {'success': False, 'error': 'Archivo no encontrado después de la descarga'}

                file_size = os.path.getsize(self.output_path)
                if file_size == 0:
                    os.remove(self.output_path)
                    self.status = "failed"
                    return {'success': False, 'error': 'Archivo vacío (0 bytes)'}

                if file_size > Config.MAX_FILE_SIZE:
                    os.remove(self.output_path)
                    self.status = "failed"
                    return {
                        'success': False,
                        'error': f'Archivo demasiado grande ({file_size//1024//1024}MB > {Config.MAX_FILE_SIZE//1024//1024}MB)'
                    }

                # Actualizar metadata
                self.metadata.update({
                    'title': info.get('title', 'Video'),
                    'filename': os.path.basename(self.output_path),
                    'filesize': file_size,
                    'download_time': time.time() - start_time
                })

                self.status = "completed"
                self.progress = 100

                return {
                    'success': True,
                    'filename': self.metadata['filename'],
                    'filepath': self.output_path,
                    'filesize': file_size,
                    'filesize_mb': round(file_size / (1024 * 1024), 2),
                    'download_time': round(self.metadata['download_time'], 2),
                    'title': self.metadata['title'],
                    'temp_dir': self.temp_dir
                }

        except yt_dlp.utils.DownloadError as e:
            self.status = "failed"
            error_msg = str(e)
            if 'Too many requests' in error_msg:
                return {'success': False, 'error': 'Demasiadas solicitudes. Intenta más tarde.'}
            else:
                return {'success': False, 'error': f'Error de descarga: {error_msg}'}
        except Exception as e:
            self.status = "failed"
            logger.error(f"Error en descarga: {e}", exc_info=True)
            return {'success': False, 'error': f'Error inesperado: {str(e)}'}

    def _progress_hook(self, d):
        if d['status'] == 'downloading':
            if 'total_bytes' in d:
                self.progress = (d['downloaded_bytes'] / d['total_bytes']) * 100
            elif 'total_bytes_estimate' in d:
                self.progress = (d['downloaded_bytes'] / d['total_bytes_estimate']) * 100

    def get_status(self) -> Dict[str, Any]:
        return {
            'status': self.status,
            'progress': self.progress,
            'error': self.error,
            'metadata': self.metadata,
            'download_type': self.download_type
        }

# ==============================
# GESTOR DE DESCARGA GLOBAL
# ==============================
class DownloadService:
    def __init__(self):
        self.downloads: Dict[str, DownloadManager] = {}
        self.async_downloader = AsyncDownloader()
        self.lock = threading.RLock()
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.cleanup_thread.start()
        logger.info("DownloadService inicializado")

    def create_download(self, url: str, download_type: str = "best") -> str:
        import uuid
        download_id = str(uuid.uuid4())

        with self.lock:
            download_manager = DownloadManager(url, download_type)
            self.downloads[download_id] = download_manager

            task_id = self.async_downloader.submit_download(download_manager.download)
            download_manager.download_id = task_id

        logger.info(f"Nueva descarga creada: {download_id} para {url[:50]}...")
        return download_id

    def get_download_status(self, download_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            download = self.downloads.get(download_id)
            if not download:
                return None

            status = download.get_status()

            if download.download_id:
                task_status = self.async_downloader.get_task_status(download.download_id)
                if task_status:
                    status.update({
                        'task_status': task_status['status'],
                        'task_error': task_status.get('error')
                    })

            return status

    def get_download_result(self, download_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            download = self.downloads.get(download_id)
            if not download or download.status != "completed":
                return None

            if download.download_id:
                task_status = self.async_downloader.get_task_status(download.download_id)
                if task_status and task_status['status'] == 'completed':
                    return task_status.get('result')

            return None

    def _cleanup_loop(self):
        while True:
            time.sleep(300)
            try:
                with self.lock:
                    to_remove = []
                    for download_id, download in self.downloads.items():
                        # Si la descarga tiene más de 30 minutos, limpiar
                        if download.status in ['completed', 'failed']:
                            if hasattr(download, 'metadata') and 'download_time' in download.metadata:
                                if time.time() - download.metadata['download_time'] > 1800:
                                    download.cleanup()
                                    to_remove.append(download_id)

                    for download_id in to_remove:
                        del self.downloads[download_id]

                    if to_remove:
                        logger.info(f"Limpiadas {len(to_remove)} descargas antiguas")

                self.async_downloader.cleanup_old_tasks()

            except Exception as e:
                logger.error(f"Error en cleanup loop: {e}")

# ==============================
# INICIALIZAR FLASK APP
# ==============================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

download_service = DownloadService()

def setup_signal_handlers():
    def signal_handler(signum, frame):
        logger.info(f"Recibida señal {signum}, cerrando aplicación...")
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

setup_signal_handlers()

# ==============================
# ENDPOINTS DE LA API
# ==============================

@app.route('/')
def home():
    return jsonify({
        'service': 'YouTube/TikTok Downloader API',
        'version': '2.2',
        'status': 'online',
        'timestamp': datetime.now().isoformat(),
        'endpoints': {
            '/': 'Documentación',
            '/health': 'Health check',
            '/info': 'Obtener información de video (POST)',
            '/download/start': 'Iniciar descarga (POST)',
            '/download/status/<id>': 'Consultar estado (GET)',
            '/download/get/<id>': 'Descargar archivo (GET)',
        },
        'limits': {
            'max_file_size': f'{Config.MAX_FILE_SIZE // 1024 // 1024}MB',
            'timeout': f'{Config.TIMEOUT} segundos',
            'concurrent_downloads': Config.MAX_WORKERS
        }
    })

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'youtube-downloader-v2',
        'environment': os.environ.get('RENDER', 'development'),
        'active_downloads': len(download_service.downloads),
        'python_version': sys.version.split()[0]
    })

@app.route('/info', methods=['POST', 'GET'])
def get_video_info():
    try:
        if request.method == 'POST':
            data = request.get_json(silent=True) or request.form
        else:
            data = request.args

        url = data.get('url')

        if not url:
            return jsonify({'success': False, 'error': 'Se requiere parámetro "url"'}), 400

        if not any(domain in url.lower() for domain in ['youtube.com', 'youtu.be', 'tiktok.com', 'vm.tiktok.com']):
            return jsonify({
                'success': False,
                'error': 'URL no válida. Solo se soportan YouTube y TikTok.'
            }), 400

        download_manager = DownloadManager(url)
        result = download_manager.get_info()

        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        logger.error(f"Error en /info: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

@app.route('/download/start', methods=['POST'])
def start_download():
    try:
        data = request.get_json(silent=True) or request.form

        if not data:
            return jsonify({'success': False, 'error': 'No se recibieron datos'}), 400

        url = data.get('url')
        download_type = data.get('type', 'best')

        if not url:
            return jsonify({'success': False, 'error': 'Se requiere URL'}), 400

        if download_type not in ['video', 'audio', 'best']:
            return jsonify({'success': False, 'error': 'Tipo debe ser: video, audio o best'}), 400

        if not any(domain in url.lower() for domain in ['youtube.com', 'youtu.be', 'tiktok.com', 'vm.tiktok.com']):
            return jsonify({'success': False, 'error': 'URL no válida. Solo YouTube y TikTok'}), 400

        download_id = download_service.create_download(url, download_type)

        return jsonify({
            'success': True,
            'download_id': download_id,
            'message': 'Descarga iniciada',
            'status_url': f'/download/status/{download_id}',
            'download_url': f'/download/get/{download_id}'
        })

    except Exception as e:
        logger.error(f"Error en /download/start: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

@app.route('/download/status/<download_id>', methods=['GET'])
def download_status(download_id):
    try:
        status = download_service.get_download_status(download_id)

        if not status:
            return jsonify({'success': False, 'error': 'Descarga no encontrada'}), 404

        return jsonify({
            'success': True,
            'download_id': download_id,
            'status': status['status'],
            'progress': status['progress'],
            'metadata': status.get('metadata', {}),
            'download_type': status.get('download_type', 'unknown'),
            'task_status': status.get('task_status', 'unknown'),
            'error': status.get('error') or status.get('task_error')
        })

    except Exception as e:
        logger.error(f"Error en /download/status: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

@app.route('/download/get/<download_id>', methods=['GET'])
def download_file(download_id):
    try:
        result = download_service.get_download_result(download_id)

        if not result:
            return jsonify({'success': False, 'error': 'Archivo no disponible o descarga incompleta'}), 404

        if not result['success']:
            return jsonify(result), 400

        filepath = result['filepath']
        filename = result['filename']

        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': 'Archivo no encontrado en servidor'}), 404

        def generate():
            try:
                with open(filepath, 'rb') as f:
                    while chunk := f.read(8192):
                        yield chunk
            finally:
                try:
                    os.remove(filepath)
                    temp_dir = result.get('temp_dir')
                    if temp_dir and os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
                    with download_service.lock:
                        if download_id in download_service.downloads:
                            del download_service.downloads[download_id]
                except Exception as e:
                    logger.error(f"Error limpiando archivos: {e}")

        if filename.lower().endswith('.mp4'):
            mimetype = 'video/mp4'
        elif filename.lower().endswith('.mp3'):
            mimetype = 'audio/mpeg'
        elif filename.lower().endswith('.webm'):
            mimetype = 'video/webm'
        else:
            mimetype = 'application/octet-stream'

        return Response(
            generate(),
            mimetype=mimetype,
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(result['filesize']),
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0',
            }
        )

    except Exception as e:
        logger.error(f"Error en /download/get: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

@app.route('/download/direct', methods=['POST'])
def direct_download():
    """Descarga directa (sincrónica) - para compatibilidad"""
    try:
        data = request.get_json(silent=True) or request.form

        if not data:
            return jsonify({'success': False, 'error': 'No se recibieron datos'}), 400

        url = data.get('url')
        download_type = data.get('type', 'best')

        if not url:
            return jsonify({'success': False, 'error': 'Se requiere URL'}), 400

        # Ejecutar descarga directa
        download_manager = DownloadManager(url, download_type)
        result = download_manager.download()

        if not result['success']:
            return jsonify(result), 400

        filepath = result['filepath']
        filename = result['filename']

        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': 'Archivo no encontrado'}), 404

        # Enviar archivo directamente
        def generate():
            try:
                with open(filepath, 'rb') as f:
                    while chunk := f.read(8192):
                        yield chunk
            finally:
                try:
                    os.remove(filepath)
                    temp_dir = result.get('temp_dir')
                    if temp_dir and os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
                except Exception as e:
                    logger.error(f"Error limpiando archivos directos: {e}")

        return Response(
            generate(),
            mimetype='application/octet-stream',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(result['filesize']),
            }
        )

    except Exception as e:
        logger.error(f"Error en /download/direct: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

@app.route('/stats', methods=['GET'])
def get_stats():
    """Estadísticas del servidor sin dependencia de psutil"""
    try:
        import platform
        
        # Información básica del sistema
        memory_usage = 0
        try:
            # Intentar obtener uso de memoria de forma simple
            import resource
            memory_usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if platform.system() == 'Darwin':  # macOS
                memory_usage /= 1024  # KB
            else:
                memory_usage /= 1024  # Linux: ya está en KB
        except:
            pass

        return jsonify({
            'success': True,
            'server_time': datetime.now().isoformat(),
            'active_downloads': len(download_service.downloads),
            'pending_tasks': len(download_service.async_downloader.active_tasks),
            'memory_usage_kb': round(memory_usage, 2),
            'python_version': sys.version,
            'platform': platform.platform()
        })
    except Exception as e:
        logger.error(f"Error obteniendo stats: {e}")
        return jsonify({
            'success': True,
            'server_time': datetime.now().isoformat(),
            'active_downloads': len(download_service.downloads),
            'error': f'No se pudieron obtener todas las estadísticas: {e}'
        })

# ==============================
# MANEJO DE ERRORES
# ==============================
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': 'Endpoint no encontrado',
        'available_endpoints': ['/', '/health', '/info', '/download/start', '/download/status/<id>', '/download/get/<id>', '/stats']
    }), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({'success': False, 'error': 'Método no permitido para este endpoint'}), 405

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Error 500: {error}", exc_info=True)
    return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

# ==============================
# INICIALIZACIÓN
# ==============================
if __name__ == '__main__':
    print("\n" + "="*70)
    print("🚀 SERVIDOR YOUTUBE/TIKTOK - VERSIÓN 2.2")
    print("="*70)
    print(f"📡 Host: {Config.HOST}")
    print(f"🔌 Puerto: {Config.PORT}")
    print("="*70)
    print(f"📅 Iniciado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")

    os.makedirs('/tmp/youtube_downloads', exist_ok=True)

    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=False,
        threaded=True,
        use_reloader=False
    )
