#!/usr/bin/env python3
"""
🚀 YOUTUBE SERVER API v3.1 - MEJORADO PARA EVITAR BLOQUEOS
Versión: 3.1.0 - CON SOLUCIÓN PARA BOT CHECK
"""

import os
import sys
import json
import logging
import random
import time
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import yt_dlp
from werkzeug.middleware.proxy_fix import ProxyFix

# Configuración
class Config:
    PORT = int(os.environ.get('PORT', 5000))
    HOST = '0.0.0.0'
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
    RATE_LIMIT = os.environ.get('RATE_LIMIT', '100 per hour')
    
    # Lista de User-Agents para rotar
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
    ]

# Configuración de logging
def setup_logging():
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format))
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    
    return root_logger

logger = setup_logging()

# Clase mejorada para manejar YouTube
class YouTubeDownloader:
    def __init__(self):
        self.ydl_opts = self.get_ydl_options()
        
    def get_ydl_options(self):
        """Obtiene opciones de yt-dlp con configuraciones para evitar bloqueos"""
        
        # Rotar User-Agent aleatoriamente
        user_agent = random.choice(Config.USER_AGENTS)
        
        return {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'ignoreerrors': True,
            'socket_timeout': 30,
            'retries': 10,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True,
            
            # Configuraciones para evitar bloqueo de YouTube
            'http_headers': {
                'User-Agent': user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0',
                'DNT': '1',
            },
            
            # Usar extractores alternativos
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'skip': ['hls'],
                    'player_skip': ['configs', 'webpage'],
                }
            },
            
            # Procesadores para manejar mejor los formatos
            'postprocessors': [],
            
            # Evitar descarga de listas de reproducción automáticamente
            'noplaylist': True,
            
            # Configuraciones de red
            'source_address': '0.0.0.0',
            'force_ipv4': True,
            
            # Limitar formatos para evitar problemas
            'format': 'best[height<=1080]',
            
            # Manejo de cookies (opcional, descomentar si tienes cookies.txt)
            # 'cookiefile': 'cookies.txt',
            
            # Usar extractor genérico como fallback
            'force_generic_extractor': False,
        }
    
    def get_video_info(self, url):
        """Obtiene información del video con manejo mejorado de errores"""
        try:
            logger.info(f"Obteniendo info para: {url[:50]}...")
            
            # Intentar diferentes estrategias
            strategies = [
                self._try_extract_with_default,
                self._try_extract_with_android_client,
                self._try_extract_with_m3u8,
            ]
            
            for strategy in strategies:
                result = strategy(url)
                if result and result.get('success'):
                    return result
                
                # Pequeña pausa entre intentos
                time.sleep(1)
            
            # Si todas las estrategias fallan
            return {
                'success': False,
                'error': 'No se pudo extraer información del video',
                'details': 'YouTube está bloqueando las peticiones. Intenta más tarde.'
            }
                
        except Exception as e:
            logger.error(f"Error inesperado: {str(e)}")
            return {
                'success': False,
                'error': 'Error interno del servidor',
                'details': str(e)
            }
    
    def _try_extract_with_default(self, url):
        """Intenta extraer con configuración por defecto"""
        try:
            opts = self.ydl_opts.copy()
            opts.update({
                'extractor_args': {'youtube': {'player_client': ['web']}},
            })
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if info:
                    return self._process_video_info(info)
        except:
            pass
        return None
    
    def _try_extract_with_android_client(self, url):
        """Intenta extraer usando cliente Android"""
        try:
            opts = self.ydl_opts.copy()
            opts.update({
                'extractor_args': {'youtube': {'player_client': ['android']}},
                'http_headers': {
                    **opts['http_headers'],
                    'User-Agent': 'com.google.android.youtube/17.36.4 (Linux; U; Android 11) gzip'
                }
            })
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if info:
                    return self._process_video_info(info)
        except:
            pass
        return None
    
    def _try_extract_with_m3u8(self, url):
        """Intenta extraer usando formato m3u8"""
        try:
            opts = self.ydl_opts.copy()
            opts.update({
                'format': 'best[ext=m3u8]/best',
                'extractor_args': {'youtube': {'skip': []}},
            })
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if info:
                    return self._process_video_info(info)
        except:
            pass
        return None
    
    def _process_video_info(self, info):
        """Procesa la información del video"""
        formats = []
        audio_formats = []
        
        for fmt in info.get('formats', []):
            if fmt.get('url'):
                format_info = {
                    'id': fmt.get('format_id', ''),
                    'ext': fmt.get('ext', ''),
                    'height': fmt.get('height'),
                    'width': fmt.get('width'),
                    'filesize': fmt.get('filesize'),
                    'format_note': fmt.get('format_note', ''),
                    'acodec': fmt.get('acodec', 'none'),
                    'vcodec': fmt.get('vcodec', 'none'),
                    'url': fmt.get('url'),
                }
                
                if fmt.get('vcodec') != 'none':
                    formats.append(format_info)
                elif fmt.get('acodec') != 'none':
                    audio_formats.append(format_info)
        
        # Ordenar formatos
        formats.sort(key=lambda x: x.get('height') or 0, reverse=True)
        audio_formats.sort(key=lambda x: x.get('filesize') or 0, reverse=True)
        
        return {
            'success': True,
            'data': {
                'id': info.get('id', ''),
                'title': info.get('title', 'Sin título'),
                'description': info.get('description', '')[:200],
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail', ''),
                'uploader': info.get('uploader', 'Desconocido'),
                'view_count': info.get('view_count', 0),
                'formats': formats[:10],
                'audio_formats': audio_formats[:5],
                'best_quality': formats[0] if formats else None,
                'best_audio': audio_formats[0] if audio_formats else None,
            }
        }
    
    def get_direct_url(self, url, format_id='best[height<=720]', audio_only=False):
        """Obtiene URL directa para descarga"""
        try:
            logger.info(f"Obteniendo URL para formato: {format_id}")
            
            opts = self.ydl_opts.copy()
            
            if audio_only:
                opts['format'] = 'bestaudio/best'
                opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                }]
            else:
                opts['format'] = format_id
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    return {
                        'success': False,
                        'error': 'No se pudo obtener información del video'
                    }
                
                # Buscar el formato solicitado
                selected_format = None
                for fmt in info.get('formats', []):
                    if fmt.get('url'):
                        if fmt.get('format_id') == format_id or format_id == 'best[height<=720]':
                            selected_format = fmt
                            break
                
                # Si no se encuentra, usar el mejor disponible
                if not selected_format and info.get('formats'):
                    selected_format = info['formats'][0]
                
                if selected_format:
                    return {
                        'success': True,
                        'url': selected_format['url'],
                        'filesize': selected_format.get('filesize'),
                        'ext': selected_format.get('ext'),
                        'format_id': selected_format.get('format_id'),
                        'title': info.get('title', 'video'),
                    }
                else:
                    return {
                        'success': False,
                        'error': 'No se pudo obtener URL directa'
                    }
                    
        except Exception as e:
            logger.error(f"Error al obtener URL directa: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

# Inicializar Flask
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# Configurar CORS
CORS(app)

# Configurar rate limiting
try:
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=[Config.RATE_LIMIT],
        storage_uri="memory://"
    )
    logger.info("Rate limiting configurado")
