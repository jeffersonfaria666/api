import os
import sys
import time
import sqlite3
import requests
import random
import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from yt_dlp import YoutubeDL
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters
from telegram.error import BadRequest, RetryAfter

# Configuración
BOT_TOKEN = "7239423213:AAE6lmCeiuz9_GoeujWDYo64B0FOfcHoFFA"
USDT_ADDRESS = "0x594EAB95D5683851E0eBFfC457C07dc217Bf4830".lower()
BSC_API_KEY = "9769MICJ2Z1PAEZVVZCX9HKYSIRWVYZA"
LIMIT_POR_DIA = 100
MIN_USDT = 4.99  # Cambiado a 4.99 para coincidir con el precio
DB_NAME = "usuarios.db"
MAX_WORKERS = 3
MAX_FRAGMENTS = 16
CHUNK_SIZE = 10 * 1024 * 1024
MAX_FILE_SIZE = 7000 * 1024 * 1024  
ADMIN_IDS = []
MIN_WITHDRAWAL = 50

# Sistema de recompensas
REWARD_PER_DOWNLOAD_MIN = 0.01
REWARD_PER_DOWNLOAD_MAX = 0.50
REFERRAL_REWARD = 5.00

# URLs
COMUNIDAD_URL = "https://t.me/descargar_videos_de_tiktok"
DONACION_URL = "https://www.paypal.com/paypalme/JeffersonFaria525"
RECOMPENSAS_URL = "https://cryptorewards.page.gd/"

# Límites
MAX_TT_SIZE_NON_PREMIUM = 50 * 1024 * 1024
YOUTUBE_DAILY_LIMIT = 5

# Almacenamiento temporal
download_jobs = {}
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
current_downloads = {}
progress_trackers = {}

