#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE/TIKTOK PARA RENDER.COM - VERSIÓN 5.1
Versión: 5.1 - Corregido problema de descarga MHTML y mejorado formato
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
    TIMEOUT = 180  # 3 minutos
    MAX_WORKERS = 2
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    return logging.getLogger(__name__)

logger = setup_logging()

# ==============================
# UTILIDADES
# ==============================
class FileUtils:
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

    @staticmethod
    def is_valid_media_file(filepath: str) -> bool:
        """Verifica si un archivo multimedia es válido"""
        try:
            if not os.path.exists(filepath):
                return False
            
            file_size = os.path.getsize(filepath)
            
            # Verificaciones básicas
            if file_size == 0:
                logger.warning(f"Archivo vacío: {filepath}")
                return False
            
            # Verificar por extensión
            filename = filepath.lower()
            
            if filename.endswith('.mp3'):
                # MP3 debe tener al menos 100KB para ser válido
                if file_size < 100 * 1024:
                    logger.warning(f"MP3 muy pequeño: {filepath} - {file_size} bytes")
                    return False
                
                # Verificar cabecera MP3
                with open(filepath, 'rb') as f:
                    header = f.read(10)
                    # Verificar si comienza con ID3 tag o tiene frame sync
                    if not (header.startswith(b'ID3') or b'\xff\xfb' in header or b'\xff\xf3' in header):
                        logger.warning(f"MP3 sin cabecera válida: {filepath}")
                        return False
                        
            elif filename.endswith('.mp4'):
                # MP4 debe tener al menos 500KB para ser válido
                if file_size < 500 * 1024:
                    logger.warning(f"MP4 muy pequeño: {filepath} - {file_size} bytes")
                    return False
                
                # Verificar cabecera MP4
                with open(filepath, 'rb') as f:
                    header = f.read(12)
                    # Debe comenzar con 'ftyp' (mp4) o 'moov' (mov)
                    if not (header[4:8] == b'ftyp' or header[4:8] == b'moov'):
                        logger.warning(f"MP4 sin cabecera válida: {filepath}")
                        return False
            else:
                # No es un formato multimedia esperado
                logger.warning(f"Formato no soportado: {filepath}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error verificando archivo {filepath}: {e}")
            return False

