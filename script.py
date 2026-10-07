import datetime
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse

import yaml
from yaml.loader import SafeLoader
from jinja2 import Environment, FileSystemLoader

try:
    from PIL import Image, ImageOps
except ImportError:
    raise SystemExit(
        "ОШИБКА: не установлена библиотека Pillow (нужна для обработки картинок дипломов). "
        "Выполните: pip3 install --user -r requirements.txt"
    )

RU_MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

VIDEOS_PATH = "data/videos.json"
THUMB_DIR = os.path.join("public", "resources", "video-thumbs")
THUMB_URL_PREFIX = "/resources/video-thumbs"
MAXRES_MIN_BYTES = 10000  # a missing maxresdefault.jpg still returns HTTP 200 with a tiny grey placeholder

EDUCATION_PATH = "data/education.yaml"
DOCS_SRC_DIR = "assets/documents"
DOCS_FULL_DIR = os.path.join("public", "resources", "education")
DOCS_FULL_URL_PREFIX = "/resources/education"
DOCS_THUMB_DIR = os.path.join("public", "resources", "education", "thumbs")
DOCS_THUMB_URL_PREFIX = "/resources/education/thumbs"
DOCS_FULL_MAX_SIDE = 1600  # не увеличиваем, только ограничиваем сверху
DOCS_THUMB_MAX_SIDE = 500
DOCS_JPEG_QUALITY = 82

YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "youtube-nocookie.com", "www.youtube-nocookie.com",
}
YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Однобуквенные и короткие предлоги/союзы, после которых ставится неразрывный пробел.
# "со", "обо" и другие составные формы сознательно не считаются за "с"/"о" — совпадение
# по целому слову (\b...\b) само это обеспечивает.
NBSP_WORDS = ["в", "с", "к", "о", "у", "и", "а", "на", "по", "за", "из", "от", "до", "не"]
NBSP_RE = re.compile(r"\b(" + "|".join(NBSP_WORDS) + r")\b[ \t]+", re.IGNORECASE)

# Инициалы вида "И.В." или "А." — неразрывный пробел перед фамилией. Отрицательный
# lookbehind не даёт зацепить хвост обычного слова/аббревиатуры (например "США.").
INITIALS_RE = re.compile(r"(?<![А-Яа-яЁё])((?:[А-ЯЁ]\.){1,3})[ \t]+")

# Число и сокращение "ч" (часы) — неразрывный пробел между ними, например "144 ч".
HOURS_RE = re.compile(r"(?<=\d)[ \t]+(?=ч\b)")

# Первый год из поля "year" таймлайна (например "2021" из "2021–2023") — по нему
# таймлайн сортируется автоматически, независимо от порядка записей в файле.
TIMELINE_YEAR_RE = re.compile(r"\d{4}")


def ru_date(d):
    return f"{d.day} {RU_MONTHS[d.month - 1]} {d.year}"


def apply_nbsp(text):
    """Расставляет неразрывные пробелы в обычном тексте без ручной разметки:
    после инициалов, между числом и "ч", после коротких предлогов/союзов."""
    if not text:
        return text
    text = INITIALS_RE.sub(lambda m: m.group(1) + " ", text)
    text = HOURS_RE.sub(" ", text)
    text = NBSP_RE.sub(lambda m: m.group(1) + " ", text)
    return text


def extract_youtube_id(raw_url):
    url = (raw_url or "").strip()
    if not url:
        return None
    if "//" not in url:
        url = "https://" + url
    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    candidate = None

    if host in ("youtu.be", "www.youtu.be"):
        trimmed = path.strip("/")
        candidate = trimmed.split("/")[0] if trimmed else None
    elif host in YOUTUBE_HOSTS:
        parts = [p for p in path.split("/") if p]
        if parts and parts[0] in ("shorts", "embed", "live") and len(parts) > 1:
            candidate = parts[1]
        elif path in ("/watch", "/watch/"):
            values = parse_qs(parsed.query).get("v")
            candidate = values[0] if values else None

    if candidate and YOUTUBE_ID_RE.match(candidate):
        return candidate
    return None


def is_shorts_url(raw_url):
    return "/shorts/" in (raw_url or "")


