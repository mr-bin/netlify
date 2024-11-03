import yaml
from yaml.loader import SafeLoader
from jinja2 import Environment, FileSystemLoader

environment = Environment(loader=FileSystemLoader("."))
settings = yaml.load(open("settings.yaml"), Loader=SafeLoader)
template = environment.get_template('index.html.template')
content = template.render(title=settings["title"],
                          price=settings["price"])

with open("public/index.html", mode="w", encoding="utf-8") as message:
    message.write(content)
