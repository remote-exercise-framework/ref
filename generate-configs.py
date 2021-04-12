#!/usr/bin/python3

"""
Used to generate the docker-compose configs used by ref.
"""


import jinja2

COMPOSE_TEMPLATE = 'docker-compose.template.yml'

def main():
    template_loader = jinja2.FileSystemLoader(searchpath="./")
    template_env = jinja2.Environment(loader=template_loader)
    template = template_env.get_template(COMPOSE_TEMPLATE)

    # TODO: Load settings.ini and use values to generate the docker file.

    cgroup_base = 'ref'
    cgroup_parent = f'{cgroup_base}-core.slice'
    instances_cgroup_parent = f'{cgroup_base}-instances.slice'

    render_out = template.render(testing=False, data_path='./data', exercises_path='./exercises', cgroup_parent=cgroup_parent, instances_cgroup_parent=instances_cgroup_parent)
    with open('docker-compose.yml', 'w') as f:
        f.write(render_out)

    render_out = template.render(testing=True, data_path='./data-testing', exercises_path='./exercises-testing', cgroup_parent=cgroup_parent, instances_cgroup_parent=instances_cgroup_parent)
    with open('docker-compose-testing.yml', 'w') as f:
        f.write(render_out)


if __name__ == '__main__':
    main()