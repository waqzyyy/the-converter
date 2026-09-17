import asyncio
import logging
import os
from io import BytesIO

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile, Message
from PIL import Image, ImageDraw, ImageFont, ImageOps


TOKEN = "ВСТАВЬ_СЮДА_ТОКЕН_БОТА"

ASCII_WIDTH = 180
FONT_SIZE = 16
MAX_FILE_SIZE = 15 * 1024 * 1024
MAX_PIXELS = 25_000_000

CHARS = "@%&#*+=-:. "
WATERMARK = "ВСТАВЬ_СЮДА_ВОДЯНОЙ_ЗНАК"

dp = Dispatcher()
semaphore = asyncio.Semaphore(2)


def get_font():
    windows = os.environ.get("WINDIR", r"C:\Windows")

    fonts = [
        os.path.join(windows, "Fonts", "consola.ttf"),
        os.path.join(windows, "Fonts", "cour.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "DejaVuSansMono.ttf",
    ]

    for path in fonts:
        try:
            return ImageFont.truetype(path, FONT_SIZE)
        except OSError:
            pass

    return ImageFont.load_default()


def create_ascii_image(data: bytes) -> bytes:
    font = get_font()

    character_width = max(1, round(font.getlength("M")))
    ascent, descent = font.getmetrics()
    character_height = ascent + descent

    with Image.open(BytesIO(data)) as original:
        if original.width * original.height > MAX_PIXELS:
            raise ValueError("Слишком большое изображение")

        image = ImageOps.exif_transpose(original).convert("RGBA")

        white_background = Image.new("RGBA", image.size, "white")
        image = Image.alpha_composite(
            white_background,
            image,
        ).convert("L")

        columns = max(40, min(300, ASCII_WIDTH))

        rows = round(
            image.height
            / image.width
            * columns
            * character_width
            / character_height
        )

        rows = max(1, min(350, rows))

        image = image.resize(
            (columns, rows),
            Image.Resampling.LANCZOS,
        )

        image = ImageOps.autocontrast(image, cutoff=1)
        pixels = list(image.getdata())

    lines = []

    for start in range(0, len(pixels), columns):
        line_pixels = pixels[start:start + columns]

        line = "".join(
            CHARS[
                pixel * (len(CHARS) - 1) // 255
            ]
            for pixel in line_pixels
        )

        lines.append(line)

    padding = 20

    watermark_width = round(font.getlength(WATERMARK))
    footer_height = character_height + padding

    picture_width = max(
        columns * character_width + padding * 2,
        watermark_width + padding * 2,
    )

    picture_height = (
        rows * character_height
        + padding * 2
        + footer_height
    )

    canvas = Image.new(
        "RGB",
        (picture_width, picture_height),
        "white",
    )

    draw = ImageDraw.Draw(canvas)

    for number, line in enumerate(lines):
        draw.text(
            (
                padding,
                padding + number * character_height,
            ),
            line,
            font=font,
            fill="black",
            anchor="lt",
        )

    draw.text(
        (
            picture_width - padding,
            picture_height - padding,
        ),
        WATERMARK,
        font=font,
        fill="black",
        anchor="rb",
    )

    result = BytesIO()
    canvas.save(result, format="PNG")

    return result.getvalue()


def prepare_photo(png_data: bytes) -> bytes:
    with Image.open(BytesIO(png_data)) as image:
        image = image.convert("RGB")
        image.thumbnail((2560, 2560), Image.Resampling.LANCZOS)

        width, height = image.size

        min_width = (height + 9) // 10
        min_height = (width + 9) // 10

        new_width = max(width, min_width)
        new_height = max(height, min_height)

        if new_width != width or new_height != height:
            canvas = Image.new(
                "RGB",
                (new_width, new_height),
                "white",
            )

            canvas.paste(
                image,
                (
                    (new_width - width) // 2,
                    (new_height - height) // 2,
                ),
            )

            image = canvas

        result = BytesIO()
        image.save(
            result,
            format="JPEG",
            quality=95,
            subsampling=0,
        )

        return result.getvalue()


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "Отправь фотографию, и я превращу её "
        "в рисунок из символов."
    )


@dp.message(F.photo | F.document)
async def image_handler(message: Message, bot: Bot):
    if message.photo:
        file = message.photo[-1]
    else:
        file = message.document

        if file is None:
            return

        if not (file.mime_type or "").startswith("image/"):
            await message.answer(
                "Отправь изображение в формате JPG, PNG или WEBP."
            )
            return

    if file.file_size and file.file_size > MAX_FILE_SIZE:
        await message.answer(
            "Файл слишком большой. Максимальный размер — 15 МБ."
        )
        return

    status = await message.answer("Обрабатываю фотографию...")

    try:
        async with semaphore:
            source = BytesIO()
            await bot.download(file, destination=source)

            data = source.getvalue()

            if len(data) > MAX_FILE_SIZE:
                await status.edit_text(
                    "Файл слишком большой. Максимальный размер — 15 МБ."
                )
                return

            png_data = await asyncio.to_thread(
                create_ascii_image,
                data,
            )

            photo_data = await asyncio.to_thread(
                prepare_photo,
                png_data,
            )

    except Exception as error:
        logging.exception("Ошибка обработки изображения")

        if isinstance(error, (OSError, ValueError)):
            text = (
                "Не получилось обработать изображение. "
                "Попробуй отправить фотографию меньшего размера."
            )
        else:
            text = "Произошла ошибка. Попробуй отправить фото ещё раз."

        await status.edit_text(text)
        return

    await message.answer_photo(
        photo=BufferedInputFile(
            photo_data,
            filename="ascii_by_areabomb.jpg",
        ),
        caption="Готово.",
    )

    await status.delete()


@dp.message()
async def other_handler(message: Message):
    await message.answer(
        "Отправь фотографию, чтобы получить рисунок из символов."
    )


async def main():
    if not TOKEN or TOKEN == "ВСТАВЬ_СЮДА_ТОКЕН_БОТА":
        print("Вставь токен бота в переменную TOKEN.")
        return

    logging.basicConfig(level=logging.INFO)

    async with Bot(token=TOKEN) as bot:
        await bot.delete_webhook(drop_pending_updates=True)

        print("Бот запущен.")
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
