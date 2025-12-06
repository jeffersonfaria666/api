#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE - VERSIÓN SIN COOKIES CON RATE LIMITING
Versión: 10.0 - Manejo de errores 429 y cookies expiradas
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
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from collections import defaultdict
from urllib.parse import urlparse

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
    
    # Rate limiting
    REQUESTS_PER_MINUTE = 30  # Límite conservador para evitar 429
    ENABLE_RATE_LIMITING = True
    
    # User Agents
    USER_AGENTS = [
        # Chrome en Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
        
        # Firefox
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0',
        
        # Safari
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        
        # Edge
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
        
        # Mobile
        'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    ]
    
    # Proxies (opcional, dejar vacío si no se usan)
    PROXIES = []  # Ejemplo: ['http://proxy1:port', 'http://proxy2:port']
    
    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # segundos entre reintentos
    
    # Timeouts
    SOCKET_TIMEOUT = 45
    CONNECT_TIMEOUT = 30

# ==============================
# RATE LIMITER
# ==============================
class RateLimiter:
    """Simple rate limiter para evitar error 429"""
    def __init__(self, requests_per_minute: int = 30):
        self.requests_per_minute = requests_per_minute
        self.request_times = []
        self.lock = threading.Lock()
    
    def wait_if_needed(self):
        """Espera si se ha excedido el límite de requests"""
        if not Config.ENABLE_RATE_LIMITING:
            return
        
        with self.lock:
            now = time.time()
            
            # Limpiar requests más viejos de 1 minuto
            cutoff_time = now - 60
            self.request_times = [t for t in self.request_times if t > cutoff_time]
            
            # Si estamos cerca del límite, esperar
            if len(self.request_times) >= self.requests_per_minute:
                oldest_time = self.request_times[0]
                wait_time = 60 - (now - oldest_time)
                if wait_time > 0:
                    logger.info(f"⏳ Rate limiting: esperando {wait_time:.1f}s")
                    time.sleep(wait_time)
                    # Actualizar lista después de esperar
                    now = time.time()
                    cutoff_time = now - 60
                    self.request_times = [t for t in self.request_times if t > cutoff_time]
            
            # Agregar este request
            self.request_times.append(now)
    
    def get_status(self):
        """Obtener estado actual del rate limiter"""
        with self.lock:
            now = time.time()
            cutoff_time = now - 60
            recent_requests = [t for t in self.request_times if t > cutoff_time]
            return {
                'recent_requests': len(recent_requests),
                'limit_per_minute': self.requests_per_minute,
                'available': self.requests_per_minute - len(recent_requests),
                'oldest_request': min(recent_requests) if recent_requests else None
            }

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
    logging.getLogger('yt_dlp').setLevel(logging.ERROR)  # Reducir logs de yt-dlp
    return logging.getLogger(__name__)

logger = setup_logging()

# ==============================
# INSTANCIAS GLOBALES
# ==============================
rate_limiter = RateLimiter(Config.REQUESTS_PER_MINUTE)

# ==============================
# UTILIDADES
# ==============================
def get_random_user_agent():
    return random.choice(Config.USER_AGENTS)

def get_proxy():
    """Obtener proxy aleatorio si están configurados"""
    if Config.PROXIES:
        return random.choice(Config.PROXIES)
    return None

def is_cookies_valid():
    """Verificar si las cookies son válidas (básico)"""
    if not os.path.exists(Config.COOKIES_FILE):
        return False
    
    try:
        size = os.path.getsize(Config.COOKIES_FILE)
        if size < 100:
            return False
        
        # Verificar si tienen formato Netscape
        with open(Config.COOKIES_FILE, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
            if 'Netscape HTTP Cookie File' not in first_line:
                return False
        
        # Verificar si tienen cookies de YouTube
        with open(Config.COOKIES_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            if '.youtube.com' not in content:
                return False
        
        return True
    except:
        return False

def should_use_cookies():
    """Decide si usar cookies basado en su validez y estado actual"""
    if not is_cookies_valid():
        logger.info("⚠️  Cookies inválidas o expiradas, operando sin cookies")
        return False
    
    # Las cookies pueden ser válidas pero causar problemas
    # Por ahora, mejor no usarlas si hemos tenido problemas
    return False  # Forzar sin cookies por ahora

# ==============================
# CLASE PRINCIPAL
# ==============================
class YouTubeDownloader:
    def __init__(self, use_cookies: bool = None):
        self.temp_dir = None
        self.output_path = None
        
        # Decidir si usar cookies
        if use_cookies is None:
            self.use_cookies = should_use_cookies()
        else:
            self.use_cookies = use_cookies
        
        logger.info(f"📡 Modo: {'CON cookies' if self.use_cookies else 'SIN cookies'}")
    
    def _get_base_options(self, attempt: int = 0):
        """Opciones base optimizadas para evitar 429"""
        
        # Aplicar rate limiting
        rate_limiter.wait_if_needed()
        
        # User Agent específico para este intento
        user_agent = get_random_user_agent()
        
        base_opts = {
            'quiet': True,
            'no_warnings': attempt > 0,  # Solo warnings en primer intento
            'ignoreerrors': True,
            'no_color': True,
            'noprogress': True,
            'socket_timeout': Config.SOCKET_TIMEOUT,
            'connect_timeout': Config.CONNECT_TIMEOUT,
            'retries': 10,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True,
            'noplaylist': True,
            'extract_flat': False,
            'ignore_no_formats_error': True,
            'throttled_rate': '1M',  # Limitar velocidad de descarga
            
            # Headers para parecer navegador real
            'http_headers': {
                'User-Agent': user_agent,
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
                'DNT': '1',
            },
            
            # Configuración específica de YouTube
            'youtube_include_dash_manifest': False,
            'youtube_include_hls_manifest': False,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['configs'],
                    'skip': ['hls', 'dash'],
                }
            },
        }
        
        # Añadir cookies si se deben usar
        if self.use_cookies and is_cookies_valid():
            base_opts['cookiefile'] = Config.COOKIES_FILE
            logger.debug("Usando cookies del archivo")
        
        # Añadir proxy si está configurado (solo en reintentos)
        if attempt > 0 and Config.PROXIES:
            proxy = get_proxy()
            if proxy:
                base_opts['proxy'] = proxy
                logger.info(f"Usando proxy: {proxy}")
        
        # En reintentos, cambiar estrategia
        if attempt > 0:
            # Cambiar User Agent
            base_opts['http_headers']['User-Agent'] = get_random_user_agent()
            
            # Aumentar timeouts
            base_opts['socket_timeout'] = Config.SOCKET_TIMEOUT + (attempt * 10)
            base_opts['connect_timeout'] = Config.CONNECT_TIMEOUT + (attempt * 5)
            
            # Forzar modo simple en último intento
            if attempt >= 2:
                base_opts['extract_flat'] = True
                if 'cookiefile' in base_opts:
                    del base_opts['cookiefile']
        
        return base_opts
    
    def get_info(self, url: str) -> Dict[str, Any]:
        """Obtiene información del video con manejo robusto de errores"""
        last_error = None
        
        for attempt in range(Config.MAX_RETRIES):
            try:
                logger.info(f"📊 Obteniendo info (intento {attempt + 1}) para: {url[:50]}...")
                
                ydl_opts = self._get_base_options(attempt)
                ydl_opts['skip_download'] = True
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    
                    if not info:
                        return {
                            'success': False, 
                            'error': 'Video no encontrado o no disponible',
                            'used_cookies': self.use_cookies
                        }
                    
                    # Formatear información
                    duration = info.get('duration', 0)
                    if duration > 0:
                        minutes = duration // 60
                        seconds = duration % 60
                        duration_str = f"{minutes}:{seconds:02d}"
                    else:
                        duration_str = "Desconocida"
                    
                    # Verificar si hay formatos disponibles
                    formats = info.get('formats', [])
                    has_formats = len(formats) > 0
                    
                    return {
                        'success': True,
                        'title': info.get('title', 'Video sin título'),
                        'duration': duration_str,
                        'duration_seconds': duration,
                        'uploader': info.get('uploader', 'Desconocido'),
                        'view_count': info.get('view_count', 0),
                        'thumbnail': info.get('thumbnail', ''),
                        'available': True,
                        'has_formats': has_formats,
                        'formats_count': len(formats),
                        'used_cookies': self.use_cookies,
                        'attempt': attempt + 1
                    }
                    
            except yt_dlp.utils.DownloadError as e:
                error_msg = str(e)
                last_error = error_msg
                
                # Analizar tipo de error
                if "HTTP Error 429" in error_msg:
                    logger.warning(f"⏳ Error 429 (Too Many Requests) en intento {attempt + 1}")
                    # Esperar más tiempo antes de reintentar
                    wait_time = Config.RETRY_DELAY * (attempt + 2)  # Esperar más en cada intento
                    logger.info(f"Esperando {wait_time}s antes de reintentar...")
                    time.sleep(wait_time)
                    continue
                
                elif "Failed to extract any player response" in error_msg:
                    logger.warning(f"⚠️  Error de player response en intento {attempt + 1}")
                    # Cambiar estrategia: no usar cookies en próximo intento
                    self.use_cookies = False
                    
                elif "cookies are no longer valid" in error_msg:
                    logger.warning("🍪 Cookies expiradas, desactivando...")
                    self.use_cookies = False
                    
                else:
                    logger.error(f"❌ Error en intento {attempt + 1}: {error_msg[:100]}")
                
                # Esperar antes del siguiente intento
                if attempt < Config.MAX_RETRIES - 1:
                    time.sleep(Config.RETRY_DELAY)
                    
            except Exception as e:
                error_msg = str(e)
                last_error = error_msg
                logger.error(f"❌ Error inesperado en intento {attempt + 1}: {error_msg}")
                
                if attempt < Config.MAX_RETRIES - 1:
                    time.sleep(Config.RETRY_DELAY)
        
        # Si llegamos aquí, todos los intentos fallaron
        logger.error(f"❌ Todos los intentos fallaron para: {url}")
        
        # Mensaje de error amigable
        if last_error and "HTTP Error 429" in last_error:
            return {
                'success': False,
                'error': 'YouTube está limitando las solicitudes (Error 429). Por favor, espera unos minutos antes de intentar nuevamente.',
                'used_cookies': self.use_cookies,
                'suggestion': 'Intenta nuevamente en 2-3 minutos'
            }
        elif last_error and "Failed to extract any player response" in last_error:
            return {
                'success': False,
                'error': 'No se pudo acceder al video. Puede ser privado, estar restringido o tener limitaciones de región.',
                'used_cookies': self.use_cookies,
                'suggestion': 'Verifica que el video sea público y esté disponible'
            }
        else:
            return {
                'success': False,
                'error': f'Error al obtener información: {last_error[:200] if last_error else "Error desconocido"}',
                'used_cookies': self.use_cookies
            }
    
    def download_audio(self, url: str) -> Dict[str, Any]:
        """Descarga audio con manejo robusto"""
        self.temp_dir = tempfile.mkdtemp(prefix="yt_audio_")
        start_time = time.time()
        
        for attempt in range(Config.MAX_RETRIES):
            try:
                logger.info(f"🎵 Descargando audio (intento {attempt + 1}) para: {url[:50]}...")
                
                ydl_opts = self._get_base_options(attempt)
                ydl_opts.update({
                    'outtmpl': os.path.join(self.temp_dir, 'audio.%(ext)s'),
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'keepvideo': False,
                    'writethumbnail': False,
                    'quiet': attempt == 0,  # Mostrar logs solo en primer intento
                })
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    title = info.get('title', 'audio_descargado') if info else 'audio'
                
                # Buscar archivo MP3
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        if file.endswith('.mp3'):
                            self.output_path = os.path.join(root, file)
                            break
                    if self.output_path:
                        break
                
                # Si no se encontró MP3, buscar otros formatos y convertir
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
                            ], capture_output=True, text=True, timeout=120)
                            
                            if os.path.exists(mp3_output) and os.path.getsize(mp3_output) > 0:
                                self.output_path = mp3_output
                                logger.info("✅ Audio convertido a MP3 exitosamente")
                        except Exception as e:
                            logger.error(f"Error convirtiendo a MP3: {e}")
                
                if not self.output_path or not os.path.exists(self.output_path):
                    if attempt < Config.MAX_RETRIES - 1:
                        logger.warning(f"⚠️  No se generó archivo, reintentando...")
                        time.sleep(Config.RETRY_DELAY)
                        continue
                    else:
                        return {
                            'success': False, 
                            'error': 'No se pudo generar archivo de audio',
                            'used_cookies': self.use_cookies
                        }
                
                # Verificar archivo
                file_size = os.path.getsize(self.output_path)
                
                if file_size == 0:
                    if attempt < Config.MAX_RETRIES - 1:
                        logger.warning("⚠️  Archivo vacío, reintentando...")
                        time.sleep(Config.RETRY_DELAY)
                        continue
                    else:
                        return {'success': False, 'error': 'Archivo vacío', 'used_cookies': self.use_cookies}
                
                if file_size > Config.MAX_FILE_SIZE:
                    return {'success': False, 'error': 'Archivo muy grande', 'used_cookies': self.use_cookies}
                
                # Éxito
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
                    'used_cookies': self.use_cookies,
                    'attempts': attempt + 1
                }
                    
            except yt_dlp.utils.DownloadError as e:
                error_msg = str(e)
                logger.error(f"❌ Error de descarga (intento {attempt + 1}): {error_msg[:100]}")
                
                if "HTTP Error 429" in error_msg:
                    wait_time = Config.RETRY_DELAY * (attempt + 2) * 2  # Esperar más por 429
                    logger.info(f"⏳ Error 429, esperando {wait_time}s...")
                    time.sleep(wait_time)
                
                if attempt < Config.MAX_RETRIES - 1:
                    time.sleep(Config.RETRY_DELAY)
                else:
                    if "HTTP Error 429" in error_msg:
                        return {
                            'success': False,
                            'error': 'YouTube está limitando las solicitudes. Por favor, espera unos minutos.',
                            'used_cookies': self.use_cookies
                        }
                    else:
                        return {'success': False, 'error': error_msg[:200], 'used_cookies': self.use_cookies}
                    
            except Exception as e:
                logger.error(f"❌ Error inesperado (intento {attempt + 1}): {e}")
                
                if attempt < Config.MAX_RETRIES - 1:
                    time.sleep(Config.RETRY_DELAY)
                else:
                    return {'success': False, 'error': str(e)[:200], 'used_cookies': self.use_cookies}
        
        return {'success': False, 'error': 'Todos los intentos fallaron', 'used_cookies': self.use_cookies}
    
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
    rate_status = rate_limiter.get_status()
    cookies_valid = is_cookies_valid()
    
    return jsonify({
        'service': 'YouTube Downloader API',
        'version': '10.0 - Rate Limiting & Sin Cookies',
        'status': 'online',
        'rate_limiting': {
            'enabled': Config.ENABLE_RATE_LIMITING,
            'status': rate_status,
            'requests_per_minute': Config.REQUESTS_PER_MINUTE
        },
        'cookies': {
            'enabled': False,  # Forzamos sin cookies por ahora
            'valid': cookies_valid,
            'file_exists': os.path.exists(Config.COOKIES_FILE),
            'note': 'Cookies deshabilitadas debido a problemas de expiración'
        },
        'endpoints': {
            'GET /': 'Esta página',
            'GET /health': 'Estado del servidor',
            'GET /info?url=URL': 'Info del video',
            'POST /info': 'Info del video (POST)',
            'POST /download/audio': 'Descargar audio MP3',
            'GET /rate/status': 'Estado del rate limiting',
            'GET /system/status': 'Estado del sistema'
        },
        'notes': [
            '✅ Rate limiting activado para evitar error 429',
            '✅ Cookies deshabilitadas (problemas de expiración)',
            '✅ User-Agents rotativos',
            '✅ Sistema de reintentos automático'
        ]
    })

