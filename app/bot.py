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

# --- Configuración logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# --- OpenAI ---
API_KEY = os.getenv("OPENAI_API_KEY", "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")
client = OpenAI(api_key=API_KEY)
MODEL = "gpt-4o-mini"
SYSTEM_PROMPT = (
    "Eres un experto en biomecánica de calistenia mediante visión por computador. "
    "Interpreta 0% como ejecución totalmente deficiente y 100% como ejecución perfecta a nivel propioceptivo. "
    "Ten en cuenta siempre la mejor como referencia para indicar en la observacion"
    "Si la imagen no corresponde con la técnica solicitada, responde únicamente:\n"
    "Imagen incorrecta para el ejercicio {exercise}. Por favor, envía la imagen correcta.\n"
    "De lo contrario, responde exclusivamente con:\n"
    "Propiocepción general: xx%\n"
    "Observación: breve indicando de qué lado está mal y por qué."
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
    ["5. 🏋️ Rutina gratuita",                "6. 🔄 Volver al menú"],
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

def extract_choice(text: str) -> str:
    """Extrae el dígito antes del punto o devuelve el texto si no hay formato 'n.'."""
    if "." in text:
        return text.split(".")[0]
    return text

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # preservar flags de propiocepción
    attempts = context.user_data.get("attempts_proprio")
    done = context.user_data.get("proprio_done")
    context.user_data.clear()
    if attempts:
        context.user_data["attempts_proprio"] = attempts
    if done:
        context.user_data["proprio_done"] = done

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
    lower = text.lower()
    state = context.user_data.get("state")

    # /start o saludo
    if lower in ("hola", "hola!"):
        return await show_main_menu(update, context)

    # submenú propiocepción
    if state == "awaiting_prop_option":
        choice = extract_choice(text)
        if choice not in PROP_MENU:
            return await update.message.reply_text(
                "❌ Debes elegir 1 o 2.",
                reply_markup=ReplyKeyboardMarkup(PROP_BUTTONS, resize_keyboard=True, one_time_keyboard=True),
            )
        if choice == "1":
            # prueba gratuita: seleccionar técnica
            if context.user_data.get("proprio_done"):
                await update.message.reply_text(
                    "❌ Ya usaste tu prueba gratuita.",
                    reply_markup=ReplyKeyboardRemove(),
                )
                return await show_main_menu(update, context)
                
            await update.message.reply_text(
                "Elige la técnica a evaluar:",
                reply_markup=ReplyKeyboardMarkup(EX_BUTTONS, resize_keyboard=True, one_time_keyboard=True),
            )
            context.user_data["state"] = "awaiting_exercise"
        else:
            # costos y pago con inline keyboard
            pay_btn = InlineKeyboardMarkup([[
                InlineKeyboardButton("💳 Pagar ahora", url="https://pago.nexuscalistenia.com")
            ]])
            await update.message.reply_text(
                "<b>Costos y pagar</b>\nServicio completo: $50 USD por análisis detallado.",
                parse_mode=ParseMode.HTML,
                reply_markup=pay_btn,
            )
            # limpiar teclado y volver
            await update.message.reply_text("", reply_markup=ReplyKeyboardRemove())
            return await show_main_menu(update, context)
        return

    # selección de técnica tras prueba gratuita
    if state == "awaiting_exercise":
        choice = extract_choice(text)
        if choice not in EXERCISES:
            return await update.message.reply_text(
                "❌ Elige un número del 1 al 6 para la técnica.",
                reply_markup=ReplyKeyboardMarkup(EX_BUTTONS, resize_keyboard=True, one_time_keyboard=True),
            )
        context.user_data["exercise"] = EXERCISES[choice]
        await update.message.reply_text(
            f"Envía una foto practicando <b>{EXERCISES[choice]}</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data["state"] = "awaiting_proprio_photo"
        return

    # esperando lado anatómico
    if state == "awaiting_side":
        side = text.lower()
        if side not in ("izquierdo", "derecho"):
            return await update.message.reply_text("❌ Responde ‘izquierdo’ o ‘derecho’.")
        context.user_data["side"] = side
        context.user_data["state"] = None
        await analyze_proprioception(update, context)
        return await show_main_menu(update, context)
    # flujo principal del menú
    choice = extract_choice(text)
    if choice not in MAIN_MENU:
        return await update.message.reply_text(
            "❌ Opción no válida. Toca un botón.",
            reply_markup=ReplyKeyboardMarkup(MENU_BUTTONS, resize_keyboard=True, one_time_keyboard=True),
        )

    # opción 2: flujo propiocepción, un intento
    if choice == "2":
        await update.message.reply_text(
            "Contratar propiocepción:",
            reply_markup=ReplyKeyboardMarkup(PROP_BUTTONS, resize_keyboard=True, one_time_keyboard=True),
        )
        context.user_data["state"] = "awaiting_prop_option"
        return

    # límites por acción
    key = f"attempts_{choice}"
    if context.user_data.get(key):
        return await update.message.reply_text("❌ Solo un intento por acción.")
    context.user_data[key] = True

    # demás opciones
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
            "<b>¿Qué es la propiocepción?</b>\n"
            "Es la percepción interna de la posición y movimiento de tu cuerpo.\n"
            "Ejemplo: sentir la alineación de tu pelvis en un handstand.",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )
        return await show_main_menu(update, context)

    if choice == "4":
        await update.message.reply_text(
            "<b>¿Quiénes somos?</b>\n"
            "Nexus Calistenia: tu coach digital de propiocepción y rutinas personalizadas.",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )
        return await show_main_menu(update, context)

    if choice == "5":
        await update.message.reply_text(
            "<b>Rutina gratuita</b>\n"
            "1) Warm\-up (5′)\n"
            "2) Push\-ups 3×10\n"
            "3) Squats 3×15\n"
            "4) Plank 3×30″\n"
            "5) Stretching (5′)",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=ReplyKeyboardRemove(),
        )
        return await show_main_menu(update, context)

    # volver al menú
    return await show_main_menu(update, context)

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # proteger reenvío tras análisis
    if context.user_data.get("proprio_done"):
        return await update.message.reply_text("Ya realizamos el análisis.")
    if context.user_data.get("state") != "awaiting_proprio_photo":
        return await update.message.reply_text("Primero elige Prueba gratuita y técnica.")
    # descarga y redimensiona
    photo = update.message.photo[-1]
    img_file = await photo.get_file()
    img_bytes = await img_file.download_as_bytearray()
    img = Image.open(BytesIO(img_bytes))
    if img.width > 512:
        nh = int(img.height * 512 / img.width)
        img = img.resize((512, nh), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    resized = buf.getvalue()
    context.user_data["b64_image"] = base64.b64encode(resized).decode()

    # preguntar lado
    await update.message.reply_text("¿Cuál es tu lado derecho anatómico? (izquierdo/derecho)")
    context.user_data["state"] = "awaiting_side"

async def analyze_proprioception(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exercise = context.user_data["exercise"]
    side = context.user_data["side"]
    b64 = context.user_data["b64_image"]
    user_prompt = (
        f"Técnica: {exercise}.\n"
        f"Analiza mi propiocepción general para {exercise}. "
        f"Considera que mi lado derecho anatómico en la foto es “{side}”."
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
        max_output_tokens=150,
        temperature=0.0
    )
    await update.message.reply_text(resp.output_text)
    context.user_data["proprio_done"] = True
    # limpiar teclado y volver
    await update.message.reply_text("", reply_markup=ReplyKeyboardRemove())
    await show_main_menu(update, context)

if __name__ == "__main__":
    app = ApplicationBuilder()\
        .token(os.getenv("TELEGRAM_TOKEN", "7600712992:AAGKYF0lCw7h7B-ROthuOKlb90QZM20MZis"))\
        .build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))

    app.run_polling()
