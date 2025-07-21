import os
import logging
import time
from datetime import datetime
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import redis
from sqlalchemy.dialects.postgresql import UUID
import uuid

# --- Configuración logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# --- Configuración de base de datos ---
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://user:password@postgres-service:5432/shpd_db"
)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Modelos ---
class Paciente(Base):
    __tablename__ = "pacientes"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(String, unique=True, index=True, nullable=False)
    device_id = Column(String, unique=True, index=True, nullable=False)
    nombre = Column(String, nullable=False)
    edad = Column(Integer)
    sexo = Column(String)
    diagnostico = Column(String)

class Sesion(Base):
    __tablename__ = "sesiones"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    intervalo_segundos = Column(Integer)
    modo = Column(String)

class MetricaPostural(Base):
    __tablename__ = "metricas_posturales"
    id = Column(Integer, primary_key=True, index=True)
    sesion_id = Column(UUID, ForeignKey("sesiones.id"))
    porcentaje_correcta = Column(Float)
    porcentaje_incorrecta = Column(Float)
    tiempo_sentado = Column(Float)
    tiempo_parado = Column(Float)
    alertas_enviadas = Column(Integer)

# Crear tablas si no existen
Base.metadata.create_all(bind=engine)

# Conectarse a Redis
try:
    r = redis.Redis(host='redis', port=6379, decode_responses=True) # Apuntar al servicio de Redis
    r.ping()
    logging.info("Conexión a Redis exitosa desde el Bot.")
except redis.exceptions.ConnectionError as e:
    logging.error(f"No se pudo conectar a Redis desde el Bot: {e}")
    r = None

# --- Menús y botones ---
MAIN_MENU = {
    "1": "Configurar sesión",
    "2": "Ver métricas",
    "3": "Ajustar alertas",
    "4": "Mis datos",
    "5": "Logros y badges",
    "6": "Ayuda",
    "7": "Volver al menú",
}

MENU_BUTTONS = [
    ["1. ⚙️ Configurar sesión", "2. 📊 Ver métricas"],
    ["3. 🔔 Ajustar alertas", "4. 👤 Mis datos"],
    ["5. 🏆 Logros y badges", "6. ❓ Ayuda"],
    ["7. 🔄 Volver al menú"],
]

# Configuración de sesión
SESSION_MENU = {
    "1": "10 minutos",
    "2": "30 minutos",
    "3": "1 hora",
    "4": "Personalizado",
}

SESSION_BUTTONS = [
    ["1. 10 minutos", "2. 30 minutos"],
    ["3. 1 hora", "4. Personalizado"],
]

# Opciones de sexo para el registro de pacientes
GENDER_BUTTONS = [
    ["Masculino", "Femenino"],
    ["Otro"]
]

# Estados de registro de paciente
FIELDS = ["nombre", "edad", "sexo", "diagnostico", "device_id"]

# --- Selectores de rol y menús personalizados ---
ROLE_BUTTONS = [["Paciente", "Especialista"]]

PATIENT_MENU_BUTTONS = [
    ["1. ⚙️ Configurar sesión", "2. 📊 Ver métricas"],
    ["3. 🔔 Ajustar alertas", "4. 👤 Mis datos"],
    ["5. 🏆 Logros y badges", "6. ❓ Ayuda"],
    ["7. 🔄 Volver al menú"],
]

SPECIALIST_MENU_BUTTONS = [
    ["📋 Ver lista de pacientes", "📊 Informes de paciente"],
    ["⚙️ Ajustes de servicio", "🔔 Alertas de riesgo"],
    ["🗂️ Exportar datos", "💬 Chat con especialista"],
]

# --- Utilidades de pacientes ---
def _format_patient(full_name: str) -> str:
    parts = full_name.split()
    if len(parts) >= 2:
        last = parts[-1]
        first = " ".join(parts[:-1])
        return f"{last} {first}"
    return full_name


