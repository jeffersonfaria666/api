#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE/TIKTOK PARA RENDER.COM - VERSIÓN 3.0
Versión: 3.0 - Corregidos problemas de descarga y reinicios
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
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    TIMEOUT = 120  # 2 minutos
    MAX_WORKERS = 2  # Reducido para Render (menos consumo de recursos)
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    ]

# ==============================
# SETUP DE LOGGING
# ==============================
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    # Reducir log de librerías externas
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
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
# CLASE DE DESCARGA SIMPLIFICADA
# ==============================
class SimpleDownloader:
    def __init__(self, url: str, download_type: str = "best"):
        self.url = url
        self.download_type = download_type
        self.temp_dir = tempfile.mkdtemp(prefix=f"ytdl_{int(time.time())}_", dir="/tmp")
        self.output_path = None
        self.status = "pending"
        self.progress = 0
        self.error = None
        self.metadata = {}
        self.start_time = time.time()
        logger.info(f"Descarga iniciada: {url[:50]}...")

    def __del__(self):
        self.cleanup()

    def cleanup(self):
        """Limpia archivos temporales"""
        try:
            if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception as e:
            logger.error(f"Error limpiando directorio temporal: {e}")

    def get_info(self) -> Dict[str, Any]:
        """Obtiene información del video sin descargar"""
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
                    'youtube': {'player_client': ['android', 'web']}
                },
                'http_headers': {'User-Agent': random.choice(Config.USER_AGENTS)},
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
                }

                return {
                    'success': True,
                    'title': self.metadata['title'],
                    'duration': DownloadUtils.format_duration(self.metadata['duration']),
                    'duration_seconds': self.metadata['duration'],
                    'thumbnail': self.metadata['thumbnail'],
                    'uploader': self.metadata['uploader'],
                    'view_count': self.metadata['view_count'],
                }

        except Exception as e:
            logger.error(f"Error obteniendo info: {e}")
            return {'success': False, 'error': f'Error procesando video: {str(e)}'}

    def download(self) -> Dict[str, Any]:
        """Ejecuta la descarga del video/audio"""
        self.status = "downloading"
        
        try:
            # Configurar opciones según tipo
            ydl_opts = {
                'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,
                'no_check_certificate': True,
                'socket_timeout': 15,
                'retries': 3,
                'fragment_retries': 3,
                'concurrent_fragment_downloads': 1,  # Reducido para estabilidad
                'http_headers': {'User-Agent': random.choice(Config.USER_AGENTS)},
            }

            if self.download_type == "audio":
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'extractaudio': True,
                })
            elif self.download_type == "video":
                # Video de calidad media para evitar problemas
                ydl_opts['format'] = 'best[height<=720][filesize<100M]/best[height<=480]'
            else:
                ydl_opts['format'] = 'best[filesize<150M]/best'

            # Ejecutar descarga
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=True)

                if not info:
                    self.status = "failed"
                    return {'success': False, 'error': 'No se pudo extraer información del video'}

                # Buscar archivo descargado
                downloaded_files = []
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        # Ignorar archivos temporales
                        if not file.endswith(('.part', '.ytdl')):
                            downloaded_files.append(os.path.join(root, file))

                if not downloaded_files:
                    self.status = "failed"
                    return {'success': False, 'error': 'No se generó ningún archivo'}

                # Tomar el archivo más grande (probablemente el descargado)
                self.output_path = max(downloaded_files, key=lambda x: os.path.getsize(x))

                # Verificar archivo
                if not os.path.exists(self.output_path):
                    self.status = "failed"
                    return {'success': False, 'error': 'Archivo no encontrado'}

                file_size = os.path.getsize(self.output_path)
                if file_size == 0:
                    os.remove(self.output_path)
                    self.status = "failed"
                    return {'success': False, 'error': 'Archivo vacío'}

                if file_size > Config.MAX_FILE_SIZE:
                    os.remove(self.output_path)
                    self.status = "failed"
                    return {
                        'success': False,
                        'error': f'Archivo demasiado grande ({file_size//1024//1024}MB)'
                    }

                # Actualizar metadata
                self.metadata.update({
                    'title': info.get('title', 'Video'),
                    'filename': os.path.basename(self.output_path),
                    'filesize': file_size,
                    'download_time': time.time() - self.start_time
                })

                self.status = "completed"
                logger.info(f"Descarga completada: {self.metadata['filename']} ({file_size} bytes)")

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

        except Exception as e:
            self.status = "failed"
            logger.error(f"Error en descarga: {e}", exc_info=True)
            return {'success': False, 'error': f'Error de descarga: {str(e)}'}