# Sistema de colas mejorado
class DownloadQueueSystem:
    def __init__(self, max_workers=3):
        self.max_workers = max_workers
        self.priority_queue = asyncio.Queue()
        self.active_tasks = {}
        self.task_counter = 0
        self.workers = []
        self.is_running = True
        self.app = None
        
    def set_application(self, app):
        self.app = app
        
    async def start(self):
        """Inicia los workers de la cola"""
        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker(i))
            self.workers.append(worker)
        log_event(f"🚀 Sistema de colas iniciado con {self.max_workers} workers")
        
    async def stop(self):
        """Detiene todos los workers"""
        self.is_running = False
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        
    async def add_task(self, priority, task_data):
        """Añade una tarea a la cola con prioridad"""
        self.task_counter += 1
        task_id = self.task_counter
        await self.priority_queue.put((priority, task_id, task_data))
        return task_id
        
    async def _worker(self, worker_id):
        """Worker que procesa tareas de la cola"""
        log_event(f"👷 Worker {worker_id} iniciado")
        
        while self.is_running:
            try:
                try:
                    priority, task_id, task_data = await asyncio.wait_for(
                        self.priority_queue.get(), timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue
                    
                job_id, user_id, url, tipo, chat_id, message_id = task_data
                
                if user_id in self.active_tasks:
                    log_event(f"⏳ Usuario {user_id} ya tiene tarea activa, reencolando...")
                    new_priority = max(0, priority - 0.1)
                    await self.add_task(new_priority, task_data)
                    self.priority_queue.task_done()
                    await asyncio.sleep(1)
                    continue
                
                self.active_tasks[user_id] = task_id
                try:
                    await self._process_task(worker_id, task_data)
                finally:
                    if user_id in self.active_tasks:
                        del self.active_tasks[user_id]
                    self.priority_queue.task_done()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_event(f"❌ Error en worker {worker_id}: {e}")
                await asyncio.sleep(1)
                
    async def _process_task(self, worker_id, task_data):
        """Procesa una tarea individual"""
        job_id, user_id, url, tipo, chat_id, message_id = task_data
        
        try:
            log_event(f"🔁 Worker {worker_id} procesando tarea para usuario {user_id}")
            
            progress_tracker = SafeProgressTracker(chat_id, message_id, user_id, self.app)
            progress_trackers[user_id] = progress_tracker
            
            lang = get_user_language(user_id)
            t = translations[lang]
            
            if "youtube.com" in url or "youtu.be" in url:
                if not await puede_descargar_youtube(user_id):
                    await progress_tracker.safe_edit_message(
                        "❌ Has alcanzado tu límite diario de descargas de YouTube (5).\n\n"
                        "💎 Conviértete en Premium para descargas ilimitadas de YouTube."
                    )
                    return
            
            await progress_tracker.safe_edit_message(t['analyzing_size'])
            
            es_valido, tamano_estimado, titulo, duracion, calidad, formato = await analizar_video_con_detalles(url, user_id, tipo)
            
            if not es_valido:
                if tipo.startswith("tt_"):
                    tamano_mb = tamano_estimado / (1024 * 1024)
                    error_msg = t['video_too_large'].format(tamano_mb)
                    await progress_tracker.safe_edit_message(error_msg)
                return
                
            tamano_mb = tamano_estimado / (1024 * 1024) if tamano_estimado > 0 else 0
            duracion_formateada = format_duration(duracion) if duracion > 0 else "Desconocida"
            
            if "youtube" in url:
                platform = "YouTube"
            else:
                platform = "TikTok"
                
            info_msg = f"📊 **Información del {platform}:**\n• Duración: {duracion_formateada}\n• Tamaño estimado: {tamano_mb:.2f}MB\n• Calidad: {calidad}"
            await progress_tracker.safe_edit_message(info_msg)
            await asyncio.sleep(2)
            
            loop = asyncio.get_event_loop()
            downloader = SafeParallelDownloader(url, user_id, tipo, progress_tracker)
            downloader.estimated_size = tamano_estimado
            
            success = await loop.run_in_executor(executor, downloader.download)
            filename = downloader.filename
            
            if not success or not filename:
                error_msg = t['download_failed'].format(1)
                await progress_tracker.safe_edit_message(error_msg)
                log_event(f"❌ Error al descargar: {url}")
                return
                
            await progress_tracker.safe_edit_message("📤 Preparando para enviar...")
            await self._send_file(user_id, filename, tipo, progress_tracker)
            
            recompensa = incrementar_descarga(user_id)
            
            if "youtube.com" in url or "youtu.be" in url:
                incrementar_descarga_youtube(user_id)
                
            actualizar_estadisticas(user_id)
            
            # CORREGIDO: Asegurar que se muestre el menú después de la descarga
            await mostrar_menu_post_descarga(self.app, chat_id, message_id, recompensa)
            
            try:
                if filename and os.path.exists(filename):
                    os.remove(filename)
                    log_event(f"🧹 Archivo temporal eliminado: {filename}")
            except Exception as e:
                log_event(f"⚠️ Error eliminando archivo: {e}")
                
        except Exception as e:
            log_event(f"❌ Error procesando tarea: {e}")
            try:
                lang = get_user_language(user_id)
                t = translations[lang]
                await progress_tracker.safe_edit_message(f"❌ Error: {str(e)}")
            except:
                pass
                
    async def _send_file(self, user_id, filename, tipo, progress_tracker):
        """Envía el archivo al usuario"""
        try:
            file_size = os.path.getsize(filename)
            file_size_mb = file_size / (1024 * 1024)
            
            if file_size > MAX_FILE_SIZE:
                raise Exception(f"Archivo demasiado grande ({file_size_mb:.2f}MB)")
            
            for progress in range(0, 101, 20):
                await progress_tracker.update_upload_progress(progress)
                await asyncio.sleep(0.5)
            
            timeout = 60
            
            if tipo.endswith("video"):
                with open(filename, 'rb') as video_file:
                    await self.app.bot.send_video(
                        chat_id=user_id,
                        video=video_file,
                        caption="✅ ¡Descarga completada!",
                        supports_streaming=True,
                        read_timeout=timeout,
                        write_timeout=timeout,
                        connect_timeout=timeout
                    )
            else:
                with open(filename, 'rb') as audio_file:
                    await self.app.bot.send_audio(
                        chat_id=user_id,
                        audio=audio_file,
                        caption="✅ ¡Descarga completada!",
                        read_timeout=timeout,
                        write_timeout=timeout,
                        connect_timeout=timeout
                    )
                    
            await progress_tracker.update_upload_progress(100)
            log_event(f"✅ Archivo enviado: {filename} ({file_size_mb:.2f}MB)")
            
        except Exception as e:
            log_event(f"❌ Error enviando archivo: {e}")
            raise

download_queue_system = DownloadQueueSystem(max_workers=MAX_WORKERS)

stats = {
    "start_time": time.time(),
    "total_downloads": 0,
    "daily_downloads": 0,
    "unique_users": set(),
    "premium_users": 0,
    "active_downloads": 0,
    "completed_today": 0,
    "queue_size": 0,
    "errors": 0,
    "total_rewards": 0.0,
    "total_withdrawals": 0.0,
    "total_referral_earnings": 0.0
}

translations = {
    "es": {
        "welcome": "🌟 ¡Bienvenido al Bot de Descargas más Potente! 🚀",
        "download_options": "🎬 Descarga videos y audio en calidad premium de TikTok y YouTube ✨",
        "select_option": "👇 ¡Elige una opción y comienza a descargar!",
        "download_content": "⬇️ Descargar Contenido",
        "premium": "💎 Premium VIP",
        "referrals": "👥 Programa de Referidos",
        "stats": "📊 Mis Estadísticas",
        "support": "🆘 Soporte Técnico",
        "withdraw": "💰 Retirar Fondos",
        "language": "🌐 Idioma/Language",
        "menu_principal": "🏠 Menú Principal",
        "back": "🔙 Volver",
        "available_downloads": "📊 Descargas disponibles hoy: {}/{}",
        "youtube_downloads": "🎵 Descargas de YouTube hoy: {}/{}",
        "balance_info": "💰 Balance Actual: ${:.2f} USDT",
        "withdraw_minimum": "⚠️ El mínimo para retirar es {} USDT",
        "withdraw_success": "✅ ¡Retiro procesado exitosamente!",
        "withdraw_request": "📋 Solicitud de retiro enviada para revisión",
        "referral_notification": "🎉 ¡Has ganado ${} por referir a un nuevo usuario!",
        "limit_reached": "⛔ ¡Límite Diario Alcanzado!",
        "limit_message": "Has usado tus {} descargas gratuitas de hoy.\n🔓 Obtén descargas ilimitadas:",
        "large_file": "📦 El archivo es grande ({:.2f}MB). ⏳ Esto puede tardar varios minutos...",
        "community": "👥 Unirse a la Comunidad",
        "donate": "❤️ Apoyar con Donación",
        "video_too_large": "❌ **Video demasiado grande**\n\nEste video es de {:.2f}MB y supera el límite de 50MB. ⚠️\n\n💎 Conviértete en Premium para descargar videos de cualquier tamaño.",
        "referral_earnings": "💰 **Ganancias por referidos:** ${:.2f} USDT",
        "processing_queue": "⏳ **Procesando tu solicitud**\n\n{}",
        "queue_position": "📊 Posición en cola: {}",
        "premium_priority": "🚀 Prioridad Premium (procesamiento inmediato)",
        "analyzing": "🔍 **Analizando video...**",
        "downloading": "⬇️ **Descargando... {}%**",
        "uploading": "📤 **Enviando... {}%**",
        "daily_reminder": "📢 **Recordatorio Diario**\n\nTienes {} descargas disponibles hoy!\n\n",
        "error_download": "❌ Error durante la descarga: {}",
        "error_upload": "❌ Error durante el envío: {}",
        "file_too_large": "❌ El archivo es demasiado grande ({:.2f}MB). El límite de Telegram es {:.2f}MB.",
        "try_audio": "💡 Intenta descargar solo el audio o un video de menor calidad.",
        "download_failed": "❌ La descarga falló después de {} intentos.",
        "retrying": "🔄 Reintentando ({}/{})...",
        "download_cancelled": "❌ Descarga cancelada debido a múltiples errores.",
        "analyzing_size": "🔍 **Analizando video...**\n\n📊 Calculando tamaño y duración...",
        "size_info": "📊 **Información del video:**\n• Duración: {}\n• Tamaño estimado: {:.2f}MB\n• Calidad: {}",
        "new_referral": "🎉 **¡Nuevo referido!**\n\n@{} ha usado tu enlace de referido.\n💰 Has ganado ${:.2f} USDT de recompensa!",
        "queue_stalled": "⚠️ **Procesamiento retrasado**\n\nEl sistema está experimentando alta demanda. Tu descarga se reanudará automáticamente.",
        "youtube_premium_only": "❌ **YouTube requiere Premium para video**\n\nPara descargar videos de YouTube necesitas una cuenta Premium. 💎\n\n🎵 Pero puedes descargar el audio MP3 gratis (límite 5 por día)",
        "more_rewards": "🎁 Más Recompensas",
        "youtube_audio_only": "🎵 **Descarga de YouTube**\n\nLos usuarios gratuitos pueden descargar solo audio MP3 de YouTube (límite 5 por día).\n\n💎 Conviértete en Premium para descargar videos completos de YouTube.",
        "enter_tx_hash": "🔍 **Verificación de Pago**\n\nPor favor, envía el **hash de la transacción (TX ID)** de tu pago de 4.99 USDT.\n\nEjemplo: `0x1234567890abcdef...`\n\n⚠️ Asegúrate de que:\n- El monto sea exactamente 4.99 USDT\n- La red sea BSC (BEP-20)\n- La transacción esté confirmada"
    },
    "en": {
        "welcome": "🌟 Welcome to the Most Powerful Download Bot! 🚀",
        "download_options": "🎬 Download premium quality videos and audio from TikTok and YouTube ✨",
        "select_option": "👇 Choose an option and start downloading!",
        "download_content": "⬇️ Download Content",
        "premium": "💎 Premium VIP", 
        "referrals": "👥 Referral Program",
        "stats": "📊 My Statistics",
        "support": "🆘 Technical Support",
        "withdraw": "💰 Withdraw Funds",
        "language": "🌐 Language/Idioma",
        "menu_principal": "🏠 Main Menu",
        "back": "🔙 Back",
        "available_downloads": "📊 Downloads available today: {}/{}",
        "youtube_downloads": "🎵 YouTube downloads today: {}/{}",
        "balance_info": "💰 Current Balance: ${:.2f} USDT",
        "withdraw_minimum": "⚠️ Minimum withdrawal is {} USDT",
        "withdraw_success": "✅ Withdrawal processed successfully!",
        "withdraw_request": "📋 Withdrawal request sent for review",
        "referral_notification": "🎉 You've earned ${} for referring a new user!",
        "limit_reached": "⛔ Daily Limit Reached!",
        "limit_message": "You've used your {} free downloads today.\n🔓 Get unlimited downloads:",
        "large_file": "📦 The file is large ({:.2f}MB). ⏳ This may take several minutes...",
        "community": "👥 Join Community",
        "donate": "❤️ Support with Donation",
        "video_too_large": "❌ **Video too large**\n\nThis video is {:.2f}MB and exceeds the 50MB limit. ⚠️\n\n💎 Become Premium to download videos of any size.",
        "referral_earnings": "💰 **Referral earnings:** ${:.2f} USDT",
        "processing_queue": "⏳ **Processing your request**\n\n{}",
        "queue_position": "📊 Queue position: {}",
        "premium_priority": "🚀 Premium priority (immediate processing)",
        "analyzing": "🔍 **Analyzing video...**",
        "downloading": "⬇️ **Downloading... {}%**",
        "uploading": "📤 **Uploading... {}%**",
        "daily_reminder": "📢 **Daily Reminder**\n\nYou have {} downloads available today!\n\n",
        "error_download": "❌ Error during download: {}",
        "error_upload": "❌ Error during upload: {}",
        "file_too_large": "❌ The file is too large ({:.2f}MB). The Telegram limit is {:.2f}MB.",
        "try_audio": "💡 Try downloading only audio or a lower quality video.",
        "download_failed": "❌ Download failed after {} attempts.",
        "retrying": "🔄 Retrying ({}/{})...",
        "download_cancelled": "❌ Download cancelled due to multiple errors.",
        "analyzing_size": "🔍 **Analyzing video...**\n\n📊 Calculating size and duration...",
        "size_info": "📊 **Video information:**\n• Duration: {}\n• Estimated size: {:.2f}MB\n• Quality: {}",
        "new_referral": "🎉 **New referral!**\n\n@{} used your referral link.\n💰 You earned ${:.2f} USDT reward!",
        "queue_stalled": "⚠️ **Processing delayed**\n\nThe system is experiencing high demand. Your download will resume automatically.",
        "youtube_premium_only": "❌ **YouTube requires Premium for video**\n\nTo download YouTube videos you need a Premium account. 💎\n\n🎵 But you can download MP3 audio for free (limit 5 per day)",
        "more_rewards": "🎁 More Rewards",
        "youtube_audio_only": "🎵 **YouTube Download**\n\nFree users can only download MP3 audio from YouTube (limit 5 per day).\n\n💎 Become Premium to download full YouTube videos.",
        "enter_tx_hash": "🔍 **Payment Verification**\n\nPlease send the **transaction hash (TX ID)** of your 4.99 USDT payment.\n\nExample: `0x1234567890abcdef...`\n\n⚠️ Make sure:\n- Amount is exactly 4.99 USDT\n- Network is BSC (BEP-20)\n- Transaction is confirmed"
    }
}

def print_stats():
    os.system('cls' if os.name == 'nt' else 'clear')
    
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elapsed_time = time.time() - stats["start_time"]
    hours, remainder = divmod(elapsed_time, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    stats["queue_size"] = download_queue_system.priority_queue.qsize()
    stats["active_downloads"] = len(download_queue_system.active_tasks)
    
    print(f"🤖 BOT ACTIVO | {current_time}")
    print("=" * 50)
    print(f"⬇️  DESCARGAS TOTALES: {stats['total_downloads']}")
    print(f"📊 DESCARGAS HOY: {stats['daily_downloads']}")
    print(f"👤 USUARIOS ÚNICOS: {len(stats['unique_users'])}")
    print(f"💎 USUARIOS PREMIUM: {stats['premium_users']}")
    print(f"🚀 DESCARGAS ACTIVAS: {stats['active_downloads']}")
    print(f"⏳ EN COLA: {stats['queue_size']}")
    print(f"✅ COMPLETADAS HOY: {stats['completed_today']}")
    print(f"❌ ERRORES: {stats['errors']}")
    print(f"💰 RECOMPENSAS: ${stats['total_rewards']:.2f}")
    print(f"💸 RETIROS: ${stats['total_withdrawals']:.2f}")
    print(f"👥 GANANCIAS POR REFERIDOS: ${stats['total_referral_earnings']:.2f}")
    print(f"⏱  TIEMPO ACTIVO: {int(hours)}h {int(minutes)}m {int(seconds)}s")
    print("=" * 50)
    
    if stats["active_downloads"] > 0:
        print("ESTADO ACTUAL: Procesando descargas...")
    elif stats["queue_size"] > 0:
        print("ESTADO ACTUAL: En espera (cola no vacía)")
    else:
        print("ESTADO ACTUAL: Esperando solicitudes...")

def log_event(event):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {event}")

def conectar_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def crear_tabla():
    conn = conectar_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY,
            username TEXT,
            descargas INTEGER DEFAULT 0,
            youtube_descargas INTEGER DEFAULT 0,
            ultimo_reset INTEGER,
            youtube_ultimo_reset INTEGER,
            premium INTEGER DEFAULT 0,
            referido_por INTEGER,
            ultima_tx TEXT DEFAULT '',
            referrals INTEGER DEFAULT 0,
            last_active INTEGER,
            balance REAL DEFAULT 0.0,
            language TEXT DEFAULT 'es',
            total_earned REAL DEFAULT 0.0,
            referral_earnings REAL DEFAULT 0.0,
            last_daily_notification INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            type TEXT,
            description TEXT,
            timestamp INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            address TEXT,
            status TEXT DEFAULT 'pending',
            timestamp INTEGER,
            tx_hash TEXT
        )
    """)
    
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(usuarios)")
        columns = [column[1] for column in cur.fetchall()]
        
        if 'youtube_descargas' not in columns:
            conn.execute("ALTER TABLE usuarios ADD COLUMN youtube_descargas INTEGER DEFAULT 0")
            log_event("✅ Columna 'youtube_descargas' añadida")
            
        if 'youtube_ultimo_reset' not in columns:
            conn.execute("ALTER TABLE usuarios ADD COLUMN youtube_ultimo_reset INTEGER DEFAULT 0")
            log_event("✅ Columna 'youtube_ultimo_reset' añadida")
            
        if 'ultima_tx' not in columns:
            conn.execute("ALTER TABLE usuarios ADD COLUMN ultima_tx TEXT DEFAULT ''")
            log_event("✅ Columna 'ultima_tx' añadida")
            
    except Exception as e:
        log_event(f"⚠️ Error verificando columnas: {e}")
    
    conn.commit()
    conn.close()

def es_url_valida(url):
    patterns = [
        r'https?://(www\.)?tiktok\.com/',
        r'https?://vm\.tiktok\.com/',
        r'https?://(www\.)?youtube\.com/',
        r'https?://youtu\.be/'
    ]
    return any(re.match(pattern, url) for pattern in patterns)

def get_user_language(user_id):
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("SELECT language FROM usuarios WHERE id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["language"] if row else "es"

def get_user_balance(user_id):
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM usuarios WHERE id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["balance"] if row else 0.0

def add_user_balance(user_id, amount):
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET balance = balance + ?, total_earned = total_earned + ? WHERE id=?", 
                (amount, amount, user_id))
    conn.commit()
    conn.close()
    stats["total_rewards"] += amount

def add_referral_earnings(user_id, amount):
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET referral_earnings = referral_earnings + ? WHERE id=?", 
                (amount, user_id))
    conn.commit()
    conn.close()
    stats["total_referral_earnings"] += amount

def es_premium(user_id):
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("SELECT premium FROM usuarios WHERE id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row and row["premium"] == 1

def get_priority(user_id):
    return 0 if es_premium(user_id) else 1

def actualizar_estadisticas(user_id):
    stats["unique_users"].add(user_id)
    stats["daily_downloads"] += 1
    stats["total_downloads"] += 1
    stats["completed_today"] += 1
    
    if es_premium(user_id):
        stats["premium_users"] = len([u for u in stats["unique_users"] if es_premium(u)])
    
    print_stats()

def sanitize_filename(filename):
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    if len(filename) > 100:
        filename = filename[:100]
    return filename

def format_duration(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{int(hours)}:{int(minutes):02d}:{int(seconds):02d}"
    else:
        return f"{int(minutes)}:{int(seconds):02d}"

def registrar_usuario(user_id, username, referido_por=None):
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM usuarios WHERE id=?", (user_id,))
    usuario_existente = cur.fetchone()
    
    if not usuario_existente:
        cur.execute(
            "INSERT INTO usuarios (id, username, descargas, youtube_descargas, ultimo_reset, youtube_ultimo_reset, premium, referido_por, last_active, balance, language, total_earned, referral_earnings, last_daily_notification, ultima_tx) VALUES (?, ?, 0, 0, ?, ?, 0, ?, ?, 0.0, 'es', 0.0, 0.0, ?, '')",
            (user_id, username, int(time.time()), int(time.time()), referido_por, int(time.time()), int(time.time()))
        )
        
        if referido_por:
            cur.execute("UPDATE usuarios SET referrals = referrals + 1 WHERE id=?", (referido_por,))
            add_user_balance(referido_por, REFERRAL_REWARD)
            add_referral_earnings(referido_por, REFERRAL_REWARD)
            
            cur.execute(
                "INSERT INTO transactions (user_id, amount, type, description, timestamp) VALUES (?, ?, ?, ?, ?)",
                (referido_por, REFERRAL_REWARD, 'referral', 'Bonus por nuevo referido', int(time.time()))
            )
    else:
        cur.execute("UPDATE usuarios SET last_active = ?, username = ? WHERE id = ?", 
                   (int(time.time()), username, user_id))
    conn.commit()
    conn.close()
    
    stats["unique_users"].add(user_id)
    print_stats()
    log_event(f"👤 Usuario registrado: @{username} ({user_id})")

async def notificar_referidor(referidor_id, username_referido, recompensa):
    try:
        application = ApplicationBuilder().token(BOT_TOKEN).build()
        lang = get_user_language(referidor_id)
        t = translations[lang]
        
        mensaje = t['new_referral'].format(username_referido, recompensa)
        
        await application.bot.send_message(
            chat_id=referidor_id,
            text=mensaje,
            parse_mode='Markdown'
        )
        log_event(f"✅ Notificación enviada al referidor {referidor_id}")
    except Exception as e:
        log_event(f"❌ Error enviando notificación a referidor: {e}")

def puede_descargar(user_id):
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM usuarios WHERE id=?", (user_id,))
    usuario = cur.fetchone()
    conn.close()
    
    if not usuario:
        return False, 0, 0
        
    limite_base = LIMIT_POR_DIA
    limite_extra = usuario["referrals"]
    limite_total = limite_base + limite_extra
    
    if usuario["premium"]:
        return True, 0, 0
        
    ahora = int(time.time())
    if ahora - usuario["ultimo_reset"] > 86400:
        conn = conectar_db()
        conn.execute(
            "UPDATE usuarios SET descargas=0, ultimo_reset=? WHERE id=?", (ahora, user_id)
        )
        conn.commit()
        conn.close()
        return True, 0, limite_total
        
    descargas_restantes = limite_total - usuario["descargas"]
    return usuario["descargas"] < limite_total, usuario["descargas"], limite_total

async def puede_descargar_youtube(user_id):
    if es_premium(user_id):
        return True
        
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("SELECT youtube_descargas, youtube_ultimo_reset FROM usuarios WHERE id=?", (user_id,))
    usuario = cur.fetchone()
    
    if not usuario:
        conn.close()
        return False
        
    ahora = int(time.time())
    
    if ahora - usuario["youtube_ultimo_reset"] > 86400:
        conn.execute(
            "UPDATE usuarios SET youtube_descargas=0, youtube_ultimo_reset=? WHERE id=?", (ahora, user_id)
        )
        conn.commit()
        conn.close()
        return True
        
    puede = usuario["youtube_descargas"] < YOUTUBE_DAILY_LIMIT
    conn.close()
    return puede

def incrementar_descarga(user_id):
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET descargas = descargas + 1, last_active = ? WHERE id=?", 
                (int(time.time()), user_id))
    
    recompensa = round(random.uniform(REWARD_PER_DOWNLOAD_MIN, REWARD_PER_DOWNLOAD_MAX), 2)
    cur.execute("UPDATE usuarios SET balance = balance + ?, total_earned = total_earned + ? WHERE id=?", 
                (recompensa, recompensa, user_id))
    
    conn.commit()
    conn.close()
    
    stats["total_rewards"] += recompensa
    return recompensa

def incrementar_descarga_youtube(user_id):
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET youtube_descargas = youtube_descargas + 1 WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

def get_youtube_stats(user_id):
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("SELECT youtube_descargas, youtube_ultimo_reset FROM usuarios WHERE id=?", (user_id,))
    usuario = cur.fetchone()
    conn.close()
    
    if not usuario:
        return 0, YOUTUBE_DAILY_LIMIT
        
    ahora = int(time.time())
    if ahora - usuario["youtube_ultimo_reset"] > 86400:
        return 0, YOUTUBE_DAILY_LIMIT
    else:
        return usuario["youtube_descargas"], YOUTUBE_DAILY_LIMIT

# NUEVO: Diccionario para usuarios esperando TX
waiting_for_tx = {}

def validar_pago_con_tx(user_id, tx_hash):
    """Verifica un pago específico usando el hash de transacción"""
    try:
        url = f"https://api.bscscan.com/api?module=transaction&action=gettxreceiptstatus&txhash={tx_hash}&apikey={BSC_API_KEY}"
        
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            return False, "❌ Error consultando BscScan. Intenta más tarde."
            
        data = response.json()
        
        # Verificar si la transacción existe y fue exitosa
        if data.get("status") != "1":
            return False, "❌ Transacción no encontrada o fallida."
            
        # Obtener detalles de la transacción
        url_details = f"https://api.bscscan.com/api?module=proxy&action=eth_getTransactionByHash&txhash={tx_hash}&apikey={BSC_API_KEY}"
        response_details = requests.get(url_details, timeout=15)
        
        if response_details.status_code != 200:
            return False, "❌ Error obteniendo detalles de la transacción."
            
        tx_data = response_details.json()
        
        if not tx_data.get("result"):
            return False, "❌ No se pudieron obtener los detalles de la transacción."
            
        tx_result = tx_data["result"]
        
        # Verificar que la transacción es para nuestra dirección
        if tx_result.get("to", "").lower() != USDT_ADDRESS.lower():
            return False, "❌ Esta transacción no fue enviada a la dirección correcta."
        
        # Verificar el valor de la transacción
        if tx_result.get("value"):
            value_wei = int(tx_result["value"], 16)
            value_bnb = value_wei / 10**18
            
            # Para transacciones de BNB directas
            if value_bnb > 0:
                # Convertir BNB a USDT (aproximadamente)
                bnb_price_url = "https://api.binance.com/api/v3/ticker/price?symbol=BNBUSDT"
                bnb_response = requests.get(bnb_price_url, timeout=10)
                if bnb_response.status_code == 200:
                    bnb_data = bnb_response.json()
                    bnb_price = float(bnb_data["price"])
                    value_usdt = value_bnb * bnb_price
                    
                    if value_usdt >= MIN_USDT:
                        return activar_premium(user_id, tx_hash, value_usdt, "BNB")
        
        # Buscar transacciones de tokens USDT
        url_token = f"https://api.bscscan.com/api?module=account&action=tokentx&address={USDT_ADDRESS}&txhash={tx_hash}&apikey={BSC_API_KEY}"
        response_token = requests.get(url_token, timeout=15)
        
        if response_token.status_code == 200:
            token_data = response_token.json()
            
            if token_data.get("status") == "1" and token_data.get("result"):
                for tx in token_data["result"]:
                    if (tx.get("to", "").lower() == USDT_ADDRESS.lower() and 
                        tx.get("tokenSymbol") == "USDT"):
                        
                        decimals = int(tx.get("tokenDecimal", 6))
                        amount = float(tx["value"]) / (10 ** decimals)
                        
                        if amount >= MIN_USDT:
                            return activar_premium(user_id, tx_hash, amount, "USDT")
        
        return False, "❌ No se encontró un pago válido de 4.99 USDT en esta transacción."
        
    except Exception as e:
        log_event(f"❌ Error validando TX: {e}")
        return False, f"❌ Error de conexión: {str(e)}"

def activar_premium(user_id, tx_hash, amount, token_type):
    """Activa la cuenta premium para un usuario"""
    try:
        conn = conectar_db()
        cur = conn.cursor()
        
        # Verificar si el TX ya fue usado
        cur.execute("SELECT id FROM usuarios WHERE ultima_tx = ?", (tx_hash,))
        if cur.fetchone():
            conn.close()
            return False, "❌ Esta transacción ya fue utilizada anteriormente."
        
        # Activar premium
        cur.execute("UPDATE usuarios SET premium=1, ultima_tx=? WHERE id=?", (tx_hash, user_id))
        conn.commit()
        conn.close()
        
        stats["premium_users"] += 1
        print_stats()
        
        log_event(f"✅ Pago confirmado para usuario {user_id}: {amount:.2f} {token_type} (TX: {tx_hash})")
        return True, f"✅ **¡Pago confirmado!** 🎉\n\n💎 **Cuenta Premium Activada**\n💰 Monto: {amount:.2f} {token_type}\n🔗 TX: `{tx_hash}`\n\n¡Disfruta de tus beneficios premium!"
        
    except Exception as e:
        log_event(f"❌ Error activando premium: {e}")
        return False, "❌ Error activando cuenta premium."

def solicitar_retiro(user_id, amount, address):
    user_balance = get_user_balance(user_id)
    
    if amount < MIN_WITHDRAWAL:
        return False, f"El mínimo para retirar es {MIN_WITHDRAWAL} USDT"
    
    if amount > user_balance:
        return False, "Fondos insuficientes"
    
    conn = conectar_db()
    cur = conn.cursor()
    
    cur.execute(
        "INSERT INTO withdrawals (user_id, amount, address, timestamp) VALUES (?, ?, ?, ?)",
        (user_id, amount, address, int(time.time()))
    )
    
    cur.execute("UPDATE usuarios SET balance = balance - ? WHERE id = ?", (amount, user_id))
    
    conn.commit()
    conn.close()
    
    stats["total_withdrawals"] += amount
    
    for admin_id in ADMIN_IDS:
        try:
            asyncio.create_task(send_async_message(admin_id, f"🔄 Nueva solicitud de retiro:\nUser: {user_id}\nAmount: {amount} USDT\nAddress: {address}"))
        except:
            pass
    
    return True, "Solicitud de retiro procesada. Será revisada por un administrador."

async def analizar_video_con_detalles(url, user_id, tipo):
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'forcejson': True
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            titulo = info.get('title', 'Video sin título')
            duracion = info.get('duration', 0)
            formato = info.get('ext', 'desconocido')
            
            if 'filesize' in info and info['filesize']:
                tamaño = info['filesize']
            elif 'filesize_approx' in info and info['filesize_approx']:
                tamaño = info['filesize_approx']
            else:
                if duracion > 0:
                    tamaño = duracion * 2 * 1024 * 1024 / 60
                else:
                    tamaño = 0
            
            calidad = "Desconocida"
            if 'height' in info:
                calidad = f"{info['height']}p"
            
            if ("youtube.com" in url or "youtu.be" in url) and tipo == "yt_audio":
                return True, tamaño, titulo, duracion, calidad, formato
            
            if not es_premium(user_id) and tamaño > MAX_TT_SIZE_NON_PREMIUM:
                return False, tamaño, titulo, duracion, calidad, formato
            
            return True, tamaño, titulo, duracion, calidad, formato
            
    except Exception as e:
        log_event(f"❌ Error analizando video: {e}")
        return True, 0, "Video", 0, "Desconocida", "desconocido"

async def send_async_message(chat_id, text):
    try:
        application = ApplicationBuilder().token(BOT_TOKEN).build()
        await application.bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        log_event(f"Error enviando mensaje async: {e}")

class SafeProgressTracker:
    def __init__(self, chat_id, message_id, user_id, app):
        self.chat_id = chat_id
        self.message_id = message_id
        self.user_id = user_id
        self.app = app
        self.download_progress = 0
        self.upload_progress = 0
        self.is_active = True
        self.lang = get_user_language(user_id)
        self.t = translations[self.lang]
        self.last_update_time = 0
        self.last_message = ""
        
    async def safe_edit_message(self, text):
        if text == self.last_message:
            return False
            
        try:
            await self.app.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
                parse_mode='Markdown'
            )
            self.last_message = text
            self.last_update_time = time.time()
            return True
        except BadRequest as e:
            if "Message is not modified" in str(e):
                self.last_message = text
                return True
            else:
                log_event(f"⚠️ Error editando mensaje: {e}")
                return False
        except Exception as e:
            log_event(f"⚠️ Error editando mensaje: {e}")
            return False
            
    async def update_download_progress(self, progress):
        if not self.is_active:
            return
            
        self.download_progress = progress
        if time.time() - self.last_update_time >= 1:
            text = self.t['downloading'].format(progress)
            await self.safe_edit_message(text)
            
    async def update_upload_progress(self, progress):
        if not self.is_active:
            return
            
        self.upload_progress = progress
        if time.time() - self.last_update_time >= 1:
            text = self.t['uploading'].format(progress)
            await self.safe_edit_message(text)
            
    def stop(self):
        self.is_active = False

class SafeParallelDownloader:
    def __init__(self, url, user_id, tipo, progress_tracker):
        self.url = url
        self.user_id = user_id
        self.tipo = tipo
        self.filename = None
        self.video_title = None
        self.estimated_size = 0
        self.priority = 0 if es_premium(user_id) else 1
        self.timestamp = int(time.time())
        self.prefix = "download"
        self.base_filename = f"{self.prefix}_{user_id}_{self.timestamp}"
        self.progress_tracker = progress_tracker
        
    def get_video_info(self):
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'forcejson': True
            }
            
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                self.video_title = info.get('title', 'video')
                self.estimated_size = info.get('filesize', 0) or info.get('filesize_approx', 0)
                return True
        except Exception as e:
            log_event(f"❌ Error obteniendo información del video: {e}")
            self.video_title = None
            self.estimated_size = 0
            return False
            
    def download(self):
        try:
            self.get_video_info()
                
            ydl_opts = self._get_ydl_options()
            
            ydl_opts['progress_hooks'] = [self._progress_hook]
            
            ydl_opts['socket_timeout'] = 0
            ydl_opts['retries'] = 0
            ydl_opts['fragment_retries'] = 0
            
            with open(os.devnull, 'w') as devnull:
                with YoutubeDL(ydl_opts) as ydl:
                    ydl.download([self.url])
            
            for file in os.listdir('.'):
                if file.startswith(self.base_filename):
                    self.filename = file
                    
                    if self.video_title:
                        file_ext = os.path.splitext(file)[1]
                        safe_title = sanitize_filename(self.video_title)
                        new_filename = f"{safe_title}{file_ext}"
                        
                        counter = 1
                        original_new_filename = new_filename
                        while os.path.exists(new_filename):
                            new_filename = f"{os.path.splitext(original_new_filename)[0]}_{counter}{file_ext}"
                            counter += 1
                            
                        os.rename(file, new_filename)
                        self.filename = new_filename
                    
                    file_size = os.path.getsize(self.filename)
                    if file_size > MAX_FILE_SIZE:
                        raise Exception(f"El archivo es demasiado grande ({file_size/1024/1024:.2f}MB > {MAX_FILE_SIZE/1024/1024}MB)")
                        
                    return True
            return False
        except Exception as e:
            log_event(f"❌ Error en descarga: {e}")
            stats["errors"] += 1
            return False
            
    def _progress_hook(self, d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes', 0)
            downloaded = d.get('downloaded_bytes', 0)
            if total and downloaded:
                progress = int((downloaded / total) * 100)
                if progress % 5 == 0:
                    try:
                        asyncio.run(self.progress_tracker.update_download_progress(progress))
                    except RuntimeError as e:
                        if "Event loop is closed" not in str(e):
                            raise
                        log_event("⚠️ Event loop cerrado, no se puede actualizar progreso")
        elif d['status'] == 'finished':
            try:
                asyncio.run(self.progress_tracker.update_download_progress(100))
            except RuntimeError as e:
                if "Event loop is closed" not in str(e):
                    raise
                log_event("⚠️ Event loop cerrado, no se puede actualizar progreso")
            
    def _get_ydl_options(self):
        base_opts = {
            'outtmpl': self.base_filename + '.%(ext)s',
            'noprogress': True,
            'socket_timeout': 0,
            'retries': 0,
            'fragment_retries': 0,
            'concurrent_fragment_downloads': MAX_FRAGMENTS,
            'http_chunk_size': CHUNK_SIZE,
            'abort_on_unavailable_fragment': False,
            'quiet': True,
        }
        
        if self.tipo == "tt_video":
            return {**base_opts, 'format': 'best'}
        elif self.tipo == "tt_audio":
            return {
                **base_opts,
                'format': 'bestaudio/best',
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}]
            }
        elif self.tipo == "yt_audio":
            return {
                **base_opts,
                'format': 'bestaudio/best',
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}]
            }
        elif self.tipo == "yt_video":
            return {**base_opts, 'format': 'best'}
        else:
            return {**base_opts, 'format': 'best'}

async def monitor_sistema():
    while True:
        try:
            await asyncio.sleep(30)
            
            workers_activos = sum(1 for worker in download_queue_system.workers if not worker.done())
            
            if workers_activos < download_queue_system.max_workers:
                log_event(f"⚠️ Solo {workers_activos}/{download_queue_system.max_workers} workers activos")
                
                for i in range(download_queue_system.max_workers - workers_activos):
                    worker = asyncio.create_task(download_queue_system._worker(len(download_queue_system.workers)))
                    download_queue_system.workers.append(worker)
                log_event("🔄 Workers reiniciados")
                
            download_queue_system.workers = [w for w in download_queue_system.workers if not w.done()]
            
        except Exception as e:
            log_event(f"❌ Error en monitor del sistema: {e}")
            await asyncio.sleep(60)

async def verificar_estado_sistema():
    while True:
        try:
            await asyncio.sleep(60)
            
            stats["queue_size"] = download_queue_system.priority_queue.qsize()
            stats["active_downloads"] = len(download_queue_system.active_tasks)
            
            print_stats()
                
        except Exception as e:
            log_event(f"❌ Error en verificador del sistema: {e}")
            await asyncio.sleep(60)

async def mostrar_menu_principal(update: Update, context: ContextTypes.DEFAULT_TYPE, message_id=None):
    if hasattr(update, 'effective_user'):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
    else:
        user_id = update.from_user.id
        chat_id = update.message.chat_id
    
    lang = get_user_language(user_id)
    t = translations[lang]
    
    puede_desc, usadas, total = puede_descargar(user_id)
    balance = get_user_balance(user_id)
    youtube_usadas, youtube_total = get_youtube_stats(user_id)
    
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("SELECT referral_earnings FROM usuarios WHERE id=?", (user_id,))
    row = cur.fetchone()
    referral_earnings = row["referral_earnings"] if row else 0.0
    conn.close()
    
    texto = (
        f"{t['welcome']}\n\n"
        f"{t['download_options']}\n\n"
        f"{t['available_downloads'].format(usadas, total) if not es_premium(user_id) else '💎 Descargas ilimitadas (Premium)'}\n"
        f"{t['youtube_downloads'].format(youtube_usadas, youtube_total) if not es_premium(user_id) else '🎵 Descargas YouTube ilimitadas (Premium)'}\n"
        f"{t['balance_info'].format(balance)}\n"
        f"{t['referral_earnings'].format(referral_earnings)}\n\n"
        f"{t['select_option']}"
    )
    
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton(t['download_content'], callback_data="iniciar_descarga")],
        [
            InlineKeyboardButton(t['premium'], callback_data="menu_premium"),
            InlineKeyboardButton(t['referrals'], callback_data="menu_referral")
        ],
        [
            InlineKeyboardButton(t['more_rewards'], url=RECOMPENSAS_URL),
            InlineKeyboardButton(t['withdraw'], callback_data="menu_withdraw")
        ],
        [
            InlineKeyboardButton(t['support'], url="https://t.me/soporte_bot"),
            InlineKeyboardButton(t['language'], callback_data="menu_language")
        ],
        [
            InlineKeyboardButton(t['community'], url=COMUNIDAD_URL),
            InlineKeyboardButton(t['donate'], url=DONACION_URL)
        ]
    ])
    
    if message_id:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=texto,
            reply_markup=teclado,
            parse_mode='Markdown'
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=texto,
            reply_markup=teclado,
            parse_mode='Markdown'
        )

# CORREGIDO: Función corregida con todos los parámetros necesarios
async def mostrar_menu_premium(update: Update, context: ContextTypes.DEFAULT_TYPE, message_id=None):
    if hasattr(update, 'effective_user'):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
    else:
        user_id = update.from_user.id
        chat_id = update.message.chat.id
    
    lang = get_user_language(user_id)
    t = translations[lang]
    
    texto = (
        "💎 **¡CONVIÉRTETE EN PREMIUM!** 💎\n\n"
        "✨ **Beneficios exclusivos:**\n"
        "- Descargas ilimitadas 24/7\n"
        "- Videos en 4K/HD sin restricciones\n"
        "- Procesamiento prioritario\n"
        "- Soporte directo\n"
        "- Videos sin límite de tamaño\n"
        "- Descargas ilimitadas de YouTube\n\n"
        "💳 **Cómo activar:**\n"
        "1. Envía *4.99 USDT* (BEP-20) a:\n"
        f"`{USDT_ADDRESS}`\n"
        "2. Verifica tu pago enviando el TX Hash\n\n"
        "⏱️ **Activación inmediata** después de la confirmación\n"
        "🛡️ **Garantía de satisfacción**"
    )
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Verificar TX Hash", callback_data="verificar_pago")],
        [InlineKeyboardButton("❓ Cómo pagar", callback_data="como_pagar")],
        [InlineKeyboardButton(t['back'], callback_data="menu_principal")]
    ])
    
    if message_id:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=texto,
            reply_markup=teclado,
            parse_mode='Markdown'
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=texto,
            reply_markup=teclado,
            parse_mode='Markdown'
        )

async def mostrar_como_pagar(update: Update, context: ContextTypes.DEFAULT_TYPE, message_id):
    if hasattr(update, 'effective_user'):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
    else:
        user_id = update.from_user.id
        chat_id = update.message.chat.id
    
    lang = get_user_language(user_id)
    t = translations[lang]
    
    texto = (
        "❓ **¿Cómo pagar?** ❓\n\n"
        "1. **Necesitas tener una billetera con USDT en la red BSC (Binance Smart Chain).**\n"
        "2. Envía exactamente **4.99 USDT** a la siguiente dirección:\n"
        f"`{USDT_ADDRESS}`\n"
        "3. Asegúrate de que la red sea **BEP-20 (BSC)**.\n"
        "4. Después de enviar, copia el **TX Hash** de la transacción.\n"
        "5. Regresa al bot y presiona '🔍 Verificar TX Hash'.\n\n"
        "⚠️ **Nota:** Las transacciones pueden tardar unos minutos en confirmarse."
    )
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Verificar TX Hash", callback_data="verificar_pago")],
        [InlineKeyboardButton(t['back'], callback_data="menu_premium")]
    ])
    
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=texto,
        reply_markup=teclado,
        parse_mode='Markdown'
    )

async def mostrar_menu_referral(update: Update, context: ContextTypes.DEFAULT_TYPE, message_id):
    if hasattr(update, 'effective_user'):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
    else:
        user_id = update.from_user.id
        chat_id = update.message.chat.id
    
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("SELECT referrals, referral_earnings FROM usuarios WHERE id=?", (user_id,))
    row = cur.fetchone()
    referrals = row["referrals"] if row else 0
    referral_earnings = row["referral_earnings"] if row else 0.0
    conn.close()
    
    lang = get_user_language(user_id)
    t = translations[lang]
    
    link = f"https://t.me/DescargaVideoTikTokBot?start=ref_{user_id}"
    texto = (
        "🔥 **¡GANA DESCARGAS EXTRA Y RECOMPENSAS!** 🔥\n\n"
        f"👥 **Referidos actuales:** {referrals}\n"
        f"💰 **Ganancias por referidos:** ${referral_earnings:.2f} USDT\n"
        f"🎁 **Recompensa por referido:** ${REFERRAL_REWARD} USDT\n"
        f"🎯 **Beneficios:** +1 descarga/día por cada amigo\n\n"
        f"🔗 Tu enlace exclusivo:\n`{link}`\n\n"
        "📤 Compártelo con tus amigos and disfruta de más descargas y recompensas!"
    )
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Copiar enlace", callback_data=f"copiar_{user_id}")],
        [InlineKeyboardButton(t['more_rewards'], url=RECOMPENSAS_URL)],
        [InlineKeyboardButton(t['menu_principal'], callback_data="menu_principal")]
    ])
    
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=texto,
        reply_markup=teclado,
        parse_mode='Markdown'
    )

async def mostrar_menu_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE, message_id):
    if hasattr(update, 'effective_user'):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
    else:
        user_id = update.from_user.id
        chat_id = update.message.chat.id
    
    lang = get_user_language(user_id)
    t = translations[lang]
    
    balance = get_user_balance(user_id)
    
    texto = (
        "💰 **RETIRO DE FONDOS** 💰\n\n"
        f"💵 **Balance disponible:** ${balance:.2f} USDT\n"
        f"📦 **Mínimo para retirar:** {MIN_WITHDRAWAL} USDT\n\n"
        "Para retirar tus fondos, envía un mensaje con el siguiente formato:\n"
        "`/withdraw <cantidad> <dirección_billetera>`\n\n"
        "Ejemplo:\n"
        "`/withdraw 50 0xTuDirecciónDeBilletera`"
    )
    
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton(t['menu_principal'], callback_data="menu_principal")]
    ])
    
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=texto,
        reply_markup=teclado,
        parse_mode='Markdown'
    )

async def mostrar_menu_language(update: Update, context: ContextTypes.DEFAULT_TYPE, message_id):
    if hasattr(update, 'effective_user'):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
    else:
        user_id = update.from_user.id
        chat_id = update.message.chat.id
    
    lang = get_user_language(user_id)
    t = translations[lang]
    
    texto = "🌐 **SELECCIONA TU IDIOMA** 🌐\n\nElige el idioma de tu preferencia:"
    
    teclado = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇪🇸 Español", callback_data="setlang_es"),
            InlineKeyboardButton("🇺🇸 English", callback_data="setlang_en")
        ],
        [InlineKeyboardButton(t['back'], callback_data="menu_principal")]
    ])
    
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=texto,
        reply_markup=teclado,
        parse_mode='Markdown'
    )

async def mostrar_menu_post_descarga(app, chat_id: int, message_id: int, recompensa: float = 0):
    user_id = chat_id
    lang = get_user_language(user_id)
    t = translations[lang]
    
    texto = f"🎉 **¡Descarga completada!**\n\n"
    if recompensa > 0:
        texto += f"💰 Has ganado ${recompensa:.2f} USDT por esta descarga!\n\n"
    texto += "¿Qué deseas hacer ahora?"
    
    teclado = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬇️ Descargar Otro", callback_data="iniciar_descarga"),
            InlineKeyboardButton("👥 Invitar Amigos", callback_data="menu_referral")
        ],
        [
            InlineKeyboardButton("💎 Obtener Premium", callback_data="menu_premium"),
            InlineKeyboardButton(t['more_rewards'], url=RECOMPENSAS_URL)
        ],
        [InlineKeyboardButton("🏠 Menú principal", callback_data="menu_principal")]
    ])
    
    await app.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=texto,
        reply_markup=teclado,
        parse_mode='Markdown'
    )

async def mostrar_estadisticas(update: Update, context: ContextTypes.DEFAULT_TYPE, message_id):
    if hasattr(update, 'effective_user'):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
    else:
        user_id = update.from_user.id
        chat_id = update.message.chat.id
    
    lang = get_user_language(user_id)
    t = translations[lang]
    
    conn = conectar_db()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT descargas, youtube_descargas, premium, referrals, balance, total_earned, referral_earnings, 
               (SELECT COUNT(*) FROM usuarios WHERE referido_por = ?) as referidos_activos
        FROM usuarios WHERE id = ?
    """, (user_id, user_id))
    
    usuario = cur.fetchone()
    
    if not usuario:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="❌ No se encontraron estadísticas.",
            parse_mode='Markdown'
        )
        return
    
    puede_desc, usadas, total = puede_descargar(user_id)
    youtube_usadas, youtube_total = get_youtube_stats(user_id)
    
    texto = (
        "📊 **TUS ESTADÍSTICAS** 📊\n\n"
        f"⬇️ **Descargas TikTok hoy:** {usadas}/{total}\n"
        f"🎵 **Descargas YouTube hoy:** {youtube_usadas}/{youtube_total}\n"
        f"💰 **Balance actual:** ${usuario['balance']:.2f} USDT\n"
        f"🎯 **Total ganado:** ${usuario['total_earned']:.2f} USDT\n"
        f"👥 **Referidos:** {usuario['referrals']} (${usuario['referral_earnings']:.2f} USDT)\n"
        f"👤 **Referidos activos:** {usuario['referidos_activos']}\n"
        f"💎 **Estado:** {'Premium ✅' if usuario['premium'] else 'Gratuito ⏳'}\n\n"
    )
    
    if not usuario['premium']:
        texto += "🔓 **Mejora a Premium para:**\n- Descargas ilimitadas\n- Videos sin límite de tamaño\n- Prioridad en procesamiento\n- Descargas ilimitadas de YouTube"
    
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton(t['menu_principal'], callback_data="menu_principal")]
    ])
    
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=texto,
        reply_markup=teclado,
        parse_mode='Markdown'
    )
    
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    referido_por = None
    
    if context.args and context.args[0].startswith('ref_'):
        try:
            referido_por = int(context.args[0][4:])
            log_event(f"👥 Referido detectado: {user.id} -> {referido_por}")
        except:
            pass
    
    conn = conectar_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM usuarios WHERE id=?", (user.id,))
    usuario_existente = cur.fetchone()
    conn.close()
    
    if not usuario_existente:
        texto = "🌐 **¡Bienvenido! Welcome!** 🌐\n\nSelecciona tu idioma / Select your language:"
        teclado = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🇪🇸 Español", callback_data="setlang_es"),
                InlineKeyboardButton("🇺🇸 English", callback_data="setlang_en")
            ]
        ])
        await update.message.reply_text(texto, reply_markup=teclado)
        
        registrar_usuario(user.id, user.username, referido_por)
        return
    
    registrar_usuario(user.id, user.username, referido_por)
    await mostrar_menu_principal(update, context)

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    t = translations[lang]
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "❌ Formato incorrecto. Usa:\n`/withdraw <cantidad> <dirección_billetera>`",
            parse_mode='Markdown'
        )
        return
    
    try:
        amount = float(context.args[0])
        address = context.args[1]
        
        if not re.match(r'^0x[a-fA-F0-9]{40}$', address):
            await update.message.reply_text("❌ Dirección de billetera inválida.")
            return
        
        success, message = solicitar_retiro(user_id, amount, address)
        await update.message.reply_text(message)
        
    except ValueError:
        await update.message.reply_text("❌ Cantidad inválida. Debe ser un número.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    conn = conectar_db()
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM usuarios")
    total_usuarios = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM usuarios WHERE premium = 1")
    premium_usuarios = cur.fetchone()[0]
    
    cur.execute("SELECT SUM(descargas) FROM usuarios")
    total_descargas = cur.fetchone()[0] or 0
    
    cur.execute("SELECT COUNT(DISTINCT id) FROM usuarios WHERE last_active > ?", (int(time.time()) - 86400,))
    activos_24h = cur.fetchone()[0]
    
    cur.execute("SELECT SUM(balance) FROM usuarios")
    total_balance = cur.fetchone()[0] or 0
    
    cur.execute("SELECT SUM(total_earned) FROM usuarios")
    total_earned = cur.fetchone()[0] or 0
    
    cur.execute("SELECT SUM(referral_earnings) FROM usuarios")
    total_referral_earnings = cur.fetchone()[0] or 0
    
    conn.close()
    
    texto = (
        "👑 **ESTADÍSTICAS DE ADMINISTRADOR**\n\n"
        f"👥 Usuarios totales: {total_usuarios}\n"
        f"💎 Usuarios premium: {premium_usuarios}\n"
        f"⬇️ Descargas totales: {total_descargas}\n"
        f"👤 Usuarios activos (24h): {activos_24h}\n"
        f"💰 Balance total en sistema: ${total_balance:.2f}\n"
        f"🎁 Total ganado por usuarios: ${total_earned:.2f}\n"
        f"👥 Ganancias por referidos: ${total_referral_earnings:.2f}\n\n"
        f"📊 Hoy:\n"
        f"- Descargas: {stats['daily_downloads']}\n"
        f"- Completadas: {stats['completed_today']}\n"
        f"- Errores: {stats['errors']}\n\n"
        f"⚙️ Sistema:\n"
        f"- En cola: {stats['queue_size']}\n"
        f"- Activas: {stats['active_downloads']}\n"
        f"- Uptime: {time.time() - stats['start_time']:.0f} segundos"
    )
    
    await update.message.reply_text(texto, parse_mode='Markdown')

async def procesar_descarga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    lang = get_user_language(user_id)
    t = translations[lang]
    
    # Verificar si el usuario está esperando un TX
    if user_id in waiting_for_tx:
        tx_hash = update.message.text.strip()
        if re.match(r'^0x[a-fA-F0-9]{64}$', tx_hash):
            del waiting_for_tx[user_id]
            await update.message.reply_text("🔍 Verificando transacción...", parse_mode='Markdown')
            
            ok, msg = validar_pago_con_tx(user_id, tx_hash)
            await update.message.reply_text(msg, parse_mode='Markdown')
            
            if ok:
                await mostrar_menu_principal(update, context)
            else:
                # CORREGIDO: Llamada corregida con todos los parámetros
                await mostrar_menu_premium(update, context)
        else:
            await update.message.reply_text("❌ Formato de TX Hash inválido. Debe tener 64 caracteres hexadecimales después de '0x'.")
        return
    
    registrar_usuario(user_id, username)
    
    text = update.message.text.strip()
    
    es_youtube = "youtube.com" in text or "youtu.be" in text
    
    if not es_url_valida(text):
        await update.message.reply_text("❌ Solo se admiten enlaces de TikTok o YouTube.")
        log_event(f"❌ Enlace inválido de @{username}: {text}")
        return
    
    if es_youtube:
        if not await puede_descargar_youtube(user_id):
            await update.message.reply_text(
                "❌ Has alcanzado tu límite diario de descargas de YouTube (5).\n\n"
                "💎 Conviértete en Premium para descargas ilimitadas de YouTube.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 Obtener Premium", callback_data="menu_premium")],
                    [InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_principal")]
                ])
            )
            log_event(f"⚠️ Límite de YouTube alcanzado para @{username}")
            return
    else:
        puede_desc, usadas, total = puede_descargar(user_id)
        if not puede_desc:
            texto = (
                f"{t['limit_reached']}\n\n"
                f"{t['limit_message'].format(total)}\n"
                "🔓 Para descargas ilimitadas y máxima calidad:"
            )
            teclado = InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Obtener Premium", callback_data="menu_premium")],
                [InlineKeyboardButton("👥 Invitar Amigos", callback_data="menu_referral")],
                [InlineKeyboardButton(t['menu_principal'], callback_data="menu_principal")]
            ])
            await update.message.reply_text(texto, reply_markup=teclado, parse_mode='Markdown')
            log_event(f"⚠️ Límite diario alcanzado para @{username}")
            return
    
    job_id = f"{user_id}_{int(time.time())}_{random.randint(1000,9999)}"
    
    download_jobs[job_id] = {
        'url': text,
        'chat_id': update.message.chat_id,
        'message_id': update.message.message_id,
        'timestamp': time.time()
    }
    
    if es_youtube:
        if es_premium(user_id):
            teclado = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎥 Video HD", callback_data=f"yt_video|{job_id}"),
                    InlineKeyboardButton("🎵 Audio MP3", callback_data=f"yt_audio|{job_id}")
                ],
                [InlineKeyboardButton(t['menu_principal'], callback_data="menu_principal")]
            ])
            msg_text = "🎬 **Selecciona formato para YouTube:**\n✅ Calidad HD Premium"
        else:
            teclado = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎵 Audio MP3", callback_data=f"yt_audio|{job_id}")],
                [InlineKeyboardButton("💎 Obtener Premium", callback_data="menu_premium")],
                [InlineKeyboardButton(t['menu_principal'], callback_data="menu_principal")]
            ])
            msg_text = t['youtube_audio_only']
    else:
        teclado = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎥 Video HD", callback_data=f"tt_video|{job_id}"),
                InlineKeyboardButton("🎵 Audio MP3", callback_data=f"tt_audio|{job_id}")
            ],
            [InlineKeyboardButton(t['menu_principal'], callback_data="menu_principal")]
        ])
        msg_text = "🎬 **Selecciona formato para TikTok:**\n✅ Calidad HD sin marca de agua"
    
    msg = await update.message.reply_text(
        msg_text,
        reply_markup=teclado,
        parse_mode='Markdown'
    )
    download_jobs[job_id]['message_id'] = msg.message_id
    log_event(f"📥 Solicitud recibida de @{username}: {text}")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    username = query.from_user.username
    data = query.data
    message_id = query.message.message_id
    chat_id = query.message.chat_id
    
    # Obtener idioma ANTES de procesar cualquier callback
    lang = get_user_language(user_id)
    t = translations[lang]
    
    if data.startswith("setlang_"):
        nuevo_idioma = data.split('_')[1]
        conn = conectar_db()
        conn.execute("UPDATE usuarios SET language = ? WHERE id = ?", (nuevo_idioma, user_id))
        conn.commit()
        conn.close()
        
        log_event(f"🌐 Idioma cambiado a {nuevo_idioma} por @{username}")
        
        # Recargar traducciones después del cambio
        t = translations[nuevo_idioma]
        
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f"✅ Idioma cambiado a {'Español' if nuevo_idioma == 'es' else 'English'}",
            parse_mode='Markdown'
        )
        
        # Mostrar menú principal con el nuevo idioma
        await mostrar_menu_principal(update, context, message_id)
        return
    
    if data == "menu_principal":
        await mostrar_menu_principal(update, context, message_id)
        log_event(f"🏠 Menú principal mostrado a @{username}")
    
    elif data == "menu_premium":
        # CORREGIDO: Llamada corregida con todos los parámetros
        await mostrar_menu_premium(update, context, message_id)
        log_event(f"💎 Menú premium mostrado a @{username}")
    
    elif data == "menu_referral":
        await mostrar_menu_referral(update, context, message_id)
        log_event(f"👥 Menú referidos mostrado a @{username}")
    
    elif data == "menu_withdraw":
        await mostrar_menu_withdraw(update, context, message_id)
        log_event(f"💰 Menú retiros mostrado a @{username}")
    
    elif data == "menu_language":
        await mostrar_menu_language(update, context, message_id)
        log_event(f"🌐 Menú idioma mostrado a @{username}")
    
    elif data == "como_pagar":
        await mostrar_como_pagar(update, context, message_id)
        log_event(f"❓ Cómo pagar mostrado a @{username}")
    
    elif data == "iniciar_descarga":
        texto = "⬇️ **Envía el enlace del video que deseas descargar:**\nSe admiten enlaces de TikTok y YouTube."
        teclado = InlineKeyboardMarkup([[InlineKeyboardButton(t['menu_principal'], callback_data="menu_principal")]])
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=texto,
            reply_markup=teclado,
            parse_mode='Markdown'
        )
        log_event(f"⬇️ Inicio de descarga solicitado por @{username}")
    
    elif data.startswith("copiar_"):
        ref_user_id = data.split('_')[1]
        link = f"https://t.me/DescargaVideoTikTokBot?start=ref_{ref_user_id}"
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔗 Copia este enlace de referido:\n\n`{link}`\n\nLuego compártelo con tus amigos!",
            parse_mode='Markdown'
        )
        log_event(f"📋 Enlace de referido copiado por @{username}")
    
    elif data == "verificar_pago":
        # Marcar usuario como esperando TX
        waiting_for_tx[user_id] = True
        
        texto = t['enter_tx_hash']
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_verificacion")]
        ])
        
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=texto,
            reply_markup=teclado,
            parse_mode='Markdown'
        )
        log_event(f"🔍 Solicitando TX Hash a @{username}")
    
    elif data == "cancelar_verificacion":
        if user_id in waiting_for_tx:
            del waiting_for_tx[user_id]
        # CORREGIDO: Llamada corregida con todos los parámetros
        await mostrar_menu_premium(update, context, message_id)
        log_event(f"❌ Verificación cancelada por @{username}")
    
    elif data == "estadisticas":
        await mostrar_estadisticas(update, context, message_id)
        log_event(f"📊 Estadísticas mostradas a @{username}")
    
    elif "|" in data:
        tipo, job_id = data.split("|", 1)
        job = download_jobs.get(job_id)
        
        if not job:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="❌ El enlace ha expirado. Por favor, envía un nuevo enlace.",
                parse_mode='Markdown'
            )
            log_event(f"❌ Tarea expirada: {job_id}")
            return
        
        url = job['url']
        
        if tipo.startswith("yt_"):
            if not await puede_descargar_youtube(user_id):
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text="❌ Has alcanzado tu límite diario de descargas de YouTube (5).\n\n💎 Conviértete en Premium para descargas ilimitadas.",
                    parse_mode='Markdown'
                )
                log_event(f"⚠️ Límite de YouTube alcanzado al procesar: @{username}")
                return
        else:
            puede_desc, usadas, total = puede_descargar(user_id)
            if not puede_desc:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"⚠️ *Límite diario alcanzado*\n\n{t['limit_message'].format(total)}",
                    parse_mode='Markdown'
                )
                log_event(f"⚠️ Límite diario alcanzado al procesar: @{username}")
                return
        
        if tipo == "yt_video" and not es_premium(user_id):
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=t['youtube_premium_only'],
                parse_mode='Markdown'
            )
            log_event(f"❌ Intento de descarga de YouTube video sin premium: @{username}")
            return
        
        priority = 0 if es_premium(user_id) else 1
        
        task_id = await download_queue_system.add_task(
            priority, 
            (job_id, user_id, url, tipo, chat_id, message_id)
        )
        
        stats["queue_size"] = download_queue_system.priority_queue.qsize()
        print_stats()
        
        queue_size = download_queue_system.priority_queue.qsize()
        if priority == 0:
            status = t['premium_priority']
        else:
            status = t['queue_position'].format(queue_size)
            
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=t['processing_queue'].format("En cola de espera") + f"\n\n{status}",
            parse_mode='Markdown'
        )
        log_event(f"📥 Tarea añadida a cola (Prioridad: {priority}, ID: {task_id}) por @{username}: {url}")

