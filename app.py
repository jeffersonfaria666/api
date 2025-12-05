#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE DEFINITIVO PARA RENDER.COM
Versión: 5.0 - Totalmente corregido y optimizado
"""

import os
import sys
import json
import logging
import tempfile
import shutil
import time
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
    COOKIES_FILE = 'cookies.txt'
    
    # Video de prueba que SIEMPRE funciona
    TEST_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

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
# MANEJO DE COOKIES SIMPLIFICADO
# ==============================
def get_cookies_config():
    """Obtiene configuración de cookies de manera simple"""
    
    # Verificar si existe el archivo
    if os.path.exists(Config.COOKIES_FILE):
        try:
            with open(Config.COOKIES_FILE, 'r', encoding='utf-8') as f:
                content = f.read(1000)  # Leer solo un poco
                
            # Verificar que sea un archivo válido
            if content and len(content) > 100 and ('# Netscape' in content or '.youtube.com' in content):
                logger.info(f"✅ Archivo de cookies encontrado: {Config.COOKIES_FILE}")
                return {'cookiefile': Config.COOKIES_FILE}
        except Exception as e:
            logger.warning(f"⚠️  Error leyendo cookies: {e}")
    
    logger.info("ℹ️  Modo sin cookies (guest)")
    return {}

# ==============================
# CLASE DESCARGADOR OPTIMIZADA
# ==============================
class YouTubeDownloader:
    def __init__(self):
        self.temp_dir = None
        self.output_path = None
        self.cookies_config = get_cookies_config()
    
    def sanitize_filename(self, filename):
        """Limpia el nombre del archivo"""
        # Remover caracteres problemáticos
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename[:100]
    
    def _get_base_options(self):
        """Opciones base optimizadas"""
        base_opts = {
            'quiet': True,
            'no_warnings': True,
            'no_color': True,
            'ignoreerrors': True,
            'no_check_certificate': True,
            'socket_timeout': 30,
            'retries': 3,
            'fragment_retries': 3,
            'concurrent_fragment_downloads': 2,
            'noplaylist': True,
            'noprogress': True,
            
            # Headers para evitar bloqueos
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.youtube.com/',
            },
            
            # Configuración para YouTube
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios', 'web'],
                    'player_skip': ['configs', 'js'],
                }
            },
        }
        
        # Añadir cookies si están disponibles
        if self.cookies_config:
            base_opts.update(self.cookies_config)
        
        return base_opts
    
    def get_info(self, url: str) -> Dict[str, Any]:
        """Obtiene información del video - ACEPTA CUALQUIER VIDEO DISPONIBLE"""
        try:
            ydl_opts = self._get_base_options()
            ydl_opts['skip_download'] = True
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    return {
                        'success': False, 
                        'error': 'No se pudo obtener información del video'
                    }
                
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
                    'uploader': info.get('uploader', 'Desconocido'),
                    'view_count': info.get('view_count', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'available': True,
                    'has_cookies': bool(self.cookies_config)
                }
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error en get_info: {error_msg}")
            
            # Mensajes de error más amigables
            if "Private" in error_msg or "Sign in" in error_msg:
                return {
                    'success': False, 
                    'error': 'Este video es privado o requiere inicio de sesión',
                    'has_cookies': bool(self.cookies_config)
                }
            elif "not available" in error_msg or "unavailable" in error_msg:
                return {'success': False, 'error': 'Video no disponible en tu región'}
            else:
                return {'success': False, 'error': 'Error al obtener información del video'}
    
    def download_audio(self, url: str) -> Dict[str, Any]:
        """Descarga audio - USA EL FORMATO DISPONIBLE"""
        self.temp_dir = tempfile.mkdtemp(prefix="yt_audio_")
        start_time = time.time()
        
        try:
            ydl_opts = self._get_base_options()
            ydl_opts.update({
                'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
                # Formato FLEXIBLE: cualquier audio disponible
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'keepvideo': False,
            })
            
            logger.info(f"Descargando audio de: {url}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'audio') if info else 'audio'
            
            # Buscar cualquier archivo de audio
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in ['.mp3', '.m4a', '.webm', '.opus']):
                        self.output_path = os.path.join(root, file)
                        break
            
            if not self.output_path:
                # Buscar cualquier archivo
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        self.output_path = os.path.join(root, file)
                        break
            
            if not self.output_path:
                return {'success': False, 'error': 'No se pudo generar el archivo de audio'}
            
            file_size = os.path.getsize(self.output_path)
            
            if file_size == 0:
                return {'success': False, 'error': 'Archivo vacío'}
            
            if file_size > Config.MAX_FILE_SIZE:
                os.remove(self.output_path)
                return {'success': False, 'error': 'Archivo demasiado grande'}
            
            # Renombrar a MP3 si es necesario
            clean_title = self.sanitize_filename(title)
            new_filename = f"{clean_title}.mp3"
            new_path = os.path.join(self.temp_dir, new_filename)
            
            if os.path.exists(new_path):
                os.remove(new_path)
            
            # Cambiar extensión si no es MP3
            if not self.output_path.endswith('.mp3'):
                base_name = os.path.splitext(self.output_path)[0]
                mp3_path = base_name + '.mp3'
                if os.path.exists(mp3_path):
                    self.output_path = mp3_path
                else:
                    os.rename(self.output_path, new_path)
                    self.output_path = new_path
            else:
                os.rename(self.output_path, new_path)
                self.output_path = new_path
            
            file_size = os.path.getsize(self.output_path)
            download_time = time.time() - start_time
            
            return {
                'success': True,
                'filename': new_filename,
                'filepath': self.output_path,
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
        """Descarga video - USA CUALQUIER FORMATO DISPONIBLE"""
        self.temp_dir = tempfile.mkdtemp(prefix="yt_video_")
        start_time = time.time()
        
        try:
            ydl_opts = self._get_base_options()
            ydl_opts.update({
                'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
                # Formato MÁS FLEXIBLE: cualquier video disponible
                'format': 'best[ext=mp4]/best',
            })
            
            logger.info(f"Descargando video de: {url}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'video') if info else 'video'
            
            # Buscar cualquier archivo de video
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in ['.mp4', '.webm', '.mkv']):
                        self.output_path = os.path.join(root, file)
                        break
            
            if not self.output_path:
                # Buscar cualquier archivo
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        self.output_path = os.path.join(root, file)
                        break
            
            if not self.output_path:
                return {'success': False, 'error': 'No se pudo generar el archivo de video'}
            
            file_size = os.path.getsize(self.output_path)
            
            if file_size == 0:
                return {'success': False, 'error': 'Archivo vacío'}
            
            if file_size > Config.MAX_FILE_SIZE:
                os.remove(self.output_path)
                return {'success': False, 'error': 'Archivo demasiado grande'}
            
            # Renombrar si es necesario
            clean_title = self.sanitize_filename(title)
            file_ext = os.path.splitext(self.output_path)[1] or '.mp4'
            new_filename = f"{clean_title}{file_ext}"
            new_path = os.path.join(self.temp_dir, new_filename)
            
            if os.path.exists(new_path):
                os.remove(new_path)
            
            if self.output_path != new_path:
                os.rename(self.output_path, new_path)
                self.output_path = new_path
            
            file_size = os.path.getsize(self.output_path)
            download_time = time.time() - start_time
            
            # Determinar mimetype
            if self.output_path.endswith('.mp4'):
                mimetype = 'video/mp4'
            elif self.output_path.endswith('.webm'):
                mimetype = 'video/webm'
            elif self.output_path.endswith('.mkv'):
                mimetype = 'video/x-matroska'
            else:
                mimetype = 'application/octet-stream'
            
            return {
                'success': True,
                'filename': new_filename,
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
        'version': '5.0 - Definitivo',
        'status': 'online',
        'has_cookies': os.path.exists(Config.COOKIES_FILE),
        'endpoints': {
            'GET /': 'Esta página',
            'GET /health': 'Estado del servidor',
            'GET /info?url=URL': 'Información del video',
            'POST /info': 'Información del video (POST también)',
            'POST /download/audio': 'Descargar audio MP3',
            'POST /download/video': 'Descargar video'
        },
        'note': 'Usa cualquier formato disponible automáticamente'
    })

@app.route('/health')
def health():
    """Health check"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'cookies_file_exists': os.path.exists(Config.COOKIES_FILE)
    })