# ==============================
# CLASE DE DESCARGA CORREGIDA - EVITA MHTML
# ==============================
class FixedDownloader:
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
        logger.info(f"Descarga iniciada: {url[:50]}... Tipo: {download_type}")

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
                    'duration': FileUtils.format_duration(self.metadata['duration']),
                    'duration_seconds': self.metadata['duration'],
                    'thumbnail': self.metadata['thumbnail'],
                    'uploader': self.metadata['uploader'],
                    'view_count': self.metadata['view_count'],
                }

        except Exception as e:
            logger.error(f"Error obteniendo info: {e}")
            return {'success': False, 'error': f'Error procesando video: {str(e)}'}

    def download(self) -> Dict[str, Any]:
        """Ejecuta la descarga del video/audio CON CONFIGURACIÓN CORREGIDA"""
        self.status = "downloading"
        
        try:
            # CONFIGURACIÓN CORREGIDA - EVITA MHTML
            # Base configuration
            ydl_opts = {
                'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': False,
                'no_check_certificate': True,
                'socket_timeout': 30,
                'retries': 5,
                'fragment_retries': 5,
                'concurrent_fragment_downloads': 2,
                'http_headers': {'User-Agent': random.choice(Config.USER_AGENTS)},
                'progress_hooks': [self._progress_hook],
                # IMPORTANTE: Evitar formatos no deseados
                'format': None,  # Se establecerá según tipo
                'postprocessor_args': {
                    'ffmpeg': ['-hide_banner', '-loglevel', 'error']
                },
                'prefer_ffmpeg': True,
                'keepvideo': False,
                'noplaylist': True,
                'nooverwrites': True,
            }

            # Configuración ESPECÍFICA para evitar MHTML
            if self.download_type == "audio":
                # Forzar audio MP3 con formato específico
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'extractaudio': True,
                    'audioformat': 'mp3',
                    'postprocessors': [
                        {
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        },
                        {
                            'key': 'FFmpegMetadata',
                            'add_metadata': True,
                        }
                    ],
                    'writethumbnail': True,
                    'postprocessor_args': {
                        'ffmpeg': [
                            '-i', '%(filepath)s',
                            '-acodec', 'libmp3lame',
                            '-q:a', '2',
                            '-metadata', 'title=%(title)s',
                            '-metadata', 'artist=%(uploader)s',
                            '-y', '%(filepath)s.%(ext)s'
                        ]
                    },
                })
                
            elif self.download_type == "video":
                # Forzar video MP4 con formato específico
                ydl_opts.update({
                    'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best',
                    'merge_output_format': 'mp4',
                    'postprocessors': [
                        {
                            'key': 'FFmpegVideoConvertor',
                            'preferedformat': 'mp4',
                        },
                        {
                            'key': 'FFmpegMetadata',
                        }
                    ],
                    'postprocessor_args': {
                        'ffmpeg': [
                            '-i', '%(filepath)s',
                            '-c:v', 'copy',
                            '-c:a', 'aac',
                            '-b:a', '192k',
                            '-movflags', '+faststart',
                            '-y', '%(filepath)s.%(ext)s'
                        ]
                    },
                })
                
            else:  # "best"
                # Formato balanceado pero evitando MHTML
                ydl_opts.update({
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'merge_output_format': 'mp4',
                    'postprocessors': [
                        {
                            'key': 'FFmpegVideoConvertor',
                            'preferedformat': 'mp4',
                        }
                    ],
                })

            logger.info(f"Configuración de descarga: {self.download_type}")

            # Ejecutar descarga
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(self.url, download=True)
                except Exception as e:
                    logger.error(f"Error en yt-dlp: {e}")
                    self.status = "failed"
                    return {'success': False, 'error': f'Error descargando: {str(e)}'}

                if not info:
                    self.status = "failed"
                    return {'success': False, 'error': 'No se pudo extraer información del video'}

                # Buscar archivo descargado - EVITAR MHTML EXPLÍCITAMENTE
                downloaded_files = []
                expected_exts = []
                
                # Definir extensiones esperadas por tipo
                if self.download_type == "audio":
                    expected_exts = ['.mp3', '.m4a', '.ogg', '.wav']
                else:
                    expected_exts = ['.mp4', '.mkv', '.webm', '.avi', '.mov']

                logger.info(f"Buscando archivos con extensiones: {expected_exts}")
                
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        filepath = os.path.join(root, file)
                        file_ext = os.path.splitext(file)[1].lower()
                        
                        # IGNORAR EXPLÍCITAMENTE ARCHIVOS MHTML
                        if file_ext == '.mhtml':
                            logger.warning(f"Archivo MHTML ignorado: {filepath}")
                            continue
                            
                        # Ignorar archivos temporales y parciales
                        if any(file.endswith(ext) for ext in ['.part', '.ytdl', '.temp', '.tmp', '.frag', '.ytdlp']):
                            continue
                            
                        # Verificar extensión esperada
                        if expected_exts and file_ext not in expected_exts:
                            logger.warning(f"Extensión no esperada ignorada: {file_ext} - {filepath}")
                            continue
                            
                        # Verificar que tenga un tamaño mínimo
                        try:
                            file_size = os.path.getsize(filepath)
                            if file_size > 1024:  # Al menos 1KB
                                downloaded_files.append({
                                    'path': filepath,
                                    'size': file_size,
                                    'ext': file_ext
                                })
                                logger.info(f"Archivo encontrado: {file} - {file_size} bytes")
                        except:
                            continue

                if not downloaded_files:
                    self.status = "failed"
                    # Listar TODOS los archivos para debug
                    all_files = []
                    for root, dirs, files in os.walk(self.temp_dir):
                        for file in files:
                            all_files.append(f"{file} ({os.path.getsize(os.path.join(root, file))} bytes)")
                    logger.error(f"No se encontraron archivos válidos. Archivos en temp: {all_files}")
                    return {'success': False, 'error': 'No se generó ningún archivo de audio/video válido'}

                # Seleccionar el archivo más grande con extensión preferida
                preferred_ext = '.mp3' if self.download_type == 'audio' else '.mp4'
                
                # Primero intentar con la extensión preferida
                preferred_files = [f for f in downloaded_files if f['ext'] == preferred_ext]
                if preferred_files:
                    self.output_path = max(preferred_files, key=lambda x: x['size'])['path']
                else:
                    # Si no hay con la extensión preferida, usar el más grande
                    self.output_path = max(downloaded_files, key=lambda x: x['size'])['path']
                
                logger.info(f"Archivo seleccionado: {os.path.basename(self.output_path)} - {os.path.getsize(self.output_path)} bytes")
                
                # Verificar integridad del archivo
                if not FileUtils.is_valid_media_file(self.output_path):
                    self.status = "failed"
                    logger.error(f"Archivo no válido: {self.output_path}")
                    
                    # Intentar con otro archivo si hay más
                    if len(downloaded_files) > 1:
                        for file_info in downloaded_files:
                            if file_info['path'] != self.output_path and FileUtils.is_valid_media_file(file_info['path']):
                                self.output_path = file_info['path']
                                logger.info(f"Usando archivo alternativo válido: {self.output_path}")
                                break
                        else:
                            return {'success': False, 'error': 'Ningún archivo generado es válido'}
                    else:
                        return {'success': False, 'error': 'Archivo generado no es válido'}

                file_size = os.path.getsize(self.output_path)
                
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

        except yt_dlp.utils.DownloadError as e:
            self.status = "failed"
            error_msg = str(e)
            logger.error(f"Error de yt-dlp: {error_msg}")
            
            # Errores comunes
            if "Unable to download webpage" in error_msg:
                return {'success': False, 'error': 'No se puede acceder al video (puede estar restringido)'}
            elif "Private video" in error_msg:
                return {'success': False, 'error': 'Video privado'}
            elif "Video unavailable" in error_msg:
                return {'success': False, 'error': 'Video no disponible'}
            elif "format not available" in error_msg.lower():
                return {'success': False, 'error': 'Formato no disponible para este video'}
            else:
                return {'success': False, 'error': f'Error de descarga: {error_msg[:100]}'}
                
        except Exception as e:
            self.status = "failed"
            logger.error(f"Error en descarga: {e}", exc_info=True)
            return {'success': False, 'error': f'Error inesperado: {str(e)}'}

    def _progress_hook(self, d):
        """Hook para seguir el progreso"""
        if d['status'] == 'downloading':
            if 'total_bytes' in d:
                self.progress = (d['downloaded_bytes'] / d['total_bytes']) * 100
            elif 'total_bytes_estimate' in d:
                self.progress = (d['downloaded_bytes'] / d['total_bytes_estimate']) * 100
            logger.debug(f"Progreso: {self.progress:.1f}%")

