# Docker setup

Setup of user IDs, file permissions, ACLs, and other related things in docker.

## Requirements and design considerations

### The aim - Docker containers should not run as root

Generally it's considered a bad idea to run anything as root that doesn't need it.
See "Principle of Least Privilege".

Bear in mind that if you're running as a user in the `docker` group, you might as well
be running as root, because you can create docker containers that run as root.

### How to run as non-root

During the build process for the PIXL images that we build from scratch (export, imaging, hasher),
a user called `pixl` with UID `PIXL_USER_UID` and
a group called `pixl` with GID `PIXL_USER_GID` are created *on the container*.
When the container is started, it runs as this user.

The numerical IDs need to be configurable because on the GAEs,
docker is set up so that there is no remapping between user IDs on containers and
user IDs on the host.
Eg. if you're UID 7001 on the container, then
you're 7001 on the host!
So you should set these arguments to match the GAE user/group that you want the containers to run as.

The images for orthanc, postgres and rabbitmq already come with an existing non-root user.
It seems to be easier to use this, rather than trying to them run as `pixl`.

# System testing

The build args are also used by the GHA system test workflow to set up this user and group on
the GHA test runner, simulating how a user should set this up in production.

If you're running the system test on linux, you will probably have better luck if Docker
is installed in rootless mode.


