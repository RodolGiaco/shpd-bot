import os
import logging
import base64
from io import BytesIO
from PIL import Image
from openai import OpenAI
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
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler

# --- Configuración logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


RESIZE_IMAGES = os.getenv("RESIZE_IMAGES", "false").lower() in ("1", "true", "yes")
MAX_IMAGE_WIDTH = int(os.getenv("MAX_IMAGE_WIDTH", "512"))

# --- OpenAI ---
API_KEY = os.getenv("OPENAI_API_KEY", "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")
client = OpenAI(api_key=API_KEY)
MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = (
    "Actúa como un experto en biomecanica corporal especializado en propiocepción aplicada a técnicas de calistenia. \n"
    "Evalúa la propiocepción de cada lado de 0% (muy mala propiocepción) a 100% (propiocepción perfecta). \n"
    "La imagen siempre sera sacada con la camara frontal y no sera una selfie lo cual no invierte los lados anatomicos"
    "Unicamente inviertes los lados anatomicos si la persona esta de espalda caso contrario la derecha anatomica es la derecha de la imagen"
    "Responde SIEMPRE siguiendo estrictamente este formato no superando los 300 token:\n\n"
    "Análisis:\n"
    "- Lado derecho anatómico: [descripción breve, máximo 2 líneas]\n"
    "- Lado izquierdo anatómico: [descripción breve, máximo 2 líneas]\n\n"
    "Propiocepción:\n"
    "- Lado derecho anatómico: [porcentaje]%\n"
    "- Lado izquierdo anatómico: [porcentaje]%\n\n"
    "Problema detectado:\n"
    "- [explicación técnica breve en orden de prioridad de acuerdo a cintura escapular, caderas, hombros, otro problema, máximo 2 líneas]\n\n"
    "No agregues nada fuera de este esquema. Sé conciso, evita extender las descripciones más de lo indicado."
)

USER_PROMPT = (
    "Analyze the provided image of a person performing a calisthenic technique . Perform the following tasks:\n"
    "- Determine which side of the body is the person’s left and which is right using visual cues.\n"
    "- Describe the calisthenic exercise being performed, focusing on anatomical and proprioceptive details.\n"
    "- Comment on the person’s posture: note shoulder alignment, hip alignment, knee alignment, limb angles, any torso inclinations or rotations, and the person’s balance and stability.\n\n"
)
# --- Menús y botones ---
MAIN_MENU = {
    "1": "Contratar servicio personalizado",
    "2": "Contratar servicio de propiocepción",
    "3": "¿Qué es la propiocepción?",
    "4": "¿Quiénes somos?",
    "5": "Rutina de calistenia gratuita",
    "6": "Volver al menú",
}
MENU_BUTTONS = [
    ["1. 📋 Contratar servicio personalizado", "2. 🤸‍♂️ Contratar servicio de propiocepción"],
    ["3. ❓ ¿Qué es la propiocepción?",       "4. ℹ️ ¿Quiénes somos?"],
    ["5. 🏋️ Quiero mi Rutina!",                "6. 🔄 Volver al menú"],
]
PROP_MENU = {
    "1": "Prueba gratuita",
    "2": "Costos y pagar",
}
PROP_BUTTONS = [["1. Prueba gratuita", "2. Costos y pagar"]]
EXERCISES = {
    "1": "Handstand",
    "2": "Full Planche",
    "3": "Front Lever",
    "4": "Muscle Up",
    "5": "Dominadas",
    "6": "Flexiones",
}
EX_BUTTONS = [
    ["1. Handstand", "2. Full Planche"],
    ["3. Front Lever", "4. Muscle Up"],
    ["5. Dominadas",   "6. Flexiones"],
]
ROUTINE_MENU = [
    [
        InlineKeyboardButton("🏷️ Gratis", callback_data="free_routine"),
        InlineKeyboardButton("💎 Paga",  callback_data="paid_routine")
    ]
]


