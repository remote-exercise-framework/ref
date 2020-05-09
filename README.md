## Remote Exercise Framework (ref)


### How to Build

Clone the source and the submodules:
```
git clone git@git.noc.ruhr-uni-bochum.de:SysSec-Teaching/remote-exercises-framework.git
cd remote-exercises-framework
git submodule update --init --recursive

#Build all images
./ctrl.sh build

#Create environment file used for configuration
#and adapted the values .env
cp template.env .env
```

### How to run it?

Controlling `ref`:
```
#Start for development
./ctrl.sh up --debug

#Start for production
./ctrl.sh up

#Migrate current db to new version.
./ctrl.sh flask-cmd db upgrade

#Create new migration after changeing the database schema
./ctrl.sh flask-cmd db migrate

#Stop the application
./ctrl.sh stop

#Delete all images and stop.
#This is only needed if changes to the compose
#file have been applied.
./ctrl.sh down
```

After starting the application, the following services are running on the host:

#### SSH Entry-Server
```
Hostname: sshserver
Port: 22
```

#### Webinterface
```
Hostname: web
Port: 8000
User: 0
Password: See .env
```

#### PgAdmin Interface
Webinterface to interface with the postgres database. Currently the the service configuration is volatile, hence the connection must be manually configured using the credentials from the `.env` file.
```
Hostname: pgadmin
Port: 8005
User: admin@admin.de
Password: See .env
```

#### Postgres Database
```
Hostname: db
Port: Not expose to the host
User: ref
Database name: ref
Password: See .env
```
