import os
import logging
import time
from datetime import datetime
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Importar modelos y configuración de base de datos
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base

# Configuración de base de datos
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://user:password@localhost:5432/shpd_db"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Modelos
class Paciente(Base):
    __tablename__ = "pacientes"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String)
    edad = Column(Integer)
    diagnostico = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class Sesion(Base):
    __tablename__ = "sesiones"
    
    id = Column(Integer, primary_key=True, index=True)
    paciente_id = Column(Integer, ForeignKey("pacientes.id"))
    intervalo_segundos = Column(Integer)
    modo = Column(String)
    tiempo_transcurrido = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class MetricaPostural(Base):
    __tablename__ = "metricas_posturales"
    
    id = Column(Integer, primary_key=True, index=True)
    sesion_id = Column(Integer, ForeignKey("sesiones.id"))
    porcentaje_correcta = Column(Float)
    porcentaje_incorrecta = Column(Float)
    tiempo_sentado = Column(Float)
    tiempo_parado = Column(Float)
    alertas_enviadas = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

# --- Configuración logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# --- Menús y botones ---
MAIN_MENU = {
    "1": "Configurar sesión",
    "2": "Ver métricas",
    "3": "Ajustar alertas",
    "4": "Mis datos",
    "5": "Calibrar dispositivo",
    "6": "Ayuda",
    "7": "Volver al menú",
}

MENU_BUTTONS = [
    ["1. ⚙️ Configurar sesión", "2. 📊 Ver métricas"],
    ["3. 🔔 Ajustar alertas", "4. 👤 Mis datos"],
    ["5. 🎯 Calibrar dispositivo", "6. ❓ Ayuda"],
    ["7. 🔄 Volver al menú"],
]

# Configuración de sesión
SESSION_MENU = {
    "1": "30 minutos",
    "2": "1 hora",
    "3": "2 horas",
    "4": "Personalizado",
}

SESSION_BUTTONS = [
    ["1. 30 minutos", "2. 1 hora"],
    ["3. 2 horas", "4. Personalizado"],
]

# Configuración de alertas
ALERT_MENU = {
    "1": "Cada 5 minutos",
    "2": "Cada 10 minutos",
    "3": "Cada 15 minutos",
    "4": "Personalizado",
}

ALERT_BUTTONS = [
    ["1. Cada 5 minutos", "2. Cada 10 minutos"],
    ["3. Cada 15 minutos", "4. Personalizado"],
]

# Datos del paciente en memoria (temporal hasta que se guarde en BD)
PATIENT_DATA = {
    "nombre": "",
    "edad": 0,
    "diagnostico": "",
    "sesion_duracion": 1800,  # 30 minutos por defecto
    "alerta_intervalo": 300,  # 5 minutos por defecto
    "calibrado": False
}

