#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE PARA RENDER.COM CON COOKIES
Versión: Con cookies pre-configuradas y funcionando
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
# CONFIGURACIÓN RENDER CON COOKIES
# ==============================
class Config:
    PORT = int(os.environ.get('PORT', 10000))
    HOST = '0.0.0.0'
    MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB
    
    # Archivo de cookies (cambia esta ruta si usas otro nombre)
    COOKIES_FILE = os.environ.get('COOKIES_FILE', 'cookies.txt')
    
    # URL para probar cookies (usando tu cuenta)
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
# VERIFICAR Y CARGAR COOKIES
# ==============================
def load_cookies():
    """Carga y verifica las cookies"""
    
    cookies_config = {}
    cookies_file = Config.COOKIES_FILE
    
    if os.path.exists(cookies_file):
        file_size = os.path.getsize(cookies_file)
        
        # Verificar formato del archivo
        with open(cookies_file, 'r', encoding='utf-8') as f:
            content = f.read(500)  # Leer primeras 500 chars
        
        # Verificar si es formato Netscape válido
        is_netscape = "# Netscape HTTP Cookie File" in content
        has_cookies = any(line.strip() and not line.startswith('#') for line in content.split('\n'))
        
        if is_netscape and has_cookies:
            cookies_config['cookiefile'] = cookies_file
            
            # Contar cookies
            with open(cookies_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                cookie_count = sum(1 for line in lines if line.strip() and not line.startswith('#'))
            
            logger.info(f"✅ Cookies cargadas: {cookies_file}")
            logger.info(f"   Tamaño: {file_size} bytes")
            logger.info(f"   Formato: Netscape")
            logger.info(f"   Cookies: {cookie_count} encontradas")
            
            # Verificar cookies importantes
            important_cookies = ['LOGIN_INFO', 'SID', 'HSID', 'SSID', 'APISID', 'VISITOR_INFO1_LIVE']
            found_cookies = []
            
            for line in lines:
                for cookie in important_cookies:
                    if cookie in line and cookie not in found_cookies:
                        found_cookies.append(cookie)
            
            if found_cookies:
                logger.info(f"   Importantes: {', '.join(found_cookies)}")
            
            return cookies_config
        else:
            logger.warning(f"⚠️  Archivo no tiene formato Netscape válido")
    else:
        logger.warning(f"⚠️  No se encontró archivo de cookies: {cookies_file}")
    
    return cookies_config

# ==============================
# TESTEAR COOKIES CON YT-DLP
# ==============================
def test_cookies(cookies_config):
    """Testea si las cookies funcionan con YouTube"""
    
    if not cookies_config:
        logger.info("ℹ️  Sin cookies - modo anónimo")
        return False
    
    try:
        logger.info("🧪 Probando cookies con YouTube...")
        
        ydl_opts = {
            'cookiefile': cookies_config.get('cookiefile'),
            'quiet': True,
            'skip_download': True,
            'extract_flat': False,
            'no_warnings': True,
            'ignoreerrors': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Intentar obtener info de un video
            info = ydl.extract_info(Config.TEST_URL, download=False)
            
            if info:
                title = info.get('title', 'Desconocido')
                logger.info(f"✅ Cookies funcionan: '{title}'")
                return True
            else:
                logger.warning("⚠️  No se pudo obtener info del video")
                return False
                
    except yt_dlp.utils.DownloadError as e:
        if "Private video" in str(e) or "Sign in" in str(e):
            logger.info("✅ Las cookies funcionan (video privado/requiere login)")
            return True
        else:
            logger.warning(f"⚠️  Error con cookies: {str(e)[:100]}")
            return False
    except Exception as e:
        logger.warning(f"⚠️  Error testeando cookies: {str(e)[:100]}")
        return False

# ==============================
# DESCARGADOR CON COOKIES
# ==============================
class YouTubeDownloader:
    """Descargador optimizado con cookies"""
    
    def __init__(self):
        self.temp_dir = None
        self.output_path = None
        self.cookies_config = load_cookies()
        self.cookies_working = test_cookies(self.cookies_config)
    
    def sanitize_filename(self, filename):
        """Limpia el nombre de archivo"""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        # Remover emojis y caracteres especiales
        filename = ''.join(char for char in filename if ord(char) < 128)
        return filename[:100].strip()
    
    def _get_base_options(self):
        """Opciones base con cookies"""
        
        base_opts = {
            'quiet': True,
            'no_warnings': True,
            'no_color': True,
            'noprogress': True,
            'no_check_certificate': True,
            'ignoreerrors': True,
            'socket_timeout': 30,
            'retries': 10,
            'fragment_retries': 10,
            'concurrent_fragment_downloads': 4,
            'noplaylist': True,
            
            # Headers para evitar bloqueos
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Referer': 'https://www.youtube.com/',
            },
            
            # Configuración específica para YouTube
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios', 'web'],
                    'player_skip': ['configs', 'js'],
                    'skip': ['hls', 'dash'],
                }
            },
            
            # Throttling para evitar rate limits
            'sleep_interval': 2,
            'max_sleep_interval': 5,
            'throttledratelimit': 1048576,  # 1 MB/s mínimo
        }
        
        # Añadir cookies si están disponibles y funcionando
        if self.cookies_config and self.cookies_working:
            base_opts.update(self.cookies_config)
            base_opts['extractor_args']['youtube']['player_client'].append('tv')
            logger.info("🔑 Usando cookies para descarga")
        else:
            logger.info("👤 Modo anónimo (sin cookies)")
        
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
                hours = duration // 3600
                minutes = (duration % 3600) // 60
                seconds = duration % 60
                
                if hours > 0:
                    duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                else:
                    duration_str = f"{minutes:02d}:{seconds:02d}"
                
                # Obtener formatos disponibles
                formats = []
                if 'formats' in info:
                    for fmt in info['formats']:
                        if fmt.get('vcodec') != 'none':  # Video
                            quality = fmt.get('format_note', '')
                            if quality:
                                formats.append({
                                    'quality': quality,
                                    'ext': fmt.get('ext', ''),
                                    'filesize': fmt.get('filesize'),
                                    'format_id': fmt.get('format_id')
                                })
                
                return {
                    'success': True,
                    'title': info.get('title', 'Video sin título'),
                    'duration': duration_str,
                    'duration_seconds': duration,
                    'uploader': info.get('uploader', 'Desconocido'),
                    'view_count': info.get('view_count', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'has_cookies': self.cookies_working,
                    'formats': formats[:10] if formats else [],
                    'available': True
                }
                
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            if "Private video" in error_msg:
                return {'success': False, 'error': 'Video privado - Requiere cookies'}
            elif "Sign in" in error_msg:
                return {'success': False, 'error': 'Requiere inicio de sesión - Usa cookies'}
            else:
                return {'success': False, 'error': error_msg[:200]}
        except Exception as e:
            logger.error(f"Error obteniendo info: {e}")
            return {'success': False, 'error': str(e)[:200]}
    
    def download_audio(self, url: str, quality: str = '192') -> Dict[str, Any]:
        """Descarga audio en MP3"""
        self.temp_dir = tempfile.mkdtemp(prefix="yt_audio_")
        start_time = time.time()
        
        try:
            ydl_opts = self._get_base_options()
            ydl_opts.update({
                'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': quality,
                }],
                'keepvideo': False,
            })
            
            logger.info(f"Descargando audio: {url}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'audio') if info else 'audio'
            
            # Buscar archivo MP3
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file.lower().endswith('.mp3'):
                        self.output_path = os.path.join(root, file)
                        break
            
            if not self.output_path:
                return self._download_fallback(url, 'audio', start_time)
            
            file_size = os.path.getsize(self.output_path)
            
            if file_size == 0:
                return {'success': False, 'error': 'Archivo vacío'}
            
            if file_size > Config.MAX_FILE_SIZE:
                os.remove(self.output_path)
                return {'success': False, 'error': f'Archivo muy grande ({file_size/(1024*1024):.1f}MB)'}
            
            # Renombrar
            clean_title = self.sanitize_filename(title)
            new_filename = f"{clean_title}.mp3"
            new_path = os.path.join(self.temp_dir, new_filename)
            if os.path.exists(new_path):
                os.remove(new_path)
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
                'format': 'mp3',
                'quality': f'{quality}kbps'
            }
                
        except Exception as e:
            logger.error(f"Error descargando audio: {e}")
            return {'success': False, 'error': str(e)[:200]}
    
    def download_video(self, url: str, quality: str = '720') -> Dict[str, Any]:
        """Descarga video en MP4"""
        self.temp_dir = tempfile.mkdtemp(prefix="yt_video_")
        start_time = time.time()
        
        try:
            # Determinar formato según calidad
            if quality == 'best':
                format_str = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            elif quality == '720':
                format_str = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best'
            elif quality == '480':
                format_str = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best'
            elif quality == '360':
                format_str = 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best'
            else:
                format_str = f'bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            
            ydl_opts = self._get_base_options()
            ydl_opts.update({
                'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
                'format': format_str,
                'merge_output_format': 'mp4',
            })
            
            logger.info(f"Descargando video ({quality}p): {url}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'video') if info else 'video'
            
            # Buscar archivo MP4
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file.lower().endswith('.mp4'):
                        self.output_path = os.path.join(root, file)
                        break
            
            if not self.output_path:
                return self._download_fallback(url, 'video', start_time)
            
            file_size = os.path.getsize(self.output_path)
            
            if file_size == 0:
                return {'success': False, 'error': 'Archivo vacío'}
            
            if file_size > Config.MAX_FILE_SIZE:
                os.remove(self.output_path)
                return {'success': False, 'error': f'Archivo muy grande ({file_size/(1024*1024):.1f}MB)'}
            
            # Renombrar
            clean_title = self.sanitize_filename(title)
            new_filename = f"{clean_title}.mp4"
            new_path = os.path.join(self.temp_dir, new_filename)
            if os.path.exists(new_path):
                os.remove(new_path)
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
                'type': 'video',
                'format': 'mp4',
                'quality': f'{quality}p'
            }
                
        except Exception as e:
            logger.error(f"Error descargando video: {e}")
            return {'success': False, 'error': str(e)[:200]}
    
    def _download_fallback(self, url: str, media_type: str, start_time: float) -> Dict[str, Any]:
        """Método de respaldo si falla la descarga principal"""
        logger.info(f"Usando método de respaldo para {media_type}...")
        
        try:
            if media_type == 'audio':
                format_str = 'worstaudio/worst'
                ext = 'mp3'
            else:
                format_str = 'worst[ext=mp4]/worst'
                ext = 'mp4'
            
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'outtmpl': os.path.join(self.temp_dir, f'%(id)s.{ext}'),
                'format': format_str,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36',
                }
            }
            
            if self.cookies_config and self.cookies_working:
                ydl_opts.update(self.cookies_config)
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', media_type) if info else media_type
            
            # Buscar archivo
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    self.output_path = os.path.join(root, file)
                    break
            
            if not self.output_path or not os.path.exists(self.output_path):
                return {'success': False, 'error': 'No se pudo generar el archivo'}
            
            file_size = os.path.getsize(self.output_path)
            clean_title = self.sanitize_filename(title)
            new_filename = f"{clean_title}.{ext}"
            new_path = os.path.join(self.temp_dir, new_filename)
            
            if os.path.exists(new_path):
                os.remove(new_path)
            
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
                'type': media_type,
                'format': ext,
                'note': 'Calidad básica (método de respaldo)'
            }
                
        except Exception as e:
            logger.error(f"Error en método de respaldo: {e}")
            return {'success': False, 'error': 'Todos los métodos fallaron'}
    
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
# ENDPOINTS PRINCIPALES
# ==============================

