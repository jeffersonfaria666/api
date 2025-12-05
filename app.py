#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE CON COOKIES - Evita bloqueos "Sign in to confirm you're not a bot"
Versión: Cookies - Usa cookies del navegador para autenticación
"""

import os
import sys
import json
import logging
import tempfile
import shutil
import time
import re
from datetime import datetime

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp

# ==============================
# CONFIGURACIÓN
# ==============================
class Config:
    PORT = int(os.environ.get('PORT', 10000))
    HOST = '0.0.0.0'
    MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
    
    # Configuración de cookies (personaliza según tu navegador)
    COOKIES_BROWSER = os.environ.get('COOKIES_BROWSER', 'chrome')  # chrome, firefox, edge, brave
    COOKIES_FILE = os.environ.get('COOKIES_FILE', '')  # Ruta a archivo de cookies si no usas navegador

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
# VERIFICAR Y CONFIGURAR COOKIES
# ==============================
def setup_cookies_config():
    """Configura las opciones de cookies para yt-dlp"""
    cookies_config = {}
    
    # Opción 1: Usar archivo de cookies específico
    if Config.COOKIES_FILE and os.path.exists(Config.COOKIES_FILE):
        cookies_config['cookiefile'] = Config.COOKIES_FILE
        logger.info(f"✅ Usando archivo de cookies: {Config.COOKIES_FILE}")
    
    # Opción 2: Extraer cookies del navegador
    elif Config.COOKIES_BROWSER:
        try:
            # Para yt-dlp 2025.05.22, la sintaxis correcta es:
            cookies_config['cookies_from_browser'] = Config.COOKIES_BROWSER
            logger.info(f"✅ Configurando cookies del navegador: {Config.COOKIES_BROWSER}")
        except Exception as e:
            logger.warning(f"⚠️  No se pudo configurar cookies del navegador: {e}")
    
    # Opción 3: Sin cookies (modo guest - puede fallar)
    if not cookies_config:
        logger.warning("⚠️  No se configuraron cookies. Algunos videos pueden fallar.")
        # Configuración alternativa para evitar bloqueos
        cookies_config['extractor_args'] = {
            'youtube': {
                'player_client': ['android', 'ios', 'web'],
                'player_skip': ['configs', 'js'],
            }
        }
    
    return cookies_config

# ==============================
# DOWNLOADER CON COOKIES
# ==============================
class YouTubeDownloaderWithCookies:
    """Descargador de YouTube que usa cookies para evitar bloqueos"""
    
    def __init__(self):
        self.temp_dir = None
        self.output_path = None
        self.cookies_config = setup_cookies_config()
        
    def clean_filename(self, filename):
        """Limpia el nombre de archivo"""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename[:100]
    
    def _get_ydl_options(self, download_type='audio'):
        """Obtiene opciones de yt-dlp con cookies"""
        base_opts = {
            'quiet': True,
            'no_warnings': True,
            'no_color': True,
            'noprogress': True,
            'no_check_certificate': True,
            'ignoreerrors': True,
            'socket_timeout': 30,
            'retries': 5,
            'fragment_retries': 5,
            'concurrent_fragment_downloads': 3,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
            },
            # IMPORTANTE: Configuración para evitar bloqueos de YouTube
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios', 'web'],
                    'player_skip': ['configs', 'js'],
                }
            },
            # Añadir delay para evitar rate limiting
            'sleep_interval': 2,
            'max_sleep_interval': 5,
            # Evitar solicitudes innecesarias
            'extract_flat': False,
            'noplaylist': True,
        }
        
        # Añadir configuración de cookies
        base_opts.update(self.cookies_config)
        
        # Configuración específica por tipo
        if download_type == 'audio':
            base_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'keepvideo': False,
                'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
            })
        else:  # video
            base_opts.update({
                'format': 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'merge_output_format': 'mp4',
                'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
            })
        
        return base_opts
    
    def get_info(self, url):
        """Obtiene información del video"""
        try:
            ydl_opts = self._get_ydl_options()
            ydl_opts['skip_download'] = True
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    return {'success': False, 'error': 'Video no encontrado'}
                
                # Duración
                duration = info.get('duration', 0)
                minutes = duration // 60
                seconds = duration % 60
                duration_str = f"{minutes}:{seconds:02d}"
                
                return {
                    'success': True,
                    'title': info.get('title', 'Video sin título'),
                    'duration': duration_str,
                    'duration_seconds': duration,
                    'uploader': info.get('uploader', 'Desconocido'),
                    'view_count': info.get('view_count', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'video_id': info.get('id', ''),
                    'description': info.get('description', '')[:200] + '...' if info.get('description') else '',
                }
                
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            logger.error(f"Error específico: {error_msg}")
            
            # Intentar sin cookies si falla con cookies
            if 'cookies' in error_msg.lower() or 'sign in' in error_msg.lower():
                logger.info("⚠️  Intentando sin cookies...")
                return self._get_info_without_cookies(url)
            
            return {'success': False, 'error': error_msg[:200]}
        except Exception as e:
            logger.error(f"Error obteniendo info: {e}")
            return {'success': False, 'error': str(e)[:200]}
    
    def _get_info_without_cookies(self, url):
        """Intenta obtener información sin cookies"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'ios'],
                        'player_skip': ['configs', 'js', 'webpage'],
                    }
                },
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36',
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    return {'success': False, 'error': 'Video no encontrado (sin cookies)'}
                
                duration = info.get('duration', 0)
                minutes = duration // 60
                seconds = duration % 60
                duration_str = f"{minutes}:{seconds:02d}"
                
                return {
                    'success': True,
                    'title': info.get('title', 'Video sin título'),
                    'duration': duration_str,
                    'duration_seconds': duration,
                    'uploader': info.get('uploader', 'Desconocido'),
                    'view_count': info.get('view_count', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'video_id': info.get('id', ''),
                    'note': 'Información obtenida sin cookies, la descarga puede fallar',
                }
        except Exception as e:
            return {'success': False, 'error': f'Error incluso sin cookies: {str(e)[:200]}'}
    
    def download(self, url, download_type='audio'):
        """Descarga el video o audio"""
        self.temp_dir = tempfile.mkdtemp(prefix="youtube_")
        start_time = time.time()
        
        try:
            ydl_opts = self._get_ydl_options(download_type)
            
            logger.info(f"Descargando {download_type}: {url}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'video') if info else 'video'
            
            # Buscar archivo descargado
            downloaded_files = []
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file.endswith(('.part', '.ytdl')):
                        continue
                    filepath = os.path.join(root, file)
                    try:
                        size = os.path.getsize(filepath)
                        if size > 1024:
                            downloaded_files.append((filepath, size))
                    except:
                        continue
            
            if not downloaded_files:
                # Intentar sin cookies si falló
                if self.cookies_config:
                    logger.info("⚠️  Intento con cookies falló, intentando sin cookies...")
                    return self._download_without_cookies(url, download_type, start_time)
                return {'success': False, 'error': 'No se generó archivo'}
            
            # Tomar el archivo más grande
            self.output_path, file_size = max(downloaded_files, key=lambda x: x[1])
            
            if file_size == 0:
                return {'success': False, 'error': 'Archivo vacío'}
            
            if file_size > Config.MAX_FILE_SIZE:
                os.remove(self.output_path)
                return {'success': False, 'error': f'Archivo muy grande ({file_size/(1024*1024):.1f}MB)'}
            
            # Renombrar
            clean_title = self.clean_filename(title)
            file_ext = os.path.splitext(self.output_path)[1].lower()
            
            if download_type == 'audio':
                new_filename = f"{clean_title}.mp3"
                new_path = os.path.join(self.temp_dir, new_filename)
                os.rename(self.output_path, new_path)
                self.output_path = new_path
            else:
                new_filename = f"{clean_title}.mp4"
                new_path = os.path.join(self.temp_dir, new_filename)
                os.rename(self.output_path, new_path)
                self.output_path = new_path
            
            file_size = os.path.getsize(self.output_path)
            download_time = time.time() - start_time
            
            return {
                'success': True,
                'filename': os.path.basename(self.output_path),
                'filepath': self.output_path,
                'filesize': file_size,
                'filesize_mb': round(file_size / (1024 * 1024), 2),
                'download_time': round(download_time, 2),
                'title': title,
                'type': download_type,
                'format': 'mp3' if download_type == 'audio' else 'mp4'
            }
                
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            logger.error(f"Error de descarga: {error_msg}")
            
            # Intentar sin cookies
            if 'cookies' in error_msg.lower() or 'sign in' in error_msg.lower():
                logger.info("⚠️  Descarga con cookies falló, intentando sin cookies...")
                return self._download_without_cookies(url, download_type, start_time)
            
            return {'success': False, 'error': error_msg[:200]}
        except Exception as e:
            logger.error(f"Error inesperado: {e}")
            return {'success': False, 'error': str(e)[:200]}
    
    def _download_without_cookies(self, url, download_type, start_time):
        """Intenta descargar sin cookies"""
        try:
            # Configuración mínima sin cookies
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
                'no_check_certificate': True,
                'socket_timeout': 30,
                'retries': 3,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36',
                },
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'ios'],
                        'player_skip': ['configs', 'js', 'webpage'],
                    }
                },
            }
            
            if download_type == 'audio':
                ydl_opts['format'] = 'worstaudio/worst'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                }]
            else:
                ydl_opts['format'] = 'worst[ext=mp4]/worst'
            
            logger.info(f"Descargando sin cookies: {url}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'video') if info else 'video'
            
            # Buscar archivo
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file.endswith(('.mp3', '.mp4', '.m4a', '.webm')):
                        filepath = os.path.join(root, file)
                        size = os.path.getsize(filepath)
                        
                        if size > 1024:
                            clean_title = self.clean_filename(title)
                            
                            if download_type == 'audio' and not filepath.lower().endswith('.mp3'):
                                new_filename = f"{clean_title}.mp3"
                                new_path = os.path.join(self.temp_dir, new_filename)
                                os.rename(filepath, new_path)
                                filepath = new_path
                            elif download_type == 'video' and not filepath.lower().endswith('.mp4'):
                                new_filename = f"{clean_title}.mp4"
                                new_path = os.path.join(self.temp_dir, new_filename)
                                os.rename(filepath, new_path)
                                filepath = new_path
                            
                            self.output_path = filepath
                            download_time = time.time() - start_time
                            
                            return {
                                'success': True,
                                'filename': os.path.basename(filepath),
                                'filepath': filepath,
                                'filesize': size,
                                'filesize_mb': round(size / (1024 * 1024), 2),
                                'download_time': round(download_time, 2),
                                'title': title,
                                'type': download_type,
                                'format': 'mp3' if download_type == 'audio' else 'mp4',
                                'note': 'Descargado sin cookies - calidad puede ser baja'
                            }
            
            return {'success': False, 'error': 'No se pudo descargar ni siquiera sin cookies'}
            
        except Exception as e:
            logger.error(f"Error descargando sin cookies: {e}")
            return {'success': False, 'error': f'Error sin cookies: {str(e)[:200]}'}
    
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
# ENDPOINTS
# ==============================

@app.route('/')
def home():
    return jsonify({
        'service': 'YouTube Downloader with Cookies',
        'version': 'cookies-1.0',
        'status': 'online',
        'cookies_configured': bool(setup_cookies_config()),
        'endpoints': {
            '/health': 'GET - Health check',
            '/info': 'GET/POST - Video information',
            '/download/audio': 'POST - Download audio MP3',
            '/download/video': 'POST - Download video MP4'
        },
        'note': 'Some videos may require cookies to download. Configure COOKIES_BROWSER or COOKIES_FILE environment variables.'
    })

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'cookies_config': {
            'browser': Config.COOKIES_BROWSER,
            'file_configured': bool(Config.COOKIES_FILE and os.path.exists(Config.COOKIES_FILE))
        }
    })

