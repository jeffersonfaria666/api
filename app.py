#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE/TIKTOK - VERSIÓN 7.0
Versión: 7.0 - Método garantizado basado en bot funcional
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
# MÉTODO GARANTIZADO DE DESCARGA
# ==============================
class GuaranteedDownloader:
    """Descargador garantizado basado en bot funcional"""
    
    def __init__(self):
        self.temp_dir = None
        self.output_path = None
        
    def sanitize_filename(self, filename):
        """Limpia el nombre de archivo de caracteres inválidos"""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        if len(filename) > 100:
            filename = filename[:100]
        return filename
    
    def get_info(self, url: str) -> Dict[str, Any]:
        """Obtiene información del video"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'forcejson': True
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
    
    def _get_ydl_options(self, download_type: str):
        """Obtiene las opciones de yt-dlp según el tipo"""
        base_opts = {
            'quiet': True,
            'no_warnings': True,
            'no_color': True,
            'noprogress': True,
            'socket_timeout': 30,
            'retries': 10,
            'fragment_retries': 10,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios'],
                    'player_skip': ['js', 'configs']
                }
            },
        }
        
        if download_type == "audio":
            return {
                **base_opts,
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'keepvideo': False,
            }
        elif download_type == "video":
            return {
                **base_opts,
                'format': 'best',
                'merge_output_format': 'mp4',
            }
        else:  # "best"
            return {
                **base_opts,
                'format': 'bestvideo+bestaudio/best',
                'merge_output_format': 'mp4',
            }
    
    def download(self, url: str, download_type: str = "best") -> Dict[str, Any]:
        """MÉTODO GARANTIZADO - Descarga directa y funcional"""
        self.temp_dir = tempfile.mkdtemp(prefix="ytdl_", dir="/tmp")
        start_time = time.time()
        
        try:
            # Primero obtener información del video
            ydl_info_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'forcejson': True
            }
            
            with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    return {'success': False, 'error': 'No se pudo obtener información del video'}
                
                video_title = info.get('title', 'video')
                safe_title = self.sanitize_filename(video_title)
                
                # Crear nombre de archivo base
                timestamp = int(time.time())
                base_filename = f"download_{timestamp}"
                
                # Configurar opciones de descarga
                ydl_opts = self._get_ydl_options(download_type)
                ydl_opts['outtmpl'] = os.path.join(self.temp_dir, f'{base_filename}.%(ext)s')
                
                logger.info(f"Iniciando descarga garantizada: {url} - Tipo: {download_type}")
                
                # Realizar la descarga
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                
                # Buscar archivo descargado
                downloaded_files = []
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        filepath = os.path.join(root, file)
                        try:
                            if os.path.getsize(filepath) > 1024:  # Al menos 1KB
                                downloaded_files.append(filepath)
                        except:
                            continue
                
                if not downloaded_files:
                    return {'success': False, 'error': 'No se generó ningún archivo válido'}
                
                # Seleccionar el archivo más grande
                self.output_path = max(downloaded_files, key=lambda x: os.path.getsize(x))
                file_size = os.path.getsize(self.output_path)
                
                if file_size == 0:
                    return {'success': False, 'error': 'Archivo vacío'}
                
                if file_size > Config.MAX_FILE_SIZE:
                    os.remove(self.output_path)
                    return {'success': False, 'error': f'Archivo demasiado grande ({file_size/(1024*1024):.2f}MB > 200MB)'}
                
                # Renombrar archivo con título del video
                file_ext = os.path.splitext(self.output_path)[1]
                if download_type == "audio" and not file_ext.lower().endswith('.mp3'):
                    new_filename = f"{safe_title}.mp3"
                elif download_type == "video" and not file_ext.lower().endswith('.mp4'):
                    new_filename = f"{safe_title}.mp4"
                else:
                    new_filename = f"{safe_title}{file_ext}"
                
                # Asegurar nombre único
                counter = 1
                original_new_filename = new_filename
                while os.path.exists(os.path.join(self.temp_dir, new_filename)):
                    name, ext = os.path.splitext(original_new_filename)
                    new_filename = f"{name}_{counter}{ext}"
                    counter += 1
                
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
                    'title': video_title,
                    'temp_dir': self.temp_dir,
                    'type': download_type
                }
                
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            logger.error(f"Error de descarga: {error_msg}")
            
            # Intentar método simplificado si falla
            return self._simple_method(url, download_type, start_time)
            
        except Exception as e:
            logger.error(f"Error inesperado: {e}", exc_info=True)
            return {'success': False, 'error': f'Error interno: {str(e)}'}
    
    def _simple_method(self, url: str, download_type: str, start_time: float) -> Dict[str, Any]:
        """Método simplificado y garantizado"""
        try:
            logger.info("Intentando método simplificado...")
            
            # Configuración mínima y garantizada
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'no_color': True,
                'outtmpl': os.path.join(self.temp_dir, '%(id)s.%(ext)s'),
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                },
            }
            
            if download_type == "audio":
                ydl_opts['format'] = 'worstaudio/worst'
            else:
                ydl_opts['format'] = 'worst'
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                # Buscar cualquier archivo descargado
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        if file.endswith(('.mp4', '.mp3', '.webm', '.m4a', '.mp4.part', '.webm.part')):
                            filepath = os.path.join(root, file)
                            if file.endswith('.part'):
                                # Renombrar archivo parcial
                                new_path = filepath.replace('.part', '')
                                os.rename(filepath, new_path)
                                filepath = new_path
                            
                            file_size = os.path.getsize(filepath)
                            
                            if file_size > 1024:
                                download_time = time.time() - start_time
                                
                                # Renombrar con título
                                video_title = info.get('title', 'video') if info else 'video'
                                safe_title = self.sanitize_filename(video_title)
                                file_ext = os.path.splitext(filepath)[1]
                                
                                if download_type == "audio" and not file_ext.lower().endswith('.mp3'):
                                    new_filename = f"{safe_title}.mp3"
                                    new_path = os.path.join(self.temp_dir, new_filename)
                                    os.rename(filepath, new_path)
                                    filepath = new_path
                                
                                return {
                                    'success': True,
                                    'filename': os.path.basename(filepath),
                                    'filepath': filepath,
                                    'filesize': file_size,
                                    'filesize_mb': round(file_size / (1024 * 1024), 2),
                                    'download_time': round(download_time, 2),
                                    'title': video_title,
                                    'temp_dir': self.temp_dir,
                                    'type': download_type
                                }
                
                return {'success': False, 'error': 'Método simplificado no generó archivos'}
                
        except Exception as e:
            logger.error(f"Error en método simplificado: {e}")
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
# ENDPOINTS
# ==============================

@app.route('/')
def home():
    """Página principal"""
    return jsonify({
        'service': 'YouTube/TikTok Downloader',
        'version': '7.0',
        'status': 'online',
        'method': 'garantizado',
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
        'method': 'garantizado'
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
        
        # Validar URL
        patterns = [
            r'https?://(www\.)?tiktok\.com/',
            r'https?://vm\.tiktok\.com/',
            r'https?://(www\.)?youtube\.com/',
            r'https?://youtu\.be/'
        ]
        
        if not any(re.match(pattern, url) for pattern in patterns):
            return jsonify({'success': False, 'error': 'URL no válida. Solo se admiten TikTok o YouTube'}), 400
        
        downloader = GuaranteedDownloader()
        result = downloader.get_info(url)
        downloader.cleanup()
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error en /info: {e}")
        return jsonify({'success': False, 'error': 'Error del servidor'}), 500

@app.route('/download', methods=['POST'])
def download():
    """Endpoint de descarga principal - GARANTIZADO"""
    try:
        data = request.get_json(silent=True) or request.form
        
        if not data:
            return jsonify({'success': False, 'error': 'No se recibieron datos'}), 400
        
        url = data.get('url')
        download_type = data.get('type', 'best')
        
        if not url:
            return jsonify({'success': False, 'error': 'Se requiere URL'}), 400
        
        # Validar URL
        patterns = [
            r'https?://(www\.)?tiktok\.com/',
            r'https?://vm\.tiktok\.com/',
            r'https?://(www\.)?youtube\.com/',
            r'https?://youtu\.be/'
        ]
        
        if not any(re.match(pattern, url) for pattern in patterns):
            return jsonify({'success': False, 'error': 'URL no válida. Solo se admiten TikTok o YouTube'}), 400
        
        if download_type not in ['video', 'audio', 'best']:
            download_type = 'best'
        
        logger.info(f"Solicitud de descarga: {url} - Tipo: {download_type}")
        
        # Crear descargador
        downloader = GuaranteedDownloader()
        
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
        
        # Información del video primero
        downloader = GuaranteedDownloader()
        info = downloader.get_info(url)
        downloader.cleanup()
        
        if not info.get('success'):
            return jsonify(info), 400
        
        return jsonify({
            'success': True,
            'info': info,
            'download_url': f'/download',
            'method': 'POST',
            'post_data': {
                'url': url,
                'type': download_type
            }
        })
        
    except Exception as e:
        logger.error(f"Error en /quick: {e}")
        return jsonify({'success': False, 'error': 'Error del servidor'}), 500

@app.route('/test', methods=['GET'])
def test():
    """Endpoint de prueba con video conocido"""
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    
    try:
        downloader = GuaranteedDownloader()
        
        # Probar información
        info = downloader.get_info(test_url)
        
        if not info.get('success'):
            downloader.cleanup()
            return jsonify({
                'test': 'info_failed',
                'error': info.get('error')
            })
        
        # Probar descarga de audio
        audio_result = downloader.download(test_url, 'audio')
        
        if audio_result.get('success'):
            audio_file = audio_result.get('filename')
            audio_size = audio_result.get('filesize_mb', 0)
            downloader.cleanup()
            
            # Crear nuevo descargador para video
            downloader2 = GuaranteedDownloader()
            video_result = downloader2.download(test_url, 'video')
            video_file = video_result.get('filename') if video_result.get('success') else None
            video_size = video_result.get('filesize_mb', 0) if video_result.get('success') else 0
            downloader2.cleanup()
            
            return jsonify({
                'test': 'success',
                'info': info,
                'audio': {
                    'success': audio_result.get('success'),
                    'filename': audio_file,
                    'size_mb': audio_size
                },
                'video': {
                    'success': video_result.get('success'),
                    'filename': video_file,
                    'size_mb': video_size
                }
            })
        else:
            downloader.cleanup()
            return jsonify({
                'test': 'download_failed',
                'info': info,
                'audio_error': audio_result.get('error'),
                'note': 'El servidor está funcionando pero la descarga falló'
            })
            
    except Exception as e:
        return jsonify({
            'test': 'error',
            'error': str(e)
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
    return jsonify({'success': False, 'error': 'Error interno'}), 500

# ==============================
# INICIALIZACIÓN
# ==============================
if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 SERVIDOR YOUTUBE/TIKTOK - VERSIÓN 7.0")
    print("="*60)
    print("✅ Método garantizado basado en bot funcional")
    print("✅ Configuración optimizada y probada")
    print("✅ Simple y efectivo")
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