async def list_patients(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra la lista de pacientes como botones."""
    db: Session = SessionLocal()
    try:
        pacientes = db.query(Paciente).order_by(Paciente.nombre).all()
    finally:
        db.close()

    if not pacientes:
        await update.effective_message.reply_text("No se encontraron pacientes registrados.")
        return

    keyboard = [
        [InlineKeyboardButton(_format_patient(p.nombre), callback_data=f"patient:{p.id}")]
        for p in pacientes
    ]
    await update.effective_message.reply_text(
        "👥 <b>Lista de pacientes</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def patient_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra los detalles de un paciente seleccionado."""
    query = update.callback_query
    await query.answer()
    patient_id = int(query.data.split(":")[1])

    db: Session = SessionLocal()
    try:
        paciente = db.query(Paciente).filter(Paciente.id == patient_id).first()
    finally:
        db.close()

    if not paciente:
        await query.edit_message_text("Paciente no encontrado.")
        return

    msg = (
        f"<b>{paciente.nombre}</b>\n"
        f"Edad: {paciente.edad}\n"
        f"Sexo: {paciente.sexo}\n"
        f"Diagnóstico: {paciente.diagnostico}\n"
        f"Dispositivo: <code>{paciente.device_id}</code>"
    )
    await query.edit_message_text(
        msg,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Volver", callback_data="list_patients")]]
        ),
    )