@app.route('/health')
def health():
    """Health check"""
    rate_status = rate_limiter.get_status()
    
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'rate_limiting': rate_status,
        'cookies': {
            'file_exists': os.path.exists(Config.COOKIES_FILE),
            'file_size': os.path.getsize(Config.COOKIES_FILE) if os.path.exists(Config.COOKIES_FILE) else 0,
            'valid': is_cookies_valid(),
            'enabled': False  # Siempre false por ahora
        },
        'system': {
            'python': sys.version.split()[0],
            'platform': sys.platform,
            'uptime': 'unknown',  # Podría implementarse con variable global
            'memory': 'unknown'
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
        
        logger.info(f"📊 Info solicitada para: {url[:50]}...")
        
        # Crear downloader (sin cookies por defecto)
        use_cookies_param = data.get('use_cookies', '').lower() == 'true'
        downloader = YouTubeDownloader(use_cookies=use_cookies_param)
        
        # Obtener info
        result = downloader.get_info(url)
        downloader.cleanup()
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Error en /info: {e}")
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
        
        logger.info(f"🎵 Audio solicitado para: {url[:50]}...")
        
        # Opción de usar cookies (por si acaso)
        use_cookies = data.get('use_cookies', '').lower() == 'true'
        downloader = YouTubeDownloader(use_cookies=use_cookies)
        
        # Descargar
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
        response.headers['X-Used-Cookies'] = str(result.get('used_cookies', False))
        response.headers['X-Attempts'] = str(result.get('attempts', 1))
        
        # Limpiar después de enviar
        @response.call_on_close
        def cleanup_after_send():
            downloader.cleanup()
        
        return response
        
    except Exception as e:
        logger.error(f"❌ Error en /download/audio: {e}")
        return jsonify({'success': False, 'error': str(e)[:200]}), 500

@app.route('/rate/status', methods=['GET'])
def rate_status():
    """Estado del rate limiting"""
    status = rate_limiter.get_status()
    
    return jsonify({
        'rate_limiting': {
            'enabled': Config.ENABLE_RATE_LIMITING,
            'recent_requests': status['recent_requests'],
            'limit_per_minute': status['limit_per_minute'],
            'available_requests': status['available'],
            'oldest_request_seconds_ago': time.time() - status['oldest_request'] if status['oldest_request'] else None
        },
        'configuration': {
            'requests_per_minute': Config.REQUESTS_PER_MINUTE,
            'max_retries': Config.MAX_RETRIES,
            'retry_delay': Config.RETRY_DELAY
        }
    })

@app.route('/system/status', methods=['GET'])
def system_status():
    """Estado del sistema"""
    # Verificar ffmpeg
    ffmpeg_available = False
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        ffmpeg_available = True
    except:
        pass
    
    # Espacio en disco
    disk_info = {}
    try:
        stat = shutil.disk_usage('.')
        disk_info = {
            'total_gb': round(stat.total / (1024**3), 2),
            'used_gb': round(stat.used / (1024**3), 2),
            'free_gb': round(stat.free / (1024**3), 2),
            'free_percent': round((stat.free / stat.total) * 100, 1)
        }
    except:
        pass
    
    return jsonify({
        'system': {
            'python_version': sys.version,
            'platform': sys.platform,
            'current_directory': os.getcwd(),
            'temp_directory': tempfile.gettempdir()
        },
        'dependencies': {
            'ffmpeg': 'available' if ffmpeg_available else 'not available',
            'yt_dlp': yt_dlp.version.__version__
        },
        'disk': disk_info,
        'cookies': {
            'file': Config.COOKIES_FILE,
            'exists': os.path.exists(Config.COOKIES_FILE),
            'size': os.path.getsize(Config.COOKIES_FILE) if os.path.exists(Config.COOKIES_FILE) else 0,
            'valid': is_cookies_valid()
        }
    })

@app.route('/test/video/<video_id>', methods=['GET'])
def test_video(video_id):
    """Endpoint de prueba para videos específicos"""
    test_videos = {
        'dQw4w9WgXcQ': 'Rick Astley - Never Gonna Give You Up',
        'pwh60pqDDz0': 'Video de prueba (no especificado)',
        '9bZkp7q19f0': 'PSY - GANGNAM STYLE',
        'kJQP7kiw5Fk': 'Luis Fonsi - Despacito',
    }
    
    video_name = test_videos.get(video_id, 'Video desconocido')
    url = f'https://www.youtube.com/watch?v={video_id}'
    
    logger.info(f"🧪 Test video: {video_name} ({video_id})")
    
    downloader = YouTubeDownloader(use_cookies=False)
    result = downloader.get_info(url)
    downloader.cleanup()
    
    result['test_info'] = {
        'video_id': video_id,
        'video_name': video_name,
        'url': url
    }
    
    return jsonify(result)

# ==============================
# ERROR HANDLERS
# ==============================
@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': 'Endpoint no encontrado'}), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({'success': False, 'error': 'Método no permitido'}), 405

@app.errorhandler(429)
def too_many_requests(error):
    return jsonify({
        'success': False,
        'error': 'Demasiadas solicitudes. Por favor, espera unos minutos.',
        'wait_time_seconds': 60
    }), 429

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"❌ Error 500: {error}")
    return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