# ==============================
# GESTOR DE TAREAS SIMPLE
# ==============================
class TaskManager:
    """Gestor simple de tareas sin threading complejo"""
    
    def __init__(self):
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=Config.MAX_WORKERS)
        logger.info(f"TaskManager inicializado con {Config.MAX_WORKERS} workers")

    def create_task(self, url: str, download_type: str = "best") -> str:
        """Crea una nueva tarea de descarga"""
        import uuid
        task_id = str(uuid.uuid4())
        
        with self.lock:
            self.tasks[task_id] = {
                'id': task_id,
                'url': url,
                'type': download_type,
                'status': 'pending',
                'progress': 0,
                'created_at': time.time(),
                'result': None,
                'error': None,
                'downloader': None
            }
        
        # Iniciar la tarea en segundo plano
        def run_task():
            try:
                with self.lock:
                    self.tasks[task_id]['status'] = 'downloading'
                    self.tasks[task_id]['downloader'] = SimpleDownloader(url, download_type)
                
                downloader = self.tasks[task_id]['downloader']
                result = downloader.download()
                
                with self.lock:
                    self.tasks[task_id]['status'] = result.get('status', 'completed')
                    self.tasks[task_id]['result'] = result
                    self.tasks[task_id]['progress'] = 100
                    
                    if not result['success']:
                        self.tasks[task_id]['error'] = result.get('error')
                        self.tasks[task_id]['status'] = 'failed'
            
            except Exception as e:
                with self.lock:
                    self.tasks[task_id]['status'] = 'failed'
                    self.tasks[task_id]['error'] = str(e)
        
        self.executor.submit(run_task)
        logger.info(f"Nueva tarea creada: {task_id}")
        return task_id

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene estado de una tarea"""
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return None
            
            # Si hay un downloader, obtener su progreso
            if task.get('downloader'):
                downloader = task['downloader']
                task['progress'] = downloader.progress
                task['status'] = downloader.status
                task['error'] = downloader.error
            
            return {
                'task_id': task_id,
                'status': task['status'],
                'progress': task['progress'],
                'error': task.get('error'),
                'created_at': task['created_at'],
                'elapsed_time': time.time() - task['created_at']
            }

    def get_task_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene el resultado de una tarea completada"""
        with self.lock:
            task = self.tasks.get(task_id)
            if not task or task['status'] not in ['completed', 'failed']:
                return None
            
            return task.get('result')

    def cleanup_old_tasks(self):
        """Limpia tareas antiguas"""
        with self.lock:
            current_time = time.time()
            to_remove = []
            
            for task_id, task in self.tasks.items():
                # Limpiar tareas con más de 1 hora
                if current_time - task['created_at'] > 3600:
                    # Limpiar downloader si existe
                    if task.get('downloader'):
                        try:
                            task['downloader'].cleanup()
                        except:
                            pass
                    to_remove.append(task_id)
            
            for task_id in to_remove:
                del self.tasks[task_id]
            
            if to_remove:
                logger.info(f"Limpiadas {len(to_remove)} tareas antiguas")

# ==============================
# INICIALIZAR FLASK APP
# ==============================
app = Flask(__name__)
CORS(app)

# Inicializar gestor de tareas
task_manager = TaskManager()

# Limpieza periódica de tareas antiguas
def cleanup_loop():
    while True:
        time.sleep(300)  # Cada 5 minutos
        try:
            task_manager.cleanup_old_tasks()
        except Exception as e:
            logger.error(f"Error en cleanup loop: {e}")

cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
cleanup_thread.start()

# ==============================
# ENDPOINTS DE LA API
# ==============================

@app.route('/')
def home():
    """Página principal"""
    return jsonify({
        'service': 'YouTube/TikTok Downloader API',
        'version': '3.0',
        'status': 'online',
        'timestamp': datetime.now().isoformat(),
        'endpoints': {
            '/': 'Documentación',
            '/health': 'Health check',
            '/info': 'Obtener información de video',
            '/download/start': 'Iniciar descarga (POST)',
            '/download/status/<id>': 'Consultar estado (GET)',
            '/download/get/<id>': 'Descargar archivo (GET)',
            '/download/direct': 'Descarga directa (POST)',
        }
    })