@app.route('/')
def home():
    """Página principal"""
    cookies_config = load_cookies()
    cookies_working = test_cookies(cookies_config)
    
    return jsonify({
        'service': 'YouTube Downloader API con Cookies',
        'version': '2.0 - Cookies Integradas',
        'status': 'online',
        'cookies': {
            'configured': bool(cookies_config),
            'working': cookies_working,
            'file': Config.COOKIES_FILE if cookies_config else None
        },
        'endpoints': {
            '/': 'GET - Esta página',
            '/health': 'GET - Estado del servidor',
            '/info?url=URL': 'GET - Información del video',
            '/download/audio': 'POST - Descargar audio MP3',
            '/download/video': 'POST - Descargar video MP4',
            '/test/cookies': 'GET - Probar cookies'
        },
        'limits': {
            'max_file_size': f'{Config.MAX_FILE_SIZE/(1024*1024)}MB',
            'supported_qualities': ['best', '720', '480', '360', '240']
        }
    })

@app.route('/health')
def health():
    """Health check"""
    cookies_config = load_cookies()
    cookies_working = test_cookies(cookies_config)
    
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'cookies': {
            'configured': bool(cookies_config),
            'working': cookies_working
        },
        'system': {
            'python': sys.version.split()[0],
            'platform': sys.platform
        }
    })

