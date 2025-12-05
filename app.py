#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE PARA RENDER.COM - VERSIÓN CORREGIDA
Versión: 3.0 - Optimizado para Render con cookies
"""

import os
import sys
import json
import logging
import tempfile
import shutil
import time
import mimetypes
from datetime import datetime
from typing import Dict, Any, Optional

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
    COOKIES_FILE = 'cookies.txt'  # Archivo de cookies en el repositorio

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
    logging.getLogger('yt_dlp').setLevel(logging.WARNING)
    return logging.getLogger(__name__)

logger = setup_logging()

# ==============================
# MANEJO DE COOKIES
# ==============================
def load_cookies_config():
    """Carga configuración de cookies de manera segura"""
    cookies_config = {}
    
    # Verificar si existe el archivo de cookies
    if os.path.exists(Config.COOKIES_FILE):
        try:
            # Validar que el archivo no esté vacío y tenga formato correcto
            with open(Config.COOKIES_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
                
            if content.strip() and '# Netscape HTTP Cookie File' in content:
                cookies_config['cookiefile'] = Config.COOKIES_FILE
                logger.info(f"✅ Cookies cargadas desde: {Config.COOKIES_FILE}")
                logger.info(f"   Tamaño: {len(content)} bytes")
            else:
                logger.warning(f"⚠️  Archivo de cookies vacío o formato incorrecto")
                
        except Exception as e:
            logger.error(f"❌ Error leyendo cookies: {e}")
    else:
        logger.info("ℹ️  No se encontró archivo de cookies. Modo guest.")
    
    return cookies_config

# ==============================
# CLASE DESCARGADOR OPTIMIZADA
# ==============================
class YouTubeDownloader:
    def __init__(self):
        self.temp_dir = None
        self.output_path = None
        self.cookies_config = load_cookies_config()
        self.cookies_working = False
        
        # Probar cookies con un método seguro
        self._test_cookies_safely()
    
    def _test_cookies_safely(self):
        """Prueba cookies de manera segura sin causar errores"""
        if not self.cookies_config:
            self.cookies_working = False
            return
        
        try:
            # URL de prueba simple
            test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            
            ydl_opts = {
                'cookiefile': self.cookies_config.get('cookiefile'),
                'quiet': True,
                'skip_download': True,
                'no_warnings': True,
                'ignoreerrors': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(test_url, download=False)
                
                if info and info.get('title'):
                    self.cookies_working = True
                    logger.info(f"✅ Cookies funcionan correctamente")
                else:
                    self.cookies_working = False
                    logger.warning(f"⚠️  Cookies podrían no funcionar")
                    
        except Exception as e:
            self.cookies_working = False
            logger.warning(f"⚠️  Error probando cookies: {str(e)[:100]}")
    
    def sanitize_filename(self, filename):
        """Limpia nombre de archivo para ser seguro"""
        # Remover caracteres peligrosos
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        
        # Limitar longitud
        filename = filename[:150]
        
        return filename.strip()
    
    def _get_base_options(self):
        """Opciones base optimizadas para Render"""
        base_opts = {
            'quiet': True,
            'no_warnings': True,
            'no_color': True,
            'noprogress': True,
            'ignoreerrors': True,
            'no_check_certificate': True,
            'socket_timeout': 30,
            'retries': 3,
            'fragment_retries': 3,
            'concurrent_fragment_downloads': 2,
            'noplaylist': True,
            
            # Headers genéricos para evitar bloqueos
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.youtube.com/',
            },
            
            # Evitar descargas grandes innecesarias
            'max_filesize': Config.MAX_FILE_SIZE,
            
            # Throttle para ser buen ciudadano
            'throttledratelimit': 1000000,  # 1 MB/s
        }
        
        # Añadir cookies si están disponibles
        if self.cookies_config and self.cookies_working:
            base_opts.update(self.cookies_config)
            logger.debug("Usando cookies para la descarga")
        
        return base_opts
    
    def get_info(self, url: str) -> Dict[str, Any]:
        """Obtiene información del video de manera segura"""
        try:
            ydl_opts = self._get_base_options()
            ydl_opts['skip_download'] = True
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    return {'success': False, 'error': 'No se pudo obtener información del video'}
                
                # Formatear duración
                duration = info.get('duration', 0)
                if duration > 0:
                    hours = duration // 3600
                    minutes = (duration % 3600) // 60
                    seconds = duration % 60
                    
                    if hours > 0:
                        duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                    else:
                        duration_str = f"{minutes:02d}:{seconds:02d}"
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
                    'has_cookies': self.cookies_working,
                    'available': True
                }
                
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            if "Private" in error_msg or "Sign in" in error_msg:
                return {'success': False, 'error': 'Video privado o requiere inicio de sesión'}
            else:
                return {'success': False, 'error': error_msg[:150]}
        except Exception as e:
            logger.error(f"Error en get_info: {e}")
            return {'success': False, 'error': 'Error al obtener información'}
    
    def _download_media(self, url: str, media_type: str, quality: Optional[str] = None) -> Dict[str, Any]:
        """Método genérico para descargar audio o video"""
        self.temp_dir = tempfile.mkdtemp(prefix=f"yt_{media_type}_")
        start_time = time.time()
        
        try:
            ydl_opts = self._get_base_options()
            
            if media_type == 'audio':
                # Formato para audio - usar el mejor audio disponible
                ydl_opts['format'] = 'bestaudio/best'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': quality if quality in ['128', '192', '256', '320'] else '192',
                }]
                ydl_opts['keepvideo'] = False
                file_ext = 'mp3'
                mimetype = 'audio/mpeg'
            else:
                # Formato para video - buscar el mejor disponible
                if quality == 'best':
                    ydl_opts['format'] = 'best[ext=mp4]/best'
                elif quality == '720':
                    ydl_opts['format'] = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
                elif quality == '480':
                    ydl_opts['format'] = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
                elif quality == '360':
                    ydl_opts['format'] = 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
                else:
                    # Por defecto, buscar cualquier formato de video
                    ydl_opts['format'] = 'best[ext=mp4]/best'
                
                ydl_opts['merge_output_format'] = 'mp4'
                file_ext = 'mp4'
                mimetype = 'video/mp4'
            
            ydl_opts['outtmpl'] = os.path.join(self.temp_dir, '%(title)s.%(ext)s')
            
            logger.info(f"Descargando {media_type}: {url}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'descarga') if info else 'descarga'
            
            # Buscar archivo descargado
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file.endswith(f'.{file_ext}') or (media_type == 'video' and file.endswith(('.mp4', '.webm', '.mkv'))):
                        self.output_path = os.path.join(root, file)
                        break
            
            if not self.output_path:
                # Intentar encontrar cualquier archivo
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        self.output_path = os.path.join(root, file)
                        break
            
            if not self.output_path or not os.path.exists(self.output_path):
                return {'success': False, 'error': 'No se pudo generar el archivo'}
            
            file_size = os.path.getsize(self.output_path)
            
            if file_size == 0:
                return {'success': False, 'error': 'Archivo vacío'}
            
            if file_size > Config.MAX_FILE_SIZE:
                return {'success': False, 'error': f'Archivo demasiado grande ({file_size/(1024*1024):.1f}MB)'}
            
            # Sanitizar nombre y asegurar extensión correcta
            clean_title = self.sanitize_filename(title)
            actual_ext = os.path.splitext(self.output_path)[1]
            final_filename = f"{clean_title}{actual_ext}"
            final_path = os.path.join(self.temp_dir, final_filename)
            
            if self.output_path != final_path:
                if os.path.exists(final_path):
                    os.remove(final_path)
                os.rename(self.output_path, final_path)
                self.output_path = final_path
            
            download_time = time.time() - start_time
            
            return {
                'success': True,
                'filename': final_filename,
                'filepath': self.output_path,
                'filesize': file_size,
                'filesize_mb': round(file_size / (1024 * 1024), 2),
                'download_time': round(download_time, 2),
                'title': title,
                'type': media_type,
                'mimetype': mimetype,
                'has_cookies': self.cookies_working
            }
                
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            if "format is not available" in error_msg:
                return {'success': False, 'error': 'Formato solicitado no disponible'}
            else:
                return {'success': False, 'error': error_msg[:150]}
        except Exception as e:
            logger.error(f"Error descargando {media_type}: {e}")
            return {'success': False, 'error': f'Error al descargar {media_type}'}
    
    def download_audio(self, url: str, quality: str = '192') -> Dict[str, Any]:
        """Descarga audio"""
        return self._download_media(url, 'audio', quality)
    
    def download_video(self, url: str, quality: str = '720') -> Dict[str, Any]:
        """Descarga video"""
        return self._download_media(url, 'video', quality)
    
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
        'version': '3.0 - Render Optimized',
        'status': 'online',
        'cookies': load_cookies_config() != {},
        'endpoints': {
            'GET /': 'Esta página',
            'GET /health': 'Estado del servidor',
            'GET /info': 'Información del video',
            'POST /download/audio': 'Descargar audio MP3',
            'POST /download/video': 'Descargar video MP4'
        },
        'limits': {
            'max_file_size': f'{Config.MAX_FILE_SIZE/(1024*1024)}MB',
            'timeout': '30 segundos'
        }
    })

@app.route('/health')
def health():
    """Health check para Render"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'cookies': os.path.exists(Config.COOKIES_FILE)
    })

