#!/usr/bin/env python3

"""
Used to generate the docker-compose configs used by ref.
"""


import jinja2
import subprocess
import shutil
from pathlib import Path

COMPOSE_TEMPLATE = 'docker-compose.template.yml'

def generate_docker_compose():
    template_loader = jinja2.FileSystemLoader(searchpath="./")
    template_env = jinja2.Environment(loader=template_loader)
    template = template_env.get_template(COMPOSE_TEMPLATE)

    # TODO: Load settings.ini and use values to generate the docker file.

    cgroup_base = 'ref'
    cgroup_parent = f'{cgroup_base}-core.slice'
    instances_cgroup_parent = f'{cgroup_base}-instances.slice'

    render_out = template.render(
        testing=False,
        data_path='./data',
        exercises_path='./exercises',
        cgroup_parent=cgroup_parent,
        instances_cgroup_parent=instances_cgroup_parent,
        binfmt_support=False,
        )
    with open('docker-compose.yml', 'w') as f:
        f.write(render_out)

def generate_ssh_keys():
    """
    Generate the SSH keys that are used by the ssh entry server to authenticate at the containers.
    """
    container_root_key_path = Path("container-keys/root_key")
    container_user_key_path = Path("container-keys/user_key")

    # generate keys in the ssh-wrapper dir
    for key_path_suffix in [container_root_key_path, container_user_key_path]:
        ssh_wrapper_key_path = "ssh-wrapper" / key_path_suffix
        if not ssh_wrapper_key_path.exists():
            assert ssh_wrapper_key_path.parent.exists(), f"{ssh_wrapper_key_path.parent} doe not exists"
            subprocess.check_call(f"ssh-keygen -t ed25519 -N '' -f {ssh_wrapper_key_path.as_posix()}", shell=True)
            # Copy keys to the ref-docker-base
            shutil.copytree(ssh_wrapper_key_path.parent, Path("ref-docker-base") / key_path_suffix.parent, dirs_exist_ok=True)

def main():
    generate_docker_compose()
    generate_ssh_keys()



if __name__ == '__main__':
    main()
