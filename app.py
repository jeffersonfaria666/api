#!/usr/bin/env python3
"""
🚀 SERVIDOR YOUTUBE/TIKTOK PARA RENDER.COM - FIXED
Versión: 1.1 - Corregido para Render
"""

import os
import sys
import json
import logging
import random
import time
import threading
import tempfile
import shutil
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import yt_dlp

# ==============================
# CONFIGURACIÓN PARA RENDER
# ==============================
class Config:
    # Render establece PORT automáticamente
    PORT = int(os.environ.get('PORT', 10000))
    HOST = '0.0.0.0'
    
    # Directorio temporal en Render (usar /tmp/)
    TEMP_DIR = '/tmp/youtube_downloads'
    
    # Límites para evitar problemas en free tier
    MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB máximo (más seguro)
    TIMEOUT = 120  # 2 minutos máximo por descarga
    
    # User-Agents para rotar
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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
    return logging.getLogger(__name__)

logger = setup_logging()

# ==============================
# CLASE DE DESCARGA SIMPLE
# ==============================
class SimpleDownloader:
    """Descargador simple y confiable"""
    
    def __init__(self, url, download_type="best"):
        self.url = url
        self.download_type = download_type
        
        # Crear directorio temporal único
        self.temp_dir = tempfile.mkdtemp(prefix="ytdl_", dir="/tmp")
        
        # Estado
        self.status = "pending"
        self.error = None
        self.filename = None
        self.video_info = None
        
        logger.info(f"Iniciando descarga: {url[:50]}...")
    
    def __del__(self):
        """Destructor para limpiar archivos temporales"""
        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        except:
            pass
    
    def clean_filename(self, name):
        """Limpia caracteres inválidos del nombre"""
        if not name:
            return "video"
        
        invalid = '<>:"/\\|?*'
        for char in invalid:
            name = name.replace(char, '_')
        
        # Limitar longitud
        if len(name) > 80:
            name = name[:77] + "..."
        
        return name
    
    def get_video_info(self):
        """Obtiene información básica del video"""
        try:
            opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'socket_timeout': 10,
                'retries': 2,
                'ignoreerrors': True,
                'no_check_certificate': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web']
                    }
                },
                'http_headers': {
                    'User-Agent': random.choice(Config.USER_AGENTS),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate',
                }
            }
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                
                if not info:
                    return {'success': False, 'error': 'Video no encontrado'}
                
                # Guardar información para usar después
                self.video_info = info
                
                # Formato simple
                formats = []
                for fmt in info.get('formats', []):
                    if fmt.get('url'):
                        formats.append({
                            'id': fmt.get('format_id', ''),
                            'ext': fmt.get('ext', ''),
                            'quality': fmt.get('height', 0),
                            'size': fmt.get('filesize', 0),
                            'format_note': fmt.get('format_note', ''),
                        })
                
                # Ordenar por calidad y filtrar duplicados
                seen = set()
                unique_formats = []
                for fmt in sorted(formats, key=lambda x: x['quality'], reverse=True):
                    key = (fmt['quality'], fmt['ext'])
                    if key not in seen:
                        seen.add(key)
                        unique_formats.append(fmt)
                
                return {
                    'success': True,
                    'title': info.get('title', 'Video'),
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'uploader': info.get('uploader', ''),
                    'view_count': info.get('view_count', 0),
                    'formats': unique_formats[:8],
                }
                
        except Exception as e:
            logger.error(f"Error obteniendo info: {e}")
            return {'success': False, 'error': str(e)}
    
    def download(self):
        """Descarga el archivo"""
        self.status = "downloading"
        start_time = time.time()
        
        try:
            # Configurar opciones según tipo
            opts = {
                'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'retries': 3,
                'fragment_retries': 3,
                'ignoreerrors': True,
                'no_check_certificate': True,
                'http_headers': {
                    'User-Agent': random.choice(Config.USER_AGENTS),
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                },
                'concurrent_fragment_downloads': 4,  # Reducido para Render
            }
            
            if self.download_type == "audio":
                opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'extractaudio': True,
                    'audioformat': 'mp3',
                })
            elif self.download_type == "video":
                # Para video, limitar tamaño y calidad
                opts['format'] = 'best[height<=480][filesize<50M]/best[height<=720]'
            else:
                # Modo best: intentar calidad media
                opts['format'] = 'best[height<=720][filesize<100M]/best'
            
            # Descargar con timeout
            import signal
            
            def timeout_handler(signum, frame):
                raise TimeoutError("Tiempo de descarga excedido")
            
            # Configurar timeout
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(Config.TIMEOUT)
            
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(self.url, download=True)
                    
                    if not info:
                        self.status = "failed"
                        return {'success': False, 'error': 'No se pudo descargar'}
                    
                    # Buscar archivo descargado en el directorio temporal
                    downloaded_files = os.listdir(self.temp_dir)
                    if not downloaded_files:
                        self.status = "failed"
                        return {'success': False, 'error': 'No se generó archivo'}
                    
                    self.filename = downloaded_files[0]
                    filepath = os.path.join(self.temp_dir, self.filename)
                    
                    # Verificar que el archivo existe y tiene tamaño
                    if not os.path.exists(filepath):
                        self.status = "failed"
                        return {'success': False, 'error': 'Archivo no encontrado'}
                    
                    filesize = os.path.getsize(filepath)
                    if filesize == 0:
                        self.status = "failed"
                        os.remove(filepath)
                        return {'success': False, 'error': 'Archivo vacío'}
                    
                    # Verificar tamaño máximo
                    if filesize > Config.MAX_FILE_SIZE:
                        os.remove(filepath)
                        self.status = "failed"
                        return {
                            'success': False, 
                            'error': f'Archivo muy grande ({filesize//1024//1024}MB > {Config.MAX_FILE_SIZE//1024//1024}MB)'
                        }
                    
                    self.status = "completed"
                    download_time = time.time() - start_time
                    
                    return {
                        'success': True,
                        'filename': self.filename,
                        'filepath': filepath,
                        'filesize': filesize,
                        'download_time': download_time,
                        'title': info.get('title', 'Video'),
                        'temp_dir': self.temp_dir,
                    }
                    
            finally:
                # Cancelar alarm
                signal.alarm(0)
                
        except TimeoutError as e:
            self.status = "failed"
            self.error = str(e)
            return {'success': False, 'error': 'Tiempo de descarga excedido (2 minutos)'}
        except Exception as e:
            self.status = "failed"
            self.error = str(e)
            logger.error(f"Error en descarga: {e}")
            return {'success': False, 'error': f'Error: {str(e)}'}
        finally:
            # Limpiar si hay error
            if self.status == "failed":
                try:
                    if os.path.exists(self.temp_dir):
                        shutil.rmtree(self.temp_dir)
                except:
                    pass