def extract_choice(text: str) -> str:
    """Extrae el dígito antes del punto o devuelve el texto si no hay formato 'n.'."""
    return text.split(".")[0] if "." in text else text

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Uso de context.chat_data para contar menús mostrados por chat
    count = context.chat_data.get("menu_count", 0) + 1
    context.chat_data["menu_count"] = count
    logging.info(f"Menú principal mostrado {count} veces en chat {update.effective_chat.id}")

    # Preservar datos de propiocepción (user_data)
    attempts = context.user_data.get("attempts_proprio")
    done = context.user_data.get("proprio_done")
    context.user_data.clear()
    if attempts:
        context.user_data["attempts_proprio"] = attempts
    if done:
        context.user_data["proprio_done"] = done

    # Mostrar menú
    await update.message.reply_text(
        "👋 <b>Bienvenido a Nexus</b>\nElige una opción:",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardMarkup(
            MENU_BUTTONS, resize_keyboard=True, one_time_keyboard=True
        ),
    )
    context.user_data["state"] = None

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

    # Flujo submenú propiocepción
    if state == "awaiting_prop_option":
        if choice not in PROP_MENU:
            return await update.message.reply_text(
                "❌ Debes elegir 1 o 2.",
                reply_markup=ReplyKeyboardMarkup(
                    PROP_BUTTONS, resize_keyboard=True, one_time_keyboard=True
                ),
            )
        if choice == "1":
            # Prueba gratuita: verificar intento y elegir técnica
            if context.user_data.get("proprio_done"):
                await update.message.reply_text(
                    "❌ Ya usaste tu prueba gratuita.",
                    reply_markup=ReplyKeyboardRemove(),
                )
                return await show_main_menu(update, context)
            await update.message.reply_text(
                "Elige la técnica a evaluar:",
                reply_markup=ReplyKeyboardMarkup(
                    EX_BUTTONS, resize_keyboard=True, one_time_keyboard=True
                ),
            )
            context.user_data["state"] = "awaiting_exercise"
        else:
            # Costos y pago
            pay_btn = InlineKeyboardMarkup([[
                InlineKeyboardButton("💳 Pagar ahora", url="https://pago.nexuscalistenia.com")
            ]])
            await update.message.reply_text(
                "<b>Costos y pagar</b>\nServicio completo: $5000 pesos por mes hasta 8 consultas por dia.",
                parse_mode=ParseMode.HTML,
                reply_markup=pay_btn,
            )
            #await update.message.reply_text("", reply_markup=ReplyKeyboardRemove())
            return await show_main_menu(update, context)
        return

    # Selección de técnica tras prueba gratuita
    if state == "awaiting_exercise":
        if choice not in EXERCISES:
            return await update.message.reply_text(
                "❌ Elige un número del 1 al 6 para la técnica.",
                reply_markup=ReplyKeyboardMarkup(
                    EX_BUTTONS, resize_keyboard=True, one_time_keyboard=True
                ),
            )
        context.user_data["exercise"] = EXERCISES[choice]
        await update.message.reply_text(
            f"Envía una foto practicando <b>{EXERCISES[choice]}</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data["state"] = "awaiting_proprio_photo"
        return

        
    # Flujo principal del menú
    if choice not in MAIN_MENU:
        return await update.message.reply_text(
            "❌ Opción no válida. Toca un botón.",
            reply_markup=ReplyKeyboardMarkup(
                MENU_BUTTONS, resize_keyboard=True, one_time_keyboard=True
            ),
        )

    # Opciones principales
    if choice == "2":
        # iniciar propiocepción (un intento)
        await update.message.reply_text(
            "Contratar propiocepción:",
            reply_markup=ReplyKeyboardMarkup(
                PROP_BUTTONS, resize_keyboard=True, one_time_keyboard=True
            ),
        )
        context.user_data["state"] = "awaiting_prop_option"
        return

    key = f"attempts_{choice}"
    if context.user_data.get(key):
        return await update.message.reply_text("❌ Solo un intento por acción.")
    context.user_data[key] = True

    if choice == "1":
        await update.message.reply_text(
            "<b>Servicio personalizado</b>\n"
            "• 4 sesiones semanales\n"
            "• Seguimiento vía Telegram\n"
            "• Ajustes mensuales\n\n"
            "<i>Contacto: contacto@nexuscalistenia.com</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )
        return await show_main_menu(update, context)

    if choice == "3":
        await update.message.reply_text(
            "<b>🤸‍♂️ ¿Qué es la propiocepción?</b>\n\n"
            "🔹 Es la capacidad de sentir y controlar la posición y el movimiento de tu cuerpo, sin necesidad de mirar.\n"
            "🔹 Permite mantener el equilibrio, la alineación y la técnica en cada ejercicio.\n\n"
            "💪 En calistenia, una buena propiocepción mejora el control corporal, acelera el progreso y previene lesiones.\n\n"
            "📍 Ejemplo práctico: sentir y corregir la alineación de tu pelvis durante un handstand.",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )
        return await show_main_menu(update, context)

    if choice == "4":
        # Enviar el logo o imagen
        with open("nexus/logo-blanco.webp", "rb") as logo:
            await update.message.reply_sticker(sticker=logo)

        # Enviar el mensaje descriptivo
        await update.message.reply_text(
            "<b>🏋️‍♂️ ¿Quiénes somos?</b>\n\n"
            "✨ Nexus es el punto de conexión entre <b>el cuerpo y la mente</b>, donde el movimiento se vuelve consciente y el entrenamiento, una experiencia de autoconocimiento.\n\n"
            "💡 Creemos en la fuerza con propósito, en entender el cuerpo desde adentro, en la <b>propiocepción</b> como clave para moverte mejor, sin límites.\n\n"
            "🤝 No se trata solo de entrenar, sino de sentir, conectar y potenciar cada movimiento con inteligencia.\n\n"
            "🚀 <b>En Nexus el desafío es descubrir de qué estás hecho y hasta dónde podés llegar.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )
        return await show_main_menu(update, context)

    elif choice == "5":
        # Limpia teclado y lanza submenú inline
        await update.message.reply_text(
            "<b>Selecciona tu rutina:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(ROUTINE_MENU)
        )
        return
    


    # opción 6 o retorno
    return await show_main_menu(update, context)

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("proprio_done"):
        return await update.message.reply_text("Ya realizamos el análisis.")
    if context.user_data.get("state") != "awaiting_proprio_photo":
        return await update.message.reply_text("Primero elige Prueba gratuita y técnica.")

    photo = update.message.photo[-1]
    img_file = await photo.get_file()
    img_bytes = await img_file.download_as_bytearray()
    img = Image.open(BytesIO(img_bytes))

    # ——— redimensión opcional ———
    if RESIZE_IMAGES:
        if img.width > MAX_IMAGE_WIDTH:
            nh = int(img.height * MAX_IMAGE_WIDTH / img.width)
            img = img.resize((MAX_IMAGE_WIDTH, nh), Image.LANCZOS)
            logging.info(f"Imagen redimensionada a {img.size}")
    else:
        logging.info("Redimensionamiento desactivado, usando tamaño original")

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=100)
    context.user_data["b64_image"] = base64.b64encode(buf.getvalue()).decode()
    await update.message.reply_text("Envia una imagen tomada con la camara frontal (Selfie ❌!!))")


async def analyze_proprioception(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exercise = context.user_data["exercise"]
    side = context.user_data["side"]
    b64 = context.user_data["b64_image"]
    user_prompt = (
            f"Analiza la imagen enviada con la tecnica {exercise} a nivel escapular y alineacion de cadera. \n"
            f"Indica qué lado anatómico tiene peor propiocepción, cuánto porcentaje de propiocepción tiene cada lado, \n"
            f"Evalua si esta de espalda la persona para detectar que lado es el correcto."
        )
    resp = client.responses.create(
        model=MODEL,
        user=str(update.effective_user.id),
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": [
                {"type": "input_text",  "text": user_prompt},
                {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"}
            ]}
        ],
        max_output_tokens=200,
        temperature=0.0
    )
    # 1. Obtén la cadena cruda
    raw = resp.output_text

    # 2. Dale formato amigable
    formatted = format_proprioception_response(raw)

    # 3. Muestra al usuario con HTML y limpia el teclado
    await update.message.reply_text(
        formatted,
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data["proprio_done"] = True
    #await update.message.reply_text("", reply_markup=ReplyKeyboardRemove())
    #await show_main_menu(update, context)


async def free_routine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        text=(
            "<b>Rutina Gratuita 🆓</b>\n\n"
            "1️⃣ <b>Calentamiento (×2):</b>\n"
            "   • Shoulder Rotations\n"
            "   • Elbow Rotations\n"
            "   • Arm Swings\n"
            "   • Wrist Rotations\n"
            "   • Band Shoulder Dislocates\n\n"
            "2️⃣ <b>Movilidad Dinámica:</b>\n"
            "   • 15\" Hollow Body\n"
            "   • 10\" Forearm Plank\n"
            "   • Shoulder Taps ×8\n"
            "   • Scapular Push-Ups ×8\n"
            "   • Reverse Snow Angels ×5\n\n"
            "3️⃣ <b>Básicos Específicos (×3):</b>\n"
            "   • Planche Lean 20\" \n"
            "   • Tuck Back Lever 10\"\n"
            "   • Skin the Cat ×5\n\n"
            "4️⃣ <b>Básicos (×3):</b>\n"
            "   • Pull-Ups ×8\n"
            "   • Push-Ups ×12\n"
            "   • Dips ×10\n"
            "   • Air Squats ×15\n\n"
            "5️⃣ <b>Enfriamiento:</b>\n"
            "   • Chest Stretch 30\" por lado\n"
            "   • Child’s Pose 30\"\n"
            "   • Shoulder Cross-Body 30\" por lado\n"
            "   • Butterfly Stretch 30\"\n\n"
            "¡Disfruta tu entrenamiento! 💪"
        ),
        parse_mode=ParseMode.HTML
    )
    # vuelve al menú principal tras unos segundos
    await show_main_menu(update, context)

async def paid_routine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Acknowledge the callback to remove the “loading” state
    await update.callback_query.answer()
    # Construimos un InlineKeyboard con la tarjeta y enlace de pago
    pay_btn = InlineKeyboardMarkup([[
        InlineKeyboardButton("💳 Pagar servicio de propiocepción", url="https://pago.nexuscalistenia.com")
    ]])
    # Editamos el mensaje original para mostrar solo el botón de pago
    await update.callback_query.edit_message_text(
        text=(
            "<b>Servicio de propiocepción Premium</b>\n\n"
            "Haz clic en el botón para proceder al pago y activar tu análisis personalizado."
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=pay_btn
    )
def format_proprioception_response(raw: str) -> str:
    """
    Convierte la respuesta cruda de OpenAI en un mensaje
    con emojis, negritas y viñetas para Telegram.
    """
    lines = raw.splitlines()
    sections = {"Análisis": [], "Propiocepción": [], "Problema detectado": []}
    current = None

    for line in lines:
        if line.startswith("Análisis"):
            current = "Análisis";  continue
        if line.startswith("Propiocepción"):
            current = "Propiocepción";  continue
        if line.startswith("Problema detectado"):
            current = "Problema detectado";  continue
        if current and line.strip().startswith("-"):
            sections[current].append(line.lstrip("- ").strip())

    parts = []
    if sections["Análisis"]:
        parts.append("🔎 <b>Análisis</b>")
        parts += [f"• {item}" for item in sections["Análisis"]]
    if sections["Propiocepción"]:
        parts.append("\n🧠 <b>Propiocepción</b>")
        parts += [f"• {item}" for item in sections["Propiocepción"]]
    if sections["Problema detectado"]:
        parts.append("\n⚠️ <b>Problema Detectado</b>")
        parts += [f"• {item}" for item in sections["Problema detectado"]]

    parts.append("\nSi tienes dudas, ¡escríbeme! 😊")
    return "\n".join(parts)


if __name__ == "__main__":
    app = ApplicationBuilder()\
        .token(os.getenv("TELEGRAM_TOKEN", "7600712992:AAGKYF0lCw7h7B-ROthuOKlb90QZM20MZis"))\
        .build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    # Al construir el bot:
    app.add_handler(CallbackQueryHandler(free_routine, pattern="^free_routine$"))
    app.add_handler(CallbackQueryHandler(paid_routine, pattern="^paid_routine$"))


    app.run_polling()
