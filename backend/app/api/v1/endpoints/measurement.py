# backend/app/api/v1/endpoints/measurement.py
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import (
    CurrentUserDep,
    GoogleClientDep,
    GtmHeadlessVerifierDep,
    PageFetcherDep,
    ReaderFactoryDep,
    SessionDep,
    SettingsDep,
    StreamHostsFetcherDep,
    TokenCipherDep,
)
from app.api.rate_limit import limit_by_user
from app.models.enums import StackKind
from app.models.measurement_item_status import MeasurementItemStatus
from app.models.website_profile import WebsiteProfile
from app.security.rate_limit import enforce
from app.services.gtm_generator import build_selected_container, requires_site_code
from app.services.measurement.autolink import (
    LinkOutcome,
    LinkStatus,
    autolink_website,
    outcome_message,
)
from app.services.measurement.catalog import ITEMS_BY_ID, starter_pack
from app.services.measurement.google_reader import GoogleReadError
from app.services.measurement.service import (
    build_plan_view,
    clean_confirmed_types,
    get_or_create_profile,
    lock_site,
    record_state_change,
    refresh_plan,
)
from app.services.measurement.site_types import resolve_effective_types
from app.services.measurement.types import SITE_TYPES
from app.services.workspaces import owned_website, require_owner

router = APIRouter(tags=["measurement"])
logger = logging.getLogger(__name__)

_ADS_ID = re.compile(r"^AW-\d{6,}$")
_ADS_LABEL = re.compile(r"^[A-Za-z0-9_-]{6,}$")
_GA4_ID = re.compile(r"^G-[A-Z0-9]{6,}$")


# ---- schémas de sortie -------------------------------------------------------
class TypeGuessOut(BaseModel):
    type: str
    confidence: float
    signals: list[str] = []


class ProfileParamsOut(BaseModel):
    ads_conversion_id: str | None = None
    ads_conversion_label: str | None = None
    uses_google_ads: bool | None = None
    ga4_measurement_id: str | None = None


class ProfileOut(BaseModel):
    detected_types: list[TypeGuessOut]
    confirmed_types: list[str] | None
    effective_types: list[str]
    needs_confirmation: bool
    params: ProfileParamsOut


class SnippetOut(BaseModel):
    language: str
    code: str
    target_path: str
    instructions: str


class ItemOut(BaseModel):
    id: str
    layer: str
    title: str
    why: str
    weight: int
    quick_win: bool
    max_level: str
    state: str
    done: bool
    partial: bool
    reason: str | None
    evidence: dict[str, Any]
    checked_at: datetime | None
    guide: list[str]
    actions: list[str]
    snippet: SnippetOut | None


class LayerProgressOut(BaseModel):
    layer: str
    total: int
    done: int


class PlanOut(BaseModel):
    website_id: UUID
    profile: ProfileOut
    ga4_connected: bool
    gsc_linked: bool
    google_connection: Literal["none", "active", "needs_reauth"]
    next_actions: list[str]
    last_checked_at: datetime | None
    overall_done: int
    overall_total: int
    overall_percent: int
    layers: list[LayerProgressOut]
    items: list[ItemOut]
    headless_skipped: bool = False
    headless_error: str | None = None
    # Date du dernier passage du navigateur : l'interface s'en sert pour la fraîcheur
    # de la preuve « en conditions réelles ».
    headless_checked_at: datetime | None = None


class LinkOutcomeOut(BaseModel):
    status: LinkStatus
    resource_id: str | None
    candidates: list[str]
    # Texte français décidé par le code (jamais par un modèle) : pourquoi ce résultat.
    message: str


class AutolinkOut(BaseModel):
    ga4: LinkOutcomeOut
    gsc: LinkOutcomeOut
    plan: PlanOut


def _outcome_out(outcome: LinkOutcome) -> LinkOutcomeOut:
    return LinkOutcomeOut(
        status=outcome.status,
        resource_id=outcome.resource_id,
        candidates=list(outcome.candidates),
        message=outcome_message(outcome),
    )


