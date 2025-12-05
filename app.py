#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE SIMPLE - DESCARGAR EN FORMATO ORIGINAL
Versión: Simple - Descarga exactamente el formato que YouTube proporciona
"""

import os
import sys
import json
import logging
import tempfile
import shutil
import time
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
# MÉTODO SUPER SIMPLE
# ==============================
class SimpleYouTubeDownloader:
    """Descargador simple que mantiene formato original"""
    
    def __init__(self):
        self.temp_dir = None
        self.output_path = None
        
    def clean_filename(self, filename):
        """Limpia el nombre de archivo"""
        import re
        # Eliminar caracteres no seguros
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Limitar longitud
        if len(filename) > 100:
            filename = filename[:100]
        return filename
    
    def get_info(self, url: str) -> dict:
        """Obtiene información básica del video"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
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
                
                # Formatos disponibles
                formats = []
                if 'formats' in info:
                    for f in info['formats']:
                        if f.get('format_note') and f.get('ext'):
                            formats.append({
                                'format': f['format_note'],
                                'extension': f['ext'],
                                'size': f.get('filesize', 0)
                            })
                
                return {
                    'success': True,
                    'title': info.get('title', 'Video sin título'),
                    'duration': duration_str,
                    'uploader': info.get('uploader', 'Desconocido'),
                    'thumbnail': info.get('thumbnail', ''),
                    'formats': formats[:5]  # Solo primeros 5 formatos
                }
                
        except Exception as e:
            logger.error(f"Error obteniendo info: {e}")
            return {'success': False, 'error': str(e)}
    
    def download_original(self, url: str) -> dict:
        """Descarga el video en su formato original"""
        self.temp_dir = tempfile.mkdtemp(prefix="youtube_")
        start_time = time.time()
        
        try:
            # Configuración MÍNIMA - formato original de YouTube
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
                'no_check_certificate': True,
                'retries': 3,
                'fragment_retries': 3,
                # NO convertimos, NO procesamos - formato ORIGINAL
                'format': 'best',  # El mejor formato disponible
                'merge_output_format': None,  # No mezclar formatos
                # Mantener el formato original de YouTube
                'keepvideo': True,
                'noplaylist': True,
                # Configuración para evitar problemas
                'socket_timeout': 30,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                }
            }
            
            logger.info(f"Descargando: {url}")
            
            # Descargar
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'video') if info else 'video'
            
            # Buscar archivo descargado
            downloaded_files = []
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file.endswith(('.part', '.ytdl')):  # Ignorar parciales
                        continue
                    filepath = os.path.join(root, file)
                    try:
                        size = os.path.getsize(filepath)
                        if size > 1024:  # Al menos 1KB
                            downloaded_files.append((filepath, size))
                    except:
                        continue
            
            if not downloaded_files:
                return {'success': False, 'error': 'No se generó archivo'}
            
            # Tomar el archivo más grande (normalmente el video principal)
            self.output_path, file_size = max(downloaded_files, key=lambda x: x[1])
            
            if file_size == 0:
                return {'success': False, 'error': 'Archivo vacío'}
            
            if file_size > Config.MAX_FILE_SIZE:
                os.remove(self.output_path)
                return {'success': False, 'error': 'Archivo muy grande'}
            
            # Limpiar nombre del archivo
            clean_title = self.clean_filename(title)
            file_ext = os.path.splitext(self.output_path)[1]
            new_filename = f"{clean_title}{file_ext}"
            new_path = os.path.join(self.temp_dir, new_filename)
            
            # Renombrar si es diferente
            if os.path.basename(self.output_path) != new_filename:
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
                'extension': file_ext.lstrip('.'),
                'format': 'original'
            }
                
        except Exception as e:
            logger.error(f"Error en descarga: {e}")
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
# ENDPOINTS MUY SIMPLES
# ==============================

@app.route('/')
def home():
    return jsonify({
        'service': 'YouTube Downloader - Formato Original',
        'version': 'simple',
        'instruction': 'Envía URL de YouTube a /download'
    })

@app.route('/health')
def health():
    return jsonify({
        'status': 'online',
        'time': datetime.now().isoformat()
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
        
        downloader = SimpleYouTubeDownloader()
        result = downloader.get_info(url)
        downloader.cleanup()
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/download', methods=['POST'])
def download():
    try:
        # Aceptar JSON o form data
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form
        
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL requerida'}), 400
        
        if 'youtube.com' not in url and 'youtu.be' not in url:
            return jsonify({'success': False, 'error': 'Solo URLs de YouTube'}), 400
        
        logger.info(f"Descarga solicitada: {url[:50]}...")
        
        # Descargar
        downloader = SimpleYouTubeDownloader()
        result = downloader.download_original(url)
        
        if not result['success']:
            downloader.cleanup()
            return jsonify(result), 400
        
        filepath = result['filepath']
        filename = result['filename']
        
        if not os.path.exists(filepath):
            downloader.cleanup()
            return jsonify({'success': False, 'error': 'Archivo no existe'}), 404
        
        file_size = os.path.getsize(filepath)
        
        # Determinar tipo MIME según extensión
        ext = filename.lower().split('.')[-1]
        mime_types = {
            'mp4': 'video/mp4',
            'webm': 'video/webm',
            'mkv': 'video/x-matroska',
            'avi': 'video/x-msvideo',
            'mov': 'video/quicktime',
            'mp3': 'audio/mpeg',
            'm4a': 'audio/mp4',
            'ogg': 'audio/ogg',
            'wav': 'audio/wav'
        }
        
        mimetype = mime_types.get(ext, 'application/octet-stream')
        
        # Stream del archivo
        def generate():
            try:
                chunk_size = 8192
                with open(filepath, 'rb') as f:
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        yield chunk
            finally:
                downloader.cleanup()
        
        return Response(
            generate(),
            mimetype=mimetype,
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(file_size),
                'X-Download-Time': str(result['download_time']),
                'X-File-Size': str(file_size),
                'X-File-Extension': result.get('extension', 'unknown')
            }
        )
        
    except Exception as e:
        logger.error(f"Error en descarga: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/quick', methods=['GET'])
def quick():
    """Endpoint rápido para pruebas"""
    url = request.args.get('url', '').strip()
    
    if not url:
        return jsonify({'success': False, 'error': '?url= requerido'}), 400
    
    return jsonify({
        'success': True,
        'url': url,
        'info': f'/info?url={url}',
        'download': f'/download (POST con {{"url": "{url}"}})'
    })

# ==============================
# MANEJO DE ERRORES SIMPLE
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
    print("🚀 SERVIDOR YOUTUBE - FORMATO ORIGINAL")
    print("="*60)
    print("✅ Descarga videos en formato original de YouTube")
    print("✅ Sin conversiones, sin procesamiento extra")
    print("✅ Simple y rápido")
    print("="*60)
    print(f"📡 Servidor: http://{Config.HOST}:{Config.PORT}")
    print("="*60)
    print("📋 Endpoints:")
    print("  GET  /info?url=URL     - Información del video")
    print("  POST /download         - Descargar (JSON: {\"url\": \"URL\"})")
    print("  GET  /quick?url=URL    - Información rápida")
    print("="*60 + "\n")
    
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=False,
        threaded=True,
        use_reloader=False
    )
