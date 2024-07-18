from jinja2 import Environment, FileSystemLoader

environment = Environment(loader=FileSystemLoader("."))
template = environment.get_template('index.html.template')
content = template.render(title="Сайт психолога")

with open("public/index.html", mode="w", encoding="utf-8") as message:
    message.write(content)