# ---- schémas d'entrée --------------------------------------------------------
class ProfilePatch(BaseModel):
    confirmed_types: list[str] | None = None
    uses_google_ads: bool | None = None
    ads_conversion_id: str | None = None
    ads_conversion_label: str | None = None
    ga4_measurement_id: str | None = None

    @field_validator("confirmed_types")
    @classmethod
    def _check_types(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unknown = [t for t in value if t not in SITE_TYPES]
        if unknown:
            raise ValueError(
                f"type de site inconnu : {', '.join(unknown)} (attendu : {', '.join(SITE_TYPES)})"
            )
        return list(dict.fromkeys(value))  # sans doublon, ordre conservé

    @field_validator("ads_conversion_id")
    @classmethod
    def _check_ads_id(cls, value: str | None) -> str | None:
        if value is not None and not _ADS_ID.match(value):
            raise ValueError("ID de conversion invalide (format AW-123456789)")
        return value

    @field_validator("ads_conversion_label")
    @classmethod
    def _check_label(cls, value: str | None) -> str | None:
        if value is not None and not _ADS_LABEL.match(value):
            raise ValueError("libellé de conversion invalide")
        return value

    @field_validator("ga4_measurement_id")
    @classmethod
    def _check_ga4_id(cls, value: str | None) -> str | None:
        if value is not None and not _GA4_ID.match(value):
            raise ValueError("ID de mesure GA4 invalide (format G-XXXXXXXXXX)")
        return value


class ItemPatch(BaseModel):
    dismissed: bool | None = None
    manual_done: bool | None = None

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.dismissed is None and self.manual_done is None:
            raise ValueError("rien à modifier : fournir dismissed ou manual_done")
        if self.dismissed is True and self.manual_done is not None:
            raise ValueError(
                "un item écarté ne se marque pas fait ou non fait dans la même requête"
            )
        return self


class ContainerBody(BaseModel):
    # Exactement un des deux : une sélection explicite OU le pack de démarrage,
    # choisi d'après le type de site.
    item_ids: list[str] | None = None
    pack: Literal["starter"] | None = None
    import_mode: Literal["merge", "overwrite"] = "merge"

    @model_validator(mode="after")
    def _exactly_one_selection(self) -> Self:
        if (self.item_ids is None) == (self.pack is None):
            raise ValueError("fournir exactement un des deux : item_ids ou pack")
        if self.item_ids is not None and not self.item_ids:
            raise ValueError("sélection vide : choisir au moins un item")
        return self


class ContainerOut(BaseModel):
    container: dict[str, Any]
    warnings: list[str]
    filename: str
    # Items dont l'événement n'existera que si le site le pousse dans le dataLayer
    # (le conteneur ne fait que l'écouter) : l'interface renvoie vers l'onglet Snippet.
    needs_site_code: list[str]


# ---- endpoints ---------------------------------------------------------------
@router.get(
    "/websites/{website_id}/measurement-plan",
    response_model=PlanOut,
    dependencies=[limit_by_user("measurement_read", limit=120, window=60)],
)
async def get_measurement_plan(
    website_id: UUID, user: CurrentUserDep, session: SessionDep
) -> PlanOut:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    return PlanOut(**await build_plan_view(session, site))


@router.post(
    "/websites/{website_id}/measurement-plan/refresh",
    response_model=PlanOut,
    dependencies=[limit_by_user("measurement_refresh", limit=10, window=60)],
)
async def refresh_measurement_plan(
    website_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    fetcher: PageFetcherDep,
    reader_factory: ReaderFactoryDep,
    verifier: GtmHeadlessVerifierDep,
    headless: Annotated[bool, Query()] = False,
) -> PlanOut:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    if headless:
        # Un vrai navigateur : plus strict que la limite générale (et que le délai de
        # 5 minutes du service, qui protège aussi contre les rafales entre instances).
        enforce(
            f"measurement_headless:user:{user.id}",
            limit=3,
            window=600,
            enabled=settings.rate_limit_enabled,
        )
    reader = await reader_factory(session, site)
    result = await refresh_plan(
        session,
        site,
        fetcher=fetcher,
        reader=reader,
        verifier=verifier,
        run_headless=headless,
    )
    await session.commit()
    view = await build_plan_view(session, site)
    return PlanOut(
        **view, headless_skipped=result.headless_skipped, headless_error=result.headless_error
    )


@router.patch(
    "/websites/{website_id}/measurement-plan/profile",
    response_model=PlanOut,
    dependencies=[limit_by_user("measurement_profile", limit=30, window=60)],
)
async def patch_measurement_profile(
    website_id: UUID,
    body: ProfilePatch,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    fetcher: PageFetcherDep,
    reader_factory: ReaderFactoryDep,
    verifier: GtmHeadlessVerifierDep,
) -> PlanOut:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    await require_owner(session, workspace_id=site.workspace_id, user_id=user.id)

    profile = await get_or_create_profile(session, site.id)
    before = (list(profile.confirmed_types or []), profile.params.get("uses_google_ads"))
    provided = body.model_fields_set
    if "confirmed_types" in provided:
        if body.confirmed_types:
            profile.confirmed_types = list(dict.fromkeys(body.confirmed_types))
            profile.confirmed_at = datetime.now(UTC)
        else:
            profile.confirmed_types = None
            profile.confirmed_at = None
    params = dict(profile.params)
    for key in ("uses_google_ads", "ads_conversion_id", "ads_conversion_label", "ga4_measurement_id"):
        if key in provided:
            value = getattr(body, key)
            if value is None:
                params.pop(key, None)
            else:
                params[key] = value
    profile.params = params  # réaffectation complète (JSONB non mutable)
    changed = before != (list(profile.confirmed_types or []), params.get("uses_google_ads"))
    if changed:
        # La vérification qui suit compte dans la limite du rafraîchissement : le PATCH
        # du profil ne doit pas la contourner. Levée avant le commit : rien n'est écrit.
        enforce(
            f"measurement_refresh:user:{user.id}",
            limit=10,
            window=60,
            enabled=settings.rate_limit_enabled,
        )
    await session.commit()
    if changed:
        # Les états enregistrés dépendent de l'applicabilité (types, publicité) : sans
        # nouvelle vérification légère, ils divergeraient du profil. Transaction séparée
        # pour ne pas tenir le verrou de la ligne du profil pendant que le service
        # attend le verrou du site (risque d'interblocage avec un rafraîchissement).
        try:
            reader = await reader_factory(session, site)
            await refresh_plan(
                session, site, fetcher=fetcher, reader=reader, verifier=verifier, run_headless=False
            )
            await session.commit()
        except SQLAlchemyError:
            # Le profil est déjà enregistré : on renvoie la vue avec les anciens états
            # (le prochain rafraîchissement les remettra d'aplomb) plutôt qu'un 500.
            logger.exception("rafraîchissement après changement de profil échoué")
            await session.rollback()
            await session.refresh(site)
    return PlanOut(**await build_plan_view(session, site))


@router.patch(
    "/websites/{website_id}/measurement-plan/items/{item_id}",
    response_model=PlanOut,
    dependencies=[limit_by_user("measurement_item", limit=60, window=60)],
)
async def patch_measurement_item(
    website_id: UUID,
    item_id: str,
    body: ItemPatch,
    user: CurrentUserDep,
    session: SessionDep,
) -> PlanOut:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    await require_owner(session, workspace_id=site.workspace_id, user_id=user.id)
    item = ITEMS_BY_ID.get(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="item inconnu")
    if body.manual_done is not None and item.check != "manual":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cet item est vérifié automatiquement, il ne se marque pas à la main",
        )

    # Même verrou que le rafraîchissement : le marquage attend la fin d'un éventuel
    # rafraîchissement en cours au lieu d'être écrasé (ou d'insérer la même clé).
    await lock_site(session, site.id)
    now = datetime.now(UTC)
    row = await session.get(MeasurementItemStatus, (site.id, item_id))
    previous = row.state if row is not None else None
    if row is None and body.dismissed is not False:
        row = MeasurementItemStatus(
            website_id=site.id, item_id=item_id, state="unknown", evidence={}, checked_at=now
        )
        session.add(row)
    # « Non concerné » et « écarté » ne réapparaissent qu'au prochain rafraîchissement,
    # qui réévalue l'applicabilité : le PATCH n'y change pas l'état affiché.
    if row is not None:
        if body.dismissed is True:
            if row.dismissed_at is None:
                row.dismissed_at = now
            if row.state != "not_applicable":
                row.state = "dismissed"
        elif body.dismissed is False and row.dismissed_at is not None:
            row.dismissed_at = None
            if row.state != "not_applicable":
                row.state = "unknown"
        if body.manual_done is not None:
            row.evidence = {**row.evidence, "manual_done": body.manual_done}
            if row.state not in ("not_applicable", "dismissed"):
                row.state = "on_page" if body.manual_done else "unverifiable"
                row.reason = None if body.manual_done else "manual_check"
                row.checked_at = now
        record_state_change(
            session,
            website_id=site.id,
            item_id=item_id,
            previous=previous,
            current=row.state,
            evidence=row.evidence,
            at=now,
        )
    await session.commit()
    return PlanOut(**await build_plan_view(session, site))


