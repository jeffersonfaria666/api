#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE/TIKTOK PARA RENDER.COM - VERSIÓN 6.0
Versión: 6.0 - Método efectivo con configuración directa y garantizada
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
# CONFIGURACIÓN
# ==============================
class Config:
    PORT = int(os.environ.get('PORT', 10000))
    HOST = '0.0.0.0'
    MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB
    TIMEOUT = 180  # 3 minutos

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
# MÉTODO EFECTIVO DE DESCARGA
# ==============================
class EffectiveDownloader:
    """Descargador directo y efectivo"""
    
    def __init__(self):
        self.temp_dir = None
        self.output_path = None
        
    def get_info(self, url: str) -> Dict[str, Any]:
        """Obtiene información del video de forma rápida"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'no_check_certificate': True,
                'socket_timeout': 10,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'ios'],
                        'player_skip': ['webpage']
                    }
                },
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                }
            }
            
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
                }
                
        except Exception as e:
            logger.error(f"Error obteniendo info: {e}")
            return {'success': False, 'error': f'Error: {str(e)}'}
    
    def download(self, url: str, download_type: str = "best") -> Dict[str, Any]:
        """MÉTODO EFECTIVO - Descarga directa garantizada"""
        self.temp_dir = tempfile.mkdtemp(prefix="ytdl_", dir="/tmp")
        start_time = time.time()
        
        try:
            # CONFIGURACIÓN EFECTIVA Y GARANTIZADA
            ydl_opts = {
                'outtmpl': os.path.join(self.temp_dir, 'video.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'no_check_certificate': True,
                'socket_timeout': 30,
                'retries': 10,
                'fragment_retries': 10,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'ios'],
                        'player_skip': ['js', 'configs']
                    }
                },
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate',
                },
                'no_color': True,
                'noprogress': True,
            }
            
            # CONFIGURACIÓN ESPECÍFICA POR TIPO - GARANTIZADA
            if download_type == "audio":
                # Método 1: Descargar solo audio
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'extractaudio': True,
                    'audioformat': 'mp3',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'keepvideo': False,
                })
            elif download_type == "video":
                # Método 2: Descargar video con audio incluido
                ydl_opts.update({
                    'format': 'best',
                    'merge_output_format': 'mp4',
                })
            else:  # "best"
                # Método 3: Lo mejor disponible
                ydl_opts.update({
                    'format': 'bestvideo+bestaudio/best',
                    'merge_output_format': 'mp4',
                })
            
            logger.info(f"Iniciando descarga efectiva: {url}")
            
            # EJECUTAR DESCARGA
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                if not info:
                    return {'success': False, 'error': 'No se pudo procesar el video'}
                
                # Buscar archivo descargado - Método garantizado
                downloaded_files = []
                
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        filepath = os.path.join(root, file)
                        # Ignorar archivos muy pequeños o temporales
                        try:
                            if os.path.getsize(filepath) > 1024:  # Al menos 1KB
                                downloaded_files.append(filepath)
                        except:
                            continue
                
                if not downloaded_files:
                    return {'success': False, 'error': 'No se generó ningún archivo'}
                
                # Seleccionar el archivo más grande
                self.output_path = max(downloaded_files, key=lambda x: os.path.getsize(x))
                file_size = os.path.getsize(self.output_path)
                
                if file_size == 0:
                    return {'success': False, 'error': 'Archivo vacío'}
                
                if file_size > Config.MAX_FILE_SIZE:
                    os.remove(self.output_path)
                    return {'success': False, 'error': 'Archivo demasiado grande'}
                
                # Renombrar archivo con título del video
                title = info.get('title', 'video')
                # Limpiar caracteres inválidos
                invalid_chars = '<>:"/\\|?*'
                for char in invalid_chars:
                    title = title.replace(char, '_')
                
                # Determinar extensión
                if download_type == "audio":
                    new_filename = f"{title[:50]}.mp3"
                else:
                    new_filename = f"{title[:50]}.mp4"
                
                new_path = os.path.join(self.temp_dir, new_filename)
                os.rename(self.output_path, new_path)
                self.output_path = new_path
                
                download_time = time.time() - start_time
                
                return {
                    'success': True,
                    'filename': new_filename,
                    'filepath': new_path,
                    'filesize': file_size,
                    'filesize_mb': round(file_size / (1024 * 1024), 2),
                    'download_time': round(download_time, 2),
                    'title': title,
                    'temp_dir': self.temp_dir
                }
                
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            logger.error(f"Error de descarga: {error_msg}")
            
            # Intentar método alternativo si falla el primero
            return self._alternative_method(url, download_type, start_time)
            
        except Exception as e:
            logger.error(f"Error inesperado: {e}", exc_info=True)
            return {'success': False, 'error': f'Error interno: {str(e)}'}
    
    def _alternative_method(self, url: str, download_type: str, start_time: float) -> Dict[str, Any]:
        """Método alternativo si el principal falla"""
        try:
            logger.info("Intentando método alternativo...")
            
            # Configuración alternativa más simple
            ydl_opts = {
                'outtmpl': os.path.join(self.temp_dir, '%(id)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'no_check_certificate': True,
                'format': 'worst',  # Usar peor calidad pero garantizado
            }
            
            if download_type == "audio":
                ydl_opts.update({
                    'format': 'worstaudio/worst',
                    'extractaudio': True,
                })
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                # Buscar archivo
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        if file.endswith(('.mp4', '.mp3', '.webm', '.m4a')):
                            filepath = os.path.join(root, file)
                            file_size = os.path.getsize(filepath)
                            
                            if file_size > 1024:
                                download_time = time.time() - start_time
                                
                                return {
                                    'success': True,
                                    'filename': file,
                                    'filepath': filepath,
                                    'filesize': file_size,
                                    'filesize_mb': round(file_size / (1024 * 1024), 2),
                                    'download_time': round(download_time, 2),
                                    'title': info.get('title', 'video'),
                                    'temp_dir': self.temp_dir
                                }
                
                return {'success': False, 'error': 'Método alternativo también falló'}
                
        except Exception as e:
            logger.error(f"Error en método alternativo: {e}")
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
# ENDPOINTS SIMPLES Y EFECTIVOS
# ==============================

@app.route('/')
def home():
    """Página principal minimalista"""
    return jsonify({
        'service': 'YouTube/TikTok Downloader',
        'version': '6.0',
        'status': 'online',
        'endpoints': {
            '/health': 'GET - Health check',
            '/info': 'POST {"url": "video_url"}',
            '/download': 'POST {"url": "video_url", "type": "video|audio|best"}'
        }
    })

@app.route('/health')
def health():
    """Health check simple"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/info', methods=['POST', 'GET'])