@app.route('/info', methods=['GET', 'POST'])
def get_info():
    """Obtiene información del video"""
    try:
        if request.method == 'POST':
            data = request.get_json(silent=True) or request.form
        else:
            data = request.args
        
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        # Validar URL de YouTube
        if not ('youtube.com/watch' in url or 'youtu.be/' in url):
            return jsonify({'success': False, 'error': 'URL de YouTube inválida'}), 400
        
        downloader = YouTubeDownloader()
        result = downloader.get_info(url)
        downloader.cleanup()
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error en /info: {e}")
        return jsonify({'success': False, 'error': 'Error del servidor'}), 500

@app.route('/download/audio', methods=['POST'])
def download_audio():
    """Descarga audio MP3"""
    try:
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form
        
        url = data.get('url', '').strip()
        quality = data.get('quality', '192')
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        if 'youtube.com/watch' not in url and 'youtu.be/' not in url:
            return jsonify({'success': False, 'error': 'URL de YouTube inválida'}), 400
        
        logger.info(f"Descarga de audio solicitada: {url[:50]}...")
        
        downloader = YouTubeDownloader()
        result = downloader.download_audio(url, quality)
        
        if not result['success']:
            downloader.cleanup()
            return jsonify(result), 400
        
        filepath = result['filepath']
        filename = result['filename']
        
        if not os.path.exists(filepath):
            downloader.cleanup()
            return jsonify({'success': False, 'error': 'Archivo no generado'}), 500
        
        file_size = os.path.getsize(filepath)
        
        # Enviar archivo
        response = send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
            mimetype='audio/mpeg'
        )
        
        # Headers adicionales
        response.headers['X-Download-Time'] = str(result['download_time'])
        response.headers['X-File-Size'] = str(file_size)
        response.headers['X-File-Type'] = 'audio/mp3'
        
        # Configurar cleanup después de enviar
        @response.call_on_close
        def cleanup_after_send():
            downloader.cleanup()
        
        return response
        
    except Exception as e:
        logger.error(f"Error en descarga de audio: {e}")
        return jsonify({'success': False, 'error': str(e)[:200]}), 500

