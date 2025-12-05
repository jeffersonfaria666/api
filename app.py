#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE/TIKTOK PARA RENDER.COM
Versión: Actualizada - Compatible con yt-dlp 2025.05.22
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
    TIMEOUT = 300  # 5 minutos para descargas largas

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
# MÉTODO ACTUALIZADO DE DESCARGA
# ==============================
class ModernDownloader:
    """Descargador compatible con yt-dlp 2025.05.22"""
    
    def __init__(self):
        self.temp_dir = None
        self.output_path = None
        
    def sanitize_filename(self, filename):
        """Limpia caracteres inválidos del nombre de archivo"""
        # Eliminar caracteres no seguros para nombres de archivo
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        
        # Limitar longitud
        if len(filename) > 100:
            filename = filename[:100]
        
        return filename.strip()
    
    def get_info(self, url: str) -> Dict[str, Any]:
        """Obtiene información del video"""
        try:
            # Configuración simplificada para yt-dlp 2025
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'extract_flat': False,
                'no_check_certificate': True,
                'ignoreerrors': True,
                'socket_timeout': 10,
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
                
                # Determinar plataforma
                platform = 'YouTube' if any(x in url.lower() for x in ['youtube.com', 'youtu.be']) else 'TikTok'
                
                return {
                    'success': True,
                    'title': info.get('title', 'Video sin título'),
                    'duration': duration_str,
                    'duration_seconds': duration,
                    'uploader': info.get('uploader', 'Desconocido'),
                    'view_count': info.get('view_count', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'platform': platform,
                    'url': url
                }
                
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"Error específico obteniendo info: {e}")
            return {'success': False, 'error': f'Error del servicio: {str(e)[:100]}'}
        except Exception as e:
            logger.error(f"Error obteniendo info: {e}")
            return {'success': False, 'error': f'Error: {str(e)[:100]}'}
    
    def download(self, url: str, download_type: str = "best") -> Dict[str, Any]:
        """Descarga el video/audio"""
        self.temp_dir = tempfile.mkdtemp(prefix="ytdl_")
        start_time = time.time()
        
        try:
            # Configuración base para yt-dlp 2025
            ydl_opts = {
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
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                },
            }
            
            # Configuración específica para TikTok
            if 'tiktok.com' in url:
                ydl_opts.update({
                    'extractor_args': {
                        'tiktok': {
                            'app_version': '33.4.4',
                            'manifest_app_version': '33.4.4',
                        }
                    }
                })
            
            # Configuración según tipo de descarga
            if download_type == "audio":
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'keepvideo': False,
                    'outtmpl': os.path.join(self.temp_dir, 'audio.%(ext)s'),
                })
            elif download_type == "video":
                ydl_opts.update({
                    'format': 'best[ext=mp4]/best',
                    'merge_output_format': 'mp4',
                    'outtmpl': os.path.join(self.temp_dir, 'video.%(ext)s'),
                })
            else:  # "best"
                ydl_opts.update({
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'merge_output_format': 'mp4',
                    'outtmpl': os.path.join(self.temp_dir, 'video.%(ext)s'),
                })
            
            logger.info(f"Iniciando descarga: {url} - Tipo: {download_type}")
            
            # Realizar descarga
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'video') if info else 'video'
            
            # Buscar archivo descargado
            downloaded_files = []
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file.endswith(('.part', '.ytdl', '.tmp')):
                        continue  # Ignorar archivos temporales
                    
                    filepath = os.path.join(root, file)
                    try:
                        file_size = os.path.getsize(filepath)
                        if file_size > 1024:  # Al menos 1KB
                            downloaded_files.append((filepath, file_size))
                    except:
                        continue
            
            if not downloaded_files:
                return {'success': False, 'error': 'No se generó ningún archivo válido'}
            
            # Tomar el archivo más grande
            self.output_path, file_size = max(downloaded_files, key=lambda x: x[1])
            
            if file_size == 0:
                return {'success': False, 'error': 'Archivo vacío'}
            
            if file_size > Config.MAX_FILE_SIZE:
                os.remove(self.output_path)
                return {'success': False, 'error': f'Archivo demasiado grande ({file_size/(1024*1024):.2f}MB)'}
            
            # Renombrar archivo
            safe_title = self.sanitize_filename(title)
            file_ext = os.path.splitext(self.output_path)[1].lower()
            
            if download_type == "audio":
                if file_ext != '.mp3':
                    new_filename = f"{safe_title}.mp3"
                    new_path = os.path.join(self.temp_dir, new_filename)
                    os.rename(self.output_path, new_path)
                    self.output_path = new_path
                else:
                    new_filename = f"{safe_title}.mp3"
                    new_path = os.path.join(self.temp_dir, new_filename)
                    os.rename(self.output_path, new_path)
                    self.output_path = new_path
            else:  # video o best
                if file_ext != '.mp4':
                    # Buscar si hay MP4 en los archivos descargados
                    for f, _ in downloaded_files:
                        if f.lower().endswith('.mp4'):
                            self.output_path = f
                            file_size = os.path.getsize(f)
                            file_ext = '.mp4'
                            break
                
                new_filename = f"{safe_title}.mp4"
                new_path = os.path.join(self.temp_dir, new_filename)
                os.rename(self.output_path, new_path)
                self.output_path = new_path
            
            download_time = time.time() - start_time
            
            return {
                'success': True,
                'filename': os.path.basename(self.output_path),
                'filepath': self.output_path,
                'filesize': file_size,
                'filesize_mb': round(file_size / (1024 * 1024), 2),
                'download_time': round(download_time, 2),
                'title': title,
                'temp_dir': self.temp_dir,
                'type': download_type,
                'platform': 'YouTube' if any(x in url.lower() for x in ['youtube.com', 'youtu.be']) else 'TikTok'
            }
                
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            logger.error(f"Error de descarga: {error_msg}")
            return {'success': False, 'error': f'Error de descarga: {error_msg[:100]}'}
            
        except Exception as e:
            logger.error(f"Error inesperado: {e}", exc_info=True)
            return {'success': False, 'error': f'Error interno: {str(e)[:100]}'}
    
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
    """Página principal"""
    return jsonify({
        'service': 'YouTube/TikTok Downloader API',
        'version': '2025.05.22',
        'status': 'online',
        'ytdlp_version': yt_dlp.version.__version__,
        'endpoints': {
            '/health': 'GET - Health check',
            '/info': 'POST {"url": "video_url"}',
            '/download': 'POST {"url": "video_url", "type": "video|audio|best"}',
            '/quick': 'GET ?url=video_url&type=audio|video|best'
        }
    })