@router.post(
    "/websites/{website_id}/measurement-plan/google-autolink",
    response_model=AutolinkOut,
    dependencies=[limit_by_user("measurement_autolink", limit=10, window=60)],
)
async def autolink_google(
    website_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    oauth: GoogleClientDep,
    cipher: TokenCipherDep,
    stream_hosts: StreamHostsFetcherDep,
    fetcher: PageFetcherDep,
    reader_factory: ReaderFactoryDep,
    verifier: GtmHeadlessVerifierDep,
) -> AutolinkOut:
    # Tout membre du workspace, comme `link-resource` (l'auto-liaison ne fait que ce que
    # ce dernier permet déjà, et seulement quand le choix est unique et complet).
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    result = await autolink_website(
        session, site, oauth=oauth, cipher=cipher, stream_hosts=stream_hosts
    )
    await session.commit()
    if "linked" in (result.ga4.status, result.gsc.status):
        # Les états des items dépendent des liaisons : sans nouvelle vérification légère,
        # le plan renvoyé ignorerait la liaison qui vient d'être faite. Transaction
        # séparée (la liaison est déjà enregistrée), et comptée dans la limite du
        # rafraîchissement pour ne pas la contourner : au-delà, on renvoie la vue telle
        # quelle (le prochain rafraîchissement la remettra d'aplomb).
        try:
            enforce(
                f"measurement_refresh:user:{user.id}",
                limit=10,
                window=60,
                enabled=settings.rate_limit_enabled,
            )
            allowed = True
        except HTTPException:
            allowed = False  # limite atteinte : liaison conservée, rafraîchissement remis
        if allowed:
            try:
                reader = await reader_factory(session, site)
                await refresh_plan(
                    session,
                    site,
                    fetcher=fetcher,
                    reader=reader,
                    verifier=verifier,
                    run_headless=False,
                )
                await session.commit()
            except SQLAlchemyError:
                logger.exception("rafraîchissement après auto-liaison échoué")
                await session.rollback()
                await session.refresh(site)
    view = await build_plan_view(session, site)
    return AutolinkOut(
        ga4=_outcome_out(result.ga4), gsc=_outcome_out(result.gsc), plan=PlanOut(**view)
    )