@app.route('/info', methods=['GET', 'POST'])
def get_info():
    """Obtiene información del video - ACEPTA GET Y POST"""
    try:
        # Manejar tanto GET como POST
        if request.method == 'POST':
            if request.is_json:
                data = request.get_json()
            elif request.form:
                data = request.form.to_dict()
            else:
                data = {}
            
            # También intentar leer del body si es texto plano
            if not data.get('url'):
                try:
                    body_data = request.get_data(as_text=True)
                    if body_data and 'http' in body_data:
                        data['url'] = body_data.strip()
                except:
                    pass
        else:  # GET
            data = request.args.to_dict()
        
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        # Validación básica de URL
        if not ('youtube.com' in url or 'youtu.be' in url):
            return jsonify({'success': False, 'error': 'URL de YouTube inválida'}), 400
        
        logger.info(f"Solicitud info para: {url[:50]}...")
        
        downloader = YouTubeDownloader()
        result = downloader.get_info(url)
        downloader.cleanup()
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error en /info: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

@app.route('/download/audio', methods=['POST'])
def download_audio():
    """Descarga audio MP3"""
    try:
        # Manejar diferentes formatos de solicitud
        if request.is_json:
            data = request.get_json()
        elif request.form:
            data = request.form.to_dict()
        else:
            # Intentar leer como texto plano
            body_text = request.get_data(as_text=True)
            data = {'url': body_text.strip()} if body_text else {}
        
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        if not ('youtube.com' in url or 'youtu.be' in url):
            return jsonify({'success': False, 'error': 'URL de YouTube inválida'}), 400
        
        logger.info(f"Solicitud audio para: {url[:50]}...")
        
        downloader = YouTubeDownloader()
        result = downloader.download_audio(url)
        
        if not result['success']:
            downloader.cleanup()
            return jsonify(result), 400
        
        # Preparar respuesta
        response = send_file(
            result['filepath'],
            as_attachment=True,
            download_name=result['filename'],
            mimetype='audio/mpeg'
        )
        
        # Headers informativos
        response.headers['X-Download-Time'] = str(result['download_time'])
        response.headers['X-File-Size'] = str(result['filesize'])
        
        # Configurar cleanup
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
        # Manejar diferentes formatos de solicitud
        if request.is_json:
            data = request.get_json()
        elif request.form:
            data = request.form.to_dict()
        else:
            # Intentar leer como texto plano
            body_text = request.get_data(as_text=True)
            data = {'url': body_text.strip()} if body_text else {}
        
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        if not ('youtube.com' in url or 'youtu.be' in url):
            return jsonify({'success': False, 'error': 'URL de YouTube inválida'}), 400
        
        logger.info(f"Solicitud video para: {url[:50]}...")
        
        downloader = YouTubeDownloader()
        result = downloader.download_video(url)
        
        if not result['success']:
            downloader.cleanup()
            return jsonify(result), 400
        
        # Preparar respuesta
        response = send_file(
            result['filepath'],
            as_attachment=True,
            download_name=result['filename'],
            mimetype=result['mimetype']
        )
        
        # Headers informativos
        response.headers['X-Download-Time'] = str(result['download_time'])
        response.headers['X-File-Size'] = str(result['filesize'])
        response.headers['X-Video-Format'] = result['format']
        
        # Configurar cleanup
        @response.call_on_close
        def cleanup_after_send():
            downloader.cleanup()
        
        return response
        
    except Exception as e:
        logger.error(f"Error en /download/video: {e}")
        return jsonify({'success': False, 'error': str(e)[:200]}), 500