# ==============================
# GESTOR DE TAREAS
# ==============================
class TaskManager:
    """Gestor de tareas de descarga"""
    
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
                    downloader = FixedDownloader(url, download_type)
                    self.tasks[task_id]['downloader'] = downloader
                
                result = downloader.download()
                
                with self.lock:
                    self.tasks[task_id]['result'] = result
                    self.tasks[task_id]['progress'] = 100
                    
                    if result['success']:
                        self.tasks[task_id]['status'] = 'completed'
                    else:
                        self.tasks[task_id]['status'] = 'failed'
                        self.tasks[task_id]['error'] = result.get('error')
            
            except Exception as e:
                with self.lock:
                    self.tasks[task_id]['status'] = 'failed'
                    self.tasks[task_id]['error'] = str(e)
        
        self.executor.submit(run_task)
        logger.info(f"Nueva tarea creada: {task_id} - {url[:50]}...")
        return task_id

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene estado de una tarea"""
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return None
            
            # Obtener progreso del downloader si existe
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
                # Limpiar tareas con más de 30 minutos
                if current_time - task['created_at'] > 1800:
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

# Limpieza periódica
def cleanup_loop():
    while True:
        time.sleep(300)
        try:
            task_manager.cleanup_old_tasks()
        except Exception as e:
            logger.error(f"Error en cleanup loop: {e}")

cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
cleanup_thread.start()

# ==============================
# ENDPOINTS DE LA API - SIMPLIFICADOS
# ==============================

@app.route('/')
def home():
    """Página principal"""
    return jsonify({
        'service': 'YouTube/TikTok Downloader API',
        'version': '5.1',
        'status': 'online',
        'timestamp': datetime.now().isoformat(),
        'endpoints': {
            '/': 'Documentación',
            '/health': 'Health check',
            '/info': 'Obtener información de video (POST)',
            '/download/direct': 'Descarga directa (POST)',
        },
        'usage': {
            'info': 'POST /info {"url": "youtube_url"}',
            'download': 'POST /download/direct {"url": "youtube_url", "type": "video|audio|best"}'
        }
    })

@app.route('/health')
def health():
    """Health check para Render"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'youtube-downloader-v5.1',
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
            return jsonify({'success': False, 'error': 'URL no válida. Solo YouTube y TikTok'}), 400
        
        downloader = FixedDownloader(url)
        result = downloader.get_info()
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error en /info: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