async def list_patients_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para volver a listar pacientes."""
    query = update.callback_query
    await query.answer()
    await list_patients(update, context)

# Utilidad para extraer la opción seleccionada
def extract_choice(text: str) -> str:
    if "." in text:
        return text.split(".")[0].strip()
    return text.strip()

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el menú principal según el rol guardado."""
    context.user_data.pop("state", None)
    role = context.user_data.get("rol")

    if role == "especialista":
        keyboard = SPECIALIST_MENU_BUTTONS
        title = "👋 <b>Menú de Especialista</b>"
    else:
        keyboard = PATIENT_MENU_BUTTONS
        title = "👋 <b>Menú de Paciente</b>"

    await update.message.reply_text(
        f"{title}\nElige una opción:",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Solicita el rol del usuario al iniciar la conversación."""
    # Limpiar rol previo y teclado
    context.user_data.pop("rol", None)
    context.user_data.pop("state", None)
    await update.message.reply_text(
        "¿Eres Paciente o Especialista?",
        reply_markup=ReplyKeyboardMarkup(ROLE_BUTTONS, resize_keyboard=True, one_time_keyboard=True)
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    choice = text.split('.')[0] if "." in text else text
    state = context.user_data.get("state")

    # --- Selección de rol inicial ---
    if context.user_data.get("rol") is None:
        if text.lower() == "paciente":
            context.user_data["rol"] = "paciente"
            return await show_main_menu(update, context)
        elif text.lower() == "especialista":
            context.user_data["rol"] = "especialista"
            return await show_main_menu(update, context)
        else:
            return await update.message.reply_text(
                "Por favor selecciona 'Paciente' o 'Especialista'.",
                reply_markup=ReplyKeyboardMarkup(ROLE_BUTTONS, resize_keyboard=True, one_time_keyboard=True)
            )

    role = context.user_data.get("rol")

    # --- Opciones del menú de Especialista ---
    if role == "especialista":
        if text == "📋 Ver lista de pacientes":
            await list_patients(update, context)
            return
        if text == "📊 Informes de paciente":
            await update.message.reply_text("Funcionalidad de informes pendiente.")
            return
        if text == "⚙️ Ajustes de servicio":
            await update.message.reply_text("Funcionalidad de ajustes pendiente.")
            return
        if text == "🔔 Alertas de riesgo":
            await update.message.reply_text("Funcionalidad de alertas pendiente.")
            return
        if text == "🗂️ Exportar datos":
            await update.message.reply_text("Funcionalidad de exportación pendiente.")
            return
        if text == "💬 Chat con especialista":
            await update.message.reply_text("Funcionalidad de chat pendiente.")
            return

    # --- Opciones del menú de Paciente ---
    if role == "paciente":
        if text.startswith("5") or "Logros" in text:
            await update.message.reply_text("Funcionalidad de logros pendiente.")
            return

    # Manejo de 'Mis datos' (opción 4)
    if choice == "4":
        telegram_id = str(update.effective_user.id)
        db: Session = SessionLocal()
        try:
            paciente = db.query(Paciente).filter(Paciente.telegram_id == telegram_id).first()
            if not paciente:
                context.user_data['state'] = 'awaiting_patient_data'
                context.user_data['field_index'] = 0
                return await update.message.reply_text(
                    "Por favor, ingresa tu nombre completo:",
                    reply_markup=ReplyKeyboardRemove()
                )
            # Si ya existe, mostrar y dar opción de modificar
            context.user_data['paciente_id'] = paciente.id
            context.user_data['modificar_paciente'] = True
            return await update.message.reply_text(
                f"👤 <b>Mis datos</b>\n"
                f"Nombre: {paciente.nombre}\n"
                f"Edad: {paciente.edad}\n"
                f"Sexo: {paciente.sexo}\n"
                f"Diagnóstico: {paciente.diagnostico}\n"
                "¿Deseas modificar tus datos?",
                parse_mode=ParseMode.HTML,
                reply_markup=ReplyKeyboardMarkup(
                    [["Sí", "No"]], resize_keyboard=True, one_time_keyboard=True
                )
            )
        finally:
            db.close()
        return

    # Si el usuario responde a la pregunta de modificar datos
    if state is None and context.user_data.get('modificar_paciente'):
        if text.lower() == "no":
            context.user_data.pop('modificar_paciente', None)
            return await show_main_menu(update, context)
        elif text.lower() == "sí":
            context.user_data['state'] = 'awaiting_patient_data'
            context.user_data['field_index'] = 0
            context.user_data.pop('modificar_paciente', None)
            return await update.message.reply_text(
                "Por favor, ingresa tu nombre completo:",
                reply_markup=ReplyKeyboardRemove()
            )
        else:
            return await update.message.reply_text(
                "Por favor, responde 'Sí' o 'No'.",
                reply_markup=ReplyKeyboardMarkup(
                    [["Sí", "No"]], resize_keyboard=True, one_time_keyboard=True
                )
            )

    # Flujo de registro de paciente
    if state == 'awaiting_patient_data':
        idx = context.user_data['field_index']
        field = FIELDS[idx]
        val = text
        if field == 'edad':
            try:
                v = int(val)
                if v < 1 or v > 120:
                    raise ValueError
                context.user_data['edad'] = v
            except Exception:
                return await update.message.reply_text(
                    "❌ Edad inválida. Ingresa un número entre 1 y 120:"
                )
        elif field == 'sexo':
            mapa = {
                'masculino': 'Masculino',
                'femenino': 'Femenino',
                'otro': 'Otro',
                'm': 'M',
                'f': 'F',
                'o': 'O'
            }
            val_normalizado = mapa.get(val.lower())
            if not val_normalizado:
                return await update.message.reply_text(
                    "Selecciona una opción válida:",
                    reply_markup=ReplyKeyboardMarkup(
                        GENDER_BUTTONS, resize_keyboard=True, one_time_keyboard=True
                    )
                )
            context.user_data['sexo'] = val_normalizado
        else:
            context.user_data[field] = val
        idx += 1
        if idx < len(FIELDS):
            context.user_data['field_index'] = idx
            prompts = {
                'nombre': "Ingresa tu edad:",
                'sexo': "Ingresa tu diagnóstico médico:",
                'diagnostico': "Ingresa el ID de tu dispositivo (código de la pegatina):"
            }
            if field == 'edad':
                return await update.message.reply_text(
                    "Selecciona tu sexo:",
                    reply_markup=ReplyKeyboardMarkup(
                        GENDER_BUTTONS, resize_keyboard=True, one_time_keyboard=True
                    )
                )
            return await update.message.reply_text(prompts[field])
        # Todos los datos ingresados, guardar en BD
        db: Session = SessionLocal()
        try:
            telegram_id = str(update.effective_user.id)
            # 1) Buscamos si ya existe
            paciente = db.query(Paciente).filter(Paciente.telegram_id == telegram_id).first()
            if paciente:
                # 2a) Si existe, actualizamos campos
                paciente.device_id = context.user_data['device_id']
                paciente.nombre    = context.user_data['nombre']
                paciente.edad      = context.user_data['edad']
                paciente.sexo      = context.user_data['sexo']
                paciente.diagnostico = context.user_data['diagnostico']
                mensaje = "✅ Datos actualizados con éxito."
            else:
                # 2b) Si no existe, creamos uno nuevo
                paciente = Paciente(
                    telegram_id=telegram_id,
                    device_id=context.user_data['device_id'],
                    nombre=context.user_data['nombre'],
                    edad=context.user_data['edad'],
                    sexo=context.user_data['sexo'],
                    diagnostico=context.user_data['diagnostico']
                )
                db.add(paciente)
                mensaje = "✅ Registro completado con éxito."

            # 3) Commit y refresco
            db.commit()
            db.refresh(paciente)
            context.user_data['paciente_id'] = paciente.id

            await update.message.reply_text(mensaje)
        except Exception as e:
            logging.error(e)
            await update.message.reply_text("❌ Error al guardar. Intenta de nuevo.")
        finally:
            db.close()
            await show_main_menu(update, context)
        return

    # --- FLUJO: Configuración de Sesión ---
    if choice == "1" and state is None:
        db: Session = SessionLocal()
        paciente = db.query(Paciente).filter(Paciente.telegram_id == str(update.effective_user.id)).first()
        db.close()
        if not paciente:
            return await update.message.reply_text(
                "❌ Primero debes registrar tus datos usando la opción 'Mis datos'."
            )
        context.user_data['state'] = 'awaiting_session_config'
        await update.message.reply_text(
            "Elige la duración de la sesión:",
            reply_markup=ReplyKeyboardMarkup(SESSION_BUTTONS, resize_keyboard=True, one_time_keyboard=True)
        )
        return

    if state == 'awaiting_session_config':
        choice_num = extract_choice(choice)
        if choice_num not in SESSION_MENU:
            return await update.message.reply_text("❌ Opción no válida. Por favor, elige una del menú.")

        # Mapeo de opciones a segundos
        duration_map = {"1": 600, "2": 1800, "3": 3600}
        
        if choice_num == "4":
            return await update.message.reply_text("La duración personalizada aún no está implementada.")
        
        intervalo_segundos = duration_map[choice_num]
        db: Session = SessionLocal()
        try:
            # Obtener el device_id del paciente
            telegram_id = str(update.effective_user.id)
            paciente = db.query(Paciente).filter(Paciente.telegram_id == telegram_id).first()
            if not paciente:
                await update.message.reply_text("Error: no se encontraron datos de paciente.")
                context.user_data['state'] = None
                await show_main_menu(update, context)
                return
            device_id = paciente.device_id

            # Crear una nueva sesión con UUID autogenerado
            sesion = Sesion(intervalo_segundos=intervalo_segundos, modo="monitor_activo")
            db.add(sesion)
            db.commit()
            db.refresh(sesion)
            session_id = str(sesion.id)

            # --- Lógica de Redis ---
            if r:
                redis_key = f"shpd-session:{session_id}"
        
                session_data = {
                    "start_ts": int(time.time()),
                    "intervalo_segundos": sesion.intervalo_segundos,
                }
                r.hset(redis_key, mapping=session_data)
                logging.info(f"Sesión {session_id} guardada en Redis.")
                
                redis_shpd_key = f"shpd-data:{device_id}"
                shpd_data = {
                    "session_id": session_id,
                }
                r.hset(redis_shpd_key, mapping=shpd_data)
                logging.info(f"Shpd-data {device_id} guardada en Redis.")
            else:
                logging.error("No se pudo guardar la sesión en Redis.")

            # Devuelve la URL con el session_id y el device_id al usuario en un mensaje aparte, interactivo
            url = f"http://172.18.0.2:30080/?session_id={session_id}&device_id={device_id}"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎥 Ver monitoreo en vivo", url=url)]
            ])
            await update.message.reply_text(
                f"✅ <b>Sesión configurada</b>\n"
                f"<b>Duración:</b> {SESSION_MENU[choice_num]}\n"
                f"<b>Dispositivo:</b> <code>{device_id}</code>\n\n"
                f"Puedes abrir el monitoreo tocando el botón o copiar la URL:\n{url}",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception as e:
            logging.error(f"Error configurando sesión: {e}")
            await update.message.reply_text("❌ Ocurrió un error al configurar la sesión.")
        finally:
            db.close()
            context.user_data['state'] = None
            await show_main_menu(update, context)
        return

    # Resto de opciones: 2,3,5,6,7 … (mantener lógica existente)
    if choice in MAIN_MENU and choice not in ("1", "4"):
        # ...) Aquí iría la lógica para las demás opciones, idéntica al código previo
        await update.message.reply_text("Esta opción aún no está implementada.")
        return await show_main_menu(update, context)

    # Si no coincide con ningún flujo activo, mostrar menú
    if not state:
        await show_main_menu(update, context)

if __name__ == "__main__":
    app = ApplicationBuilder()\
        .token(os.getenv("TELEGRAM_TOKEN", "7796011838:AAGFuQRg2OdEhYT-Cqvg_mGRIOeKWkYNSic"))\
        .build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(patient_details, pattern=r"^patient:\d+$"))
    app.add_handler(CallbackQueryHandler(list_patients_callback, pattern=r"^list_patients$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()
