#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE - VERSIÓN RESISTENTE A ERRORES
Versión: 9.0 - Manejo mejorado de errores y cookies
"""

import os
import sys
import json
import logging
import tempfile
import shutil
import time
import subprocess
import random
from datetime import datetime
from typing import Dict, Any, Optional

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp

# ==============================
# CONFIGURACIÓN
# ==============================
class Config:
    PORT = int(os.environ.get('PORT', 10000))
    HOST = '0.0.0.0'
    MAX_FILE_SIZE = 200 * 1024 * 1024
    COOKIES_FILE = 'cookies.txt'
    TEMP_RETRIES = 3
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0',
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
    logging.getLogger('yt_dlp').setLevel(logging.WARNING)
    return logging.getLogger(__name__)

logger = setup_logging()

# ==============================
# UTILIDADES
# ==============================
def get_random_user_agent():
    return random.choice(Config.USER_AGENTS)

def clean_cookies_file():
    """Limpia el archivo de cookies de líneas inválidas"""
    if not os.path.exists(Config.COOKIES_FILE):
        return False
    
    try:
        with open(Config.COOKIES_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Filtrar solo líneas válidas (que contengan .youtube.com)
        valid_lines = []
        for line in lines:
            line = line.strip()
            if line.startswith('#') or not line:
                valid_lines.append(line)
            elif '.youtube.com' in line and len(line.split('\t')) >= 7:
                valid_lines.append(line)
        
        if len(valid_lines) > 5:  # Si hay suficientes cookies válidas
            with open(Config.COOKIES_FILE, 'w', encoding='utf-8') as f:
                f.write('\n'.join(valid_lines))
            logger.info(f"✅ Cookies limpiadas: {len(valid_lines)} líneas válidas")
            return True
        else:
            logger.warning("⚠️  Pocas cookies válidas encontradas")
            return False
    except Exception as e:
        logger.error(f"Error limpiando cookies: {e}")
        return False

def check_cookies_validity():
    """Verifica si las cookies son válidas"""
    if not os.path.exists(Config.COOKIES_FILE):
        return False, "Archivo no existe"
    
    try:
        size = os.path.getsize(Config.COOKIES_FILE)
        if size < 100:
            return False, "Archivo muy pequeño"
        
        with open(Config.COOKIES_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verificar formato básico
        if '.youtube.com' not in content:
            return False, "No contiene dominio youtube.com"
        
        # Verificar cookies importantes
        required_cookies = ['__Secure-3PSID', 'LOGIN_INFO', 'SID']
        has_required = any(cookie in content for cookie in required_cookies)
        
        if not has_required:
            return True, "Cookies básicas encontradas (algunas pueden faltar)"
        
        return True, "Cookies válidas detectadas"
    except Exception as e:
        return False, f"Error: {str(e)}"

# ==============================
# CLASE PRINCIPAL
# ==============================
class YouTubeDownloader:
    def __init__(self):
        self.temp_dir = None
        self.output_path = None
        self.cookies_config = {}
        self.cookies_valid = False
        
        self._init_cookies()
    
    def _init_cookies(self):
        """Inicializa las cookies con verificación robusta"""
        # Primero limpiar el archivo de cookies
        clean_cookies_file()
        
        # Verificar validez
        self.cookies_valid, message = check_cookies_validity()
        
        if self.cookies_valid:
            self.cookies_config = {
                'cookiefile': Config.COOKIES_FILE,
                'cookiesfrombrowser': None  # Forzar uso del archivo
            }
            logger.info(f"✅ {message}")
        else:
            logger.warning(f"⚠️  {message} - Operando sin cookies")
    
    def _get_base_options(self, retry_count=0):
        """Opciones base con manejo de reintentos"""
        base_opts = {
            'quiet': True,
            'no_warnings': retry_count > 1,  # Mostrar warnings solo en primeros intentos
            'ignoreerrors': True,
            'no_color': True,
            'noprogress': True,
            'socket_timeout': 30 + (retry_count * 10),
            'retries': 10,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True,
            'noplaylist': True,
            'extract_flat': False,
            'ignore_no_formats_error': True,
            
            # Headers dinámicos
            'http_headers': {
                'User-Agent': get_random_user_agent(),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0',
            },
            
            # Configuraciones específicas para YouTube
            'youtube_include_dash_manifest': True,
            'youtube_include_hls_manifest': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'skip': ['hls', 'dash'],
                }
            },
        }
        
        # Añadir cookies solo si son válidas y no estamos en reintento fallido
        if self.cookies_valid and retry_count < 2:
            base_opts.update(self.cookies_config)
        
        # En reintentos, cambiar estrategia
        if retry_count > 0:
            base_opts['extractor_args']['youtube']['player_client'].append('ios')
            base_opts['http_headers']['User-Agent'] = get_random_user_agent()
        
        return base_opts
    
    def get_info(self, url: str) -> Dict[str, Any]:
        """Obtiene información del video con reintentos"""
        max_retries = 2
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                ydl_opts = self._get_base_options(attempt)
                ydl_opts['skip_download'] = True
                
                # En el último intento, forzar modo simple
                if attempt == max_retries:
                    ydl_opts['extract_flat'] = True
                    if 'cookiefile' in ydl_opts:
                        del ydl_opts['cookiefile']
                
                logger.info(f"Obteniendo info (intento {attempt + 1}) para: {url[:50]}...")
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    
                    if not info:
                        return {
                            'success': False, 
                            'error': 'Video no encontrado',
                            'has_cookies': self.cookies_valid
                        }
                    
                    # Formatear información
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
                        'has_cookies': self.cookies_valid,
                        'formats_count': len(info.get('formats', [])),
                        'attempt': attempt + 1
                    }
                    
            except yt_dlp.utils.DownloadError as e:
                error_msg = str(e)
                last_error = error_msg
                logger.warning(f"Intento {attempt + 1} fallido: {error_msg[:100]}")
                
                # Si es error de player response, intentar sin cookies
                if "Failed to extract any player response" in error_msg:
                    logger.info("Probando sin cookies en próximo intento...")
                    # Forzar no cookies en próximo intento
                    self.cookies_valid = False
                    continue
                
                # Esperar antes de reintentar
                if attempt < max_retries:
                    time.sleep(1)
                    
            except Exception as e:
                error_msg = str(e)
                last_error = error_msg
                logger.error(f"Error en get_info (intento {attempt + 1}): {error_msg}")
                if attempt < max_retries:
                    time.sleep(1)
        
        # Si llegamos aquí, todos los intentos fallaron
        error_msg = last_error or "Error desconocido"
        
        # Mensajes de error más amigables
        if "Private" in error_msg or "Sign in" in error_msg:
            return {
                'success': False, 
                'error': 'Video privado o requiere login',
                'has_cookies': self.cookies_valid,
                'suggestion': 'Verifica que las cookies sean válidas y estén actualizadas'
            }
        elif "Failed to extract any player response" in error_msg:
            return {
                'success': False,
                'error': 'Error de conexión con YouTube',
                'has_cookies': self.cookies_valid,
                'suggestion': 'Intenta nuevamente en unos momentos o verifica la URL'
            }
        else:
            return {
                'success': False, 
                'error': f'Error: {error_msg[:200]}',
                'has_cookies': self.cookies_valid
            }
    
    def download_audio(self, url: str) -> Dict[str, Any]:
        """Descarga audio con manejo robusto"""
        self.temp_dir = tempfile.mkdtemp(prefix="yt_audio_")
        start_time = time.time()
        
        try:
            # Opciones para audio con múltiples formatos de respaldo
            ydl_opts = self._get_base_options(0)
            ydl_opts.update({
                'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'keepvideo': False,
                'writethumbnail': False,
                'quiet': False,  # Mostrar progreso para debugging
            })
            
            logger.info(f"Descargando audio: {url}")
            
            # Intentar descarga
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'audio') if info else 'audio'
            
            # Buscar archivo MP3
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file.endswith('.mp3'):
                        self.output_path = os.path.join(root, file)
                        break
                if self.output_path:
                    break
            
            # Si no hay MP3, buscar y convertir
            if not self.output_path:
                audio_files = []
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        if any(file.endswith(ext) for ext in ['.m4a', '.webm', '.opus', '.wav']):
                            audio_files.append(os.path.join(root, file))
                
                if audio_files:
                    # Convertir el primer archivo a MP3
                    audio_file = audio_files[0]
                    mp3_output = os.path.join(self.temp_dir, 'converted.mp3')
                    
                    try:
                        result = subprocess.run([
                            'ffmpeg', '-i', audio_file,
                            '-codec:a', 'libmp3lame',
                            '-q:a', '2',
                            '-y', mp3_output
                        ], capture_output=True, text=True, timeout=60)
                        
                        if os.path.exists(mp3_output):
                            self.output_path = mp3_output
                    except Exception as e:
                        logger.error(f"Error convirtiendo a MP3: {e}")
            
            if not self.output_path or not os.path.exists(self.output_path):
                return {
                    'success': False, 
                    'error': 'No se pudo generar archivo de audio',
                    'has_cookies': self.cookies_valid
                }
            
            file_size = os.path.getsize(self.output_path)
            
            if file_size == 0:
                return {'success': False, 'error': 'Archivo vacío', 'has_cookies': self.cookies_valid}
            
            if file_size > Config.MAX_FILE_SIZE:
                return {'success': False, 'error': 'Archivo muy grande', 'has_cookies': self.cookies_valid}
            
            # Nombre seguro para descarga
            safe_title = ''.join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()[:100]
            safe_title = safe_title or 'audio_descargado'
            download_filename = f"{safe_title}.mp3"
            
            download_time = time.time() - start_time
            
            return {
                'success': True,
                'filename': download_filename,
                'filepath': self.output_path,
                'filesize': file_size,
                'filesize_mb': round(file_size / (1024 * 1024), 2),
                'download_time': round(download_time, 2),
                'title': title,
                'type': 'audio',
                'format': 'mp3',
                'has_cookies': self.cookies_valid
            }
                
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            logger.error(f"Error de descarga: {error_msg}")
            
            if "Failed to extract any player response" in error_msg:
                return {
                    'success': False,
                    'error': 'Error de conexión con YouTube',
                    'has_cookies': self.cookies_valid,
                    'suggestion': 'Las cookies pueden estar expiradas o la URL es inválida'
                }
            else:
                return {'success': False, 'error': error_msg[:200], 'has_cookies': self.cookies_valid}
                
        except Exception as e:
            logger.error(f"Error descargando audio: {e}")
            return {'success': False, 'error': str(e)[:200], 'has_cookies': self.cookies_valid}
    
    def cleanup(self):
        """Limpia archivos temporales"""
        try:
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception as e:
            logger.debug(f"Error limpiando temporal: {e}")

# ==============================
# FLASK APP
# ==============================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ==============================
# ENDPOINTS
# ==============================

@app.route('/')
def home():
    """Endpoint principal"""
    cookies_valid, message = check_cookies_validity()
    
    return jsonify({
        'service': 'YouTube Downloader API',
        'version': '9.0 - Resistentes a Errores',
        'status': 'online',
        'cookies': {
            'enabled': cookies_valid,
            'message': message,
            'file': Config.COOKIES_FILE,
            'size': os.path.getsize(Config.COOKIES_FILE) if os.path.exists(Config.COOKIES_FILE) else 0
        },
        'endpoints': {
            'GET /': 'Esta página',
            'GET /health': 'Estado del servidor',
            'GET /info?url=URL': 'Info del video',
            'POST /info': 'Info del video (POST)',
            'POST /download/audio': 'Descargar audio MP3',
            'GET /cookies/status': 'Estado detallado cookies',
            'GET /cookies/refresh': 'Refrescar cookies'
        }
    })

@app.route('/health')
def health():
    """Health check"""
    cookies_valid, message = check_cookies_validity()
    
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'cookies': {
            'valid': cookies_valid,
            'message': message,
            'file_exists': os.path.exists(Config.COOKIES_FILE),
            'file_size': os.path.getsize(Config.COOKIES_FILE) if os.path.exists(Config.COOKIES_FILE) else 0
        },
        'system': {
            'python': sys.version.split()[0],
            'platform': sys.platform,
            'working_directory': os.getcwd()
        }
    })

@app.route('/info', methods=['GET', 'POST'])
def get_info():
    """Obtiene información del video"""
    try:
        # Obtener URL
        if request.method == 'POST':
            if request.is_json:
                data = request.get_json()
            elif request.form:
                data = request.form.to_dict()
            else:
                body_text = request.get_data(as_text=True)
                data = {'url': body_text.strip()} if body_text else {}
        else:  # GET
            data = request.args
        
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        # Verificar si es URL de YouTube
        if not ('youtube.com' in url or 'youtu.be' in url):
            return jsonify({'success': False, 'error': 'URL de YouTube inválida'}), 400
        
        logger.info(f"Info solicitada para: {url[:50]}...")
        
        # Procesar
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
        
        # Descargar
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
            mimetype='audio/mpeg',
            conditional=True
        )
        
        # Headers informativos
        response.headers['X-File-Size'] = str(result['filesize'])
        response.headers['X-Download-Time'] = str(result['download_time'])
        response.headers['X-Has-Cookies'] = str(result.get('has_cookies', False))
        
        # Limpiar después de enviar
        @response.call_on_close
        def cleanup_after_send():
            downloader.cleanup()
        
        return response
        
    except Exception as e:
        logger.error(f"Error en /download/audio: {e}")
        return jsonify({'success': False, 'error': str(e)[:200]}), 500

@app.route('/cookies/status', methods=['GET'])
def cookies_status():
    """Estado detallado de cookies"""
    cookies_valid, message = check_cookies_validity()
    
    if not os.path.exists(Config.COOKIES_FILE):
        return jsonify({
            'exists': False,
            'valid': False,
            'message': 'Archivo no encontrado',
            'path': os.path.abspath(Config.COOKIES_FILE)
        })
    
    try:
        with open(Config.COOKIES_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        lines = content.strip().split('\n')
        youtube_lines = [l for l in lines if '.youtube.com' in l]
        
        # Contar cookies importantes
        important_cookies = {
            '__Secure-3PSID': 0,
            'LOGIN_INFO': 0,
            'SID': 0,
            '__Secure-1PSID': 0,
            'VISITOR_INFO1_LIVE': 0,
            'YSC': 0
        }
        
        for cookie_name in important_cookies:
            important_cookies[cookie_name] = sum(1 for l in youtube_lines if cookie_name in l)
        
        return jsonify({
            'exists': True,
            'valid': cookies_valid,
            'message': message,
            'details': {
                'file_size': os.path.getsize(Config.COOKIES_FILE),
                'total_lines': len(lines),
                'youtube_cookies': len(youtube_lines),
                'important_cookies': important_cookies,
                'has_netscape_header': any('Netscape HTTP Cookie File' in l for l in lines[:3]),
                'sample': content[:500] + '...' if len(content) > 500 else content
            }
        })
        
    except Exception as e:
        return jsonify({
            'exists': True,
            'valid': False,
            'error': str(e),
            'path': os.path.abspath(Config.COOKIES_FILE)
        })

@app.route('/cookies/refresh', methods=['GET'])
def refresh_cookies():
    """Refresca y limpia las cookies"""
    try:
        cleaned = clean_cookies_file()
        cookies_valid, message = check_cookies_validity()
        
        return jsonify({
            'success': True,
            'cleaned': cleaned,
            'valid': cookies_valid,
            'message': message,
            'file_size': os.path.getsize(Config.COOKIES_FILE) if os.path.exists(Config.COOKIES_FILE) else 0
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/test', methods=['GET'])
def test_connection():
    """Endpoint de prueba simple"""
    return jsonify({
        'success': True,
        'message': 'Servidor funcionando',
        'timestamp': datetime.now().isoformat()
    })

# ==============================
# ERROR HANDLERS
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
    return jsonify({'success': False, 'error': 'Error interno'}), 500

# ==============================
# INICIALIZACIÓN
# ==============================
if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 SERVIDOR YOUTUBE - VERSIÓN RESISTENTE 9.0")
    print("="*60)
    
    # Verificar cookies
    cookies_valid, message = check_cookies_validity()
    if cookies_valid:
        print(f"✅ Cookies: {message}")
    else:
        print(f"⚠️  Cookies: {message}")
    
    # Verificar ffmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ FFmpeg: Disponible")
    except:
        print("⚠️  FFmpeg: No disponible (la conversión puede fallar)")
    
    print(f"✅ Puerto: {Config.PORT}")
    print(f"✅ Host: {Config.HOST}")
    print("="*60)
    print("📡 Endpoints:")
    print("  GET /                 - Esta página")
    print("  GET /health           - Estado del servidor")
    print("  POST /info            - Info del video")
    print("  POST /download/audio  - Descargar audio MP3")
    print("  GET /cookies/status   - Verificar cookies")
    print("  GET /cookies/refresh  - Limpiar cookies")
    print("="*60)
    print("🔧 Características:")
    print("  • Reintentos automáticos")
    print("  • Manejo robusto de errores")
    print("  • User-Agents rotativos")
    print("  • Limpieza automática de cookies")
    print("="*60 + "\n")
    
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=False,
        threaded=True
    )