def extract_choice(text: str) -> str:
    """Extrae el dígito antes del punto o devuelve el texto si no hay formato 'n.'."""
    if "." in text:
        return text.split(".")[0].strip()
    return text.strip()

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # No limpiamos el contexto completamente, solo el estado
    if "state" in context.user_data:
        context.user_data.pop("state")

    # Envía el menú interactivo
    await update.message.reply_text(
        "👋 <b>Bienvenido al Sistema de Monitoreo Postural</b>\nElige una opción:",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardMarkup(
            MENU_BUTTONS,
            resize_keyboard=True,
            one_time_keyboard=True
        ),
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    choice = extract_choice(text)
    lower = text.lower()
    state = context.user_data.get("state")

    # Saludo o reinicio
    if lower in ("hola", "hola!"):
        return await show_main_menu(update, context)

    # Gestión de datos del paciente
    if state == "awaiting_patient_data":
        if not context.user_data.get("awaiting_field"):
            context.user_data["awaiting_field"] = "nombre"
            await update.message.reply_text(
                "Por favor, ingresa tu nombre completo:",
                reply_markup=ReplyKeyboardRemove()
            )
            return
            
        field = context.user_data["awaiting_field"]
        if field == "nombre":
            PATIENT_DATA["nombre"] = text
            context.user_data["awaiting_field"] = "edad"
            await update.message.reply_text(
                "Ingresa tu edad:",
                reply_markup=ReplyKeyboardRemove()
            )
            return
        elif field == "edad":
            try:
                edad = int(text)
                if edad < 1 or edad > 120:
                    await update.message.reply_text(
                        "❌ Por favor, ingresa una edad válida (entre 1 y 120 años):",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    return
                PATIENT_DATA["edad"] = edad
                context.user_data["awaiting_field"] = "diagnostico"
                await update.message.reply_text(
                    "Ingresa tu diagnóstico médico:",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            except ValueError:
                await update.message.reply_text(
                    "❌ Por favor, ingresa un número válido para la edad:",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
        elif field == "diagnostico":
            PATIENT_DATA["diagnostico"] = text
            context.user_data.pop("awaiting_field")
            
            # Guardar en base de datos
            db = SessionLocal()
            try:
                paciente = await save_patient_data(db, PATIENT_DATA)
                context.user_data["paciente_id"] = paciente.id
                await update.message.reply_text(
                    "✅ Datos guardados correctamente",
                    reply_markup=ReplyKeyboardRemove()
                )
            except Exception as e:
                logging.error(f"Error al guardar datos del paciente: {e}")
                await update.message.reply_text(
                    "❌ Error al guardar los datos. Por favor, intenta de nuevo.",
                    reply_markup=ReplyKeyboardRemove()
                )
            finally:
                db.close()
                
            context.user_data["state"] = None
            return await show_main_menu(update, context)

    # Función auxiliar para verificar datos del paciente
    def verify_patient_data():
        if not PATIENT_DATA["nombre"] or not context.user_data.get("paciente_id"):
            return False
        return True

    # Gestión de métricas
    if choice == "2":
        db = SessionLocal()
        try:
            paciente_id = context.user_data.get("paciente_id")
            if not paciente_id:
                await update.message.reply_text(
                    "❌ Primero debes completar tus datos personales.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return await show_main_menu(update, context)
                
            metrics = await get_patient_metrics(db, paciente_id)
            if not metrics:
                await update.message.reply_text(
                    "📊 <b>Métricas</b>\n\n"
                    "No hay métricas disponibles aún.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=ReplyKeyboardRemove()
                )
            else:
                await update.message.reply_text(
                    "📊 <b>Métricas de postura</b>\n\n"
                    f"• Postura correcta: {metrics.porcentaje_correcta:.1f}%\n"
                    f"• Postura incorrecta: {metrics.porcentaje_incorrecta:.1f}%\n"
                    f"• Tiempo sentado: {metrics.tiempo_sentado:.1f}s\n"
                    f"• Tiempo parado: {metrics.tiempo_parado:.1f}s\n"
                    f"• Alertas enviadas: {metrics.alertas_enviadas}\n\n"
                    f"Última actualización: {metrics.created_at.strftime('%d/%m/%Y %H:%M')}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=ReplyKeyboardRemove()
                )
        except Exception as e:
            logging.error(f"Error al obtener métricas: {e}")
            await update.message.reply_text(
                "❌ Error al obtener las métricas. Por favor, intenta de nuevo.",
                reply_markup=ReplyKeyboardRemove()
            )
        finally:
            db.close()
            
        return await show_main_menu(update, context)

    # Gestión de configuración de sesión
    if state == "awaiting_session_config":
        if choice not in SESSION_MENU:
            return await update.message.reply_text(
                "❌ Opción no válida. Elige una duración:",
                reply_markup=ReplyKeyboardMarkup(
                    SESSION_BUTTONS, resize_keyboard=True, one_time_keyboard=True
                ),
            )
        
        if choice == "4":
            await update.message.reply_text(
                "Ingresa la duración en minutos:",
                reply_markup=ReplyKeyboardRemove()
            )
            context.user_data["state"] = "awaiting_custom_session"
            return
            
        duration = int(choice) * 30 * 60  # Convertir a segundos
        context.user_data["sesion_duracion"] = duration
        PATIENT_DATA["sesion_duracion"] = duration
        
        # Verificar datos del paciente antes de preguntar por iniciar sesión
        if not verify_patient_data():
            await update.message.reply_text(
                "❌ Primero debes completar tus datos personales.",
                reply_markup=ReplyKeyboardRemove()
            )
            return await show_main_menu(update, context)
            
        if not PATIENT_DATA["calibrado"]:
            await update.message.reply_text(
                "❌ Primero debes calibrar el dispositivo.\n\n"
                "Por favor, accede a la siguiente URL para calibrar:\n"
                "http://172.18.0.2:30080/\n\n"
                "Una vez completada la calibración, podrás iniciar la sesión.",
                parse_mode=ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove()
            )
            return await show_main_menu(update, context)
        
        await update.message.reply_text(
            f"✅ Sesión configurada para {int(duration/60)} minutos\n\n"
            "¿Deseas iniciar la sesión ahora?",
            reply_markup=ReplyKeyboardMarkup(
                [["Sí", "No"]], resize_keyboard=True, one_time_keyboard=True
            )
        )
        context.user_data["state"] = "awaiting_session_start"
        return

    # Gestión de inicio de sesión
    if state == "awaiting_session_start":
        if lower not in ("sí", "si", "no"):
            await update.message.reply_text(
                "❌ Por favor, responde Sí o No.",
                reply_markup=ReplyKeyboardMarkup(
                    [["Sí", "No"]], resize_keyboard=True, one_time_keyboard=True
                )
            )
            return
            
        if lower in ("sí", "si"):
            return await start_session(update, context)
        else:
            await update.message.reply_text(
                "Sesión guardada. Puedes iniciarla más tarde desde el menú principal.",
                reply_markup=ReplyKeyboardRemove()
            )
            return await show_main_menu(update, context)

    # Gestión de configuración de alertas
    if state == "awaiting_alert_config":
        if choice not in ALERT_MENU:
            return await update.message.reply_text(
                "❌ Opción no válida. Elige un intervalo:",
                reply_markup=ReplyKeyboardMarkup(
                    ALERT_BUTTONS, resize_keyboard=True, one_time_keyboard=True
                ),
            )
        
        if choice == "4":
            await update.message.reply_text(
                "Ingresa el intervalo en minutos:",
                reply_markup=ReplyKeyboardRemove()
            )
            context.user_data["state"] = "awaiting_custom_alert"
            return
            
        interval = int(choice) * 5 * 60  # Convertir a segundos
        context.user_data["alerta_intervalo"] = interval
        PATIENT_DATA["alerta_intervalo"] = interval
        
        await update.message.reply_text(
            f"✅ Alertas configuradas cada {int(interval/60)} minutos",
            reply_markup=ReplyKeyboardRemove()
        )
        return await show_main_menu(update, context)

    # Gestión de calibración
    if choice == "5":
        await update.message.reply_text(
            "🎯 <b>Calibración del dispositivo</b>\n\n"
            "Para calibrar el dispositivo, accede a la siguiente URL:\n"
            "http://172.18.0.2:30080/\n\n"
            "Una vez completada la calibración, marca esta opción como completada.",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardMarkup(
                [["✅ Marcar como calibrado"]], resize_keyboard=True, one_time_keyboard=True
            )
        )
        context.user_data["state"] = "awaiting_calibration"
        return

    if state == "awaiting_calibration":
        if text == "✅ Marcar como calibrado":
            PATIENT_DATA["calibrado"] = True
            await update.message.reply_text(
                "✅ Dispositivo calibrado correctamente",
                reply_markup=ReplyKeyboardRemove()
            )
            return await show_main_menu(update, context)

    # Gestión de actualización de datos
    if state == "awaiting_data_update":
        if lower not in ("sí", "si", "no"):
            await update.message.reply_text(
                "❌ Por favor, responde Sí o No.",
                reply_markup=ReplyKeyboardMarkup(
                    [["Sí", "No"]], resize_keyboard=True, one_time_keyboard=True
                )
            )
            return
            
        if lower in ("sí", "si"):
            context.user_data["state"] = "awaiting_patient_data"
            context.user_data["awaiting_field"] = "nombre"
            await update.message.reply_text(
                "Por favor, ingresa tu nombre completo:",
                reply_markup=ReplyKeyboardRemove()
            )
        else:
            return await show_main_menu(update, context)

    # Gestión de confirmación de sesión existente
    if state == "awaiting_session_confirm":
        if lower not in ("mantener", "cambiar"):
            await update.message.reply_text(
                "❌ Por favor, elige una opción válida.",
                reply_markup=ReplyKeyboardMarkup(
                    [["Mantener", "Cambiar"]], resize_keyboard=True, one_time_keyboard=True
                )
            )
            return
            
        if lower == "mantener":
            # Verificar datos del paciente antes de preguntar por iniciar sesión
            if not verify_patient_data():
                await update.message.reply_text(
                    "❌ Primero debes completar tus datos personales.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return await show_main_menu(update, context)
                
            if not PATIENT_DATA["calibrado"]:
                await update.message.reply_text(
                    "❌ Primero debes calibrar el dispositivo.\n\n"
                    "Por favor, accede a la siguiente URL para calibrar:\n"
                    "http://172.18.0.2:30080/\n\n"
                    "Una vez completada la calibración, podrás iniciar la sesión.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=ReplyKeyboardRemove()
                )
                return await show_main_menu(update, context)
            
            await update.message.reply_text(
                f"✅ Sesión configurada para {int(context.user_data['sesion_duracion']/60)} minutos\n\n"
                "¿Deseas iniciar la sesión ahora?",
                reply_markup=ReplyKeyboardMarkup(
                    [["Sí", "No"]], resize_keyboard=True, one_time_keyboard=True
                )
            )
            context.user_data["state"] = "awaiting_session_start"
            return
        else:  # Si elige "cambiar"
            await update.message.reply_text(
                "Elige la duración de la sesión:",
                reply_markup=ReplyKeyboardMarkup(
                    SESSION_BUTTONS, resize_keyboard=True, one_time_keyboard=True
                ),
            )
            context.user_data["state"] = "awaiting_session_config"
            return

    # Manejo del menú principal
    if choice in MAIN_MENU:
        if choice == "1":
            # Si ya hay una duración configurada, preguntar si quiere mantenerla o cambiarla
            if context.user_data.get("sesion_duracion"):
                await update.message.reply_text(
                    f"Ya tienes una sesión configurada para {int(context.user_data['sesion_duracion']/60)} minutos.\n\n"
                    "¿Deseas mantener esta configuración o cambiarla?",
                    reply_markup=ReplyKeyboardMarkup(
                        [["Mantener", "Cambiar"]], resize_keyboard=True, one_time_keyboard=True
                    )
                )
                context.user_data["state"] = "awaiting_session_confirm"
                return
            else:
                await update.message.reply_text(
                    "Elige la duración de la sesión:",
                    reply_markup=ReplyKeyboardMarkup(
                        SESSION_BUTTONS, resize_keyboard=True, one_time_keyboard=True
                    ),
                )
                context.user_data["state"] = "awaiting_session_config"
                return

        elif choice == "3":
            # Ajustar alertas
            await update.message.reply_text(
                "Elige el intervalo para las alertas:",
                reply_markup=ReplyKeyboardMarkup(
                    ALERT_BUTTONS, resize_keyboard=True, one_time_keyboard=True
                ),
            )
            context.user_data["state"] = "awaiting_alert_config"
            return

        elif choice == "4":
            # Mis datos
            if not PATIENT_DATA["nombre"]:
                context.user_data["state"] = "awaiting_patient_data"
                context.user_data["awaiting_field"] = "nombre"
                await update.message.reply_text(
                    "Por favor, ingresa tu nombre completo:",
                    reply_markup=ReplyKeyboardRemove()
                )
            else:
                await update.message.reply_text(
                    "👤 <b>Mis datos</b>\n\n"
                    f"Nombre: {PATIENT_DATA['nombre']}\n"
                    f"Edad: {PATIENT_DATA['edad']}\n"
                    f"Diagnóstico: {PATIENT_DATA['diagnostico']}\n\n"
                    "¿Deseas modificar tus datos?",
                    parse_mode=ParseMode.HTML,
                    reply_markup=ReplyKeyboardMarkup(
                        [["Sí", "No"]], resize_keyboard=True, one_time_keyboard=True
                    )
                )
                context.user_data["state"] = "awaiting_data_update"
            return

        elif choice == "6":
            # Ayuda
            await update.message.reply_text(
                "❓ <b>Ayuda</b>\n\n"
                "1. Configura la duración de tu sesión\n"
                "2. Ajusta las alertas según tus necesidades\n"
                "3. Completa tus datos personales\n"
                "4. Calibra el dispositivo\n"
                "5. Consulta tu historial de sesiones\n\n"
                "Para más ayuda, contacta a tu terapeuta.",
                parse_mode=ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove()
            )
            return await show_main_menu(update, context)

        elif choice == "7":
            return await show_main_menu(update, context)
    else:
        # Si no es una opción válida del menú principal y no estamos en un estado específico
        if not state:
            await update.message.reply_text(
                "❌ Por favor, selecciona una opción del menú:",
                reply_markup=ReplyKeyboardMarkup(
                    MENU_BUTTONS, resize_keyboard=True, one_time_keyboard=True
                ),
            )
        return

async def handle_custom_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        minutes = int(update.message.text)
        if minutes < 1 or minutes > 240:  # Máximo 4 horas
            await update.message.reply_text(
                "❌ La duración debe estar entre 1 y 240 minutos.",
                reply_markup=ReplyKeyboardRemove()
            )
            return
            
        duration = minutes * 60  # Convertir a segundos
        context.user_data["sesion_duracion"] = duration
        PATIENT_DATA["sesion_duracion"] = duration
        
        await update.message.reply_text(
            f"✅ Sesión configurada para {minutes} minutos\n\n"
            "¿Deseas iniciar la sesión ahora?",
            reply_markup=ReplyKeyboardMarkup(
                [["Sí", "No"]], resize_keyboard=True, one_time_keyboard=True
            )
        )
        context.user_data["state"] = "awaiting_session_start"
        return
    except ValueError:
        await update.message.reply_text(
            "❌ Por favor, ingresa un número válido de minutos.",
            reply_markup=ReplyKeyboardRemove()
        )

async def handle_custom_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        minutes = int(update.message.text)
        if minutes < 1 or minutes > 60:  # Máximo 1 hora
            await update.message.reply_text(
                "❌ El intervalo debe estar entre 1 y 60 minutos.",
                reply_markup=ReplyKeyboardRemove()
            )
            return
            
        interval = minutes * 60  # Convertir a segundos
        context.user_data["alerta_intervalo"] = interval
        PATIENT_DATA["alerta_intervalo"] = interval
        
        await update.message.reply_text(
            f"✅ Alertas configuradas cada {minutes} minutos",
            reply_markup=ReplyKeyboardRemove()
        )
        return await show_main_menu(update, context)
    except ValueError:
        await update.message.reply_text(
            "❌ Por favor, ingresa un número válido de minutos.",
            reply_markup=ReplyKeyboardRemove()
        )

async def start_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Verificar que el paciente tenga datos y esté calibrado
    if not PATIENT_DATA["nombre"] or not context.user_data.get("paciente_id"):
        await update.message.reply_text(
            "❌ Primero debes completar tus datos personales.",
            reply_markup=ReplyKeyboardRemove()
        )
        return await show_main_menu(update, context)
        
    if not PATIENT_DATA["calibrado"]:
        await update.message.reply_text(
            "❌ Primero debes calibrar el dispositivo.\n\n"
            "Por favor, accede a la siguiente URL para calibrar:\n"
            "http://172.18.0.2:30080/\n\n"
            "Una vez completada la calibración, podrás iniciar la sesión.",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove()
        )
        return await show_main_menu(update, context)
        
    duration = context.user_data.get("sesion_duracion", PATIENT_DATA["sesion_duracion"])
    interval = context.user_data.get("alerta_intervalo", PATIENT_DATA["alerta_intervalo"])
    
    # Crear nueva sesión en la base de datos
    db = SessionLocal()
    try:
        sesion = await save_session(db, context.user_data["paciente_id"], duration)
        session_id = sesion.id
        
        context.user_data["current_session"] = {
            "id": session_id,
            "start_time": time.time(),
            "duration": duration,
            "alert_interval": interval,
            "alerts_sent": 0
        }
        
        await update.message.reply_text(
            f"✅ Sesión iniciada\n\n"
            f"⏱️ Duración: {duration/60} minutos\n"
            f"🔔 Alertas: cada {interval/60} minutos\n\n"
            "La sesión se detendrá automáticamente al finalizar.",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove()
        )
        
        # Programar alertas
        context.job_queue.run_repeating(
            send_alert,
            interval=interval,
            first=interval,
            data={"session_id": session_id}
        )
        
        # Programar fin de sesión
        context.job_queue.run_once(
            end_session,
            duration,
            data={"session_id": session_id}
        )
    except Exception as e:
        logging.error(f"Error al iniciar sesión: {e}")
        await update.message.reply_text(
            "❌ Error al iniciar la sesión. Por favor, intenta de nuevo.",
            reply_markup=ReplyKeyboardRemove()
        )
    finally:
        db.close()

async def send_alert(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    session_id = job.data["session_id"]
    
    if session_id not in context.user_data.get("current_session", {}).get("id"):
        return
        
    session = context.user_data["current_session"]
    session["alerts_sent"] += 1
    
    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text=(
            "🔔 <b>Recordatorio de postura</b>\n\n"
            "Por favor, verifica tu postura:\n"
            "• Espalda recta\n"
            "• Hombros relajados\n"
            "• Pantalla a la altura de los ojos\n"
            "• Pies apoyados en el suelo\n\n"
            f"Tiempo restante: {int((session['duration'] - (time.time() - session['start_time'])) / 60)} minutos"
        ),
        parse_mode=ParseMode.HTML
    )

async def end_session(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    session_id = job.data["session_id"]
    
    if session_id not in context.user_data.get("current_session", {}).get("id"):
        return
        
    session = context.user_data["current_session"]
    
    # Guardar métricas finales
    db = SessionLocal()
    try:
        metrics = {
            "porcentaje_correcta": 0.0,  # Estos valores deberían venir del sistema de monitoreo
            "porcentaje_incorrecta": 0.0,
            "tiempo_sentado": 0.0,
            "tiempo_parado": 0.0,
            "alertas_enviadas": session["alerts_sent"]
        }
        await save_metrics(db, session_id, metrics)
        
        await context.bot.send_message(
            chat_id=context.job.chat_id,
            text=(
                "✅ <b>Sesión finalizada</b>\n\n"
                f"• Duración: {session['duration']/60} minutos\n"
                f"• Alertas enviadas: {session['alerts_sent']}\n\n"
                "¡Gracias por usar el sistema de monitoreo postural!"
            ),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logging.error(f"Error al finalizar sesión: {e}")
    finally:
        db.close()
    
    # Limpiar datos de la sesión
    context.user_data.pop("current_session", None)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def save_patient_data(db: Session, data: dict):
    paciente = Paciente(
        nombre=data["nombre"],
        edad=data["edad"],
        diagnostico=data["diagnostico"]
    )
    db.add(paciente)
    db.commit()
    db.refresh(paciente)
    return paciente

async def save_session(db: Session, paciente_id: int, duration: int, mode: str = "monitor_activo"):
    sesion = Sesion(
        paciente_id=paciente_id,
        intervalo_segundos=duration,
        modo=mode
    )
    db.add(sesion)
    db.commit()
    db.refresh(sesion)
    return sesion

async def save_metrics(db: Session, sesion_id: int, metrics: dict):
    metrica = MetricaPostural(
        sesion_id=sesion_id,
        porcentaje_correcta=metrics["porcentaje_correcta"],
        porcentaje_incorrecta=metrics["porcentaje_incorrecta"],
        tiempo_sentado=metrics["tiempo_sentado"],
        tiempo_parado=metrics["tiempo_parado"],
        alertas_enviadas=metrics["alertas_enviadas"]
    )
    db.add(metrica)
    db.commit()
    db.refresh(metrica)
    return metrica

async def get_patient_metrics(db: Session, paciente_id: int):
    return db.query(MetricaPostural)\
        .join(Sesion)\
        .filter(Sesion.paciente_id == paciente_id)\
        .order_by(MetricaPostural.created_at.desc())\
        .first()

if __name__ == "__main__":
    app = ApplicationBuilder()\
        .token(os.getenv("TELEGRAM_TOKEN", "7600712992:AAGKYF0lCw7h7B-ROthuOKlb90QZM20MZis"))\
        .build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Nuevos handlers para sesiones personalizadas
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r"^\d+$") & filters.ChatType.PRIVATE,
        handle_custom_session,
        block=False
    ))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r"^\d+$") & filters.ChatType.PRIVATE,
        handle_custom_alert,
        block=False
    ))

    app.run_polling()