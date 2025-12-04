#!/usr/bin/env python3
"""
🚀 YOUTUBE SERVER API - DESPLIEGUE RENDER.COM
Versión: 2.0.0
Autor: YouTube Server Team
"""

import os
import sys
import json
import logging
import secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import yt_dlp
import redis
from werkzeug.middleware.proxy_fix import ProxyFix
import gunicorn

# Configuración
class Config:
    # Configuración de Render.com
    PORT = int(os.environ.get('PORT', 5000))
    HOST = '0.0.0.0'
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    # Seguridad
    API_KEY = os.environ.get('API_KEY', secrets.token_urlsafe(32))
    RATE_LIMIT = os.environ.get('RATE_LIMIT', '100 per hour')
    
    # Redis para rate limiting (opcional en Render)
    REDIS_URL = os.environ.get('REDIS_URL', None)
    
    # Configuración yt-dlp
    YDL_OPTIONS = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'no_check_certificate': True,
        'ignoreerrors': True,
        'socket_timeout': 30,
        'retries': 3,
    }

# Configuración de logging
def setup_logging():
    """Configura el sistema de logging"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Log a consola (para Render)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format))
    
    # Log a archivo
    file_handler = logging.FileHandler('logs/server.log')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format))
    
    # Configurar logger raíz
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    return root_logger

# Inicializar logging
logger = setup_logging()

# Clase principal para manejar YouTube
class YouTubeDownloader:
    """Manejador principal de descargas de YouTube"""
    
    def __init__(self):
        self.ydl_opts = Config.YDL_OPTIONS.copy()
        
    def get_video_info(self, url):
        """
        Obtiene información detallada del video
        Returns: Dict con información del video
        """
        try:
            logger.info(f"Obteniendo info para URL: {url[:50]}...")
            
            # Opciones para extracción
            info_opts = self.ydl_opts.copy()
            info_opts.update({
                'extract_flat': False,
                'force_generic_extractor': False,
            })
            
            with yt_dlp.YoutubeDL(info_opts) as ydl:
                # Extraer información
                info = ydl.extract_info(url, download=False)
                
                # Procesar formatos disponibles
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
                            'quality': fmt.get('quality'),
                        }
                        
                        # Separar audio y video
                        if fmt.get('vcodec') != 'none':
                            formats.append(format_info)
                        elif fmt.get('acodec') != 'none':
                            audio_formats.append(format_info)
                
                # Ordenar formatos
                formats.sort(key=lambda x: x.get('height') or 0, reverse=True)
                audio_formats.sort(key=lambda x: x.get('filesize') or 0, reverse=True)
                
                # Construir respuesta
                response = {
                    'success': True,
                    'data': {
                        'id': info.get('id', ''),
                        'title': info.get('title', 'Sin título'),
                        'description': info.get('description', '')[:500],
                        'duration': info.get('duration', 0),
                        'thumbnail': info.get('thumbnail', ''),
                        'uploader': info.get('uploader', 'Desconocido'),
                        'upload_date': info.get('upload_date', ''),
                        'view_count': info.get('view_count', 0),
                        'like_count': info.get('like_count', 0),
                        'categories': info.get('categories', []),
                        'tags': info.get('tags', [])[:10],
                        'formats': formats[:15],  # Limitar a 15 formatos
                        'audio_formats': audio_formats[:10],
                        'best_quality': formats[0] if formats else None,
                        'best_audio': audio_formats[0] if audio_formats else None,
                    }
                }
                
                logger.info(f"Info obtenida exitosamente para: {info.get('title', '')[:50]}")
                return response
                
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"Error yt-dlp: {str(e)}")
            return {
                'success': False,
                'error': 'Error al procesar el video',
                'details': str(e)
            }
        except Exception as e:
            logger.error(f"Error inesperado: {str(e)}")
            return {
                'success': False,
                'error': 'Error interno del servidor',
                'details': str(e)
            }
    
    def get_direct_url(self, url, format_id='best[height<=720]', audio_only=False):
        """
        Obtiene URL directa para descarga
        Args:
            url: URL del video
            format_id: Formato específico (opcional)
            audio_only: Si es True, solo audio
        Returns: Dict con URL directa
        """
        try:
            logger.info(f"Obteniendo URL directa para formato: {format_id}")
            
            # Configurar formato según parámetros
            dl_opts = self.ydl_opts.copy()
            
            if audio_only:
                dl_opts['format'] = 'bestaudio/best'
                dl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                }]
            else:
                dl_opts['format'] = format_id
            
            with yt_dlp.YoutubeDL(dl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # Buscar el formato solicitado
                selected_format = None
                for fmt in info.get('formats', []):
                    if fmt.get('format_id') == format_id or format_id == 'best[height<=720]':
                        if fmt.get('url'):
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
                        'duration': info.get('duration', 0),
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
CORS(app, resources={
    r"/*": {
        "origins": ["*"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "X-API-Key", "Authorization"]
    }
})

# Configurar rate limiting
try:
    if Config.REDIS_URL:
        limiter = Limiter(
            app=app,
            key_func=get_remote_address,
            storage_uri=Config.REDIS_URL,
            default_limits=[Config.RATE_LIMIT]
        )
        logger.info("Rate limiting con Redis configurado")
    else:
        limiter = Limiter(
            app=app,
            key_func=get_remote_address,
            default_limits=[Config.RATE_LIMIT],
            storage_uri="memory://"
        )
        logger.info("Rate limiting en memoria configurado")
except Exception as e:
    logger.warning(f"Error configurando rate limiting: {e}")
    limiter = Limiter(app=app, key_func=get_remote_address)

# Inicializar YouTube Downloader
youtube = YouTubeDownloader()

# Middleware de autenticación
def require_api_key(f):
    """Decorador para requerir API key"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Obtener API key de headers, query params o JSON body
        api_key = (
            request.headers.get('X-API-Key') or
            request.args.get('api_key') or
            (request.get_json(silent=True) or {}).get('api_key')
        )
        
        # Validar API key
        if not api_key:
            return jsonify({
                'success': False,
                'error': 'API key requerida',
                'code': 'MISSING_API_KEY'
            }), 401
        
        if api_key != Config.API_KEY:
            return jsonify({
                'success': False,
                'error': 'API key inválida',
                'code': 'INVALID_API_KEY'
            }), 401
        
        # Registrar uso
        client_ip = request.remote_addr
        logger.info(f"API key válida usada desde IP: {client_ip}")
        
        return f(*args, **kwargs)
    return decorated_function

