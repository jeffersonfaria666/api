#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE PARA RENDER.COM
Versión: Render Optimizada - Funciona con y sin cookies
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

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp

# ==============================
# CONFIGURACIÓN RENDER
# ==============================
class Config:
    PORT = int(os.environ.get('PORT', 10000))
    HOST = '0.0.0.0'
    MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB
    
    # Configuración de cookies para Render
    COOKIES_FILE = os.environ.get('COOKIES_FILE', '')
    COOKIES_BROWSER = os.environ.get('COOKIES_BROWSER', '')

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
# VERIFICAR DISPONIBILIDAD DE COOKIES EN RENDER
# ==============================
def check_cookies():
    """Verifica si hay cookies disponibles en Render"""
    cookies_config = {}
    
    # Opción 1: Archivo de cookies en el repositorio
    if Config.COOKIES_FILE and os.path.exists(Config.COOKIES_FILE):
        cookies_config['cookiefile'] = Config.COOKIES_FILE
        logger.info(f"✅ Cookies encontradas: {Config.COOKIES_FILE}")
    
    # Opción 2: Cookies de navegador (poco probable en Render)
    elif Config.COOKIES_BROWSER:
        cookies_config['cookies_from_browser'] = Config.COOKIES_BROWSER
        logger.info(f"✅ Usando cookies del navegador: {Config.COOKIES_BROWSER}")
    
    else:
        logger.info("ℹ️  No se configuraron cookies. Usando modo guest...")
    
    return cookies_config

# ==============================
# MÉTODO ROBUSTO PARA RENDER
# ==============================
class RenderDownloader:
    """Descargador optimizado para Render.com"""
    
    def __init__(self):
        self.temp_dir = None
        self.output_path = None
        self.cookies_config = check_cookies()
    
    def sanitize_filename(self, filename):
        """Limpia el nombre de archivo"""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename[:100]
    
    def _get_base_options(self):
        """Opciones base optimizadas para Render"""
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
            # Headers para evitar bloqueos
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
            },
            # Configuración para evitar bloqueos de YouTube
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios', 'web'],
                    'player_skip': ['configs', 'js'],
                }
            },
            # Añadir delay para evitar rate limiting
            'sleep_interval': 3,
            'max_sleep_interval': 8,
            'noplaylist': True,
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
                hours = duration // 3600
                minutes = (duration % 3600) // 60
                seconds = duration % 60
                
                if hours > 0:
                    duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                else:
                    duration_str = f"{minutes:02d}:{seconds:02d}"
                
                return {
                    'success': True,
                    'title': info.get('title', 'Video sin título'),
                    'duration': duration_str,
                    'duration_seconds': duration,
                    'uploader': info.get('uploader', 'Desconocido'),
                    'view_count': info.get('view_count', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'has_cookies': bool(self.cookies_config)
                }
                
        except Exception as e:
            logger.error(f"Error obteniendo info: {e}")
            return {'success': False, 'error': str(e)[:200]}
    
    def download_audio(self, url: str) -> Dict[str, Any]:
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
                    'preferredquality': '192',
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
                # Si no hay MP3, buscar cualquier audio
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        if any(file.lower().endswith(ext) for ext in ['.m4a', '.webm', '.opus']):
                            self.output_path = os.path.join(root, file)
                            break
            
            if not self.output_path:
                # Intentar método alternativo
                return self._download_simple_audio(url, start_time)
            
            file_size = os.path.getsize(self.output_path)
            
            if file_size == 0:
                return {'success': False, 'error': 'Archivo vacío'}
            
            if file_size > Config.MAX_FILE_SIZE:
                os.remove(self.output_path)
                return {'success': False, 'error': 'Archivo muy grande'}
            
            # Renombrar
            clean_title = self.sanitize_filename(title)
            new_filename = f"{clean_title}.mp3"
            new_path = os.path.join(self.temp_dir, new_filename)
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
    
    def _download_simple_audio(self, url: str, start_time: float) -> Dict[str, Any]:
        """Método alternativo simple para audio"""
        try:
            logger.info("Intentando método simple para audio...")
            
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'outtmpl': os.path.join(self.temp_dir, '%(id)s.%(ext)s'),
                'format': 'worstaudio/worst',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                }],
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36',
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'audio') if info else 'audio'
            
            # Buscar cualquier archivo
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in ['.mp3', '.m4a', '.webm']):
                        self.output_path = os.path.join(root, file)
                        break
            
            if not self.output_path:
                return {'success': False, 'error': 'No se generó archivo de audio'}
            
            file_size = os.path.getsize(self.output_path)
            clean_title = self.sanitize_filename(title)
            new_filename = f"{clean_title}.mp3"
            new_path = os.path.join(self.temp_dir, new_filename)
            os.rename(self.output_path, new_path)
            self.output_path = new_path
            
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
                'note': 'Calidad básica (método simple)'
            }
                
        except Exception as e:
            logger.error(f"Error en método simple: {e}")
            return {'success': False, 'error': 'Todos los métodos fallaron'}
    
    def download_video(self, url: str) -> Dict[str, Any]:
        """Descarga video en MP4"""
        self.temp_dir = tempfile.mkdtemp(prefix="yt_video_")
        start_time = time.time()
        
        try:
            ydl_opts = self._get_base_options()
            ydl_opts.update({
                'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
                'format': 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'merge_output_format': 'mp4',
            })
            
            logger.info(f"Descargando video: {url}")
            
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
                # Si no hay MP4, buscar cualquier video
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        if any(file.lower().endswith(ext) for ext in ['.webm', '.mkv']):
                            self.output_path = os.path.join(root, file)
                            break
            
            if not self.output_path:
                # Intentar método alternativo
                return self._download_simple_video(url, start_time)
            
            file_size = os.path.getsize(self.output_path)
            
            if file_size == 0:
                return {'success': False, 'error': 'Archivo vacío'}
            
            if file_size > Config.MAX_FILE_SIZE:
                os.remove(self.output_path)
                return {'success': False, 'error': 'Archivo muy grande'}
            
            # Renombrar
            clean_title = self.sanitize_filename(title)
            new_filename = f"{clean_title}.mp4"
            new_path = os.path.join(self.temp_dir, new_filename)
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
                'format': 'mp4'
            }
                
        except Exception as e:
            logger.error(f"Error descargando video: {e}")
            return {'success': False, 'error': str(e)[:200]}
    
    def _download_simple_video(self, url: str, start_time: float) -> Dict[str, Any]:
        """Método alternativo simple para video"""
        try:
            logger.info("Intentando método simple para video...")
            
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'outtmpl': os.path.join(self.temp_dir, '%(id)s.%(ext)s'),
                'format': 'worst[ext=mp4]/worst',
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36',
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'video') if info else 'video'
            
            # Buscar cualquier archivo de video
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in ['.mp4', '.webm']):
                        self.output_path = os.path.join(root, file)
                        break
            
            if not self.output_path:
                return {'success': False, 'error': 'No se generó archivo de video'}
            
            file_size = os.path.getsize(self.output_path)
            clean_title = self.sanitize_filename(title)
            new_filename = f"{clean_title}.mp4"
            new_path = os.path.join(self.temp_dir, new_filename)
            os.rename(self.output_path, new_path)
            self.output_path = new_path
            
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
                'note': 'Calidad básica (método simple)'
            }
                
        except Exception as e:
            logger.error(f"Error en método simple: {e}")
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
# ENDPOINTS OPTIMIZADOS PARA RENDER
# ==============================