# ==============================
# INICIALIZACIÓN
# ==============================
if __name__ == '__main__':
    print("\n" + "="*70)
    print("🚀 SERVIDOR YOUTUBE - VERSIÓN 10.0")
    print("="*70)
    
    # Estado del sistema
    print("📊 Estado del sistema:")
    print(f"  • Puerto: {Config.PORT}")
    print(f"  • Host: {Config.HOST}")
    print(f"  • Rate limiting: {'✅ ACTIVADO' if Config.ENABLE_RATE_LIMITING else '❌ DESACTIVADO'}")
    print(f"  • Límite: {Config.REQUESTS_PER_MINUTE} solicitudes/minuto")
    print(f"  • User-Agents: {len(Config.USER_AGENTS)} disponibles")
    
    # Cookies
    cookies_valid = is_cookies_valid()
    print(f"  • Cookies: {'✅ VÁLIDAS' if cookies_valid else '❌ INVÁLIDAS/NO USADAS'}")
    if os.path.exists(Config.COOKIES_FILE):
        size = os.path.getsize(Config.COOKIES_FILE)
        print(f"    Archivo: {Config.COOKIES_FILE} ({size} bytes)")
    
    # Dependencias
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("  • FFmpeg: ✅ DISPONIBLE")
    except:
        print("  • FFmpeg: ❌ NO DISPONIBLE (conversiones limitadas)")
    
    print("="*70)
    print("📡 Endpoints principales:")
    print("  GET /                 - Información del servicio")
    print("  POST /info            - Info de video (JSON o form)")
    print("  POST /download/audio  - Descargar audio MP3")
    print("  GET /rate/status      - Estado del rate limiting")
    print("  GET /test/video/ID    - Probar video específico")
    print("="*70)
    print("💡 Consejos:")
    print("  1. Si recibes error 429, espera 1-2 minutos")
    print("  2. Los videos muy nuevos pueden no estar disponibles")
    print("  3. Usa /test/video/dQw4w9WgXcQ para probar")
    print("="*70 + "\n")
    
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=False,
        threaded=True
    )