# Middleware para logging
@app.before_request
def log_request_info():
    """Log información de cada request"""
    logger.info(f"Request: {request.method} {request.path} - IP: {request.remote_addr}")
    
    if request.method == 'POST' and request.is_json:
        data = request.get_json(silent=True) or {}
        # Ocultar datos sensibles en logs
        safe_data = data.copy()
        if 'api_key' in safe_data:
            safe_data['api_key'] = '***HIDDEN***'
        logger.debug(f"Request body: {json.dumps(safe_data, ensure_ascii=False)[:500]}")

@app.after_request
def log_response_info(response):
    """Log información de cada response"""
    logger.info(f"Response: {request.method} {request.path} - Status: {response.status_code}")
    return response

# Endpoints de la API
@app.route('/')
@limiter.exempt
def home():
    """Endpoint principal - Información del servicio"""
    return jsonify({
        'service': 'YouTube Server API',
        'version': '2.0.0',
        'status': 'online',
        'timestamp': datetime.now().isoformat(),
        'endpoints': {
            '/': 'Información del servicio (GET)',
            '/health': 'Estado del servidor (GET)',
            '/api/info': 'Información de video (POST)',
            '/api/download': 'URL de descarga (POST)',
            '/api/formats': 'Formatos disponibles (POST)',
            '/docs': 'Documentación de la API (GET)'
        },
        'limits': Config.RATE_LIMIT,
        'documentation': 'https://github.com/tu-usuario/youtube-server#readme'
    })

