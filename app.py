#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE ULTRA SIMPLE - VERSIÓN CORREGIDA
Versión: 8.0 - Corrección de formato + Cookies robustas
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
        self._load_cookies()
    
    def _load_cookies(self):
        """Carga las cookies de manera robusta"""
        if os.path.exists(Config.COOKIES_FILE):
            try:
                file_size = os.path.getsize(Config.COOKIES_FILE)
                if file_size > 100:  # Archivo no vacío
                    # Verificar formato de cookies
                    with open(Config.COOKIES_FILE, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    if 'youtube.com' in content or 'Netscape' in content:
                        self.cookies_config = {'cookiefile': Config.COOKIES_FILE}
                        logger.info(f"✅ Cookies cargadas correctamente ({file_size} bytes)")
                    else:
                        logger.warning("⚠️  Archivo de cookies no tiene formato válido")
                else:
                    logger.warning("⚠️  Archivo de cookies vacío")
            except Exception as e:
                logger.error(f"⚠️  Error leyendo cookies: {e}")
        else:
            logger.info("ℹ️  No hay archivo de cookies, operando en modo público")
    
    def _get_base_options(self):
        """Opciones base con headers robustos para evitar detección"""
        base_opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'no_color': True,
            'noprogress': True,
            'socket_timeout': 30,
            'retries': 10,
            'fragment_retries': 10,
            'buffersize': 1024 * 1024,
            'http_chunk_size': 10 * 1024 * 1024,
            'noplaylist': True,
            
            # Headers robustos para evitar detección como bot
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0',
                'DNT': '1',
            },
            
            # Parámetros para YouTube
            'youtube_include_dash_manifest': False,
            'youtube_include_hls_manifest': False,
        }
        
        # Añadir cookies si están disponibles
        if self.cookies_config:
            base_opts.update(self.cookies_config)
        
        return base_opts
    
    def _get_format_options(self, media_type='audio'):
        """Obtiene opciones de formato flexibles que evitan errores"""
        if media_type == 'audio':
            # Formatos de audio en orden de preferencia
            return {
                'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'keepvideo': False,
            }
        else:  # video
            # Formatos de video en orden de preferencia
            return {
                'format': 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best[ext=webm]/best',
                'merge_output_format': 'mp4',
            }
    
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
                
                # Verificar formatos disponibles
                formats = info.get('formats', [])
                has_audio = any(f.get('vcodec') == 'none' for f in formats)
                has_video = any(f.get('acodec') != 'none' and f.get('vcodec') != 'none' for f in formats)
                
                return {
                    'success': True,
                    'title': info.get('title', 'Video sin título'),
                    'duration': duration_str,
                    'duration_seconds': duration,
                    'uploader': info.get('uploader', 'Desconocido'),
                    'view_count': info.get('view_count', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'available': True,
                    'has_cookies': bool(self.cookies_config),
                    'formats_available': {
                        'audio': has_audio,
                        'video': has_video
                    },
                    'formats_count': len(formats)
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
            elif "format" in error_msg.lower():
                return {
                    'success': False,
                    'error': 'Error de formato disponible - Intente nuevamente',
                    'has_cookies': bool(self.cookies_config)
                }
            else:
                return {'success': False, 'error': 'Error obteniendo información'}
    
    def download_audio(self, url: str) -> Dict[str, Any]:
        """Descarga audio - Método robusto"""
        self.temp_dir = tempfile.mkdtemp(prefix="yt_audio_")
        start_time = time.time()
        
        try:
            # Opciones flexibles para audio
            ydl_opts = self._get_base_options()
            ydl_opts.update({
                'outtmpl': os.path.join(self.temp_dir, 'audio.%(ext)s'),
            })
            ydl_opts.update(self._get_format_options('audio'))
            
            logger.info(f"Descargando audio: {url}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'audio') if info else 'audio'
            
            # Buscar archivo MP3 generado
            mp3_file = os.path.join(self.temp_dir, 'audio.mp3')
            
            if os.path.exists(mp3_file):
                self.output_path = mp3_file
            else:
                # Buscar cualquier archivo MP3 en el directorio
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        if file.endswith('.mp3'):
                            self.output_path = os.path.join(root, file)
                            break
                    if self.output_path:
                        break
            
            # Si no hay MP3, buscar archivos de audio y convertir
            if not self.output_path or not os.path.exists(self.output_path):
                # Buscar cualquier archivo de audio
                audio_extensions = ['.m4a', '.webm', '.opus', '.wav', '.flac']
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        if any(file.endswith(ext) for ext in audio_extensions):
                            audio_file = os.path.join(root, file)
                            # Convertir a MP3
                            import subprocess
                            mp3_output = os.path.join(self.temp_dir, 'converted.mp3')
                            try:
                                subprocess.run([
                                    'ffmpeg', '-i', audio_file,
                                    '-codec:a', 'libmp3lame',
                                    '-qscale:a', '2',
                                    mp3_output
                                ], check=True, capture_output=True)
                                if os.path.exists(mp3_output):
                                    self.output_path = mp3_output
                                    break
                            except:
                                pass
                    if self.output_path:
                        break
            
            if not self.output_path or not os.path.exists(self.output_path):
                return {'success': False, 'error': 'No se pudo generar archivo MP3'}
            
            file_size = os.path.getsize(self.output_path)
            
            if file_size == 0:
                return {'success': False, 'error': 'Archivo vacío'}
            
            if file_size > Config.MAX_FILE_SIZE:
                return {'success': False, 'error': 'Archivo muy grande'}
            
            # Crear nombre de archivo seguro
            safe_title = ''.join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()[:50]
            download_filename = f"{safe_title}.mp3"
            
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
                'type': 'audio',
                'format': 'mp3',
                'has_cookies': bool(self.cookies_config)
            }
                
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            logger.error(f"Error de descarga: {error_msg}")
            
            if "format" in error_msg.lower():
                return {
                    'success': False,
                    'error': 'Formato no disponible - Intente con otro video',
                    'has_cookies': bool(self.cookies_config)
                }
            elif "Private" in error_msg or "Sign in" in error_msg:
                return {
                    'success': False,
                    'error': 'Video privado o requiere login',
                    'has_cookies': bool(self.cookies_config)
                }
            else:
                return {'success': False, 'error': error_msg[:200]}
                
        except Exception as e:
            logger.error(f"Error descargando audio: {e}")
            return {'success': False, 'error': str(e)[:200]}
    
    def download_video(self, url: str) -> Dict[str, Any]:
        """Descarga video - Método robusto"""
        self.temp_dir = tempfile.mkdtemp(prefix="yt_video_")
        start_time = time.time()
        
        try:
            # Opciones flexibles para video
            ydl_opts = self._get_base_options()
            ydl_opts.update({
                'outtmpl': os.path.join(self.temp_dir, 'video.%(ext)s'),
            })
            ydl_opts.update(self._get_format_options('video'))
            
            logger.info(f"Descargando video: {url}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'video') if info else 'video'
            
            # Buscar archivo de video
            video_extensions = ['.mp4', '.webm', '.mkv', '.avi', '.mov']
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if any(file.endswith(ext) for ext in video_extensions):
                        self.output_path = os.path.join(root, file)
                        break
                if self.output_path:
                    break
            
            if not self.output_path or not os.path.exists(self.output_path):
                return {'success': False, 'error': 'No se generó archivo de video'}
            
            file_size = os.path.getsize(self.output_path)
            
            if file_size == 0:
                return {'success': False, 'error': 'Archivo vacío'}
            
            if file_size > Config.MAX_FILE_SIZE:
                return {'success': False, 'error': 'Archivo muy grande'}
            
            # Crear nombre de archivo seguro
            safe_title = ''.join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()[:50]
            file_ext = os.path.splitext(self.output_path)[1] or '.mp4'
            download_filename = f"{safe_title}{file_ext}"
            
            # Determinar mimetype
            mimetypes = {
                '.mp4': 'video/mp4',
                '.webm': 'video/webm',
                '.mkv': 'video/x-matroska',
                '.avi': 'video/x-msvideo',
                '.mov': 'video/quicktime'
            }
            mimetype = mimetypes.get(file_ext.lower(), 'application/octet-stream')
            
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
                'mimetype': mimetype,
                'has_cookies': bool(self.cookies_config)
            }
                
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            logger.error(f"Error de descarga video: {error_msg}")
            
            if "format" in error_msg.lower():
                return {
                    'success': False,
                    'error': 'Formato de video no disponible',
                    'has_cookies': bool(self.cookies_config)
                }
            else:
                return {'success': False, 'error': error_msg[:200]}
                
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
    has_cookies = os.path.exists(Config.COOKIES_FILE) and os.path.getsize(Config.COOKIES_FILE) > 100
    
    return jsonify({
        'service': 'YouTube Downloader API',
        'version': '8.0 - Formato Robusto + Cookies',
        'status': 'online',
        'has_cookies': has_cookies,
        'cookie_file': Config.COOKIES_FILE,
        'cookie_size': os.path.getsize(Config.COOKIES_FILE) if os.path.exists(Config.COOKIES_FILE) else 0,
        'endpoints': {
            'GET /': 'Esta página',
            'GET /health': 'Estado del servidor',
            'GET /info?url=URL': 'Información del video',
            'POST /info': 'Información del video (POST)',
            'POST /download/audio': 'Descargar audio MP3',
            'POST /download/video': 'Descargar video',
            'GET /test/cookies': 'Probar cookies'
        },
        'note': 'Sistema de formatos flexibles para evitar errores'
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
            'valid': has_cookies,
            'file': Config.COOKIES_FILE
        },
        'system': {
            'python': sys.version,
            'platform': sys.platform,
            'memory': os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') if hasattr(os, 'sysconf') else 'unknown'
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
    """Descarga audio MP3"""
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
        
        # Enviar archivo
        response = send_file(
            result['filepath'],
            as_attachment=True,
            download_name=result['filename'],
            mimetype='audio/mpeg'
        )
        
        # Headers informativos
        response.headers['X-Download-Time'] = str(result['download_time'])
        response.headers['X-File-Size'] = str(result['filesize'])
        response.headers['X-Has-Cookies'] = str(result.get('has_cookies', False))
        
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
        response.headers['X-Has-Cookies'] = str(result.get('has_cookies', False))
        
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
            'file_size': os.path.getsize(Config.COOKIES_FILE) if os.path.exists(Config.COOKIES_FILE) else 0,
            'file_path': os.path.abspath(Config.COOKIES_FILE)
        })
    
    # Probar con un video público (Rick Astley - Never Gonna Give You Up)
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    
    try:
        downloader = YouTubeDownloader()
        result = downloader.get_info(test_url)
        downloader.cleanup()
        
        # Leer contenido del archivo de cookies para verificación
        cookie_content = ""
        try:
            with open(Config.COOKIES_FILE, 'r', encoding='utf-8') as f:
                cookie_content = f.read(500)  # Leer primeros 500 caracteres
        except:
            pass
        
        if result['success']:
            return jsonify({
                'success': True,
                'message': '✅ Cookies funcionan correctamente',
                'test_video': result['title'],
                'cookies_info': {
                    'file_size': os.path.getsize(Config.COOKIES_FILE),
                    'has_youtube_domain': '.youtube.com' in cookie_content,
                    'has_secure_cookies': '__Secure-' in cookie_content,
                    'sample': cookie_content[:200] + '...' if len(cookie_content) > 200 else cookie_content
                }
            })
        else:
            return jsonify({
                'success': False,
                'message': '⚠️ Las cookies pueden no estar funcionando',
                'error': result['error'],
                'cookies_info': {
                    'file_size': os.path.getsize(Config.COOKIES_FILE),
                    'sample': cookie_content[:200] + '...' if len(cookie_content) > 200 else cookie_content
                }
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': '❌ Error probando cookies',
            'error': str(e)
        })

@app.route('/cookies/status', methods=['GET'])
def cookies_status():
    """Estado detallado de las cookies"""
    cookie_file = Config.COOKIES_FILE
    
    if not os.path.exists(cookie_file):
        return jsonify({
            'exists': False,
            'message': 'Archivo de cookies no encontrado'
        })
    
    try:
        file_size = os.path.getsize(cookie_file)
        
        with open(cookie_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Analizar contenido
        lines = content.strip().split('\n')
        youtube_lines = [l for l in lines if '.youtube.com' in l]
        secure_cookies = [l for l in lines if '__Secure-' in l]
        
        return jsonify({
            'exists': True,
            'file_size': file_size,
            'file_path': os.path.abspath(cookie_file),
            'analysis': {
                'total_lines': len(lines),
                'youtube_domain_lines': len(youtube_lines),
                'secure_cookies': len(secure_cookies),
                'has_netscape_header': 'Netscape HTTP Cookie File' in content,
                'has_valid_format': all(l.count('\t') >= 6 for l in youtube_lines) if youtube_lines else False
            },
            'sample_first_lines': lines[:5] if lines else []
        })
        
    except Exception as e:
        return jsonify({
            'exists': True,
            'error': str(e),
            'file_path': os.path.abspath(cookie_file)
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
    print("🚀 SERVIDOR YOUTUBE - VERSIÓN ROBUSTA 8.0")
    print("="*60)
    print(f"✅ Puerto: {Config.PORT}")
    print(f"✅ Host: {Config.HOST}")
    
    if os.path.exists(Config.COOKIES_FILE):
        file_size = os.path.getsize(Config.COOKIES_FILE)
        print(f"✅ Cookies: {Config.COOKIES_FILE} ({file_size} bytes)")
        
        # Verificar formato
        try:
            with open(Config.COOKIES_FILE, 'r', encoding='utf-8') as f:
                first_line = f.readline().strip()
                if 'Netscape HTTP Cookie File' in first_line:
                    print("✅ Formato de cookies: Netscape (válido)")
                else:
                    print("⚠️  Formato de cookies: No estándar (puede funcionar)")
        except:
            print("⚠️  No se pudo verificar formato de cookies")
    else:
        print("⚠️  Cookies: No encontrado (modo guest)")
    
    print("="*60)
    print("📡 Endpoints disponibles:")
    print("  GET /info?url=URL     - Información del video")
    print("  POST /download/audio  - Descargar audio MP3")
    print("  POST /download/video  - Descargar video")
    print("  GET /test/cookies     - Probar cookies")
    print("  GET /cookies/status   - Estado detallado cookies")
    print("="*60)
    print("🔧 Características:")
    print("  • Sistema de formatos flexibles")
    print("  • Headers anti-bot mejorados")
    print("  • Manejo robusto de cookies")
    print("  • Conversión automática a MP3")
    print("="*60 + "\n")
    
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=False,
        threaded=True
    )