# ==============================
# INICIALIZAR FLASK APP
# ==============================
app = Flask(__name__)
CORS(app)  # Permitir CORS para todos los orígenes

# ==============================
# ENDPOINTS DE LA API
# ==============================

@app.route('/')
def home():
    """Página principal"""
    return jsonify({
        'service': 'YouTube/TikTok Downloader API',
        'version': '1.1',
        'status': 'online',
        'timestamp': datetime.now().isoformat(),
        'endpoints': {
            '/': 'Esta página',
            '/health': 'Health check',
            '/info': 'Obtener información de video (POST)',
            '/download': 'Descargar video/audio (POST)',
        },
        'limits': {
            'max_file_size': f'{Config.MAX_FILE_SIZE // 1024 // 1024}MB',
            'timeout': f'{Config.TIMEOUT} segundos',
        },
        'usage': {
            'info': 'POST /info {"url": "youtube_url"}',
            'download': 'POST /download {"url": "youtube_url", "type": "video|audio|best"}',
        }
    })

@app.route('/health')
def health():
    """Health check para Render"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'youtube-downloader',
        'environment': os.environ.get('RENDER', 'development'),
    })

@app.route('/info', methods=['POST'])
def get_video_info():
    """Obtiene información de un video"""
    try:
        # Obtener datos
        data = request.get_json(silent=True) or request.form
        
        if not data:
            return jsonify({'success': False, 'error': 'No se recibieron datos'}), 400
        
        url = data.get('url')
        
        if not url:
            return jsonify({'success': False, 'error': 'Se requiere URL'}), 400
        
        # Validar URL
        if not any(domain in url.lower() for domain in ['youtube.com', 'youtu.be', 'tiktok.com', 'vm.tiktok.com']):
            return jsonify({'success': False, 'error': 'URL no válida. Solo YouTube y TikTok'}), 400
        
        # Obtener información
        downloader = SimpleDownloader(url)
        result = downloader.get_video_info()
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error en /info: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

@app.route('/download', methods=['POST'])
def download_video():
    """Descarga un video/audio"""
    try:
        # Obtener datos
        data = request.get_json(silent=True) or request.form
        
        if not data:
            return jsonify({'success': False, 'error': 'No se recibieron datos'}), 400
        
        url = data.get('url')
        download_type = data.get('type', 'best')
        
        if not url:
            return jsonify({'success': False, 'error': 'Se requiere URL'}), 400
        
        # Validar tipo
        if download_type not in ['video', 'audio', 'best']:
            return jsonify({'success': False, 'error': 'Tipo debe ser: video, audio o best'}), 400
        
        # Crear descargador
        downloader = SimpleDownloader(url, download_type)
        
        # Obtener información primero (para validar)
        info = downloader.get_video_info()
        if not info.get('success'):
            return jsonify(info), 400
        
        # Descargar
        result = downloader.download()
        
        if not result.get('success'):
            return jsonify(result), 400
        
        # Crear respuesta de descarga
        filepath = result['filepath']
        filename = result['filename']
        filesize = result['filesize']
        
        # Función para stream del archivo
        def generate():
            try:
                with open(filepath, 'rb') as f:
                    while chunk := f.read(8192):
                        yield chunk
            finally:
                # Limpiar archivo temporal después de enviar
                try:
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    # Limpiar directorio temporal
                    temp_dir = result.get('temp_dir')
                    if temp_dir and os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
                except Exception as e:
                    logger.error(f"Error limpiando archivos: {e}")
        
        # Determinar tipo MIME
        if filename.lower().endswith('.mp4'):
            mimetype = 'video/mp4'
        elif filename.lower().endswith('.mp3'):
            mimetype = 'audio/mpeg'
        else:
            mimetype = 'application/octet-stream'
        
        return Response(
            generate(),
            mimetype=mimetype,
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(filesize),
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0',
            }
        )
        
    except Exception as e:
        logger.error(f"Error en /download: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

@app.route('/test', methods=['GET'])
def test_endpoint():
    """Endpoint de prueba"""
    return jsonify({
        'success': True,
        'message': 'Servidor funcionando correctamente',
        'timestamp': datetime.now().isoformat(),
        'python_version': sys.version,
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
    # Mostrar información
    print("\n" + "="*60)
    print("🚀 SERVIDOR YOUTUBE/TIKTOK - LISTO PARA RENDER")
    print("="*60)
    print(f"📡 Host: {Config.HOST}")
    print(f"🔌 Puerto: {Config.PORT}")
    print(f"📦 Tamaño máximo: {Config.MAX_FILE_SIZE//1024//1024}MB")
    print(f"⏱️  Timeout: {Config.TIMEOUT} segundos")
    print("="*60)
    print("✅ Usando Flask development server")
    print("✅ CORS habilitado para todos los orígenes")
    print("✅ Sistema de limpieza automática de archivos")
    print("="*60)
    
    # Iniciar servidor
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=False,
        threaded=True
    )
