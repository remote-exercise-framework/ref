#!/usr/bin/python
import jinja2

COMPOSE_TEMPLATE = 'docker-compose.template.yml'

def main():
    template_loader = jinja2.FileSystemLoader(searchpath="./")
    template_env = jinja2.Environment(loader=template_loader)

    template = template_env.get_template(COMPOSE_TEMPLATE)

    render_out = template.render(testing=False)
    with open('docker-compose.yml', 'w') as f:
        f.write(render_out)

    render_out = template.render(testing=True)
    with open('docker-compose-testing.yml', 'w') as f:
        f.write(render_out)


if __name__ == '__main__':
    main()