@app.route('/')
def home():
    """Página principal optimizada para Render"""
    has_cookies = bool(check_cookies())
    
    return jsonify({
        'service': 'YouTube Downloader API',
        'version': 'render-optimized',
        'status': 'online',
        'environment': 'Render' if os.environ.get('RENDER') else 'Local',
        'cookies_configured': has_cookies,
        'endpoints': {
            '/health': 'GET - Health check',
            '/info?url=URL': 'GET - Video information',
            '/download/audio': 'POST - Download audio MP3',
            '/download/video': 'POST - Download video MP4'
        },
        'note': 'Para mejores resultados, añade cookies.txt a tu repositorio'
    })

@app.route('/health')
def health():
    """Health check para Render"""
    has_cookies = bool(check_cookies())
    
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'environment': os.environ.get('RENDER', 'local'),
        'cookies_configured': has_cookies,
        'cookies_file': Config.COOKIES_FILE if has_cookies else None,
        'memory_usage_mb': get_memory_usage()
    })

def get_memory_usage():
    """Obtiene uso de memoria en MB"""
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1024 / 1024
    except:
        return 0

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
        
        if 'youtube.com' not in url and 'youtu.be' not in url:
            return jsonify({'success': False, 'error': 'Solo URLs de YouTube'}), 400
        
        downloader = RenderDownloader()
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
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        if 'youtube.com' not in url and 'youtu.be' not in url:
            return jsonify({'success': False, 'error': 'Solo URLs de YouTube'}), 400
        
        logger.info(f"Descarga de audio solicitada: {url[:50]}...")
        
        downloader = RenderDownloader()
        result = downloader.download_audio(url)
        
        if not result['success']:
            downloader.cleanup()
            return jsonify(result), 400
        
        filepath = result['filepath']
        filename = result['filename']
        
        if not os.path.exists(filepath):
            downloader.cleanup()
            return jsonify({'success': False, 'error': 'Archivo no existe'}), 404
        
        file_size = os.path.getsize(filepath)
        
        # Stream del archivo optimizado para Render
        def generate():
            try:
                with open(filepath, 'rb') as f:
                    chunk_size = 8192 * 8  # Chunks más grandes para Render
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        yield chunk
            finally:
                downloader.cleanup()
        
        return Response(
            generate(),
            mimetype='audio/mpeg',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(file_size),
                'X-Download-Time': str(result['download_time']),
                'X-File-Size': str(file_size),
                'X-File-Type': 'audio/mp3',
                'Cache-Control': 'no-store, no-cache, must-revalidate'
            }
        )
        
    except Exception as e:
        logger.error(f"Error en descarga de audio: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/download/video', methods=['POST'])
def download_video():
    """Descarga video MP4"""
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
        
        logger.info(f"Descarga de video solicitada: {url[:50]}...")
        
        downloader = RenderDownloader()
        result = downloader.download_video(url)
        
        if not result['success']:
            downloader.cleanup()
            return jsonify(result), 400
        
        filepath = result['filepath']
        filename = result['filename']
        
        if not os.path.exists(filepath):
            downloader.cleanup()
            return jsonify({'success': False, 'error': 'Archivo no existe'}), 404
        
        file_size = os.path.getsize(filepath)
        
        # Stream del archivo optimizado para Render
        def generate():
            try:
                with open(filepath, 'rb') as f:
                    chunk_size = 8192 * 16  # Chunks más grandes para video
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        yield chunk
            finally:
                downloader.cleanup()
        
        return Response(
            generate(),
            mimetype='video/mp4',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(file_size),
                'X-Download-Time': str(result['download_time']),
                'X-File-Size': str(file_size),
                'X-File-Type': 'video/mp4',
                'Cache-Control': 'no-store, no-cache, must-revalidate'
            }
        )
        
    except Exception as e:
        logger.error(f"Error en descarga de video: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/test', methods=['GET'])
def test_endpoint():
    """Endpoint de prueba para Render"""
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    has_cookies = bool(check_cookies())
    
    return jsonify({
        'test': 'success',
        'server': 'running',
        'environment': os.environ.get('RENDER', 'local'),
        'cookies_configured': has_cookies,
        'test_url': test_url,
        'test_endpoints': {
            'info': f'/info?url={test_url}',
            'audio': f'/download/audio (POST)',
            'video': f'/download/video (POST)'
        }
    })

# ==============================
# MANEJO DE ERRORES PARA RENDER
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
# INICIALIZACIÓN PARA RENDER
# ==============================
if __name__ == '__main__':
    # Determinar si estamos en Render
    is_render = os.environ.get('RENDER', '').lower() == 'true'
    
    print("\n" + "="*70)
    print("🚀 SERVIDOR YOUTUBE PARA RENDER.COM")
    print("="*70)
    print(f"✅ Entorno: {'Render' if is_render else 'Local'}")
    print(f"✅ Puerto: {Config.PORT}")
    
    has_cookies = bool(check_cookies())
    if has_cookies:
        print(f"✅ Cookies: Configuradas")
    else:
        print(f"⚠️  Cookies: No configuradas (algunos videos pueden fallar)")
    
    print("="*70)
    print(f"📡 Servidor: http://{Config.HOST}:{Config.PORT}")
    print("="*70)
    print("📋 Endpoints:")
    print("  GET  /info?url=URL           - Información del video")
    print("  POST /download/audio         - Descargar audio MP3")
    print("  POST /download/video         - Descargar video MP4")
    print("  GET  /test                   - Probar servidor")
    print("="*70)
    
    # Instrucciones para Render
    if not has_cookies and is_render:
        print("\n💡 CONSEJO PARA RENDER:")
        print("Para evitar bloqueos de YouTube, añade un archivo cookies.txt:")
        print("1. Exporta cookies de YouTube desde tu navegador")
        print("2. Súbelo a tu repositorio como 'cookies.txt'")
        print("3. Render lo usará automáticamente")
    
    print("="*70 + "\n")
    
    # En Render, usar waitress para producción
    if is_render:
        try:
            from waitress import serve
            print("🚀 Iniciando servidor con Waitress (producción)...")
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
    else:
        # Para desarrollo local
        app.run(
            host=Config.HOST,
            port=Config.PORT,
            debug=False,
            threaded=True,
            use_reloader=False
        )