@router.post(
    "/websites/{website_id}/measurement-plan/gtm-container",
    response_model=ContainerOut,
    dependencies=[limit_by_user("measurement_container", limit=30, window=60)],
)
async def build_measurement_container(
    website_id: UUID,
    body: ContainerBody,
    user: CurrentUserDep,
    session: SessionDep,
    reader_factory: ReaderFactoryDep,
) -> ContainerOut:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    # Lecture seule côté profil : aucune ligne créée, donc aucun INSERT en attente pendant
    # l'appel Google ci-dessous (il gênerait un rafraîchissement concurrent).
    profile = await session.get(WebsiteProfile, site.id)
    detected = list(profile.detected_types) if profile else []
    confirmed = clean_confirmed_types(profile.confirmed_types) if profile else None
    params: dict[str, Any] = dict(profile.params) if profile else {}
    if body.pack == "starter":
        item_ids = starter_pack(resolve_effective_types(detected, confirmed))
    else:
        item_ids = list(dict.fromkeys(body.item_ids or []))
    unknown = [item_id for item_id in item_ids if item_id not in ITEMS_BY_ID]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"items inconnus : {', '.join(unknown)}",
        )

    measurement_id: str | None = params.get("ga4_measurement_id")
    if not measurement_id:
        reader = await reader_factory(session, site)
        try:
            measurement_id = await reader.measurement_id()
        except GoogleReadError:
            measurement_id = None

    container, warnings = build_selected_container(
        domain=site.domain,
        stack=site.detected_stack or StackKind.UNKNOWN,
        item_ids=item_ids,
        ga4_measurement_id=measurement_id,
        ads_conversion_id=params.get("ads_conversion_id"),
        ads_conversion_label=params.get("ads_conversion_label"),
        import_mode=body.import_mode,
    )
    return ContainerOut(
        container=container,
        warnings=warnings,
        filename=f"gtm-plan-{site.domain}.json",
        needs_site_code=[item_id for item_id in item_ids if requires_site_code(item_id)],
    )
