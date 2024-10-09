# UCLH Infrastructure setup instructions

## Install shared miniforge installation if it doesn't exist

Follow the suggestion for installing a central [miniforge](https://github.com/conda-forge/miniforge)
installation to allow all users to be able to run modern python without having admin permissions.

```shell
# Create directory with correct structure (only if it doesn't exist yet)
mkdir /gae/miniforge3
chgrp -R docker /gae/miniforge3
chmod -R g+rwxs /gae/miniforge3  # inherit group when new directories or files are created
setfacl -R -m d:g::rwX /gae/miniforge3
# Install miniforge
wget "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash Miniforge3-$(uname)-$(uname -m).sh -p /gae/miniforge3
conda update -n base -c conda-forge conda
conda create -n pixl_dev python=3.10.*
```

The directory should now have these permissions

```shell
> ls -lah /gae/miniforge3/
total 88K
drwxrws---+  19 jstein01 docker 4.0K Nov 28 12:27 .
drwxrwx---.  18 root     docker 4.0K Dec  1 19:35 ..
drwxrws---+   2 jstein01 docker 8.0K Nov 28 12:27 bin
drwxrws---+   2 jstein01 docker   30 Nov 28 11:49 compiler_compat
drwxrws---+   2 jstein01 docker   32 Nov 28 11:49 condabin
drwxrws---+   2 jstein01 docker 8.0K Nov 28 12:27 conda-meta
-rw-rws---.   1 jstein01 docker   24 Nov 28 11:49 .condarc
...
```


## If you haven't just installed the miniforge yourself, update your configuration

Edit `~/.bash_profile` to add `/gae/miniforge3/bin` to the PATH. for example

```shell
PATH=$PATH:$HOME/.local/bin:$HOME/bin:/gae/miniforge3/bin
```

Run the updated profile (or reconnect to the GAE) so that `conda` is in your PATH

```shell
source ~/.bash_profile
```

Initialise `conda`

```shell
conda init bash
```

Run the updated profile (or reconnect to the GAE) so that `conda` is in your `PATH`

```shell
source ~/.bash_profile
```

Activate an existing `pixl` environment

```shell
conda activate pixl_dev
```

## Create an instance for the GAE if it doesn't already exist

Select a place for the deployment. On UCLH infrastructure this will be in `/gae`, so `/gae/pixl_dev` for example.

```shell
mkdir /gae/pixl_dev
chgrp -R docker /gae/pixl_dev
chmod -R g+rwxs /gae/pixl_dev  # inherit group when new directories or files are created
setfacl -R -m d:g::rwX /gae/pixl_dev
# now clone the repository or copy an existing deployment
```

Following clone, the exports directory needs to be permissioned appropriately:

## Create a PIXL system account

To avoid [running Docker containers as root](https://github.com/UCLH-Foundry/PIXL/issues/234), we set up a service account on the GAE as follows 

```shell
groupadd  -r -g 250 PIXL
useradd -r -s /usr/bin/false -c "PIXL Service Account" -u 250 -g 250 PIXL
usermod -a -G PIXL $user_to_add
```

Ask [@dram1964](https://github.com/dram1964) for help with this.

Change these values in your production `.env` file:

```
PIXL_USER_UID=???
PIXL_USER_GID=???
```
so that they match the UID and GID of the pixl user/group on
your host.

Set the ownership of the "exports" directory as follows:

```
MY_EXPORT_DIR=/gae/pixl_dev/PIXL/projects/exports
chgrp -R pixl "$MY_EXPORT_DIR"
```

See Issue https://github.com/UCLH-Foundry/PIXL/issues/401 where I suggest setting
the whole PIXL repo as group `pixl` rather than `docker`, for simplicity.

See [docker permissions setup](./docker_perms.md) for further discussion about
why the docker export directory needs to be set up this way.