@app.route('/download/direct', methods=['POST'])
def direct_download():
    """Descarga directa (sincrónica) - Endpoint principal"""
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
        
        logger.info(f"Descarga directa solicitada: {url} - Tipo: {download_type}")
        
        # Ejecutar descarga
        downloader = FixedDownloader(url, download_type)
        result = downloader.download()
        
        if not result['success']:
            return jsonify(result), 400
        
        filepath = result['filepath']
        filename = result['filename']
        
        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': 'Archivo no encontrado'}), 404
        
        # Verificar integridad final
        if not FileUtils.is_valid_media_file(filepath):
            downloader.cleanup()
            return jsonify({'success': False, 'error': 'Archivo corrupto generado'}), 500
        
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
        
        # Determinar tipo MIME correcto
        filename_lower = filename.lower()
        if filename_lower.endswith('.mp3'):
            mimetype = 'audio/mpeg'
        elif filename_lower.endswith('.mp4'):
            mimetype = 'video/mp4'
        elif filename_lower.endswith('.webm'):
            mimetype = 'video/webm'
        elif filename_lower.endswith('.m4a'):
            mimetype = 'audio/mp4'
        else:
            mimetype = 'application/octet-stream'
        
        return Response(
            generate(),
            mimetype=mimetype,
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(result['filesize']),
                'Content-Type': mimetype,
            }
        )
        
    except Exception as e:
        logger.error(f"Error en /download/direct: {e}", exc_info=True)
        return jsonify({'success': False, 'error': f'Error del servidor: {str(e)}'}), 500

@app.route('/test', methods=['GET'])
def test_endpoint():
    """Endpoint de prueba simple"""
    return jsonify({
        'success': True,
        'message': 'Servidor funcionando - Versión 5.1',
        'timestamp': datetime.now().isoformat(),
    })

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
    logger.error(f"Error 500: {error}", exc_info=True)
    return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

# ==============================
# INICIALIZACIÓN
# ==============================
if __name__ == '__main__':
    print("\n" + "="*70)
    print("🚀 SERVIDOR YOUTUBE/TIKTOK - VERSIÓN 5.1")
    print("="*70)
    print(f"📡 Host: {Config.HOST}")
    print(f"🔌 Puerto: {Config.PORT}")
    print("="*70)
    print("✅ Sistema corregido - Evita archivos MHTML")
    print("✅ Forzado a formatos MP3/MP4 válidos")
    print("✅ Verificación de integridad mejorada")
    print("✅ Endpoints simplificados y estables")
    print("="*70)
    print(f"📅 Iniciado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")
    
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
