# Developer setup

See each service's README for instructions for individual developing and testing instructions.
Most modules require [`docker`](https://docs.docker.com/desktop/) and `docker-compose` to be installed to run tests.

For Python development we use [ruff](https://docs.astral.sh/ruff/) and [mypy](https://mypy.readthedocs.io/)
alongside [pytest](https://www.pytest.org/).
There is support (sometimes through plugins) for these tools in most IDEs & editors.

Before raising a PR, make sure to **run all tests** for each PIXL module
and not just the component you have been working on as this will help us catch unintentional regressions without spending GH actions minutes :-)

## Linting

We run [pre-commit](https://pre-commit.com/) as part of the GitHub Actions CI. To install and run it locally, do:

```sh
pip install pre-commit
pre-commit install
```

The `pre-commit` configuration can be found in [`.pre-commit-config.yml`](../../.pre-commit-config.yaml).


## Environment variables

Running the `pixl` pipeline and the tests requires a set of environment variables to be set. The `test/`
directory contains a complete [`.env` file](../../test/.env) that can be used to run the pipeline and tests locally.
Either run any `pixl` commands from the `test/` directory, or copy the `test/.env` file to the root of the repository.

### Secrets

PIXL uses an [Azure Keyvault](../../README.md#project-secrets) to store authentication details for
external services. We have a development keyvault for testing. Access to this keyvault is provided
by a set of environment variables specified in `test/.secrets.env.sample`.
To run the pipeline locally, you will need to copy this file to `test/.secrets.env` and fill out
the necessary values, which can be found in the `pixl-dev-secrets.env` shared LastPass note.
