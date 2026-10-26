import datetime
import hashlib
import html
import json
import os
import re
import shutil
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

MATERIALS_PATH = "data/materials.yaml"
MATERIALS_SRC_DIR = "assets/materials"
MATERIALS_DIR = os.path.join("public", "materials")
MATERIALS_URL_PREFIX = "/materials"

TOPICS_DIR = "data/topics"
TOPIC_TEMPLATE = "topic.html.template"

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

# Дефис между буквами ("по-разному", "интервью-знакомство") — неразрывный дефис
# (U+2011), чтобы слово с дефисом не разрывалось переносом строки. Общее правило
# для всего текста тематических страниц (data/topics/*.yaml), а не точечная правка.
NOBREAK_HYPHEN_RE = re.compile(r"(?<=[A-Za-zА-Яа-яЁё])-(?=[A-Za-zА-Яа-яЁё])")

# Ссылка внутри текста тематической страницы: [текст](адрес). Адрес не проходит
# через расстановку неразрывных пробелов/дефисов, внешние ссылки (http…)
# открываются в новой вкладке, внутренние (/#…, #…) — в той же.
TOPIC_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


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


def _topic_typography(text):
    text = apply_nbsp(text)
    if not text:
        return text
    return NOBREAK_HYPHEN_RE.sub("‑", text)


def apply_topic_nbsp(text):
    """Как apply_nbsp(), но дополнительно для текста тематических страниц —
    делает дефис внутри слова неразрывным (см. NOBREAK_HYPHEN_RE) и превращает
    [текст](адрес) в ссылку (см. TOPIC_LINK_RE)."""
    if not text:
        return text
    parts = []
    pos = 0
    for m in TOPIC_LINK_RE.finditer(text):
        parts.append(_topic_typography(text[pos:m.start()]))
        url = m.group(2)
        external = ' target="_blank" rel="noopener"' if url.startswith(("http://", "https://")) else ""
        parts.append(f'<a href="{html.escape(url)}"{external}>{_topic_typography(m.group(1))}</a>')
        pos = m.end()
    parts.append(_topic_typography(text[pos:]))
    return "".join(parts)


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