@app.route('/download/video', methods=['POST'])
def download_video():
    """Descarga video MP4"""
    try:
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form
        
        url = data.get('url', '').strip()
        quality = data.get('quality', '720')
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        if 'youtube.com/watch' not in url and 'youtu.be/' not in url:
            return jsonify({'success': False, 'error': 'URL de YouTube inválida'}), 400
        
        logger.info(f"Descarga de video solicitada ({quality}p): {url[:50]}...")
        
        downloader = YouTubeDownloader()
        result = downloader.download_video(url, quality)
        
        if not result['success']:
            downloader.cleanup()
            return jsonify(result), 400
        
        filepath = result['filepath']
        filename = result['filename']
        
        if not os.path.exists(filepath):
            downloader.cleanup()
            return jsonify({'success': False, 'error': 'Archivo no generado'}), 500
        
        file_size = os.path.getsize(filepath)
        
        # Enviar archivo
        response = send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
            mimetype='video/mp4'
        )
        
        # Headers adicionales
        response.headers['X-Download-Time'] = str(result['download_time'])
        response.headers['X-File-Size'] = str(file_size)
        response.headers['X-File-Type'] = 'video/mp4'
        
        # Configurar cleanup después de enviar
        @response.call_on_close
        def cleanup_after_send():
            downloader.cleanup()
        
        return response
        
    except Exception as e:
        logger.error(f"Error en descarga de video: {e}")
        return jsonify({'success': False, 'error': str(e)[:200]}), 500

@app.route('/test/cookies', methods=['GET'])
def test_cookies_endpoint():
    """Endpoint para probar las cookies"""
    cookies_config = load_cookies()
    
    if not cookies_config:
        return jsonify({
            'success': False,
            'message': 'No se encontraron cookies',
            'file': Config.COOKIES_FILE
        })
    
    try:
        # Probar cookies
        downloader = YouTubeDownloader()
        
        return jsonify({
            'success': True,
            'cookies': {
                'file': Config.COOKIES_FILE,
                'working': downloader.cookies_working,
                'test_url': Config.TEST_URL
            },
            'message': 'Cookies configuradas correctamente' if downloader.cookies_working else 'Cookies pueden no funcionar'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'file': Config.COOKIES_FILE
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
    # Verificar cookies al iniciar
    cookies_config = load_cookies()
    cookies_working = test_cookies(cookies_config)
    
    print("\n" + "="*70)
    print("🚀 SERVIDOR YOUTUBE CON COOKIES")
    print("="*70)
    print(f"✅ Puerto: {Config.PORT}")
    print(f"✅ Host: {Config.HOST}")
    
    if cookies_config:
        print(f"✅ Cookies: {Config.COOKIES_FILE}")
        if cookies_working:
            print("✅ Estado: FUNCIONANDO ✓")
        else:
            print("⚠️  Estado: POSIBLES PROBLEMAS")
    else:
        print("⚠️  Cookies: NO CONFIGURADAS")
    
    print("="*70)
    print("📡 Servidor listo en:")
    print(f"   http://localhost:{Config.PORT}")
    print("="*70)
    print("📋 Endpoints disponibles:")
    print("  GET  /                   - Información del API")
    print("  GET  /health             - Estado del servidor")
    print("  GET  /info?url=URL       - Información del video")
    print("  POST /download/audio     - Descargar audio MP3")
    print("  POST /download/video     - Descargar video MP4")
    print("  GET  /test/cookies       - Probar cookies")
    print("="*70)
    
    # Instrucciones para usar
    print("\n💡 INSTRUCCIONES:")
    print("1. Asegúrate de tener 'cookies.txt' en la misma carpeta")
    print("2. El servidor usará automáticamente las cookies")
    print("3. Puedes cambiar el nombre del archivo con variable COOKIES_FILE")
    print("="*70 + "\n")
    
    # Iniciar servidor
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=False,
        threaded=True,
        use_reloader=False
    )
