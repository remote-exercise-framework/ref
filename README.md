## Remote Exercise Framework (REF)
The REF framework intends to provide students with an interactive, practical learning environment: For pre-defined tasks, each student can work in an indvidiual Docker container with automated goal verification aiding their progress.
The framework consists of multiple components that have to be built the first time REF is set up and when it is updated. The framework heavily relies on Docker for the runtime environment itself as well as for deploying the different exercises to the students.

The following describes how to build REF, how to run it, and how to upgrade it. To learn more about creating new exercises, head to [exercises.md](./EXERCISES.md).

### Building REF
The build process is split into two parts. While the first part is mandatory and entails building the framework itself, the second part is only required if you plan to host exercises where ASLR is disabled for setuid binaries.

#### Build the framework
Building the framework is always required, and is described in the following.

Clone the source and the submodules:
```bash
git clone git@git.noc.ruhr-uni-bochum.de:SysSec-Teaching/remote-exercises-framework.git
cd remote-exercises-framework
git submodule update --init --recursive

# Create an environment file used for configuration and adapt the values in settings.env.
# Make sure to uncomment the settings and to change the password!
cp template.env setting.env

# Build all images. This command will check if your system meets the requirements
# and will print error messages in case something is not working as expected.
./ctrl.sh build
```

After successfully building REF, the database has to be initialized:
```bash
# This command will apply the current database and create all tables.
./ctrl.sh flask-cmd db upgrade
```


#### Build the custom Linux kernel
Building the custom Linux kernel is only required if you need the `no-randomize` attribute for some exercises. This attribute allows you to disable ASLR for a specific binary, even if it is a setuid binary. This is not allowed for unmodified kernels. The following assumes that your system is based on Debian and uses GRUB as a bootloader. For other systems or bootloaders, the instructions have to be adapted accordingly.

```bash
# Switch into the custom kernel source tree
cd ref-linux

# Install the dependencies needed for building the Linux kernel
sudo apt install build-essential bison flex bc lz4 libssl-dev debhelper libelf-dev pahole

# Copy the current kernel config and use it as a starting point for the new kernel.
cp /boot/config-<...> .config

# Disable kernel signing
scripts/config --disable CONFIG_SYSTEM_TRUSTED_KEYS
scripts/config --disable CONFIG_SYSTEM_REVOCATION_LIST
scripts/config --disable MODULE_SIG_KEY

# Set default values for config attributes not found in the copied config.
make olddefconfig

# Add custom suffix to the kernel's name
scripts/config --set-str CONFIG_LOCALVERSION 'ref'

# Build the kernel as .deb package. The files will be located in the parent directory.
make -j$(nproc) bindeb-pkg
```

After the kernel has been built, it needs to be installed. This can happen via the following command:
```bash
dpkg -i linux-*.deb
```

Eventually, the bootloader must be configured to boot the desired kernel. If you have access to the boot menu, it is sufficient to select the new kernel (with -ref suffix) during booting. If this is no option, the process is a bit more involved:
1. First, sub-menus in GRUB have to be disabled. For this add (or set) `GRUB_DISABLE_SUBMENU=y` in `/etc/default/grub`
2. Then update Grub via `sudo update-grub`.
3. Run `sudo grep 'menuentry ' /boot/grub/grub.cfg | cut -f 2 -d "'" | nl -v 0` which gives you the boot-id for each installed kernel.
4. Execute `sudo grub-reboot <id>` with the `id` set to the one of the REF kernel.
5. Reboot the system, and check via `uname -a` if currently used kernel is the REF kernel (recognizable by the -ref suffix).
6. If the kernel has been loaded successfully, the kernel can be configured as default via `sudo grub-set-default <id>`.


### Running REF
REF can be started via one of the following commands:
```bash
# This will start all services and remain attached to the terminal
# while printing debug information to the console. Closing the terminal,
# or sending SIGTERM will cause all services to be terminated. Hence, this
# command should be run in a `tmux` session.
./ctrl.sh up --debug

# Alternatively, omitting --debug will do the same but will not attach
# to the current terminal.
./ctrl.sh up
```

In order to shutdown all services, use the following commands:
```bash
# This will stop all services but will not remove them. This is typically
# sufficient if no changes to the images (e.g., by running `./ctrl.sh build`)
# or to the compose file have been made.
./ctrl.sh stop

# This command will delete all services that have then to be recreated from
# scratch if `./ctrl.sh up` is issued. This will not cause any data to be lost
# but requires to recreate all containers of REF itself and all user instances.
# Thus, if no changes to the system have been applied, using `./ctrl.sh stop`
# should be preferred for performance reasons.
./ctrl.sh down
```

### Upgrading REF
To upgrade to a new version of REF, perform the following steps:

```bash
# Shutdown all running services.
./ctrl.sh down

# Make a backup of the `data` directory and note down the current commit
# of the main repository. Adapt the following exemplary command.
git rev-parse HEAD > current_commit.backup
sudo cp -ra data data-$(date "+%Y-%m-%d").backup

# Update to the most recent commits.
git pull && git submodule update --init --recursive

# Rebuild all services.
./ctrl.sh build

# Migrate the database to the new version (if any changeupgrades have been applied)
./ctrl.sh flask-cmd db migrate

# Now REF can be started again and should operate normally.
./ctrl.sh up
```

In case the update fails, remove the `data` andirectory and move the backup back to its location.

### Services
After starting the application, the following services are running on the host:

#### SSH Entry-Server
This services is the entry server for all SSH connections to the exercises. Based on the clients user name and the public key, incoming SSH connection are forwarded to a container of the respective exercise.

```
Hostname: sshserver
Port: 2222
```

#### Webinterface
The webinterface to manage the exercises and users. This endpoint is alow used by the student to register.
```
Hostname: web
Port: 8000
User: 0
Password: See settings.env
```

#### Postgres Database
The database used to store all information.
```
Hostname: db
Port: Not expose to the host
User: ref
Database name: ref
Password: See settings.env
```
