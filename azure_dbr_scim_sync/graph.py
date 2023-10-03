import logging
import os
from typing import Dict, List, Optional

import requests
from databricks.sdk.service import iam
from pydantic import AliasChoices, BaseModel, Field
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger('sync.graph')


class GraphBase(BaseModel):
    id: str
    display_name: str = Field(validation_alias=AliasChoices('displayName'))


class GraphUser(GraphBase):
    mail: str = Field(validation_alias=AliasChoices('mail', 'mailNickname'))
    active: bool = Field(validation_alias=AliasChoices('accountEnabled'), default=True)

    def to_sdk_user(self):
        return iam.User(user_name=self.mail,
                        display_name=self.display_name,
                        active=self.active,
                        external_id=self.id)


class GraphServicePrincipal(GraphBase):
    application_id: str = Field(validation_alias=AliasChoices('appId'))
    active: bool = Field(validation_alias=AliasChoices('accountEnabled'), default=True)

    def to_sdk_service_principal(self):
        return iam.ServicePrincipal(application_id=self.application_id,
                                    display_name=self.display_name,
                                    active=self.active,
                                    external_id=self.id)


class GraphGroup(GraphBase):
    members: Optional[Dict[str, GraphBase]] = Field(default_factory=lambda: {})

    def to_sdk_group(self):
        return iam.Group(
            display_name=self.display_name,
            external_id=self.id,
            members=[iam.ComplexValue(display=x.display_name, value=x.id) for x in self.members.values()])


class GraphSyncObject(BaseModel):
    users: Optional[Dict[str, GraphUser]] = Field(default_factory=lambda: {})
    service_principals: Optional[Dict[str, GraphServicePrincipal]] = Field(default_factory=lambda: {})
    groups: Optional[Dict[str, GraphGroup]] = Field(default_factory=lambda: {})
    errors: Optional[List] = Field(default_factory=lambda: [])


class GraphAPIClient:

    def __init__(self, tenant_id: str = None, spn_id: str = None, spn_key: str = None):
        self._tenant_id = None

        retry_strategy = Retry(
            total=6,
            backoff_factor=1,
            status_forcelist=[429],
            respect_retry_after_header=True,
            raise_on_status=False, # return original response when retries have been exhausted
        )

        self._session = requests.Session()

        http_adapter = HTTPAdapter(max_retries=retry_strategy,
                                   pool_connections=20,
                                   pool_maxsize=20,
                                   pool_block=True)
        self._session.mount("https://", http_adapter)

        self._token = None
        self._header = None
        self._base_url = None

        self._authenticate()

    def _authenticate(self):
        tenant_id = self._tenant_id or os.getenv("GRAPH_ARM_TENANT_ID") or os.getenv("ARM_TENANT_ID")
        if not tenant_id:
            raise ValueError(
                "unknown tenant_id, set GRAPH_ARM_TENANT_ID or ARM_TENANT_ID environment variables!")

        client_id = self._tenant_id or os.getenv("GRAPH_ARM_CLIENT_ID") or os.getenv("ARM_CLIENT_ID")
        if not tenant_id:
            raise ValueError(
                "unknown client_id, set GRAPH_ARM_CLIENT_ID or ARM_CLIENT_ID environment variables!")

        client_scret = self._tenant_id or os.getenv("GRAPH_ARM_CLIENT_SECRET") or os.getenv(
            "ARM_CLIENT_SECRET")
        if not client_id:
            raise ValueError(
                "unknown client_id, set GRAPH_ARM_CLIENT_SECRET or ARM_CLIENT_SECRET environment variables!")

        self._token = self._get_access_token(tenant_id, client_id, client_scret)
        self._header = {"Authorization": f"Bearer {self._token}"}
        self._base_url = "https://graph.microsoft.com/"

    def _get_access_token(self, tenant_id, spn_id, spn_key):
        post_data = {
            'client_id': spn_id,
            'scope': 'https://graph.microsoft.com/.default',
            'client_secret': spn_key,
            'grant_type': 'client_credentials'
        }
        initial_header = {'Content-type': 'application/x-www-form-urlencoded'}
        res = self._session.post(f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
                                 data=post_data,
                                 headers=initial_header)
        res.raise_for_status()
        return res.json().get("access_token")

    def get_group_by_name(self, name: str) -> dict:
        res = self._session.get(
            f"https://graph.microsoft.com/v1.0/groups?$filter=displayName eq '{name}'&$select=id,displayName",
            headers=self._header)

        res.raise_for_status()

        data = res.json().get("value")

        if data and len(data) == 1:
            return data[0]

        return None

    def get_group_members(self,
                          group_id: str,
                          select="id,displayName,mail,mailNickname,appId,accountEnabled") -> dict:
        res = self._session.get(f"{self._base_url}/beta/groups/{group_id}/members?$select={select}",
                                headers=self._header)

        res.raise_for_status()

        return res.json().get("value")

    def get_objects_for_sync(self, group_names):
        sync_data = GraphSyncObject()

        def _register_user(d):
            id = d['id']
            if id not in sync_data.users:
                try:
                    obj = GraphUser.model_validate(d)
                    sync_data.users[id] = obj
                    logger.debug(f"Downloaded GraphUser: {obj}")
                except Exception as e:
                    logger.error(f"Invalid GraphUser: {d}", exc_info=e)
                    raise e

            return sync_data.users[id]

        def _register_service_principal(d):
            id = d['id']
            if id not in sync_data.service_principals:
                try:
                    obj = GraphServicePrincipal.model_validate(d)
                    sync_data.service_principals[id] = obj
                    logger.debug(f"Downloaded GraphServicePrincipal: {obj}")
                except Exception as e:
                    logger.error(f"Invalid GraphServicePrincipal: {d}", exc_info=e)
                    raise e

            return sync_data.service_principals[id]

        def _register_group(d):
            id = d['id']
            if id not in sync_data.groups:
                try:
                    obj = GraphGroup.model_validate(d)
                    sync_data.groups[id] = obj
                    logger.debug(f"Downloaded GraphGroup: {obj}")
                except Exception as e:
                    logger.error(f"Invalid GraphGroup: {d}", exc_info=e)
                    raise e

            return sync_data.groups[id]

        for idx, group_name in enumerate(group_names):
            logger.info(f"Downloading members of group: {group_name} ({idx+1}/{len(group_names)})")
            group_info = self.get_group_by_name(group_name)
            if not group_info:
                logger.warning(f"Group not found, skipping: {group_name}")
                continue
            
            group_members = self.get_group_members(group_info['id'])

            _register_group(group_info)

            group = sync_data.groups[group_info['id']]

            for m in group_members:
                # remove any None values, without that aliases dont work well
                m = {k: v for k, v in m.items() if v is not None}

                if m['@odata.type'] == '#microsoft.graph.user':
                    r = _register_user(m)

                if m['@odata.type'] == '#microsoft.graph.servicePrincipal':
                    r = _register_service_principal(m)

                if m['@odata.type'] == '#microsoft.graph.group':
                    r = _register_group(m)

                if isinstance(r, Exception):
                    sync_data.errors.append((m, r))
                else:
                    group.members[r.id] = r
        msg = f"Downloaded: errors={len(sync_data.errors)}, groups={len(sync_data.groups)}, users={len(sync_data.users)}, service_principals={len(sync_data.service_principals)}"
        if sync_data.errors:
            logger.error(msg)
        else:
            logger.info(msg)

        return sync_data
