#!/usr/bin/env python3

"""
Used to generate the docker-compose configs used by ref.
"""

import jinja2
import subprocess
import shutil
from pathlib import Path

COMPOSE_TEMPLATE = "docker-compose.template.yml"


def generate_docker_compose():
    template_loader = jinja2.FileSystemLoader(searchpath="./")
    template_env = jinja2.Environment(loader=template_loader)
    template = template_env.get_template(COMPOSE_TEMPLATE)

    # TODO: Load settings.ini and use values to generate the docker file.

    cgroup_base = "ref"
    cgroup_parent = f"{cgroup_base}-core.slice"
    instances_cgroup_parent = f"{cgroup_base}-instances.slice"

    render_out = template.render(
        testing=False,
        bridge_id="",  # Not used when testing=False, template uses 'ref' suffix
        data_path="./data",
        exercises_path="./exercises",
        cgroup_parent=cgroup_parent,
        instances_cgroup_parent=instances_cgroup_parent,
        binfmt_support=False,
    )
    with open("docker-compose.yml", "w") as f:
        f.write(render_out)


def generate_ssh_keys():
    """
    Generate the SSH keys that are used by the SSH reverse proxy to authenticate at the containers.
    """
    container_keys_dir = Path("container-keys")
    container_keys_dir.mkdir(exist_ok=True)

    key_paths = [
        container_keys_dir / "root_key",
        container_keys_dir / "user_key",
    ]

    for key_path in key_paths:
        if not key_path.exists():
            subprocess.check_call(
                f"ssh-keygen -t ed25519 -N '' -f {key_path.as_posix()}",
                shell=True,
            )

    # Copy keys to ref-docker-base for container builds
    shutil.copytree(
        container_keys_dir,
        Path("ref-docker-base") / "container-keys",
        dirs_exist_ok=True,
    )


def main():
    generate_docker_compose()
    generate_ssh_keys()


if __name__ == "__main__":
    main()
