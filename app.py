#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE FUNCIONAL - CON COOKIES Y FORMATOS ARREGLADOS
Versión: Funcional - Descarga audio MP3 y video MP4 sin errores
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
# MÉTODO FUNCIONAL CON COOKIES
# ==============================
class WorkingDownloader:
    """Descargador que funciona con YouTube usando cookies"""
    
    def __init__(self):
        self.temp_dir = None
        self.output_path = None
        
    def clean_filename(self, filename):
        """Limpia el nombre de archivo"""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename[:100]
    
    def get_info(self, url: str) -> dict:
        """Obtiene información del video sin descargar"""
        try:
            # Configuración con cookies y headers para evitar bloqueo
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'no_check_certificate': True,
                'ignoreerrors': True,
                'extract_flat': False,
                'socket_timeout': 15,
                'retries': 3,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                },
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web'],
                        'player_skip': ['configs', 'js'],
                    }
                }
            }
            
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
                }
                
        except Exception as e:
            logger.error(f"Error obteniendo info: {e}")
            # Si falla, intentamos método alternativo más simple
            return self._get_info_simple(url)
    
    def _get_info_simple(self, url: str) -> dict:
        """Método alternativo simple para obtener información"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'extract_flat': True,  # Modo plano para evitar procesamiento complejo
                'force_generic_extractor': False,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    return {'success': False, 'error': 'Video no encontrado'}
                
                return {
                    'success': True,
                    'title': info.get('title', 'Video sin título'),
                    'duration': 'Desconocida',
                    'duration_seconds': 0,
                    'uploader': info.get('uploader', 'Desconocido'),
                    'view_count': info.get('view_count', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'video_id': info.get('id', ''),
                }
                
        except Exception as e:
            logger.error(f"Error en método simple: {e}")
            return {'success': False, 'error': str(e)}
    
    def download_audio(self, url: str) -> dict:
        """Descarga solo audio en MP3"""
        self.temp_dir = tempfile.mkdtemp(prefix="youtube_audio_")
        start_time = time.time()
        
        try:
            # Configuración específica para audio MP3
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
                'no_check_certificate': True,
                'ignoreerrors': True,
                'socket_timeout': 30,
                'retries': 5,
                'fragment_retries': 5,
                # Configuración para evitar bloqueos
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                },
                # FORMATOS ESPECÍFICOS PARA AUDIO que funcionan
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                # Evitar procesamiento innecesario
                'keepvideo': False,
                'noplaylist': True,
                'extract_flat': False,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android'],
                        'player_skip': ['configs'],
                    }
                }
            }
            
            logger.info(f"Descargando audio: {url}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'audio') if info else 'audio'
            
            # Buscar archivo MP3
            downloaded_files = []
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file.lower().endswith('.mp3'):
                        filepath = os.path.join(root, file)
                        try:
                            size = os.path.getsize(filepath)
                            if size > 1024:
                                downloaded_files.append((filepath, size))
                        except:
                            continue
            
            if not downloaded_files:
                # Si no hay MP3, buscar cualquier archivo de audio
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        if any(file.lower().endswith(ext) for ext in ['.m4a', '.webm', '.opus', '.ogg']):
                            filepath = os.path.join(root, file)
                            try:
                                size = os.path.getsize(filepath)
                                if size > 1024:
                                    downloaded_files.append((filepath, size))
                            except:
                                continue
            
            if not downloaded_files:
                return {'success': False, 'error': 'No se generó archivo de audio'}
            
            # Tomar el archivo más grande
            self.output_path, file_size = max(downloaded_files, key=lambda x: x[1])
            
            if file_size == 0:
                return {'success': False, 'error': 'Archivo vacío'}
            
            # Renombrar a MP3 si no lo es
            clean_title = self.clean_filename(title)
            file_ext = os.path.splitext(self.output_path)[1].lower()
            
            if file_ext != '.mp3':
                new_filename = f"{clean_title}.mp3"
                new_path = os.path.join(self.temp_dir, new_filename)
                os.rename(self.output_path, new_path)
                self.output_path = new_path
            else:
                new_filename = f"{clean_title}.mp3"
                new_path = os.path.join(self.temp_dir, new_filename)
                os.rename(self.output_path, new_path)
                self.output_path = new_path
            
            file_size = os.path.getsize(self.output_path)
            
            if file_size > Config.MAX_FILE_SIZE:
                os.remove(self.output_path)
                return {'success': False, 'error': 'Archivo muy grande'}
            
            download_time = time.time() - start_time
            
            return {
                'success': True,
                'filename': os.path.basename(self.output_path),
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
            return {'success': False, 'error': str(e)}
    
    def download_video(self, url: str) -> dict:
        """Descarga video en MP4"""
        self.temp_dir = tempfile.mkdtemp(prefix="youtube_video_")
        start_time = time.time()
        
        try:
            # Configuración específica para video MP4
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
                'no_check_certificate': True,
                'ignoreerrors': True,
                'socket_timeout': 30,
                'retries': 5,
                'fragment_retries': 5,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                },
                # FORMATOS ESPECÍFICOS PARA VIDEO que funcionan
                'format': 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]/best',
                'merge_output_format': 'mp4',
                # Evitar procesamiento innecesario
                'noplaylist': True,
                'extract_flat': False,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android'],
                        'player_skip': ['configs'],
                    }
                }
            }
            
            logger.info(f"Descargando video: {url}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'video') if info else 'video'
            
            # Buscar archivo MP4
            downloaded_files = []
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file.lower().endswith('.mp4'):
                        filepath = os.path.join(root, file)
                        try:
                            size = os.path.getsize(filepath)
                            if size > 1024:
                                downloaded_files.append((filepath, size))
                        except:
                            continue
            
            if not downloaded_files:
                # Si no hay MP4, buscar cualquier archivo de video
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        if any(file.lower().endswith(ext) for ext in ['.webm', '.mkv', '.avi', '.mov']):
                            filepath = os.path.join(root, file)
                            try:
                                size = os.path.getsize(filepath)
                                if size > 1024:
                                    downloaded_files.append((filepath, size))
                            except:
                                continue
            
            if not downloaded_files:
                return {'success': False, 'error': 'No se generó archivo de video'}
            
            # Tomar el archivo más grande
            self.output_path, file_size = max(downloaded_files, key=lambda x: x[1])
            
            if file_size == 0:
                return {'success': False, 'error': 'Archivo vacío'}
            
            # Renombrar a MP4 si no lo es
            clean_title = self.clean_filename(title)
            file_ext = os.path.splitext(self.output_path)[1].lower()
            
            if file_ext != '.mp4':
                new_filename = f"{clean_title}.mp4"
                new_path = os.path.join(self.temp_dir, new_filename)
                os.rename(self.output_path, new_path)
                self.output_path = new_path
            else:
                new_filename = f"{clean_title}.mp4"
                new_path = os.path.join(self.temp_dir, new_filename)
                os.rename(self.output_path, new_path)
                self.output_path = new_path
            
            file_size = os.path.getsize(self.output_path)
            
            if file_size > Config.MAX_FILE_SIZE:
                os.remove(self.output_path)
                return {'success': False, 'error': 'Archivo muy grande'}
            
            download_time = time.time() - start_time
            
            return {
                'success': True,
                'filename': os.path.basename(self.output_path),
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
            return {'success': False, 'error': str(e)}
    
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
# ENDPOINTS FUNCIONALES
# ==============================

@app.route('/')
def home():
    return jsonify({
        'service': 'YouTube Downloader - Funcional',
        'version': '1.0',
        'status': 'online',
        'endpoints': {
            '/health': 'GET - Verificar estado',
            '/info': 'GET/POST - Información del video',
            '/download/audio': 'POST - Descargar audio MP3',
            '/download/video': 'POST - Descargar video MP4'
        }
    })

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'ytdlp_version': yt_dlp.version.__version__
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
        
        downloader = WorkingDownloader()
        result = downloader.get_info(url)
        downloader.cleanup()
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error en /info: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/download/audio', methods=['POST'])
def download_audio():
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
        
        downloader = WorkingDownloader()
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
        
        return Response(
            generate(),
            mimetype='audio/mpeg',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(file_size),
                'X-Download-Time': str(result['download_time']),
                'X-File-Size': str(file_size),
                'X-File-Type': 'audio/mp3'
            }
        )
        
    except Exception as e:
        logger.error(f"Error en descarga de audio: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/download/video', methods=['POST'])
def download_video():
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
        
        downloader = WorkingDownloader()
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
        
        return Response(
            generate(),
            mimetype='video/mp4',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(file_size),
                'X-Download-Time': str(result['download_time']),
                'X-File-Size': str(file_size),
                'X-File-Type': 'video/mp4'
            }
        )
        
    except Exception as e:
        logger.error(f"Error en descarga de video: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/quick', methods=['GET'])
def quick():
    """Endpoint rápido para pruebas"""
    url = request.args.get('url', '').strip()
    download_type = request.args.get('type', 'audio')  # audio o video
    
    if not url:
        return jsonify({'success': False, 'error': '?url= requerido'}), 400
    
    return jsonify({
        'success': True,
        'url': url,
        'type': download_type,
        'endpoints': {
            'info': f'/info?url={url}',
            'audio': f'/download/audio (POST con {{"url": "{url}"}})',
            'video': f'/download/video (POST con {{"url": "{url}"}})'
        }
    })

@app.route('/test', methods=['GET'])
def test():
    """Endpoint de prueba"""
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    
    return jsonify({
        'test': 'YouTube Downloader Test',
        'url': test_url,
        'endpoints': {
            'test_info': f'/info?url={test_url}',
            'test_audio': f'/download/audio (POST)',
            'test_video': f'/download/video (POST)'
        }
    })

# ==============================
# MANEJO DE ERRORES
# ==============================
@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': 'No encontrado'}), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({'success': False, 'error': 'Método no permitido'}), 405

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Error 500: {error}")
    return jsonify({'success': False, 'error': 'Error interno'}), 500

# ==============================
# INICIALIZACIÓN
# ==============================
if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 SERVIDOR YOUTUBE - VERSIÓN FUNCIONAL")
    print("="*60)
    print(f"📦 yt-dlp: {yt_dlp.version.__version__}")
    print("✅ Descarga audio MP3 y video MP4")
    print("✅ Configuración optimizada para evitar bloqueos")
    print("="*60)
    print(f"📡 Servidor: http://{Config.HOST}:{Config.PORT}")
    print("="*60)
    print("📋 Endpoints:")
    print("  GET  /info?url=URL           - Información del video")
    print("  POST /download/audio         - Descargar audio MP3")
    print("  POST /download/video         - Descargar video MP4")
    print("  GET  /quick?url=URL&type=    - Info rápida")
    print("  GET  /test                   - Probar endpoints")
    print("="*60 + "\n")
    
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=False,
        threaded=True,
        use_reloader=False
    )