except Exception as e:
    logger.warning(f"Error configurando rate limiting: {e}")
    limiter = Limiter(app=app, key_func=get_remote_address)

# Inicializar YouTube Downloader
youtube = YouTubeDownloader()

# Middleware para logging
@app.before_request
def log_request_info():
    logger.info(f"Request: {request.method} {request.path} - IP: {request.remote_addr}")

# Endpoints de la API
@app.route('/')
@limiter.exempt
def home():
    return jsonify({
        'service': 'YouTube Server API',
        'version': '3.1.0',
        'status': 'online',
        'timestamp': datetime.now().isoformat(),
        'endpoints': {
            '/': 'Información del servicio (GET)',
            '/health': 'Estado del servidor (GET)',
            '/api/info': 'Información de video (POST)',
            '/api/download': 'URL de descarga (POST)',
            '/api/formats': 'Formatos disponibles (POST)',
        },
        'note': '⚠️ Esta API puede tener problemas debido a restricciones de YouTube',
        'recommendation': 'Para uso personal, considera usar yt-dlp directamente'
    })

@app.route('/health')
@limiter.exempt
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'youtube-server-public'
    })

@app.route('/api/info', methods=['POST'])
def get_video_info():
    try:
        data = request.get_json(silent=True) or {}
        url = data.get('url')
        
        if not url:
            return jsonify({
                'success': False,
                'error': 'URL de YouTube es requerida'
            }), 400
        
        # Validación básica de URL
        if 'youtube.com' not in url and 'youtu.be' not in url:
            return jsonify({
                'success': False,
                'error': 'URL no válida. Solo se aceptan enlaces de YouTube'
            }), 400
        
        result = youtube.get_video_info(url)
        
        if result.get('success'):
            return jsonify(result), 200
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Error en /api/info: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Error interno del servidor'
        }), 500

@app.route('/api/download', methods=['POST'])
def get_download_url():
    try:
        data = request.get_json(silent=True) or {}
        url = data.get('url')
        format_id = data.get('format_id', 'best[height<=720]')
        audio_only = data.get('audio_only', False)
        
        if not url:
            return jsonify({
                'success': False,
                'error': 'URL de YouTube es requerida'
            }), 400
        
        result = youtube.get_direct_url(url, format_id, audio_only)
        
        if result.get('success'):
            return jsonify(result), 200
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Error en /api/download: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Error interno del servidor'
        }), 500

# Manejo de errores
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': 'Endpoint no encontrado'
    }), 404

@app.errorhandler(429)
def ratelimit_handler(error):
    return jsonify({
        'success': False,
        'error': 'Demasiadas solicitudes. Por favor, intenta más tarde.'
    }), 429

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Error 500: {str(error)}")
    return jsonify({
        'success': False,
        'error': 'Error interno del servidor'
    }), 500

# Inicialización
if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 YOUTUBE SERVER API v3.1 - MEJORADO")
    print("="*60)
    print(f"📡 Host: {Config.HOST}")
    print(f"🔌 Puerto: {Config.PORT}")
    print(f"📊 Rate Limit: {Config.RATE_LIMIT}")
    print("="*60)
    print("⚠️  ADVERTENCIA: YouTube puede bloquear estas peticiones")
    print("💡 Recomendación: Usa yt-dlp localmente para mejor resultado")
    print("="*60)
    
    if Config.DEBUG:
        app.run(
            host=Config.HOST,
            port=Config.PORT,
            debug=True,
            threaded=True
        )
    else:
        try:
            from waitress import serve
            print("⚡ Usando Waitress para producción")
            serve(
                app,
                host=Config.HOST,
                port=Config.PORT,
                threads=4
            )
        except ImportError:
            app.run(
                host=Config.HOST,
                port=Config.PORT,
                debug=False,
                threaded=True
            )