@app.route('/health')
def health():
    """Health check para Render"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'youtube-downloader',
        'python_version': sys.version.split()[0]
    })

@app.route('/info', methods=['POST'])
def get_video_info():
    """Obtiene información de un video"""
    try:
        data = request.get_json(silent=True) or request.form
        
        if not data:
            return jsonify({'success': False, 'error': 'No se recibieron datos'}), 400
        
        url = data.get('url')
        if not url:
            return jsonify({'success': False, 'error': 'Se requiere URL'}), 400
        
        # Validar URL
        if not any(domain in url.lower() for domain in ['youtube.com', 'youtu.be', 'tiktok.com']):
            return jsonify({'success': False, 'error': 'URL no válida'}), 400
        
        downloader = SimpleDownloader(url)
        result = downloader.get_info()
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error en /info: {e}")
        return jsonify({'success': False, 'error': 'Error interno'}), 500

@app.route('/download/start', methods=['POST'])
def start_download():
    """Inicia una descarga asíncrona"""
    try:
        data = request.get_json(silent=True) or request.form
        
        if not data:
            return jsonify({'success': False, 'error': 'No se recibieron datos'}), 400
        
        url = data.get('url')
        download_type = data.get('type', 'best')
        
        if not url:
            return jsonify({'success': False, 'error': 'Se requiere URL'}), 400
        
        if download_type not in ['video', 'audio', 'best']:
            return jsonify({'success': False, 'error': 'Tipo inválido'}), 400
        
        task_id = task_manager.create_task(url, download_type)
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': 'Descarga iniciada',
            'status_url': f'/download/status/{task_id}',
            'download_url': f'/download/get/{task_id}'
        })
        
    except Exception as e:
        logger.error(f"Error en /download/start: {e}")
        return jsonify({'success': False, 'error': 'Error interno'}), 500

@app.route('/download/status/<task_id>', methods=['GET'])
def download_status(task_id):
    """Consulta el estado de una descarga"""
    try:
        status = task_manager.get_task_status(task_id)
        
        if not status:
            return jsonify({'success': False, 'error': 'Tarea no encontrada'}), 404
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'status': status['status'],
            'progress': status['progress'],
            'error': status.get('error'),
            'elapsed_time': status['elapsed_time']
        })
        
    except Exception as e:
        logger.error(f"Error en /download/status: {e}")
        return jsonify({'success': False, 'error': 'Error interno'}), 500

@app.route('/download/get/<task_id>', methods=['GET'])
def download_file(task_id):
    """Descarga el archivo completado"""
    try:
        result = task_manager.get_task_result(task_id)
        
        if not result:
            return jsonify({'success': False, 'error': 'Archivo no disponible'}), 404
        
        if not result['success']:
            return jsonify(result), 400
        
        filepath = result['filepath']
        filename = result['filename']
        
        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': 'Archivo no encontrado'}), 404
        
        # Stream del archivo
        def generate():
            try:
                with open(filepath, 'rb') as f:
                    while chunk := f.read(8192):
                        yield chunk
            finally:
                # Limpiar después de enviar
                try:
                    os.remove(filepath)
                    temp_dir = result.get('temp_dir')
                    if temp_dir and os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception as e:
                    logger.error(f"Error limpiando archivos: {e}")
        
        # Determinar tipo MIME
        if filename.lower().endswith('.mp4'):
            mimetype = 'video/mp4'
        elif filename.lower().endswith('.mp3'):
            mimetype = 'audio/mpeg'
        else:
            mimetype = 'application/octet-stream'
        
        return Response(
            generate(),
            mimetype=mimetype,
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(result['filesize']),
            }
        )
        
    except Exception as e:
        logger.error(f"Error en /download/get: {e}")
        return jsonify({'success': False, 'error': 'Error interno'}), 500

@app.route('/download/direct', methods=['POST'])
def direct_download():
    """Descarga directa (sincrónica)"""
    try:
        data = request.get_json(silent=True) or request.form
        
        if not data:
            return jsonify({'success': False, 'error': 'No se recibieron datos'}), 400
        
        url = data.get('url')
        download_type = data.get('type', 'best')
        
        if not url:
            return jsonify({'success': False, 'error': 'Se requiere URL'}), 400
        
        logger.info(f"Descarga directa iniciada: {url}")
        
        # Ejecutar descarga
        downloader = SimpleDownloader(url, download_type)
        result = downloader.download()
        
        if not result['success']:
            return jsonify(result), 400
        
        filepath = result['filepath']
        filename = result['filename']
        
        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': 'Archivo no encontrado'}), 404
        
        # Stream del archivo
        def generate():
            try:
                with open(filepath, 'rb') as f:
                    while chunk := f.read(8192):
                        yield chunk
            finally:
                # Limpiar después de enviar
                try:
                    os.remove(filepath)
                    temp_dir = result.get('temp_dir')
                    if temp_dir and os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir, ignore_errors=True)
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
        return jsonify({'success': False, 'error': f'Error: {str(e)}'}), 500

# ==============================
# MANEJO DE ERRORES
# ==============================
@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': 'Endpoint no encontrado'}), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({'success': False, 'error': 'Método no permitido'}), 405

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Error 500: {error}")
    return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

# ==============================
# INICIALIZACIÓN
# ==============================
if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 SERVIDOR YOUTUBE/TIKTOK - VERSIÓN 3.0")
    print("="*60)
    print(f"📡 Host: {Config.HOST}")
    print(f"🔌 Puerto: {Config.PORT}")
    print(f"👥 Workers: {Config.MAX_WORKERS}")
    print("="*60)
    print("✅ Sistema simplificado y estabilizado")
    print("✅ Limpieza automática de archivos")
    print("✅ Compatible con YouTube y TikTok")
    print("="*60)
    print(f"📅 Iniciado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60 + "\n")
    
    # Crear directorio temporal
    os.makedirs('/tmp/youtube_downloads', exist_ok=True)
    
    # Iniciar servidor
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=False,
        threaded=True,
        use_reloader=False
    )