@app.route('/info', methods=['GET'])
def get_info():
    """Obtiene información del video"""
    try:
        url = request.args.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        if 'youtube.com' not in url and 'youtu.be' not in url:
            return jsonify({'success': False, 'error': 'URL de YouTube inválida'}), 400
        
        downloader = YouTubeDownloader()
        result = downloader.get_info(url)
        downloader.cleanup()
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error en /info: {e}")
        return jsonify({'success': False, 'error': 'Error interno'}), 500

@app.route('/download/audio', methods=['POST'])
def download_audio():
    """Descarga audio MP3"""
    try:
        # Obtener datos de la solicitud
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        url = data.get('url', '').strip()
        quality = data.get('quality', '192')
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        if 'youtube.com' not in url and 'youtu.be' not in url:
            return jsonify({'success': False, 'error': 'URL de YouTube inválida'}), 400
        
        logger.info(f"Solicitud de audio: {url[:50]}...")
        
        downloader = YouTubeDownloader()
        result = downloader.download_audio(url, quality)
        
        if not result['success']:
            downloader.cleanup()
            return jsonify(result), 400
        
        # Preparar respuesta con el archivo
        response = send_file(
            result['filepath'],
            as_attachment=True,
            download_name=result['filename'],
            mimetype=result['mimetype']
        )
        
        # Añadir headers informativos
        response.headers['X-Download-Time'] = str(result['download_time'])
        response.headers['X-File-Size'] = str(result['filesize'])
        response.headers['X-Has-Cookies'] = str(result['has_cookies'])
        
        # Limpiar después de enviar
        @response.call_on_close
        def cleanup_after_send():
            downloader.cleanup()
        
        return response
        
    except Exception as e:
        logger.error(f"Error en /download/audio: {e}")
        return jsonify({'success': False, 'error': str(e)[:200]}), 500