def get_info():
    """Obtiene información del video"""
    try:
        if request.method == 'POST':
            data = request.get_json(silent=True) or request.form
        else:
            data = request.args
        
        url = data.get('url')
        
        if not url:
            return jsonify({'success': False, 'error': 'Se requiere URL'}), 400
        
        downloader = EffectiveDownloader()
        result = downloader.get_info(url)
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error en /info: {e}")
        return jsonify({'success': False, 'error': 'Error del servidor'}), 500

@app.route('/download', methods=['POST'])
def download():
    """Endpoint de descarga principal - SIMPLE Y EFECTIVO"""
    try:
        data = request.get_json(silent=True) or request.form
        
        if not data:
            return jsonify({'success': False, 'error': 'No se recibieron datos'}), 400
        
        url = data.get('url')
        download_type = data.get('type', 'best')
        
        if not url:
            return jsonify({'success': False, 'error': 'Se requiere URL'}), 400
        
        if download_type not in ['video', 'audio', 'best']:
            download_type = 'best'
        
        logger.info(f"Solicitud de descarga: {url} - Tipo: {download_type}")
        
        # Crear descargador
        downloader = EffectiveDownloader()
        
        # Obtener información primero (opcional)
        info = downloader.get_info(url)
        if not info.get('success'):
            logger.warning(f"No se pudo obtener info, continuando igual...")
        
        # Ejecutar descarga
        result = downloader.download(url, download_type)
        
        if not result['success']:
            downloader.cleanup()
            return jsonify(result), 400
        
        filepath = result['filepath']
        filename = result['filename']
        
        if not os.path.exists(filepath):
            downloader.cleanup()
            return jsonify({'success': False, 'error': 'Archivo no encontrado'}), 404
        
        file_size = os.path.getsize(filepath)
        if file_size == 0:
            downloader.cleanup()
            return jsonify({'success': False, 'error': 'Archivo vacío'}), 400
        
        # Stream del archivo
        def generate():
            try:
                with open(filepath, 'rb') as f:
                    while chunk := f.read(8192):
                        yield chunk
            finally:
                # Limpiar siempre al final
                downloader.cleanup()
        
        # Determinar tipo MIME
        if filename.lower().endswith('.mp3'):
            mimetype = 'audio/mpeg'
        elif filename.lower().endswith('.mp4'):
            mimetype = 'video/mp4'
        elif filename.lower().endswith('.webm'):
            mimetype = 'video/webm'
        else:
            mimetype = 'application/octet-stream'
        
        return Response(
            generate(),
            mimetype=mimetype,
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(file_size),
                'X-Download-Time': str(result['download_time']),
                'X-File-Size': str(file_size),
            }
        )
        
    except Exception as e:
        logger.error(f"Error en /download: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

@app.route('/quick', methods=['GET'])
def quick_download():
    """Endpoint rápido para pruebas - GET con parámetros"""
    try:
        url = request.args.get('url')
        download_type = request.args.get('type', 'audio')
        
        if not url:
            return jsonify({'success': False, 'error': 'Se requiere parámetro ?url='}), 400
        
        # Redirigir al endpoint POST
        return jsonify({
            'success': True,
            'message': 'Usa POST /download para descargar',
            'url': url,
            'type': download_type,
            'post_endpoint': '/download',
            'post_data': {'url': url, 'type': download_type}
        })
        
    except Exception as e:
        logger.error(f"Error en /quick: {e}")
        return jsonify({'success': False, 'error': 'Error del servidor'}), 500

# ==============================
# MANEJO DE ERRORES SIMPLE
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
    print("🚀 SERVIDOR YOUTUBE/TIKTOK - VERSIÓN 6.0")
    print("="*60)
    print("✅ Método efectivo garantizado")
    print("✅ Configuración optimizada")
    print("✅ Simple y rápido")
    print("="*60)
    print(f"📡 Servidor: http://{Config.HOST}:{Config.PORT}")
    print("="*60 + "\n")
    
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=False,
        threaded=True,
        use_reloader=False
    )
