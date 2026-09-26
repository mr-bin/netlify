import datetime
import hashlib

import yaml
from yaml.loader import SafeLoader
from jinja2 import Environment, FileSystemLoader

RU_MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def ru_date(d):
    return f"{d.day} {RU_MONTHS[d.month - 1]} {d.year}"


environment = Environment(loader=FileSystemLoader("."))
settings = yaml.load(open("settings.yaml"), Loader=SafeLoader)
today = datetime.date.today()

with open("public/favicon.ico", "rb") as f:
    favicon_v = hashlib.md5(f.read()).hexdigest()[:8]

index_template = environment.get_template('index.html.template')
index_content = index_template.render(
    title=settings["title"],
    price=settings["price"],
    stats=settings["stats"],
    year=today.year,
    site_url=settings["site_url"],
    favicon_v=favicon_v,
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