@app.route('/health')
def health():
    """Health check"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'ytdlp_version': yt_dlp.version.__version__,
        'python_version': sys.version
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
        
        # Validar URL básica
        if not ('tiktok.com' in url or 'youtube.com' in url or 'youtu.be' in url):
            return jsonify({'success': False, 'error': 'URL no válida. Solo YouTube o TikTok'}), 400
        
        downloader = ModernDownloader()
        result = downloader.get_info(url)
        downloader.cleanup()
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error en /info: {e}")
        return jsonify({'success': False, 'error': 'Error del servidor'}), 500

@app.route('/download', methods=['POST'])
def download():
    """Endpoint de descarga principal"""
    try:
        data = request.get_json(silent=True) or request.form
        
        if not data:
            return jsonify({'success': False, 'error': 'No se recibieron datos'}), 400
        
        url = data.get('url')
        download_type = data.get('type', 'best')
        
        if not url:
            return jsonify({'success': False, 'error': 'Se requiere URL'}), 400
        
        # Validar URL básica
        if not ('tiktok.com' in url or 'youtube.com' in url or 'youtu.be' in url):
            return jsonify({'success': False, 'error': 'URL no válida. Solo YouTube o TikTok'}), 400
        
        if download_type not in ['video', 'audio', 'best']:
            download_type = 'best'
        
        logger.info(f"Solicitud de descarga: {url} - Tipo: {download_type}")
        
        # Crear descargador
        downloader = ModernDownloader()
        
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
                'X-File-Type': download_type,
            }
        )
        
    except Exception as e:
        logger.error(f"Error en /download: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

@app.route('/quick', methods=['GET'])
def quick_download():
    """Endpoint rápido para pruebas"""
    try:
        url = request.args.get('url')
        download_type = request.args.get('type', 'audio')
        
        if not url:
            return jsonify({'success': False, 'error': 'Se requiere parámetro ?url='}), 400
        
        return jsonify({
            'success': True,
            'url': url,
            'type': download_type,
            'info_endpoint': '/info',
            'download_endpoint': '/download',
            'method': 'POST',
            'post_data': {'url': url, 'type': download_type}
        })
        
    except Exception as e:
        logger.error(f"Error en /quick: {e}")
        return jsonify({'success': False, 'error': 'Error del servidor'}), 500

@app.route('/test', methods=['GET'])
def test():
    """Endpoint de prueba del servidor"""
    test_urls = {
        'youtube': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        'tiktok': 'https://www.tiktok.com/@example/video/1234567890'
    }
    
    return jsonify({
        'server': 'running',
        'ytdlp_version': yt_dlp.version.__version__,
        'test_urls': test_urls,
        'endpoints': {
            'test_youtube_info': f'/info?url={test_urls["youtube"]}',
            'test_tiktok_info': f'/info?url={test_urls["tiktok"]}'
        }
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
    print("\n" + "="*60)
    print("🚀 SERVIDOR YOUTUBE/TIKTOK")
    print("="*60)
    print(f"✅ yt-dlp versión: {yt_dlp.version.__version__}")
    print(f"✅ Python versión: {sys.version.split()[0]}")
    print("✅ Configuración optimizada para Render.com")
    print("="*60)
    print(f"📡 Servidor: http://{Config.HOST}:{Config.PORT}")
    print("="*60)
    print("📊 Endpoints disponibles:")
    print("  /             - Información del servicio")
    print("  /health       - Health check")
    print("  /info         - Obtener info de video (POST/GET)")
    print("  /download     - Descargar video/audio (POST)")
    print("  /quick        - Descarga rápida (GET)")
    print("  /test         - Probar servidor")
    print("="*60 + "\n")
    
    # Para producción en Render.com, usa waitress
    if os.environ.get('RENDER', '').lower() == 'true':
        from waitress import serve
        serve(app, host=Config.HOST, port=Config.PORT)
    else:
        # Para desarrollo local
        app.run(
            host=Config.HOST,
            port=Config.PORT,
            debug=False,
            threaded=True,
            use_reloader=False
        )