async def scheduled_tasks():
    while True:
        try:
            await asyncio.sleep(3600)
        except Exception as e:
            log_event(f"❌ Error en tareas programadas: {e}")
            await asyncio.sleep(3600)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        raise context.error
    except BadRequest as e:
        if "Message is not modified" in str(e):
            log_event("⚠️ Error 'Message is not modified' ignorado")
        else:
            log_event(f"❌ Error de BadRequest: {e}")
    except RetryAfter as e:
        log_event(f"⏰ Rate limit alcanzado: {e}")
    except Exception as e:
        log_event(f"❌ Error no manejado: {e}")
        stats["errors"] += 1

def start_background_tasks(application):
    download_queue_system.set_application(application)
    loop = asyncio.get_event_loop()
    loop.create_task(download_queue_system.start())
    loop.create_task(monitor_sistema())
    loop.create_task(verificar_estado_sistema())
    loop.create_task(scheduled_tasks())

def main():
    crear_tabla()
    
    stats["start_time"] = time.time()
    print_stats()
    log_event("🤖 Iniciando bot de descargas con sistema de colas mejorado...")
    
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(CommandHandler("withdraw", withdraw_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_descarga))
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    application.add_error_handler(error_handler)
    
    start_background_tasks(application)
    
    log_event("🚀 Bot en ejecución con NUEVO sistema de colas...")
    
    try:
        application.run_polling()
    except KeyboardInterrupt:
        log_event("🛑 Bot detenido por el usuario")
    except Exception as e:
        log_event(f"❌ Error crítico: {e}")
    finally:
        executor.shutdown(wait=False)

if __name__ == "__main__":
    main()