@app.route('/health')
@limiter.exempt
def health_check():
    """Health check para Render.com y monitoreo"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'youtube-server',
        'uptime': 'running',
        'memory_usage': 'stable'
    })

@app.route('/docs')
@limiter.exempt
def api_docs():
    """Documentación básica de la API"""
    return jsonify({
        'documentation': 'YouTube Server API v2.0',
        'authentication': {
            'method': 'API Key',
            'header': 'X-API-Key',
            'parameter': 'api_key'
        },
        'endpoints': [
            {
                'method': 'POST',
                'endpoint': '/api/info',
                'description': 'Obtener información de video',
                'body': {
                    'url': 'URL de YouTube (required)',
                    'api_key': 'Tu API key (required)'
                }
            },
            {
                'method': 'POST',
                'endpoint': '/api/download',
                'description': 'Obtener URL directa para descarga',
                'body': {
                    'url': 'URL de YouTube (required)',
                    'format_id': 'ID del formato (opcional, default: best[height<=720])',
                    'audio_only': 'Solo audio (opcional, boolean)',
                    'api_key': 'Tu API key (required)'
                }
            }
        ],
        'examples': {
            'curl_info': 'curl -X POST -H "Content-Type: application/json" -H "X-API-Key: YOUR_KEY" -d \'{"url":"https://youtube.com/watch?v=VIDEO_ID"}\' https://your-server.onrender.com/api/info',
            'curl_download': 'curl -X POST -H "Content-Type: application/json" -H "X-API-Key: YOUR_KEY" -d \'{"url":"https://youtube.com/watch?v=VIDEO_ID", "format_id":"22"}\' https://your-server.onrender.com/api/download'
        }
    })

@app.route('/api/info', methods=['POST'])
@require_api_key
def get_video_info():
    """
    Endpoint: Obtener información detallada del video
    Método: POST
    Body: { "url": "youtube_url", "api_key": "your_key" }
    """
    try:
        # Obtener y validar datos
        data = request.get_json(silent=True) or {}
        url = data.get('url')
        
        if not url:
            return jsonify({
                'success': False,
                'error': 'URL de YouTube es requerida',
                'code': 'MISSING_URL'
            }), 400
        
        # Validar que sea URL de YouTube
        if 'youtube.com' not in url and 'youtu.be' not in url:
            return jsonify({
                'success': False,
                'error': 'URL no válida. Solo se aceptan enlaces de YouTube',
                'code': 'INVALID_URL'
            }), 400
        
        # Obtener información del video
        result = youtube.get_video_info(url)
        
        if result.get('success'):
            return jsonify(result), 200
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Error en endpoint /api/info: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Error interno del servidor',
            'code': 'INTERNAL_ERROR'
        }), 500

@app.route('/api/download', methods=['POST'])
@require_api_key
def get_download_url():
    """
    Endpoint: Obtener URL directa para descarga
    Método: POST
    Body: { "url": "youtube_url", "format_id": "optional", "audio_only": false, "api_key": "your_key" }
    """
    try:
        # Obtener y validar datos
        data = request.get_json(silent=True) or {}
        url = data.get('url')
        format_id = data.get('format_id', 'best[height<=720]')
        audio_only = data.get('audio_only', False)
        
        if not url:
            return jsonify({
                'success': False,
                'error': 'URL de YouTube es requerida',
                'code': 'MISSING_URL'
            }), 400
        
        # Validar que sea URL de YouTube
        if 'youtube.com' not in url and 'youtu.be' not in url:
            return jsonify({
                'success': False,
                'error': 'URL no válida. Solo se aceptan enlaces de YouTube',
                'code': 'INVALID_URL'
            }), 400
        
        # Obtener URL directa
        result = youtube.get_direct_url(url, format_id, audio_only)
        
        if result.get('success'):
            return jsonify(result), 200
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Error en endpoint /api/download: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Error interno del servidor',
            'code': 'INTERNAL_ERROR'
        }), 500

@app.route('/api/formats', methods=['POST'])
@require_api_key
def get_available_formats():
    """Endpoint para obtener todos los formatos disponibles"""
    try:
        data = request.get_json(silent=True) or {}
        url = data.get('url')
        
        if not url:
            return jsonify({
                'success': False,
                'error': 'URL de YouTube es requerida',
                'code': 'MISSING_URL'
            }), 400
        
        # Obtener información completa primero
        info_result = youtube.get_video_info(url)
        
        if not info_result.get('success'):
            return jsonify(info_result), 400
        
        # Extraer y organizar formatos
        data = info_result.get('data', {})
        formats = data.get('formats', [])
        audio_formats = data.get('audio_formats', [])
        
        # Agrupar formatos por calidad
        video_by_quality = {}
        for fmt in formats:
            quality = f"{fmt.get('height') or 0}p"
            if quality not in video_by_quality:
                video_by_quality[quality] = []
            video_by_quality[quality].append(fmt)
        
        return jsonify({
            'success': True,
            'video_id': data.get('id'),
            'title': data.get('title'),
            'formats_by_quality': video_by_quality,
            'audio_formats': audio_formats[:5],
            'recommended': {
                'best_quality': data.get('best_quality'),
                'best_audio': data.get('best_audio'),
                'balanced': next((f for f in formats if f.get('height') == 720), formats[0] if formats else None)
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error en endpoint /api/formats: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Error interno del servidor',
            'code': 'INTERNAL_ERROR'
        }), 500

# Manejo de errores
@app.errorhandler(404)
def not_found(error):
    """Manejador de errores 404"""
    return jsonify({
        'success': False,
        'error': 'Endpoint no encontrado',
        'code': 'NOT_FOUND'
    }), 404

@app.errorhandler(429)
def ratelimit_handler(error):
    """Manejador de errores de rate limiting"""
    return jsonify({
        'success': False,
        'error': 'Demasiadas solicitudes. Por favor, intenta más tarde.',
        'code': 'RATE_LIMIT_EXCEEDED',
        'retry_after': error.description.get('retry_after', 3600)
    }), 429

@app.errorhandler(500)
def internal_error(error):
    """Manejador de errores 500"""
    logger.error(f"Error 500: {str(error)}")
    return jsonify({
        'success': False,
        'error': 'Error interno del servidor',
        'code': 'INTERNAL_SERVER_ERROR'
    }), 500

# Inicialización
if __name__ == '__main__':
    # Mostrar información de inicio
    print("\n" + "="*60)
    print("🚀 YOUTUBE SERVER API v2.0")
    print("="*60)
    print(f"📡 Host: {Config.HOST}")
    print(f"🔌 Puerto: {Config.PORT}")
    print(f"🔑 API Key: {Config.API_KEY}")
    print(f"📊 Rate Limit: {Config.RATE_LIMIT}")
    print(f"🔧 Debug: {Config.DEBUG}")
    print("="*60)
    print("📝 Endpoints disponibles:")
    print("  GET  /           - Información del servicio")
    print("  GET  /health     - Health check")
    print("  GET  /docs       - Documentación API")
    print("  POST /api/info   - Info de video")
    print("  POST /api/download - URL de descarga")
    print("  POST /api/formats - Formatos disponibles")
    print("="*60)
    print("✅ Servidor listo. Presiona Ctrl+C para detener.\n")
    
    # Iniciar servidor
    if Config.DEBUG:
        # Modo desarrollo
        app.run(
            host=Config.HOST,
            port=Config.PORT,
            debug=True,
            threaded=True
        )
    else:
        # Modo producción (con gunicorn si está disponible)
        try:
            from waitress import serve
            print("⚡ Usando Waitress para producción")
            serve(
                app,
                host=Config.HOST,
                port=Config.PORT,
                threads=4,
                connection_limit=100
            )
        except ImportError:
            print("⚠️  Waitress no disponible, usando Flask development server")
            app.run(
                host=Config.HOST,
                port=Config.PORT,
                debug=False,
                threaded=True
            )