def fetch_thumbnail(video_id):
    """Скачивает обложку видео во время сборки. Возвращает URL на сайте или None,
    если скачать не удалось (в этом случае сборка не останавливается)."""
    os.makedirs(THUMB_DIR, exist_ok=True)
    dest = os.path.join(THUMB_DIR, f"{video_id}.jpg")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; site-build-thumbnail-fetch/1.0)"}

    for name in ("maxresdefault", "hqdefault"):
        url = f"https://i.ytimg.com/vi/{video_id}/{name}.jpg"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = resp.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            continue

        if len(data) < 500:
            continue
        if name == "maxresdefault" and len(data) < MAXRES_MIN_BYTES:
            # maxresdefault.jpg не существует для этого видео — YouTube всё равно
            # отвечает 200 с маленькой серой заглушкой, её отбрасываем.
            continue

        with open(dest, "wb") as f:
            f.write(data)
        return f"{THUMB_URL_PREFIX}/{video_id}.jpg"

    return None


def load_videos():
    try:
        with open(VIDEOS_PATH, "r", encoding="utf-8") as f:
            raw_text = f.read()
    except FileNotFoundError:
        raise SystemExit(f"ОШИБКА в {VIDEOS_PATH}: файл не найден.")

    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise SystemExit(
            f"ОШИБКА в {VIDEOS_PATH}: файл повреждён (некорректный JSON) — "
            f"строка {e.lineno}, столбец {e.colno}: {e.msg}. "
            f"Скорее всего, рядом с этим местом пропущена или лишняя запятая либо кавычка."
        )

    if not isinstance(raw, list) or not raw:
        raise SystemExit(
            f"ОШИБКА в {VIDEOS_PATH}: файл должен содержать список видео в квадратных скобках [ ... ], "
            f"и в нём должно быть хотя бы одно видео."
        )

    videos = []
    seen_ids = {}
    featured_ids = []
    for i, item in enumerate(raw, start=1):
        label = f"видео №{i}"
        if not isinstance(item, dict):
            raise SystemExit(f"ОШИБКА в {VIDEOS_PATH}: {label} должно быть объектом в фигурных скобках {{ ... }}.")

        url = item.get("url")
        title = item.get("title")
        note = item.get("note", "")
        featured = bool(item.get("featured", False))

        if not isinstance(url, str) or not url.strip():
            raise SystemExit(f"ОШИБКА в {VIDEOS_PATH}: у {label} не указана ссылка (\"url\").")
        if not isinstance(title, str) or not title.strip():
            raise SystemExit(
                f"ОШИБКА в {VIDEOS_PATH}: у {label} (ссылка: {url}) не указано название (\"title\")."
            )

        video_id = extract_youtube_id(url)
        if not video_id:
            raise SystemExit(
                f"ОШИБКА в {VIDEOS_PATH}: у {label} «{title}» не получилось распознать ссылку на YouTube "
                f"({url}). Проверьте, что это правильная ссылка на видео или Shorts, скопированная из YouTube."
            )
        if video_id in seen_ids:
            raise SystemExit(
                f"ОШИБКА в {VIDEOS_PATH}: одно и то же видео указано дважды — {label} и {seen_ids[video_id]}."
            )
        seen_ids[video_id] = label

        thumb_url = fetch_thumbnail(video_id)
        videos.append({
            "id": video_id,
            "title": apply_nbsp(title.strip()),
            "note": apply_nbsp(note.strip()) if isinstance(note, str) else "",
            "isShorts": is_shorts_url(url),
            "thumb": thumb_url or f"{THUMB_URL_PREFIX}/{video_id}.jpg",
            "thumbOk": thumb_url is not None,
            "order": i - 1,
        })

        if featured:
            featured_ids.append(video_id)

    initial_main_id = featured_ids[0] if featured_ids else videos[0]["id"]

    videos_json = json.dumps(
        {"initialMainId": initial_main_id, "videos": videos},
        ensure_ascii=False,
    ).replace("</", "<\\/")

    return videos_json


