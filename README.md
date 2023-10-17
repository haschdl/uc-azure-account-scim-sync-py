# Azure AAD to Databricks Account SCIM Sync

**WARNING: Highly experimental**
**WARNING: Highly experimental**
**WARNING: Highly experimental**

An example of end to end synchronization of the whitelisted Azure Active Directory groups and their members into the Databricks Account.

This python based application supports synchronisation of Users, Groups and SPNs that are members of the whitelisted AAD groups and groups themselves as well.

Yes, that means that group in a group, a.k.a. nested groups are supported!

When doing synchronization no users, groups or service principals are ever deleted. Synchronization only adds new security principals, or updates their attributes (like display name) of already existing ones. Only group members are fully sychronized to match what is present in AAD.

## How to run syncing

### Configure enviroment variables for authentication

- set environment variables for graph api access:
  - `GRAPH_ARM_TENANT_ID`, `GRAPH_ARM_CLIENT_ID` and `GRAPH_ARM_CLIENT_SECRET`
  - the SPN will need to have Active Directory rights to read users, groups and service principals. Write rights are not required.
- set environment variables for storage cache of graph/aad api ids to databricks ids
  - `AZURE_STORAGE_ACCOUNT_NAME`, `AZURE_STORAGE_CONTAINER`, `AZURE_STORAGE_TENANT_ID`, `AZURE_STORAGE_CLIENT_ID`, `AZURE_STORAGE_CLIENT_SECRET`
  - the defined SPN will need to have blob storage contributor rights on container.
  - `AZURE_STORAGE_CONTAINER` must point to valid container, can be followed by subpaths, for example: `datalake/some_folder/` would store cache in container `datalake` in folder `some_folder`
  - if not set, local file system will be used and cache data needs to be persisted by external tooling
- set environment variables for databricks account access:
  - `DATABRICKS_ARM_CLIENT_ID`, `DATABRICKS_ARM_CLIENT_SECRET`, `DATABRICKS_ACCOUNT_ID` and `DATABRICKS_HOST` (most likely it will be "https://accounts.azuredatabricks.net/")
- in case both `GRAPH_ARM_...` and `DATABRICKS_ARM_...` credentials are the same, you can just use typical `ARM_...` env variables

- create JSON file containing the list of AAD groups you would like to sync, and save it to `groups_to_sync.json` (for reference, see `examples/groups_to_sync.json`)
-withut need of using specifc ones for graph and databricks account.
- `pip install azure_dbr_scim_sync` to install this package, you should pin in version number to maintain stability of the interface
- read the manual:

```shell
$ azure_dbr_scim_sync --help
Usage: azure_dbr_scim_sync [OPTIONS]

Options:
  --groups-json-file TEXT  list of AAD groups to sync (json formatted)
                           [required]
  --verbose                verbose information about changes
  --debug                  show API call
  --dry-run                dont make any changes, just display
  --help                   Show this message and exit.
```

- dry run: `azure_dbr_scim_sync --groups-json-file groups_to_sync.json --dry-run`
- if everything works ok, run the command again, but this time without `--dry-run`.
- feel free to increase verbosity with `--verbose`, or even debug API calls with `--debug`

## Limitations

- AAD disabled users or service principals are not being disabled in databricks account (needs change capture sync feature)
- AAD deleted users or service principals are not being deleted from databricks account (needs change capture sync feature)
- Only full sync is supported (needs change capture sync feature, obviously)

## Near time roadmap

- enable incremental graph api change capture, so that only group members and users who changed since last ran would be synced
- enable logging of changes into JSON and DELTA format (running from databricks workflow would be required)
- enable ability to run directly from databricks workflows, with simple installer

## Local development

- run `make dev`
- set env variables `export ARM_...=123`, or if you are using VS Code tests ASLO create `.envs` file:

```sh
# common for everything
ARM_TENANT_ID=...

# graph api access creds
GRAPH_ARM_CLIENT_ID=...
GRAPH_ARM_CLIENT_SECRET=...

# to keep cache of aad id <> dbr id mapping
AZURE_STORAGE_TENANT_ID=...
AZURE_STORAGE_CLIENT_ID=...
AZURE_STORAGE_CLIENT_SECRET=...
AZURE_STORAGE_ACCOUNT_NAME=...

# databricks account details
DATABRICKS_ACCOUNT_ID=...
DATABRICKS_HOST="https://accounts.azuredatabricks.net/"
```

- run `make install && make test` to install package locally and run tests
- run `your favorite text editor` and make code changes
- run `make fmt && make lint && make install && make test` to format, install package locally and test your changes
- `git commit && git push`