def _compose_timeline_meta(kind, author, hours):
    return " · ".join(part for part in (kind, author, hours) if part)


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
        kind = (item.get("kind") or "").strip()
        note = (item.get("note") or "").strip()
        timeline.append({
            "_sort_year": int(year_match.group()),
            "year": apply_nbsp(year),
            "title": apply_nbsp(title.strip()),
            "meta": apply_nbsp(_compose_timeline_meta(kind, author, hours)),
            "note": apply_nbsp(note),
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


def load_materials():
    try:
        with open(MATERIALS_PATH, "r", encoding="utf-8") as f:
            raw = yaml.load(f, Loader=SafeLoader)
    except FileNotFoundError:
        raise SystemExit(f"ОШИБКА в {MATERIALS_PATH}: файл не найден.")
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (примерно строка {mark.line + 1})" if mark else ""
        raise SystemExit(
            f"ОШИБКА в {MATERIALS_PATH}: файл повреждён{where} — {e}. "
            f"Скорее всего, рядом пропущен отступ, двоеточие или кавычка."
        )

    if not isinstance(raw, dict):
        raise SystemExit(f"ОШИБКА в {MATERIALS_PATH}: файл должен содержать раздел materials.")

    labels_order = raw.get("labels") or []
    if not isinstance(labels_order, list) or not all(isinstance(l, str) and l.strip() for l in labels_order):
        raise SystemExit(
            f"ОШИБКА в {MATERIALS_PATH}: раздел \"labels\" в начале файла должен быть списком названий меток."
        )
    labels_order = [l.strip() for l in labels_order]
    valid_labels = set(labels_order)

    materials = []
    seen_files = {}
    seen_card_ids = {}
    for i, item in enumerate(raw.get("materials") or [], start=1):
        label = f"материал №{i}"
        if not isinstance(item, dict):
            raise SystemExit(
                f"ОШИБКА в {MATERIALS_PATH}: {label} должен быть блоком с полями "
                f"(title, description, pages, file, video_url, show)."
            )
        title = item.get("title")
        description = item.get("description")
        pages = item.get("pages")
        file_name = item.get("file")
        if not isinstance(title, str) or not title.strip():
            raise SystemExit(f"ОШИБКА в {MATERIALS_PATH}: у {label} не указан \"title\".")
        if not isinstance(description, str) or not description.strip():
            raise SystemExit(f"ОШИБКА в {MATERIALS_PATH}: у {label} ({title}) не указан \"description\".")
        if not isinstance(pages, int) or isinstance(pages, bool) or pages < 1:
            raise SystemExit(
                f"ОШИБКА в {MATERIALS_PATH}: у {label} ({title}) поле \"pages\" должно быть "
                f"целым числом не меньше 1 (без кавычек)."
            )
        if not isinstance(file_name, str) or not file_name.strip():
            raise SystemExit(f"ОШИБКА в {MATERIALS_PATH}: у {label} ({title}) не указан \"file\".")
        file_name = file_name.strip()
        if not file_name.lower().endswith(".pdf"):
            raise SystemExit(
                f"ОШИБКА в {MATERIALS_PATH}: у {label} ({title}) файл «{file_name}» должен быть "
                f"в формате PDF (имя должно заканчиваться на .pdf)."
            )
        if file_name in seen_files:
            raise SystemExit(
                f"ОШИБКА в {MATERIALS_PATH}: файл «{file_name}» указан дважды — {label} и {seen_files[file_name]}."
            )
        seen_files[file_name] = label

        card_id = "list-" + file_name[:-4].replace("_", "-")
        if card_id in seen_card_ids:
            raise SystemExit(
                f"ОШИБКА в {MATERIALS_PATH}: у {label} ({title}) и {seen_card_ids[card_id]} получается "
                f"одинаковый id карточки «{card_id}» (имена файлов отличаются только подчёркиванием/дефисом). "
                f"Переименуйте один из файлов."
            )
        seen_card_ids[card_id] = label

        if not bool(item.get("show", True)):
            continue

        src_path = os.path.join(MATERIALS_SRC_DIR, file_name)
        if not os.path.isfile(src_path):
            raise SystemExit(
                f"ОШИБКА в {MATERIALS_PATH}: у {label} ({title}) указан файл «{file_name}», "
                f"но его нет в папке {MATERIALS_SRC_DIR}/. Проверьте имя файла (регистр букв важен)."
            )
        os.makedirs(MATERIALS_DIR, exist_ok=True)
        shutil.copyfile(src_path, os.path.join(MATERIALS_DIR, file_name))

        raw_labels = item.get("labels") or []
        if not isinstance(raw_labels, list) or not all(isinstance(l, str) and l.strip() for l in raw_labels):
            raise SystemExit(
                f"ОШИБКА в {MATERIALS_PATH}: у {label} ({title}) поле \"labels\" должно быть списком меток."
            )
        item_labels = []
        for lbl in raw_labels:
            lbl = lbl.strip()
            if lbl not in valid_labels:
                print(
                    f"ПРЕДУПРЕЖДЕНИЕ в {MATERIALS_PATH}: у листа «{title}» метка «{lbl}» не входит в список "
                    f"labels в начале файла — проверьте, нет ли опечатки, или допишите метку в этот список."
                )
                continue
            item_labels.append(lbl)

        favorite = bool(item.get("favorite", False))
        video_url = (item.get("video_url") or "").strip()
        video_id = extract_youtube_id(video_url)
        tags = list(item_labels)
        if video_id:
            tags.append("С видео")

        materials.append({
            "title": apply_nbsp(title.strip()),
            "description": apply_nbsp(description.strip()),
            "format": f"PDF · {pages} стр.",
            "url": f"{MATERIALS_URL_PREFIX}/{file_name}",
            "video_url": video_url,
            "video_id": video_id,
            "card_id": card_id,
            "labels": tags,
            "favorite": favorite,
        })

    return materials, labels_order


def _nbsp_lines(items):
    return [apply_topic_nbsp(s.strip()) for s in items if isinstance(s, str) and s.strip()]


def _parse_text_split(block):
    """Общий разбор текстового блока «заголовок слева, текст справа» для
    тематических страниц (используется и для intro, и для expect, и для
    любых будущих блоков такого вида — например на странице про менопаузу).
    bg — необязательный фон секции ("" — белый, "sage" — светло-зелёный).
    lead — крупный вводный абзац шрифтом Alegreya, показывается первым.
    highlight — выделенная курсивом строка без фона (как на странице
    «Потери беременности»). callout — светлая плашка с фоном внутри блока.
    footnote — мелкая серая строка в самом конце блока (например ссылка на
    соседнюю тематическую страницу, как на странице «ЭКО»)."""
    paragraphs = _nbsp_lines(block.get("paragraphs") or [])
    heading = (block.get("heading") or "").strip()
    lead = (block.get("lead") or "").strip()
    if not heading or not (paragraphs or lead):
        return None
    result = {
        "heading": apply_topic_nbsp(heading),
        "bg": (block.get("bg") or "").strip(),
        "paragraphs": paragraphs,
    }
    if lead:
        result["lead"] = apply_topic_nbsp(lead)
    highlight = (block.get("highlight") or "").strip()
    if highlight:
        result["highlight"] = apply_topic_nbsp(highlight)
    callout = (block.get("callout") or "").strip()
    if callout:
        result["callout"] = apply_topic_nbsp(callout)
    footnote = (block.get("footnote") or "").strip()
    if footnote:
        result["footnote"] = apply_topic_nbsp(footnote)
    return result


def load_topics():
    """Загружает тематические страницы из data/topics/*.yaml — одна страница
    на файл, адрес = имя файла (poterya-beremennosti.yaml → /poterya-beremennosti/).
    Каждый раздел страницы необязателен: если данных для него нет, он просто
    не передаётся в шаблон, и topic.html.template его не выводит."""
    if not os.path.isdir(TOPICS_DIR):
        return []

    topics = []
    for file_name in sorted(os.listdir(TOPICS_DIR)):
        if not file_name.endswith(".yaml"):
            continue
        path = os.path.join(TOPICS_DIR, file_name)
        slug = file_name[:-len(".yaml")]
        label = f"тематическая страница «{slug}» ({path})"

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = yaml.load(f, Loader=SafeLoader)
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            where = f" (примерно строка {mark.line + 1})" if mark else ""
            raise SystemExit(
                f"ОШИБКА в {path}: файл повреждён{where} — {e}. "
                f"Скорее всего, рядом пропущен отступ, двоеточие или кавычка."
            )
        if not isinstance(raw, dict):
            raise SystemExit(f"ОШИБКА в {label}: файл должен быть блоком с полями (seo, hero, ...).")

        seo = raw.get("seo") or {}
        hero = raw.get("hero") or {}
        if not isinstance(seo.get("title"), str) or not seo["title"].strip():
            raise SystemExit(f"ОШИБКА в {label}: не указан seo.title.")
        if not isinstance(seo.get("description"), str) or not seo["description"].strip():
            raise SystemExit(f"ОШИБКА в {label}: не указан seo.description.")
        if not isinstance(hero.get("h1"), str) or not hero["h1"].strip():
            raise SystemExit(f"ОШИБКА в {label}: не указан hero.h1.")
        breadcrumb = (raw.get("breadcrumb") or "").strip()
        if not breadcrumb:
            raise SystemExit(f"ОШИБКА в {label}: не указан breadcrumb (название в хлебных крошках).")
        zapis = raw.get("zapis") or {}
        if not isinstance(zapis.get("lead"), str) or not zapis["lead"].strip():
            raise SystemExit(f"ОШИБКА в {label}: не указан zapis.lead.")

        topic = {
            "slug": slug,
            "seo_title": apply_topic_nbsp(seo["title"].strip()),
            "seo_description": apply_topic_nbsp(seo["description"].strip()),
            "breadcrumb": apply_topic_nbsp(breadcrumb),
            "hero": {
                "h1": apply_topic_nbsp(hero["h1"].strip()),
                "lead": apply_topic_nbsp((hero.get("lead") or "").strip()),
                "lead_soft": apply_topic_nbsp((hero.get("lead_soft") or "").strip()),
                "photo_alt": apply_topic_nbsp((hero.get("photo_alt") or "Екатерина Заикина").strip()),
            },
            "warning": apply_topic_nbsp((raw.get("warning") or "").strip()),
            "zapis": {
                "lead": apply_topic_nbsp(zapis["lead"].strip()),
                "note": apply_topic_nbsp((zapis.get("note") or "").strip()),
                "bg": (zapis.get("bg") or "").strip(),
            },
        }

        intro_block = _parse_text_split(raw.get("intro") or {})
        if intro_block:
            topic["intro"] = intro_block

        expect_block = _parse_text_split(raw.get("expect") or {})
        if expect_block:
            topic["expect"] = expect_block

        topics_block = raw.get("topics") or {}
        raw_items = topics_block.get("items") or []
        if (topics_block.get("heading") or "").strip() and raw_items:
            parsed_items = []
            for item in raw_items:
                title = (item.get("title") or "").strip()
                if not title:
                    raise SystemExit(f"ОШИБКА в {label}: у одной из карточек topics.items не указан title.")
                parsed_items.append({
                    "title": apply_topic_nbsp(title),
                    "sub": apply_topic_nbsp((item.get("sub") or "").strip()),
                })
            topic["topics_block"] = {
                "heading": apply_topic_nbsp(topics_block["heading"].strip()),
                "cards": parsed_items,
                "note": apply_topic_nbsp((topics_block.get("note") or "").strip()),
                "note_style": (topics_block.get("note_style") or "").strip(),
            }

        steps_block = raw.get("steps") or {}
        raw_steps = steps_block.get("items") or []
        if (steps_block.get("heading") or "").strip() and raw_steps:
            parsed_steps = []
            for item in raw_steps:
                title = (item.get("title") or "").strip()
                text = (item.get("text") or "").strip()
                if not title or not text:
                    raise SystemExit(f"ОШИБКА в {label}: у одного из шагов steps.items не указан title или text.")
                parsed_steps.append({"title": apply_topic_nbsp(title), "text": apply_topic_nbsp(text)})
            topic["steps"] = {
                "heading": apply_topic_nbsp(steps_block["heading"].strip()),
                "list": parsed_steps,
                "footnote_text": apply_topic_nbsp((steps_block.get("footnote_text") or "").strip()),
                "footnote_url": (steps_block.get("footnote_url") or "").strip(),
            }

        medical = raw.get("medical_note") or {}
        medical_items = _nbsp_lines(medical.get("items") or [])
        if (medical.get("heading") or "").strip() and medical_items:
            topic["medical_note"] = {
                "heading": apply_topic_nbsp(medical["heading"].strip()),
                "intro": apply_topic_nbsp((medical.get("intro") or "").strip()),
                "list": medical_items,
                "extra": apply_topic_nbsp((medical.get("extra") or "").strip()),
                "crisis": apply_topic_nbsp((medical.get("crisis") or "").strip()),
            }

        video = raw.get("video") or {}
        video_url = (video.get("url") or "").strip()
        if video_url:
            video_id = extract_youtube_id(video_url)
            if not video_id:
                raise SystemExit(
                    f"ОШИБКА в {label}: у video.url ({video_url}) не получилось распознать ссылку на YouTube."
                )
            topic["video"] = {
                "id": video_id,
                "title": apply_topic_nbsp((video.get("title") or "").strip()),
                "description": apply_topic_nbsp((video.get("description") or "").strip()),
            }

        faq = raw.get("faq") or {}
        raw_faq = faq.get("items") or []
        if (faq.get("heading") or "").strip() and raw_faq:
            parsed_faq = []
            for item in raw_faq:
                q = (item.get("q") or "").strip()
                a = (item.get("a") or "").strip()
                if not q or not a:
                    raise SystemExit(f"ОШИБКА в {label}: у одного из вопросов faq.items не указан q или a.")
                # if_video — продолжение ответа, которое показывается, только
                # когда на странице есть блок «Видео» (заполнен video.url).
                if_video = (item.get("if_video") or "").strip()
                if if_video and "video" in topic:
                    a = f"{a} {if_video}"
                parsed_faq.append({"q": apply_topic_nbsp(q), "a": apply_topic_nbsp(a)})
            topic["faq"] = {"heading": apply_topic_nbsp(faq["heading"].strip()), "list": parsed_faq}

        topics.append(topic)

    return topics


environment = Environment(loader=FileSystemLoader("."))
# Для <head> (title/meta content) нужен обычный пробел, а не &nbsp; — неразрывные
# пробелы там не видны пользователю и не нужны, но могут случайно попасть в seo-текст
# через apply_nbsp(). Фильтр подчищает и настоящий символ U+00A0, и буквальную
# строку "&nbsp;", если она когда-нибудь попадёт в данные.
environment.filters["plain_space"] = lambda text: (text or "").replace(" ", " ").replace("&nbsp;", " ")
settings = yaml.load(open("settings.yaml"), Loader=SafeLoader)
today = datetime.date.today()

with open("public/favicon.ico", "rb") as f:
    favicon_v = hashlib.md5(f.read()).hexdigest()[:8]

videos_json = load_videos()
education = load_education()
materials, materials_labels_order = load_materials()
topics = load_topics()

# Данные для раздела "Материалы" на фронтенде (фильтры по меткам) и для
# строки "Лист к этому видео" в разделе "Видео" — та же схема, что у
# videos_json: один JSON-блок, который читает public/main.js.
materials_json = json.dumps(
    {
        "labelsOrder": materials_labels_order,
        "materials": [
            {
                "id": m["card_id"],
                "title": m["title"],
                "labels": m["labels"],
                "videoId": m["video_id"],
            }
            for m in materials
        ],
    },
    ensure_ascii=False,
).replace("</", "<\\/")

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
    materials=materials,
    materials_json=materials_json,
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

# Тематические страницы (data/topics/*.yaml) — каждая в свою папку
# public/<slug>/index.html, Netlify отдаёт её по адресу /<slug>/.
topic_template = environment.get_template(TOPIC_TEMPLATE)
for topic in topics:
    topic_content = topic_template.render(
        topic=topic,
        year=today.year,
        site_url=settings["site_url"],
        favicon_v=favicon_v,
        price=settings["price"],
    )
    topic_dir = os.path.join("public", topic["slug"])
    os.makedirs(topic_dir, exist_ok=True)
    with open(os.path.join(topic_dir, "index.html"), mode="w", encoding="utf-8") as f:
        f.write(topic_content)

# sitemap.xml: главная страница + PDF из раздела "Материалы" + тематические
# страницы (без privacy — у неё noindex). Списки берутся из тех же
# data/materials.yaml и data/topics/*.yaml, что и сами разделы/страницы на
# сайте, так что сборка и sitemap не расходятся.
site_url = settings["site_url"]
sitemap_urls = (
    [f"{site_url}/"]
    + [f"{site_url}{m['url']}" for m in materials]
    + [f"{site_url}/{t['slug']}/" for t in topics]
)
sitemap_body = "\n".join(f"  <url><loc>{u}</loc></url>" for u in sitemap_urls)
sitemap_content = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    f"{sitemap_body}\n"
    "</urlset>\n"
)
with open("public/sitemap.xml", mode="w", encoding="utf-8") as f:
    f.write(sitemap_content)
