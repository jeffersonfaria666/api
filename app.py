#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE ULTRA SIMPLE - VERSIÓN CORREGIDA
Versión: 7.0 - Sin errores de renombre
"""

import os
import sys
import json
import logging
import tempfile
import shutil
import time
from datetime import datetime
from typing import Dict, Any

from flask import Flask, request, jsonify, Response, send_file
from flask_cors import CORS
import yt_dlp

# ==============================
# CONFIGURACIÓN
# ==============================
class Config:
    PORT = int(os.environ.get('PORT', 10000))
    HOST = '0.0.0.0'
    MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB
    COOKIES_FILE = 'cookies.txt'  # Nombre fijo

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
    return logging.getLogger(__name__)

logger = setup_logging()

# ==============================
# CLASE DESCARGADOR ULTRA SIMPLE
# ==============================
class YouTubeDownloader:
    def __init__(self):
        self.temp_dir = None
        self.output_path = None
        self.cookies_config = {}
        
        # Cargar cookies si existen
        if os.path.exists(Config.COOKIES_FILE):
            try:
                file_size = os.path.getsize(Config.COOKIES_FILE)
                if file_size > 100:  # Archivo no vacío
                    self.cookies_config = {'cookiefile': Config.COOKIES_FILE}
                    logger.info(f"✅ Cookies cargadas ({file_size} bytes)")
                else:
                    logger.warning("⚠️  Archivo de cookies vacío")
            except:
                logger.warning("⚠️  Error leyendo cookies")
    
    def _get_base_options(self):
        """Opciones base ultra simples"""
        base_opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'no_color': True,
            'noprogress': True,
            'socket_timeout': 30,
            'retries': 3,
            'fragment_retries': 3,
            'noplaylist': True,
            
            # Headers básicos
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': '*/*',
            },
        }
        
        # Añadir cookies si están disponibles
        if self.cookies_config:
            base_opts.update(self.cookies_config)
        
        return base_opts
    
    def get_info(self, url: str) -> Dict[str, Any]:
        """Obtiene información del video"""
        try:
            ydl_opts = self._get_base_options()
            ydl_opts['skip_download'] = True
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    return {'success': False, 'error': 'Video no encontrado'}
                
                # Formatear duración
                duration = info.get('duration', 0)
                if duration > 0:
                    minutes = duration // 60
                    seconds = duration % 60
                    duration_str = f"{minutes}:{seconds:02d}"
                else:
                    duration_str = "Desconocida"
                
                return {
                    'success': True,
                    'title': info.get('title', 'Video sin título'),
                    'duration': duration_str,
                    'duration_seconds': duration,
                    'uploader': info.get('uploader', 'Desconocido'),
                    'view_count': info.get('view_count', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'available': True,
                    'has_cookies': bool(self.cookies_config)
                }
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error en get_info: {error_msg}")
            
            if "Private" in error_msg or "Sign in" in error_msg:
                return {
                    'success': False, 
                    'error': 'Video privado o requiere login',
                    'has_cookies': bool(self.cookies_config)
                }
            else:
                return {'success': False, 'error': 'Error obteniendo información'}
    
    def download_audio(self, url: str) -> Dict[str, Any]:
        """Descarga audio - MÉTODO SIMPLE SIN RENOMBRAR PROBLEMÁTICO"""
        self.temp_dir = tempfile.mkdtemp(prefix="yt_audio_")
        start_time = time.time()
        
        try:
            # Formato SIMPLE: mejor audio disponible
            ydl_opts = self._get_base_options()
            ydl_opts.update({
                'outtmpl': os.path.join(self.temp_dir, 'audio.%(ext)s'),  # Nombre fijo
                'format': 'bestaudio',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                }],
                'keepvideo': False,
            })
            
            logger.info(f"Descargando audio: {url}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'audio') if info else 'audio'
            
            # Buscar archivo MP3 (usará el nombre fijo 'audio.mp3')
            mp3_file = os.path.join(self.temp_dir, 'audio.mp3')
            
            if os.path.exists(mp3_file):
                self.output_path = mp3_file
            else:
                # Buscar cualquier archivo MP3
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        if file.endswith('.mp3'):
                            self.output_path = os.path.join(root, file)
                            break
            
            if not self.output_path or not os.path.exists(self.output_path):
                return {'success': False, 'error': 'No se generó archivo MP3'}
            
            file_size = os.path.getsize(self.output_path)
            
            if file_size == 0:
                return {'success': False, 'error': 'Archivo vacío'}
            
            if file_size > Config.MAX_FILE_SIZE:
                return {'success': False, 'error': 'Archivo muy grande'}
            
            # Crear nombre de archivo seguro SIN renombrar el archivo original
            safe_title = ''.join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()[:50]
            download_filename = f"{safe_title}.mp3"
            
            download_time = time.time() - start_time
            
            return {
                'success': True,
                'filename': download_filename,  # Nombre para la descarga
                'actual_filename': os.path.basename(self.output_path),  # Nombre real
                'filepath': self.output_path,  # Ruta real
                'filesize': file_size,
                'filesize_mb': round(file_size / (1024 * 1024), 2),
                'download_time': round(download_time, 2),
                'title': title,
                'type': 'audio',
                'format': 'mp3'
            }
                
        except Exception as e:
            logger.error(f"Error descargando audio: {e}")
            return {'success': False, 'error': str(e)[:200]}
    
    def download_video(self, url: str) -> Dict[str, Any]:
        """Descarga video - MÉTODO SIMPLE"""
        self.temp_dir = tempfile.mkdtemp(prefix="yt_video_")
        start_time = time.time()
        
        try:
            # Formato SIMPLE: mejor video MP4 disponible
            ydl_opts = self._get_base_options()
            ydl_opts.update({
                'outtmpl': os.path.join(self.temp_dir, 'video.%(ext)s'),  # Nombre fijo
                'format': 'best[ext=mp4]/best',
            })
            
            logger.info(f"Descargando video: {url}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'video') if info else 'video'
            
            # Buscar archivo de video
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if any(file.endswith(ext) for ext in ['.mp4', '.webm', '.mkv']):
                        self.output_path = os.path.join(root, file)
                        break
            
            if not self.output_path or not os.path.exists(self.output_path):
                return {'success': False, 'error': 'No se generó archivo de video'}
            
            file_size = os.path.getsize(self.output_path)
            
            if file_size == 0:
                return {'success': False, 'error': 'Archivo vacío'}
            
            if file_size > Config.MAX_FILE_SIZE:
                return {'success': False, 'error': 'Archivo muy grande'}
            
            # Crear nombre de archivo seguro SIN renombrar
            safe_title = ''.join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()[:50]
            file_ext = os.path.splitext(self.output_path)[1] or '.mp4'
            download_filename = f"{safe_title}{file_ext}"
            
            # Determinar mimetype
            if self.output_path.endswith('.mp4'):
                mimetype = 'video/mp4'
            elif self.output_path.endswith('.webm'):
                mimetype = 'video/webm'
            elif self.output_path.endswith('.mkv'):
                mimetype = 'video/x-matroska'
            else:
                mimetype = 'application/octet-stream'
            
            download_time = time.time() - start_time
            
            return {
                'success': True,
                'filename': download_filename,
                'actual_filename': os.path.basename(self.output_path),
                'filepath': self.output_path,
                'filesize': file_size,
                'filesize_mb': round(file_size / (1024 * 1024), 2),
                'download_time': round(download_time, 2),
                'title': title,
                'type': 'video',
                'format': file_ext.replace('.', ''),
                'mimetype': mimetype
            }
                
        except Exception as e:
            logger.error(f"Error descargando video: {e}")
            return {'success': False, 'error': str(e)[:200]}
    
    def cleanup(self):
        """Limpia archivos temporales"""
        try:
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception as e:
            logger.error(f"Error limpiando: {e}")

# ==============================
# INICIALIZAR FLASK APP
# ==============================
app = Flask(__name__)
CORS(app)

# ==============================
# ENDPOINTS API
# ==============================

@app.route('/')
def home():
    """Endpoint principal"""
    return jsonify({
        'service': 'YouTube Downloader API',
        'version': '7.0 - Simple & Funcional',
        'status': 'online',
        'has_cookies': os.path.exists(Config.COOKIES_FILE),
        'endpoints': {
            'GET /': 'Esta página',
            'GET /health': 'Estado del servidor',
            'GET /info?url=URL': 'Información del video',
            'POST /info': 'Información del video (POST)',
            'POST /download/audio': 'Descargar audio MP3',
            'POST /download/video': 'Descargar video'
        },
        'note': 'Usa cualquier formato disponible'
    })

@app.route('/health')
def health():
    """Health check"""
    has_cookies = os.path.exists(Config.COOKIES_FILE) and os.path.getsize(Config.COOKIES_FILE) > 100
    
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'cookies': {
            'exists': os.path.exists(Config.COOKIES_FILE),
            'size': os.path.getsize(Config.COOKIES_FILE) if os.path.exists(Config.COOKIES_FILE) else 0,
            'valid': has_cookies
        }
    })

@app.route('/info', methods=['GET', 'POST'])
def get_info():
    """Obtiene información del video"""
    try:
        # Manejar GET y POST
        if request.method == 'POST':
            if request.is_json:
                data = request.get_json()
            elif request.form:
                data = request.form.to_dict()
            else:
                # Texto plano
                body_text = request.get_data(as_text=True)
                data = {'url': body_text.strip()} if body_text else {}
        else:  # GET
            data = request.args
        
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        if not ('youtube.com' in url or 'youtu.be' in url):
            return jsonify({'success': False, 'error': 'URL de YouTube inválida'}), 400
        
        logger.info(f"Info solicitada para: {url[:50]}...")
        
        downloader = YouTubeDownloader()
        result = downloader.get_info(url)
        downloader.cleanup()
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error en /info: {e}")
        return jsonify({'success': False, 'error': 'Error interno'}), 500

@app.route('/download/audio', methods=['POST'])
def download_audio():
    """Descarga audio MP3 - SIN RENOMBRAR PROBLEMÁTICO"""
    try:
        # Obtener URL
        if request.is_json:
            data = request.get_json()
        elif request.form:
            data = request.form.to_dict()
        else:
            body_text = request.get_data(as_text=True)
            data = {'url': body_text.strip()} if body_text else {}
        
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        if not ('youtube.com' in url or 'youtu.be' in url):
            return jsonify({'success': False, 'error': 'URL de YouTube inválida'}), 400
        
        logger.info(f"Audio solicitado para: {url[:50]}...")
        
        downloader = YouTubeDownloader()
        result = downloader.download_audio(url)
        
        if not result['success']:
            downloader.cleanup()
            return jsonify(result), 400
        
        # Enviar archivo CON NOMBRE PERSONALIZADO pero SIN RENOMBRAR el archivo físico
        response = send_file(
            result['filepath'],
            as_attachment=True,
            download_name=result['filename'],  # Nombre para la descarga
            mimetype='audio/mpeg'
        )
        
        # Headers informativos
        response.headers['X-Download-Time'] = str(result['download_time'])
        response.headers['X-File-Size'] = str(result['filesize'])
        
        # Cleanup después de enviar
        @response.call_on_close
        def cleanup_after_send():
            downloader.cleanup()
        
        return response
        
    except Exception as e:
        logger.error(f"Error en /download/audio: {e}")
        return jsonify({'success': False, 'error': str(e)[:200]}), 500

@app.route('/download/video', methods=['POST'])
def download_video():
    """Descarga video"""
    try:
        # Obtener URL
        if request.is_json:
            data = request.get_json()
        elif request.form:
            data = request.form.to_dict()
        else:
            body_text = request.get_data(as_text=True)
            data = {'url': body_text.strip()} if body_text else {}
        
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        if not ('youtube.com' in url or 'youtu.be' in url):
            return jsonify({'success': False, 'error': 'URL de YouTube inválida'}), 400
        
        logger.info(f"Video solicitado para: {url[:50]}...")
        
        downloader = YouTubeDownloader()
        result = downloader.download_video(url)
        
        if not result['success']:
            downloader.cleanup()
            return jsonify(result), 400
        
        # Enviar archivo
        response = send_file(
            result['filepath'],
            as_attachment=True,
            download_name=result['filename'],
            mimetype=result['mimetype']
        )
        
        # Headers informativos
        response.headers['X-Download-Time'] = str(result['download_time'])
        response.headers['X-File-Size'] = str(result['filesize'])
        
        # Cleanup después de enviar
        @response.call_on_close
        def cleanup_after_send():
            downloader.cleanup()
        
        return response
        
    except Exception as e:
        logger.error(f"Error en /download/video: {e}")
        return jsonify({'success': False, 'error': str(e)[:200]}), 500

@app.route('/test/cookies', methods=['GET'])
def test_cookies():
    """Probar si las cookies funcionan"""
    has_cookies = os.path.exists(Config.COOKIES_FILE) and os.path.getsize(Config.COOKIES_FILE) > 100
    
    if not has_cookies:
        return jsonify({
            'success': False,
            'message': 'No hay cookies válidas',
            'file_exists': os.path.exists(Config.COOKIES_FILE),
            'file_size': os.path.getsize(Config.COOKIES_FILE) if os.path.exists(Config.COOKIES_FILE) else 0
        })
    
    # Probar con un video público
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    
    try:
        downloader = YouTubeDownloader()
        result = downloader.get_info(test_url)
        downloader.cleanup()
        
        if result['success']:
            return jsonify({
                'success': True,
                'message': 'Cookies funcionan correctamente',
                'test_video': result['title']
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Cookies pueden no funcionar',
                'error': result['error']
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error probando cookies',
            'error': str(e)
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
    logger.error(f"Error 500: {error}")
    return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

# ==============================
# INICIALIZACIÓN
# ==============================
if __name__ == '__main__':
    # SOLO para desarrollo local
    # En Render se ejecuta con: gunicorn app:app
    
    print("\n" + "="*60)
    print("🚀 SERVIDOR YOUTUBE - VERSIÓN SIMPLE")
    print("="*60)
    print(f"✅ Puerto: {Config.PORT}")
    print(f"✅ Host: {Config.HOST}")
    
    if os.path.exists(Config.COOKIES_FILE):
        file_size = os.path.getsize(Config.COOKIES_FILE)
        print(f"✅ Cookies: {Config.COOKIES_FILE} ({file_size} bytes)")
    else:
        print("⚠️  Cookies: No encontrado (modo guest)")
    
    print("="*60)
    print("📡 Endpoints disponibles:")
    print("  GET /info?url=URL     - Información del video")
    print("  POST /download/audio  - Descargar audio MP3")
    print("  POST /download/video  - Descargar video")
    print("  GET /test/cookies     - Probar cookies")
    print("="*60 + "\n")
    
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=False,
        threaded=True
    )