def process_document_image(file_name, src_path):
    """Готовит из одной загруженной картинки документа две копии для сайта:
    полноразмерную (для увеличения по клику) и маленькую (для плитки на
    странице «Образование»). Возвращает (url_full, url_thumb). Если картинку
    не получилось прочитать — останавливает сборку понятной ошибкой."""
    try:
        with Image.open(src_path) as img:
            # exif_transpose разворачивает фото по EXIF-ориентации (например,
            # повёрнутый бок к верху скан) — это нужно сделать ДО того, как
            # EXIF будет выброшен.
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            # Удаляем метаданные (EXIF/GPS — геолокация, модель телефона и т.п.):
            # явно вычищаем info и не передаём exif= при сохранении, чтобы
            # приватные данные не попали на сайт ни при каких условиях.
            img.info.pop("exif", None)

            os.makedirs(DOCS_FULL_DIR, exist_ok=True)
            os.makedirs(DOCS_THUMB_DIR, exist_ok=True)

            full = img.copy()
            full.info.pop("exif", None)
            full.thumbnail((DOCS_FULL_MAX_SIDE, DOCS_FULL_MAX_SIDE), Image.LANCZOS)
            full.save(os.path.join(DOCS_FULL_DIR, file_name), "JPEG", quality=DOCS_JPEG_QUALITY)

            thumb = img.copy()
            thumb.info.pop("exif", None)
            thumb.thumbnail((DOCS_THUMB_MAX_SIDE, DOCS_THUMB_MAX_SIDE), Image.LANCZOS)
            thumb.save(os.path.join(DOCS_THUMB_DIR, file_name), "JPEG", quality=DOCS_JPEG_QUALITY)
    except SystemExit:
        raise
    except Exception as e:
        raise SystemExit(
            f"ОШИБКА: не получилось обработать картинку {src_path}: {e}. "
            f"Проверьте, что это нормальный файл JPG и он не повреждён."
        )

    return f"{DOCS_FULL_URL_PREFIX}/{file_name}", f"{DOCS_THUMB_URL_PREFIX}/{file_name}"


def _compose_timeline_text(title, hours, author):
    text = title
    if author:
        text += f" ({author})"
    if hours:
        text += f", {hours}"
    return text