@app.route('/download/video', methods=['POST'])
def download_video():
    """Descarga video MP4"""
    try:
        # Obtener datos de la solicitud
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        url = data.get('url', '').strip()
        quality = data.get('quality', '720')
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        if 'youtube.com' not in url and 'youtu.be' not in url:
            return jsonify({'success': False, 'error': 'URL de YouTube inválida'}), 400
        
        logger.info(f"Solicitud de video ({quality}p): {url[:50]}...")
        
        downloader = YouTubeDownloader()
        result = downloader.download_video(url, quality)
        
        if not result['success']:
            downloader.cleanup()
            return jsonify(result), 400
        
        # Determinar mimetype basado en extensión
        filename = result['filename']
        if filename.endswith('.mp4'):
            mimetype = 'video/mp4'
        elif filename.endswith('.webm'):
            mimetype = 'video/webm'
        elif filename.endswith('.mkv'):
            mimetype = 'video/x-matroska'
        else:
            mimetype = 'application/octet-stream'
        
        # Preparar respuesta con el archivo
        response = send_file(
            result['filepath'],
            as_attachment=True,
            download_name=result['filename'],
            mimetype=mimetype
        )
        
        # Añadir headers informativos
        response.headers['X-Download-Time'] = str(result['download_time'])
        response.headers['X-File-Size'] = str(result['filesize'])
        response.headers['X-Has-Cookies'] = str(result['has_cookies'])
        response.headers['X-Quality'] = quality
        
        # Limpiar después de enviar
        @response.call_on_close
        def cleanup_after_send():
            downloader.cleanup()
        
        return response
        
    except Exception as e:
        logger.error(f"Error en /download/video: {e}")
        return jsonify({'success': False, 'error': str(e)[:200]}), 500

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
    print("🚀 SERVIDOR YOUTUBE PARA RENDER.COM")
    print("="*60)
    print(f"✅ Puerto: {Config.PORT}")
    print(f"✅ Host: {Config.HOST}")
    
    # Verificar cookies
    if os.path.exists(Config.COOKIES_FILE):
        print(f"✅ Cookies: {Config.COOKIES_FILE} encontrado")
    else:
        print("⚠️  Cookies: No encontrado (modo guest)")
    
    print("="*60)
    print("📡 Endpoints disponibles:")
    print("  GET  /               - Información del API")
    print("  GET  /health         - Estado del servidor")
    print("  GET  /info?url=URL   - Información del video")
    print("  POST /download/audio - Descargar audio MP3")
    print("  POST /download/video - Descargar video MP4")
    print("="*60 + "\n")
    
    # Usar Waitress para producción (compatible con Render)
    try:
        from waitress import serve
        print("🚀 Iniciando con Waitress (producción)...")
        serve(app, host=Config.HOST, port=Config.PORT)
    except ImportError:
        print("⚠️  Waitress no disponible, usando servidor de desarrollo...")
        app.run(
            host=Config.HOST,
            port=Config.PORT,
            debug=False,
            threaded=True,
            use_reloader=False
        )