@app.route('/info', methods=['GET', 'POST'])
def get_info():
    try:
        if request.method == 'POST':
            data = request.get_json(silent=True) or request.form
        else:
            data = request.args
        
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        if 'youtube.com' not in url and 'youtu.be' not in url:
            return jsonify({'success': False, 'error': 'Solo URLs de YouTube'}), 400
        
        downloader = YouTubeDownloaderWithCookies()
        result = downloader.get_info(url)
        downloader.cleanup()
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error en /info: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/download/<download_type>', methods=['POST'])
def download_file(download_type):
    if download_type not in ['audio', 'video']:
        return jsonify({'success': False, 'error': 'Tipo debe ser "audio" o "video"'}), 400
    
    try:
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form
        
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        if 'youtube.com' not in url and 'youtu.be' not in url:
            return jsonify({'success': False, 'error': 'Solo URLs de YouTube'}), 400
        
        logger.info(f"Descarga de {download_type} solicitada: {url[:50]}...")
        
        downloader = YouTubeDownloaderWithCookies()
        result = downloader.download(url, download_type)
        
        if not result['success']:
            downloader.cleanup()
            return jsonify(result), 400
        
        filepath = result['filepath']
        filename = result['filename']
        
        if not os.path.exists(filepath):
            downloader.cleanup()
            return jsonify({'success': False, 'error': 'Archivo no existe'}), 404
        
        file_size = os.path.getsize(filepath)
        
        # Stream del archivo
        def generate():
            try:
                with open(filepath, 'rb') as f:
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        yield chunk
            finally:
                downloader.cleanup()
        
        mimetype = 'audio/mpeg' if download_type == 'audio' else 'video/mp4'
        
        return Response(
            generate(),
            mimetype=mimetype,
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(file_size),
                'X-Download-Time': str(result['download_time']),
                'X-File-Size': str(file_size),
                'X-File-Type': download_type,
                'X-Quality-Note': result.get('note', '')
            }
        )
        
    except Exception as e:
        logger.error(f"Error en descarga: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ==============================
# INICIALIZACIÓN
# ==============================
if __name__ == '__main__':
    print("\n" + "="*70)
    print("🚀 SERVIDOR YOUTUBE CON COOKIES")
    print("="*70)
    print("✅ Configuración para evitar bloqueos de YouTube")
    print(f"✅ Navegador para cookies: {Config.COOKIES_BROWSER}")
    
    if Config.COOKIES_FILE and os.path.exists(Config.COOKIES_FILE):
        print(f"✅ Archivo de cookies: {Config.COOKIES_FILE}")
    else:
        print("⚠️  No se encontró archivo de cookies específico")
    
    print("="*70)
    print(f"📡 Servidor: http://{Config.HOST}:{Config.PORT}")
    print("="*70)
    print("📋 Endpoints:")
    print("  GET  /info?url=URL            - Información del video")
    print("  POST /download/audio          - Descargar audio MP3")
    print("  POST /download/video          - Descargar video MP4")
    print("="*70)
    print("💡 CONFIGURACIÓN DE COOKIES (opcional pero recomendado):")
    print("  Opción 1: Exporta cookies de tu navegador:")
    print("    - Usa una extensión como 'Get cookies.txt LOCALLY' para Chrome")
    print("    - Guárdalas como 'cookies.txt' en la misma carpeta")
    print("    - Configura: export COOKIES_FILE='cookies.txt'")
    print("  Opción 2: Usa cookies directamente del navegador:")
    print("    - Configura: export COOKIES_BROWSER='chrome' (o firefox, brave, edge)")
    print("="*70 + "\n")
    
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=False,
        threaded=True,
        use_reloader=False
    )