@app.route('/test', methods=['GET'])
def test():
    """Endpoint de prueba"""
    downloader = YouTubeDownloader()
    result = downloader.get_info(Config.TEST_URL)
    downloader.cleanup()
    
    return jsonify({
        'test': 'success',
        'server': 'running',
        'test_url': Config.TEST_URL,
        'video_info': result
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
    # En Render, se ejecuta con: gunicorn app:app
    
    print("\n" + "="*60)
    print("🚀 SERVIDOR YOUTUBE - VERSIÓN DEFINITIVA")
    print("="*60)
    print(f"✅ Puerto: {Config.PORT}")
    print(f"✅ Host: {Config.HOST}")
    
    if os.path.exists(Config.COOKIES_FILE):
        print(f"✅ Cookies: {Config.COOKIES_FILE} encontrado")
    else:
        print("⚠️  Cookies: No encontrado (modo guest)")
    
    print("="*60)
    print("📡 Endpoints:")
    print("  GET/POST /info          - Información del video")
    print("  POST /download/audio    - Descargar audio MP3")
    print("  POST /download/video    - Descargar video")
    print("="*60)
    print("\n⚠️  NOTA: En Render se ejecuta con 'gunicorn app:app'")
    print("="*60 + "\n")
    
    # Solo ejecutar en desarrollo local
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=False,
        threaded=True,
        use_reloader=False
    )