def load_education():
    try:
        with open(EDUCATION_PATH, "r", encoding="utf-8") as f:
            raw = yaml.load(f, Loader=SafeLoader)
    except FileNotFoundError:
        raise SystemExit(f"ОШИБКА в {EDUCATION_PATH}: файл не найден.")
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (примерно строка {mark.line + 1})" if mark else ""
        raise SystemExit(
            f"ОШИБКА в {EDUCATION_PATH}: файл повреждён{where} — {e}. "
            f"Скорее всего, рядом пропущен отступ, двоеточие или кавычка."
        )

    if not isinstance(raw, dict):
        raise SystemExit(
            f"ОШИБКА в {EDUCATION_PATH}: файл должен содержать три раздела — "
            f"timeline, memberships, documents."
        )

    display_cfg = raw.get("display") or {}
    if not isinstance(display_cfg, dict):
        raise SystemExit(f"ОШИБКА в {EDUCATION_PATH}: раздел \"display\" должен быть блоком с числами.")

    def _visible_count(key, default):
        value = display_cfg.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise SystemExit(
                f"ОШИБКА в {EDUCATION_PATH}: display.{key} должно быть целым числом не меньше 1."
            )
        return value

    timeline_visible = _visible_count("timeline_visible", 5)
    documents_visible = _visible_count("documents_visible", 4)

    timeline = []
    for i, item in enumerate(raw.get("timeline") or [], start=1):
        label = f"запись №{i} таймлайна (timeline)"
        if not isinstance(item, dict):
            raise SystemExit(f"ОШИБКА в {EDUCATION_PATH}: {label} должна быть блоком с полями (year, title, ...).")
        year = item.get("year")
        title = item.get("title")
        if not isinstance(year, str) or not year.strip():
            raise SystemExit(f"ОШИБКА в {EDUCATION_PATH}: у {label} не указан \"year\".")
        if not isinstance(title, str) or not title.strip():
            raise SystemExit(f"ОШИБКА в {EDUCATION_PATH}: у {label} ({year}) не указан \"title\".")
        if not bool(item.get("show", True)):
            continue
        year = year.strip()
        year_match = TIMELINE_YEAR_RE.search(year)
        if not year_match:
            raise SystemExit(
                f"ОШИБКА в {EDUCATION_PATH}: у {label} поле \"year\" ({year!r}) должно содержать "
                f"год из 4 цифр (например \"2022\" или \"2021–2023\") — по нему сайт сортирует таймлайн."
            )
        hours = (item.get("hours") or "").strip()
        author = (item.get("author") or "").strip()
        timeline.append({
            "_sort_year": int(year_match.group()),
            "year": apply_nbsp(year),
            "text": apply_nbsp(_compose_timeline_text(title.strip(), hours, author)),
        })

    # Таймлайн всегда сортируется по году (по возрастанию), независимо от порядка
    # записей в файле — так записи можно дописывать куда угодно, не задумываясь
    # о сортировке руками. sort() в Python устойчив (stable), поэтому записи
    # с одинаковым годом остаются в том порядке, в котором их добавили в файл.
    timeline.sort(key=lambda t: t["_sort_year"])
    for t in timeline:
        del t["_sort_year"]

    memberships = []
    for i, item in enumerate(raw.get("memberships") or [], start=1):
        label = f"запись №{i} в memberships"
        if not isinstance(item, dict):
            raise SystemExit(f"ОШИБКА в {EDUCATION_PATH}: {label} должна быть блоком с полями (text, show).")
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise SystemExit(f"ОШИБКА в {EDUCATION_PATH}: у {label} не указан \"text\".")
        if not bool(item.get("show", True)):
            continue
        memberships.append({"text": apply_nbsp(text.strip())})

    documents = []
    seen_files = {}
    for i, item in enumerate(raw.get("documents") or [], start=1):
        label = f"документ №{i}"
        if not isinstance(item, dict):
            raise SystemExit(f"ОШИБКА в {EDUCATION_PATH}: {label} должен быть блоком с полями (file, caption, show).")
        file_name = item.get("file")
        caption = item.get("caption")
        if not isinstance(file_name, str) or not file_name.strip():
            raise SystemExit(f"ОШИБКА в {EDUCATION_PATH}: у {label} не указан \"file\".")
        if not isinstance(caption, str) or not caption.strip():
            raise SystemExit(f"ОШИБКА в {EDUCATION_PATH}: у {label} ({file_name}) не указана \"caption\".")
        file_name = file_name.strip()
        if file_name in seen_files:
            raise SystemExit(
                f"ОШИБКА в {EDUCATION_PATH}: файл «{file_name}» указан дважды — {label} и {seen_files[file_name]}."
            )
        seen_files[file_name] = label

        if not bool(item.get("show", True)):
            continue

        src_path = os.path.join(DOCS_SRC_DIR, file_name)
        if not os.path.isfile(src_path):
            raise SystemExit(
                f"ОШИБКА в {EDUCATION_PATH}: у {label} указан файл «{file_name}», "
                f"но его нет в папке {DOCS_SRC_DIR}/. Проверьте имя файла (регистр букв важен)."
            )

        url_full, url_thumb = process_document_image(file_name, src_path)
        documents.append({
            "url_full": url_full,
            "url_thumb": url_thumb,
            "caption": apply_nbsp(caption.strip()),
        })

    return {
        "timeline": timeline,
        "memberships": memberships,
        "documents": documents,
        "timeline_visible": timeline_visible,
        "documents_visible": documents_visible,
    }


environment = Environment(loader=FileSystemLoader("."))
settings = yaml.load(open("settings.yaml"), Loader=SafeLoader)
today = datetime.date.today()

with open("public/favicon.ico", "rb") as f:
    favicon_v = hashlib.md5(f.read()).hexdigest()[:8]

videos_json = load_videos()
education = load_education()

index_template = environment.get_template('index.html.template')
index_content = index_template.render(
    title=settings["title"],
    price=settings["price"],
    stats=settings["stats"],
    year=today.year,
    site_url=settings["site_url"],
    favicon_v=favicon_v,
    videos_json=videos_json,
    edu_timeline=education["timeline"],
    edu_memberships=education["memberships"],
    edu_documents=education["documents"],
    edu_timeline_visible=education["timeline_visible"],
    edu_documents_visible=education["documents_visible"],
)
with open("public/index.html", mode="w", encoding="utf-8") as f:
    f.write(index_content)

privacy_template = environment.get_template('privacy.html.template')
privacy_content = privacy_template.render(
    title=settings["title"],
    year=today.year,
    updated=ru_date(today),
    site_url=settings["site_url"],
    favicon_v=favicon_v,
)
with open("public/privacy.html", mode="w", encoding="utf-8") as f:
    f.write(privacy_content)
