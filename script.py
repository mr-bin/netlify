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

RU_MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

VIDEOS_PATH = "data/videos.json"
THUMB_DIR = os.path.join("public", "resources", "video-thumbs")
THUMB_URL_PREFIX = "/resources/video-thumbs"
MAXRES_MIN_BYTES = 10000  # a missing maxresdefault.jpg still returns HTTP 200 with a tiny grey placeholder

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


def ru_date(d):
    return f"{d.day} {RU_MONTHS[d.month - 1]} {d.year}"


def apply_nbsp(text):
    if not text:
        return text
    return NBSP_RE.sub(lambda m: m.group(1) + " ", text)


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


environment = Environment(loader=FileSystemLoader("."))
settings = yaml.load(open("settings.yaml"), Loader=SafeLoader)
today = datetime.date.today()

with open("public/favicon.ico", "rb") as f:
    favicon_v = hashlib.md5(f.read()).hexdigest()[:8]

videos_json = load_videos()

index_template = environment.get_template('index.html.template')
index_content = index_template.render(
    title=settings["title"],
    price=settings["price"],
    stats=settings["stats"],
    year=today.year,
    site_url=settings["site_url"],
    favicon_v=favicon_v,
    videos_json=videos_json,
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
