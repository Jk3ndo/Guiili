from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import CurrentUserDep, GoogleClientDep, SessionDep, TokenCipherDep
from app.models.enums import ConnectionStatus, ResourceType
from app.models.google_connection import GoogleConnection
from app.models.website_google_link import WebsiteGoogleLink
from app.services.connections import decrypt_refresh_token
from app.services.google_oauth import InvalidGrantError
from app.services.workspaces import owned_website, user_workspace_ids

router = APIRouter(tags=["google"])


class ConnectionSummary(BaseModel):
    id: UUID
    email: str
    status: ConnectionStatus
    granted_scopes: list[str]
    last_refreshed_at: datetime | None


class Ga4PropertyOut(BaseModel):
    resource_id: str
    display_name: str
    account: str
    account_display_name: str
    source_connection_id: UUID
    source_email: str


class GtmContainerOut(BaseModel):
    resource_id: str
    display_name: str
    account_id: str
    container_id: str
    source_connection_id: UUID
    source_email: str


class GscSiteOut(BaseModel):
    resource_id: str
    permission_level: str
    source_connection_id: UUID
    source_email: str


class ResourcesResponse(BaseModel):
    connections: list[ConnectionSummary]
    ga4_properties: list[Ga4PropertyOut]
    gtm_containers: list[GtmContainerOut]
    gsc_sites: list[GscSiteOut]


class LinkResourceRequest(BaseModel):
    google_connection_id: UUID
    resource_type: ResourceType
    resource_id: str
    resource_display_name: str | None = None


class LinkResourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    website_id: UUID
    google_connection_id: UUID
    resource_type: ResourceType
    resource_id: str
    resource_display_name: str | None


class WebsiteGoogleLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    google_connection_id: UUID
    resource_type: ResourceType
    resource_id: str
    resource_display_name: str | None


@router.get("/google/resources", response_model=ResourcesResponse)
async def list_google_resources(
    user: CurrentUserDep,
    session: SessionDep,
    client: GoogleClientDep,
    cipher: TokenCipherDep,
) -> ResourcesResponse:
    workspace_ids = await user_workspace_ids(session, user.id)
    connections = (
        (
            await session.execute(
                select(GoogleConnection).where(GoogleConnection.workspace_id.in_(workspace_ids))
            )
        )
        .scalars()
        .all()
    )

    response = ResourcesResponse(connections=[], ga4_properties=[], gtm_containers=[], gsc_sites=[])
    status_changed = False

    for connection in connections:
        if connection.status != ConnectionStatus.ACTIVE:
            response.connections.append(_summary(connection))
            continue

        refresh_token = decrypt_refresh_token(connection, cipher=cipher)
        try:
            token = await client.refresh_access_token(refresh_token=refresh_token)
        except InvalidGrantError:
            connection.status = ConnectionStatus.NEEDS_REAUTH
            status_changed = True
            response.connections.append(_summary(connection))
            continue

        discovered = await client.discover_resources(access_token=token.access_token)
        for prop in discovered.ga4_properties:
            response.ga4_properties.append(
                Ga4PropertyOut(
                    resource_id=prop.resource_id,
                    display_name=prop.display_name,
                    account=prop.account,
                    account_display_name=prop.account_display_name,
                    source_connection_id=connection.id,
                    source_email=connection.google_account_email,
                )
            )
        for container in discovered.gtm_containers:
            response.gtm_containers.append(
                GtmContainerOut(
                    resource_id=container.resource_id,
                    display_name=container.display_name,
                    account_id=container.account_id,
                    container_id=container.container_id,
                    source_connection_id=connection.id,
                    source_email=connection.google_account_email,
                )
            )
        for site in discovered.gsc_sites:
            response.gsc_sites.append(
                GscSiteOut(
                    resource_id=site.resource_id,
                    permission_level=site.permission_level,
                    source_connection_id=connection.id,
                    source_email=connection.google_account_email,
                )
            )
        response.connections.append(_summary(connection))

    if status_changed:
        await session.commit()

    return response


@router.post(
    "/websites/{website_id}/link-resource",
    response_model=LinkResourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def link_resource(
    website_id: UUID,
    body: LinkResourceRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> WebsiteGoogleLink:
    await owned_website(session, website_id=website_id, user_id=user.id)

    connection = await session.get(GoogleConnection, body.google_connection_id)
    if connection is None or connection.workspace_id not in await user_workspace_ids(
        session, user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="connexion Google invalide pour cet utilisateur",
        )

    # Une seule ressource par (site, type) : la nouvelle liaison remplace l'ancienne.
    existing_links = (
        (
            await session.execute(
                select(WebsiteGoogleLink).where(
                    WebsiteGoogleLink.website_id == website_id,
                    WebsiteGoogleLink.resource_type == body.resource_type,
                )
            )
        )
        .scalars()
        .all()
    )
    for link in existing_links:
        await session.delete(link)
    await session.flush()

    link = WebsiteGoogleLink(
        website_id=website_id,
        google_connection_id=body.google_connection_id,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        resource_display_name=body.resource_display_name,
    )
    session.add(link)
    await session.flush()
    await session.commit()
    return link


@router.get("/websites/{website_id}/google-links", response_model=list[WebsiteGoogleLinkOut])
async def list_website_google_links(
    website_id: UUID, user: CurrentUserDep, session: SessionDep,
) -> list[WebsiteGoogleLink]:
    await owned_website(session, website_id=website_id, user_id=user.id)
    rows = (
        await session.execute(
            select(WebsiteGoogleLink).where(WebsiteGoogleLink.website_id == website_id)
        )
    ).scalars().all()
    return list(rows)


def _summary(connection: GoogleConnection) -> ConnectionSummary:
    return ConnectionSummary(
        id=connection.id,
        email=connection.google_account_email,
        status=connection.status,
        granted_scopes=connection.granted_scopes,
        last_refreshed_at=connection.last_refreshed_at,
    )
