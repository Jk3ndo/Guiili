# Plan de mesure guidé (lot A) — plan d'exécution

> **Pour les agents d'exécution :** SOUS-COMPÉTENCE OBLIGATOIRE : utiliser
> superpowers:subagent-driven-development (recommandé) ou
> superpowers:executing-plans pour exécuter ce plan tâche par tâche. Les étapes
> utilisent la syntaxe à cases (`- [ ]`) pour le suivi.

**Objectif :** donner à un utilisateur novice un plan de mesure vivant par site
(ce qui est en place, ce qui manque pour mesurer trafic et conversions, dans
quel ordre, avec guide / snippet / conteneur GTM sur mesure), où chaque « fait »
est prouvé.

**Architecture :** un catalogue déclaratif d'items (en code) + un moteur de
vérification pur (`Facts` → `Outcome`) alimenté par des collecteurs injectables
(page HTML, navigateur headless, lecteur Google GA4/Search Console). L'état
courant est persisté dans deux nouvelles tables (`website_profiles`,
`measurement_item_statuses`). Une API REST expose le plan ; le frontend ajoute
une page « Plan de mesure ».

**Stack :** Python 3.12 / FastAPI async / SQLAlchemy 2 (asyncpg) / Alembic /
httpx / Playwright (existant) ; Next.js 16 / React 19 / Tailwind v4.

**Spec :** `docs/superpowers/specs/2026-09-24-measurement-plan-design.md`
(feuille de route : `2026-09-24-roadmap-v2.md`). La spec est l'autorité ; ce plan
en est l'argumentation.

## Contraintes globales (valables pour toutes les tâches)

- **Aucune écriture dans les comptes Google, aucun nouveau scope OAuth.** Lecture
  seule via les scopes déjà demandés (`analytics.readonly`, `webmasters.readonly`).
- **Le code décide des statuts, jamais un LLM.**
- **Jamais « fait » sans preuve.** GA4 non connecté ⇒ jamais l'état `received`.
- **Additif** : 2 tables, 1 migration ; aucun changement de comportement des
  endpoints existants ; les tests existants restent verts sans modification
  (hors ajout de noms de tables à `EXPECTED_TABLES`).
- **Aucun appel réseau en test.** Le vrai navigateur headless (`verify_gtm`) n'est
  jamais exécuté en test ; il est injecté et remplacé par une fonction factice.
- **Qualité** : `cd backend && .venv/Scripts/python.exe -m pytest -W error -q` vert,
  `uv run ruff check app tests` propre (si `uv` n'est pas sur le PATH :
  `"$APPDATA/Python/Python312/Scripts/uv.exe"`), `alembic check` propre ;
  `cd frontend && npm run build && npm run lint` à 0 erreur / 0 warning.
- **Textes utilisateur en français.** Direction artistique du frontend : aucune
  couleur décorative, uniquement les couleurs de statut (`text-ok`, `text-warn`,
  `text-danger`, `bg-ok`…), cartes `rounded-xl border border-white/[0.08]
  bg-surface/60 p-5`.
- Tests : fixtures de `backend/tests/conftest.py` (`authed_client`, `make_user`,
  `owner_workspace_id`, `db_session`) ; créer les sites directement en base
  (`Website(workspace_id=…, domain=…, display_name=…)`) plutôt que via
  `POST /websites` (évite tout réseau).
- Conventions git : messages de commit en français, un commit par tâche, jamais de
  `--no-verify`, jamais de push.

## Arbitrages par rapport à la spec (à respecter)

1. Tables au **pluriel** (`website_profiles`, `measurement_item_statuses`), comme
   `websites` / `audit_snapshots`.
2. Un item porte **un** `check` (un type de vérification) qui évalue lui-même les
   niveaux « présent » puis « reçu » ; la spec parlait d'une liste de vérifications.
3. `website_profiles` gagne `headless_result` (JSONB) et `headless_checked_at` :
   le dernier résultat du navigateur est conservé pour que les statuts ne
   « clignotent » pas entre deux vérifications, et un **délai de 5 minutes** entre
   deux exécutions headless remplace la « limitation » de la spec (l'endpoint
   headless existant n'en a pas ; seul l'outil agent en a une).
4. « Search Console connectée » n'existe **qu'une fois** (couche SEO) ; la spec la
   listait aussi dans les fondations.
5. Trois items ne sont pas lisibles sans l'API Ads (Conversion Linker, balisage
   automatique, audiences de remarketing) : ils sont **manuels** — le
   propriétaire les marque « faits » (`manual_done`).
6. Nouveau paramètre de profil `uses_google_ads` : `false` ⇒ toute la couche
   publicité devient « non concernée ».
7. Le conteneur GTM sur mesure **n'inclut pas Consent Mode** (fourni comme snippet)
   et inclut la balise de conversion Ads (`awct`) et le Conversion Linker
   (`gclidw`) : ces deux types doivent être **validés par un import réel** dans un
   conteneur GTM de test (Tâche 8, étape finale) avant la mise en ligne.
8. `POST …/gtm-container` renvoie `{container, warnings, filename}` (le frontend
   fabrique le fichier), pas un téléchargement direct.

## Structure des fichiers

Backend (nouveaux) :
- `app/models/website_profile.py`, `app/models/measurement_item_status.py`
- `alembic/versions/8f2a6c41d7b3_measurement_plan.py`
- `app/services/measurement/` : `__init__.py`, `types.py`, `catalog.py`,
  `site_types.py`, `checks.py`, `fetch.py`, `google_reader.py`,
  `google_access.py`, `event_snippets.py`, `service.py`
- `app/api/v1/endpoints/measurement.py`

Backend (modifiés) : `app/models/__init__.py`, `app/services/gtm_headless.py`,
`app/services/gtm_generator.py`, `app/api/deps.py`, `app/api/v1/router.py`,
`tests/test_migrations.py` (ajout de 2 noms à `EXPECTED_TABLES`).

Frontend (nouveaux) : `lib/api/measurement.ts`, `lib/api/use-is-owner.ts`,
`app/(shell)/plan/page.tsx`, `components/plan/` (`plan-view.tsx`,
`plan-progress.tsx`, `profile-confirm.tsx`, `plan-item-row.tsx`,
`item-drawer.tsx`, `ads-settings.tsx`, `container-builder.tsx`,
`labels.ts`), `components/overview/plan-progress-card.tsx`.
Frontend (modifiés) : `lib/shell/routes.ts`, `components/overview/overview-view.tsx`,
`components/conseiller/advisor-view.tsx`.

## Ordre des tâches et dépendances

1 Modèles+migration → 2 Types+catalogue → 3 Détection du type de site →
4 Extension headless → 5 Lecteur Google → 6 Vérifications (pures) →
7 Snippets d'événements → 8 Conteneur GTM sur mesure → 9 Service + dépendances →
10 API → 11 Client frontend → 12 Page Plan de mesure → 13 Carte d'avancement +
préremplissage du conseiller → 14 Vérification finale.

---

### Tâche 1 : Modèles et migration

**Fichiers :**
- Créer : `backend/app/models/website_profile.py`
- Créer : `backend/app/models/measurement_item_status.py`
- Modifier : `backend/app/models/__init__.py`
- Créer : `backend/alembic/versions/8f2a6c41d7b3_measurement_plan.py`
- Modifier : `backend/tests/test_migrations.py` (`EXPECTED_TABLES`)
- Test : `backend/tests/test_measurement_models.py`

**Interfaces :**
- Produit : `WebsiteProfile` (PK `website_id`), `MeasurementItemStatus` (PK
  `(website_id, item_id)`), importables depuis `app.models`.

- [ ] **Étape 1 : écrire le test qui échoue**

```python
# backend/tests/test_measurement_models.py
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.measurement_item_status import MeasurementItemStatus
from app.models.website import Website
from app.models.website_profile import WebsiteProfile
from tests.conftest import owner_workspace_id


async def _site(db_session: AsyncSession, make_user, domain: str) -> Website:
    user = await make_user(sub=f"mm-{domain}")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=domain, display_name=domain)
    db_session.add(site)
    await db_session.flush()
    return site


async def test_profile_and_status_roundtrip(db_session: AsyncSession, make_user) -> None:
    site = await _site(db_session, make_user, "mm-roundtrip.test")
    db_session.add(
        WebsiteProfile(
            website_id=site.id,
            detected_types=[{"type": "ecommerce", "confidence": 0.8, "signals": ["shopify"]}],
            params={"ads_conversion_id": "AW-123456789"},
        )
    )
    db_session.add(
        MeasurementItemStatus(
            website_id=site.id,
            item_id="gtm_installed",
            state="on_page",
            evidence={"containers": ["GTM-AAAA111"]},
            checked_at=datetime.now(UTC),
        )
    )
    await db_session.flush()

    profile = (
        await db_session.execute(select(WebsiteProfile).where(WebsiteProfile.website_id == site.id))
    ).scalar_one()
    assert profile.confirmed_types is None
    assert profile.params == {"ads_conversion_id": "AW-123456789"}
    assert profile.headless_result is None

    row = (
        await db_session.execute(
            select(MeasurementItemStatus).where(MeasurementItemStatus.website_id == site.id)
        )
    ).scalar_one()
    assert row.evidence == {"containers": ["GTM-AAAA111"]}
    assert row.dismissed_at is None
    assert row.reason is None


async def test_status_primary_key_is_unique_per_site_and_item(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "mm-unique.test")
    now = datetime.now(UTC)
    db_session.add(
        MeasurementItemStatus(
            website_id=site.id, item_id="ga4_tag", state="missing", evidence={}, checked_at=now
        )
    )
    await db_session.flush()
    db_session.add(
        MeasurementItemStatus(
            website_id=site.id, item_id="ga4_tag", state="on_page", evidence={}, checked_at=now
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_rows_are_deleted_with_the_website(db_session: AsyncSession, make_user) -> None:
    site = await _site(db_session, make_user, "mm-cascade.test")
    db_session.add(WebsiteProfile(website_id=site.id, detected_types=[], params={}))
    db_session.add(
        MeasurementItemStatus(
            website_id=site.id,
            item_id="gtm_installed",
            state="missing",
            evidence={},
            checked_at=datetime.now(UTC),
        )
    )
    await db_session.flush()

    await db_session.delete(site)
    await db_session.flush()
    db_session.expunge_all()

    assert (await db_session.execute(select(WebsiteProfile))).first() is None
    assert (await db_session.execute(select(MeasurementItemStatus))).first() is None
```

Lancer : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_measurement_models.py -v`
Attendu : ÉCHEC (`ModuleNotFoundError: app.models.measurement_item_status`).

- [ ] **Étape 2 : créer les modèles**

```python
# backend/app/models/website_profile.py
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WebsiteProfile(Base):
    """Profil de mesure d'un site : types détectés / confirmés, réglages du plan,
    dernier résultat du navigateur headless. Une ligne par site."""

    __tablename__ = "website_profiles"

    website_id: Mapped[UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), primary_key=True
    )
    # [{"type": "ecommerce", "confidence": 0.8, "signals": ["..."]}, ...]
    detected_types: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    # Types validés par le propriétaire ; prime sur `detected_types`.
    confirmed_types: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ga4_measurement_id, ads_conversion_id, ads_conversion_label, uses_google_ads
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    headless_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    headless_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

```python
# backend/app/models/measurement_item_status.py
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MeasurementItemStatus(Base):
    """État courant d'un item du catalogue de mesure pour un site.

    `state` est une chaîne validée côté code (pas de pg_enum : le catalogue et ses
    états évoluent sans migration de contrainte CHECK)."""

    __tablename__ = "measurement_item_statuses"

    website_id: Mapped[UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    # Faits techniques uniquement (noms d'événements, IDs de balises, comptages).
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Dans `backend/app/models/__init__.py`, ajouter les imports (ordre alphabétique
des modules) et les noms dans `__all__` :

```python
from app.models.measurement_item_status import MeasurementItemStatus
...
from app.models.website_profile import WebsiteProfile
```
et dans `__all__` : `"MeasurementItemStatus"` (après `"IssueItem"`) et
`"WebsiteProfile"` (après `"WebsiteGoogleLink"`).

- [ ] **Étape 3 : écrire la migration**

```python
# backend/alembic/versions/8f2a6c41d7b3_measurement_plan.py
"""measurement plan tables

Revision ID: 8f2a6c41d7b3
Revises: 1d03150b69e5
Create Date: 2026-09-24 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f2a6c41d7b3"
down_revision: str | Sequence[str] | None = "1d03150b69e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "website_profiles",
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("detected_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confirmed_types", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("headless_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("headless_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name=op.f("fk_website_profiles_website_id_websites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("website_id", name=op.f("pk_website_profiles")),
    )
    op.create_table(
        "measurement_item_statuses",
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name=op.f("fk_measurement_item_statuses_website_id_websites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "website_id", "item_id", name=op.f("pk_measurement_item_statuses")
        ),
    )


def downgrade() -> None:
    op.drop_table("measurement_item_statuses")
    op.drop_table("website_profiles")
```

Dans `backend/tests/test_migrations.py`, ajouter `"website_profiles"` et
`"measurement_item_statuses"` à `EXPECTED_TABLES`.

- [ ] **Étape 4 : lancer les tests et le contrôle de schéma**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_measurement_models.py tests/test_migrations.py -v
uv run ruff check app tests
```
Attendu : tous verts (dont `test_models_match_migration`, qui échoue si la
migration et les modèles divergent). Puis suite complète :
`.venv/Scripts/python.exe -m pytest -W error -q` (aucune régression).

- [ ] **Étape 5 : commit**

```bash
git add backend/app/models backend/alembic/versions/8f2a6c41d7b3_measurement_plan.py backend/tests/test_measurement_models.py backend/tests/test_migrations.py
git commit -m "feat(measurement): tables website_profiles et measurement_item_statuses"
```

---

### Tâche 2 : Types et catalogue

**Fichiers :**
- Créer : `backend/app/services/measurement/__init__.py` (vide)
- Créer : `backend/app/services/measurement/types.py`
- Créer : `backend/app/services/measurement/catalog.py`
- Test : `backend/tests/test_measurement_catalog.py`

**Interfaces :**
- Produit : `MeasurementItem` (dataclass gelée), `Outcome`, `SITE_TYPES`,
  `ITEMS: tuple[MeasurementItem, ...]`, `ITEMS_BY_ID`, `LAYER_ORDER`,
  `is_applicable(item, types, uses_google_ads) -> bool`.
- Les `check` valides sont exactement : `gtm_installed`, `gtm_in_head`, `ga4_tag`,
  `no_double`, `consent`, `datalayer`, `event`, `purchase_params`, `key_events`,
  `key_events_value`, `ads_link`, `ads_conversion_tag`, `manual`, `gsc_linked`,
  `gsc_sitemaps`, `robots`, `tls` (constante `CHECK_KINDS`).

- [ ] **Étape 1 : écrire le test qui échoue**

```python
# backend/tests/test_measurement_catalog.py
from app.services.measurement.catalog import (
    ITEMS,
    ITEMS_BY_ID,
    LAYER_ORDER,
    is_applicable,
)
from app.services.measurement.types import CHECK_KINDS, SITE_TYPES


def test_ids_are_unique() -> None:
    assert len({item.id for item in ITEMS}) == len(ITEMS)
    assert set(ITEMS_BY_ID) == {item.id for item in ITEMS}


def test_every_item_is_complete() -> None:
    for item in ITEMS:
        assert item.title.strip(), item.id
        assert item.why.strip(), item.id
        assert item.guide, item.id
        assert all(step.strip() for step in item.guide), item.id
        assert item.check in CHECK_KINDS, item.id
        assert item.layer in LAYER_ORDER, item.id
        assert 1 <= item.weight <= 100, item.id
        assert "guide" in item.actions, item.id
        assert "advisor" in item.actions, item.id


def test_event_items_carry_their_event_name() -> None:
    for item in ITEMS:
        if item.check == "event":
            assert item.arg, item.id
            assert item.max_level == "received", item.id


def test_manual_items_are_capped_at_on_page() -> None:
    manual = [item for item in ITEMS if item.check == "manual"]
    assert {item.id for item in manual} == {
        "ads_conversion_linker",
        "ads_auto_tagging",
        "ads_remarketing",
    }
    assert all(item.max_level == "on_page" for item in manual)


def test_all_layers_and_site_types_are_covered() -> None:
    assert {item.layer for item in ITEMS} == set(LAYER_ORDER)
    covered: set[str] = set()
    for item in ITEMS:
        if item.applies_to is not None:
            covered |= set(item.applies_to)
    assert {"ecommerce", "lead_gen", "saas", "content"} <= covered
    assert set(SITE_TYPES) == {"ecommerce", "lead_gen", "saas", "content", "other"}


def test_snippet_and_gtm_actions_reference_a_snippet_event() -> None:
    for item in ITEMS:
        if "snippet" in item.actions:
            assert item.snippet_event, item.id


def test_is_applicable_by_type_and_ads_flag() -> None:
    purchase = ITEMS_BY_ID["event_purchase"]
    lead = ITEMS_BY_ID["event_generate_lead"]
    gtm = ITEMS_BY_ID["gtm_installed"]
    ads = ITEMS_BY_ID["ads_ga4_link"]

    assert is_applicable(purchase, ("ecommerce",), None)
    assert not is_applicable(purchase, ("lead_gen",), None)
    assert is_applicable(lead, ("lead_gen", "content"), None)
    assert is_applicable(gtm, ("other",), None)  # applies_to=None : tous les sites
    assert is_applicable(ads, ("ecommerce",), None)
    assert is_applicable(ads, ("ecommerce",), True)
    assert not is_applicable(ads, ("ecommerce",), False)
```

Lancer : `.venv/Scripts/python.exe -m pytest tests/test_measurement_catalog.py -v` → ÉCHEC (module absent).

- [ ] **Étape 2 : créer `types.py`**

```python
# backend/app/services/measurement/types.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Layer = Literal["foundations", "events", "conversions", "ads", "seo"]
SiteType = Literal["ecommerce", "lead_gen", "saas", "content", "other"]
State = Literal[
    "unknown",
    "missing",
    "on_page",
    "received",
    "unverifiable",
    "not_applicable",
    "dismissed",
]
Level = Literal["on_page", "received"]
ActionKind = Literal["guide", "snippet", "gtm_container", "advisor", "pr"]

SITE_TYPES: tuple[SiteType, ...] = ("ecommerce", "lead_gen", "saas", "content", "other")

CHECK_KINDS: frozenset[str] = frozenset(
    {
        "gtm_installed",
        "gtm_in_head",
        "ga4_tag",
        "no_double",
        "consent",
        "datalayer",
        "event",
        "purchase_params",
        "key_events",
        "key_events_value",
        "ads_link",
        "ads_conversion_tag",
        "manual",
        "gsc_linked",
        "gsc_sitemaps",
        "robots",
        "tls",
    }
)


@dataclass(frozen=True, slots=True)
class MeasurementItem:
    id: str
    layer: Layer
    # None = tous les sites ; sinon ensemble de types concernés.
    applies_to: frozenset[SiteType] | None
    weight: int  # 1..100, plus grand = plus prioritaire
    quick_win: bool
    title: str
    why: str  # explication novice, en français
    check: str  # une valeur de CHECK_KINDS
    arg: str | None  # ex. nom de l'événement pour check == "event"
    max_level: Level  # plus haut niveau de preuve atteignable
    guide: tuple[str, ...]
    actions: tuple[ActionKind, ...]
    snippet_event: str | None = None


@dataclass(frozen=True, slots=True)
class Outcome:
    state: State
    evidence: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
```

- [ ] **Étape 3 : créer `catalog.py`**

```python
# backend/app/services/measurement/catalog.py
"""Catalogue des items du plan de mesure.

Contenu produit : les textes (`title`, `why`, `guide`) sont relus et validés par le
propriétaire du produit avant mise en ligne, pas seulement par les tests.
"""

from __future__ import annotations

from app.services.measurement.types import (
    ActionKind,
    Layer,
    MeasurementItem,
    SiteType,
)

LAYER_ORDER: tuple[Layer, ...] = ("foundations", "events", "conversions", "ads", "seo")

_ECOM: frozenset[SiteType] = frozenset({"ecommerce"})
_LEAD: frozenset[SiteType] = frozenset({"lead_gen"})
_SAAS: frozenset[SiteType] = frozenset({"saas"})
_CONTENT: frozenset[SiteType] = frozenset({"content"})
_LEAD_SAAS: frozenset[SiteType] = frozenset({"lead_gen", "saas"})

_EVENT_ACTIONS: tuple[ActionKind, ...] = ("guide", "snippet", "gtm_container", "advisor")
_AUTO_ACTIONS: tuple[ActionKind, ...] = ("guide", "advisor")


def _event_guide(place: str) -> tuple[str, ...]:
    return (
        f"Repère où l'action se produit sur ton site : {place}.",
        "Ouvre l'onglet « Snippet » de cette ligne et copie le code fourni à cet "
        "endroit (ou transmets-le à ton développeur).",
        "Vérifie dans GA4, rapport « Temps réel », que l'événement apparaît quand tu "
        "fais l'action toi-même.",
        "Reviens ici et clique sur « Vérifier maintenant » : la ligne passe à « Reçu par "
        "GA4 » dès que GA4 a traité les données (jusqu'à 24 h).",
    )


def _event(
    *,
    event: str,
    applies_to: frozenset[SiteType],
    weight: int,
    title: str,
    why: str,
    place: str,
    quick_win: bool = False,
) -> MeasurementItem:
    return MeasurementItem(
        id=f"event_{event}",
        layer="events",
        applies_to=applies_to,
        weight=weight,
        quick_win=quick_win,
        title=title,
        why=why,
        check="event",
        arg=event,
        max_level="received",
        guide=_event_guide(place),
        actions=_EVENT_ACTIONS,
        snippet_event=event,
    )


def _auto_event(
    *,
    item_id: str,
    event: str,
    applies_to: frozenset[SiteType],
    weight: int,
    title: str,
    why: str,
    guide: tuple[str, ...],
) -> MeasurementItem:
    """Événement mesuré automatiquement par GA4 (« mesures améliorées »)."""
    return MeasurementItem(
        id=item_id,
        layer="events",
        applies_to=applies_to,
        weight=weight,
        quick_win=True,
        title=title,
        why=why,
        check="event",
        arg=event,
        max_level="received",
        guide=guide,
        actions=_AUTO_ACTIONS,
        snippet_event=None,
    )


_FOUNDATIONS: tuple[MeasurementItem, ...] = (
    MeasurementItem(
        id="gtm_installed",
        layer="foundations",
        applies_to=None,
        weight=100,
        quick_win=True,
        title="Google Tag Manager installé",
        why=(
            "GTM est la boîte à outils qui te permet d'ajouter le suivi (GA4, publicité, "
            "événements) sans modifier le code du site à chaque fois."
        ),
        check="gtm_installed",
        arg=None,
        max_level="on_page",
        guide=(
            "Crée un compte et un conteneur de type « Web » sur tagmanager.google.com.",
            "Copie les deux extraits de code fournis : le premier dans le <head> de toutes "
            "les pages, le second juste après l'ouverture de <body>.",
            "Publie le conteneur dans GTM.",
            "Reviens ici et clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="gtm_in_head",
        layer="foundations",
        applies_to=None,
        weight=70,
        quick_win=True,
        title="Snippet GTM placé dans le <head>",
        why=(
            "Placé plus bas dans la page, le snippet se charge trop tard : les premières "
            "actions du visiteur ne sont pas mesurées."
        ),
        check="gtm_in_head",
        arg=None,
        max_level="on_page",
        guide=(
            "Repère l'extrait GTM (il contient « googletagmanager.com/gtm.js »).",
            "Déplace-le le plus haut possible dans le <head>, avant les autres scripts.",
            "Reviens ici et clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="ga4_tag",
        layer="foundations",
        applies_to=None,
        weight=100,
        quick_win=True,
        title="Balise Google Analytics 4 active",
        why=(
            "Sans elle, aucun visiteur n'est compté. C'est la base de toute mesure : trafic, "
            "sources, conversions."
        ),
        check="ga4_tag",
        arg=None,
        max_level="received",
        guide=(
            "Dans GA4, crée une propriété puis un flux de données « Web » et note l'ID de "
            "mesure (il commence par G-).",
            "Dans « Mon conteneur GTM » (plus bas sur cette page), génère le conteneur avec "
            "cette balise, importe-le dans GTM (Administration > Importer un conteneur) et "
            "publie.",
            "Dans « Connexions Google », connecte ton compte pour que la plateforme voie "
            "les données arriver.",
            "Clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "gtm_container", "advisor"),
        snippet_event=None,
    ),
    MeasurementItem(
        id="no_double_tracking",
        layer="foundations",
        applies_to=None,
        weight=60,
        quick_win=False,
        title="Pas de double comptage GA4",
        why=(
            "Si GA4 est ajouté dans le code du site ET dans GTM, chaque visite est comptée "
            "deux fois et tes chiffres sont faux."
        ),
        check="no_double",
        arg=None,
        max_level="on_page",
        guide=(
            "Retire du code du site la balise GA4 codée en dur (le script « gtag/js »).",
            "Garde uniquement la balise GA4 gérée dans GTM.",
            "Reviens ici et clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="consent_mode",
        layer="foundations",
        applies_to=None,
        weight=65,
        quick_win=False,
        title="Consentement aux cookies et Consent Mode v2",
        why=(
            "Pour les visiteurs européens, la loi impose de demander le consentement. "
            "Consent Mode permet de continuer à mesurer sans cookies quand le visiteur "
            "refuse, et Google Ads l'exige pour la publicité personnalisée."
        ),
        check="consent",
        arg=None,
        max_level="on_page",
        guide=(
            "Installe une bannière de consentement compatible Consent Mode v2 (Cookiebot, "
            "Axeptio, Didomi, etc.).",
            "Vérifie qu'elle envoie l'état « par défaut : refusé » avant le chargement de GTM.",
            "Si ta bannière ne le fait pas, ajoute le snippet « consent default » fourni, "
            "placé avant le snippet GTM.",
            "Clique sur « Vérifier maintenant » (avec « en conditions réelles » pour une "
            "preuve fiable).",
        ),
        actions=("guide", "snippet", "advisor"),
        snippet_event="consent_default",
    ),
    MeasurementItem(
        id="datalayer_standard",
        layer="foundations",
        applies_to=None,
        weight=40,
        quick_win=False,
        title="dataLayer au nom standard",
        why=(
            "Les outils de test et de nombreux modèles de tags supposent le nom « dataLayer ». "
            "Un autre nom casse ces intégrations sans prévenir."
        ),
        check="datalayer",
        arg=None,
        max_level="on_page",
        guide=(
            "Dans le snippet GTM, repère le dernier paramètre (par défaut « dataLayer »).",
            "Remets-le à « dataLayer » (et adapte le code du site qui poussait vers l'ancien nom).",
            "Reviens ici et clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
)

_EVENTS: tuple[MeasurementItem, ...] = (
    # --- Boutique -----------------------------------------------------------
    _event(
        event="view_item",
        applies_to=_ECOM,
        weight=60,
        title="Vue d'une fiche produit",
        why="Sans cet événement, tu ne sais pas quels produits attirent l'attention avant l'achat.",
        place="sur chaque fiche produit, au chargement de la page",
    ),
    _event(
        event="add_to_cart",
        applies_to=_ECOM,
        weight=70,
        title="Ajout au panier",
        why=(
            "Il mesure l'intention d'achat : l'écart avec les achats montre où tu perds des "
            "clients."
        ),
        place="au clic sur le bouton « ajouter au panier »",
    ),
    _event(
        event="begin_checkout",
        applies_to=_ECOM,
        weight=70,
        title="Début du paiement",
        why=(
            "Il isole les abandons au moment de payer, l'endroit où une amélioration rapporte "
            "le plus."
        ),
        place="à l'ouverture de la page de paiement",
    ),
    _event(
        event="purchase",
        applies_to=_ECOM,
        weight=95,
        title="Achat",
        why=(
            "C'est ta conversion principale : sans elle, impossible de savoir combien te "
            "rapporte chaque source de trafic ni de piloter des campagnes."
        ),
        place="sur la page de confirmation de commande, une seule fois par commande",
        quick_win=True,
    ),
    MeasurementItem(
        id="purchase_params",
        layer="events",
        applies_to=_ECOM,
        weight=90,
        quick_win=False,
        title="Achat avec montant, devise et numéro de commande",
        why=(
            "Un achat sans montant ne dit pas combien tu gagnes : les revenus restent à zéro "
            "dans GA4 et dans tes campagnes."
        ),
        check="purchase_params",
        arg=None,
        max_level="received",
        guide=(
            "Dans le code de la confirmation de commande, renseigne « value » (montant), "
            "« currency » (EUR) et « transaction_id » (numéro de commande).",
            "Utilise le snippet de la ligne « Achat » comme modèle.",
            "Fais une commande test, puis clique sur « Vérifier maintenant » le lendemain.",
        ),
        actions=("guide", "snippet", "advisor"),
        snippet_event="purchase",
    ),
    # --- Prise de contact ---------------------------------------------------
    _event(
        event="generate_lead",
        applies_to=_LEAD,
        weight=95,
        title="Demande de contact envoyée",
        why=(
            "C'est ta conversion principale : chaque demande envoyée est un client potentiel "
            "qu'il faut pouvoir rattacher à sa source."
        ),
        place="après l'envoi réussi du formulaire de contact ou de devis",
        quick_win=True,
    ),
    _event(
        event="click_to_call",
        applies_to=_LEAD,
        weight=75,
        title="Clic sur ton numéro de téléphone",
        why=(
            "Beaucoup de clients appellent au lieu d'écrire ; sans ce suivi, ces contacts "
            "sont invisibles."
        ),
        place="au clic sur un lien téléphone (tel:)",
    ),
    _event(
        event="click_email",
        applies_to=_LEAD,
        weight=55,
        title="Clic sur ton adresse e-mail",
        why="Il compte les visiteurs qui préfèrent t'écrire depuis leur messagerie.",
        place="au clic sur un lien e-mail (mailto:)",
    ),
    _event(
        event="click_whatsapp",
        applies_to=_LEAD,
        weight=55,
        title="Clic sur WhatsApp",
        why="Il compte les contacts qui passent par WhatsApp, souvent invisibles autrement.",
        place="au clic sur le bouton ou le lien WhatsApp",
    ),
    _auto_event(
        item_id="event_file_download",
        event="file_download",
        applies_to=_LEAD,
        weight=40,
        title="Téléchargement de document",
        why="Brochures et catalogues téléchargés signalent un visiteur sérieux.",
        guide=(
            "Dans GA4 : Administration > Flux de données > ton flux web > « Mesures améliorées ».",
            "Vérifie que l'option « Téléchargements de fichiers » est activée.",
            "Télécharge un PDF sur ton site, puis clique sur « Vérifier maintenant » le lendemain.",
        ),
    ),
    # --- SaaS ---------------------------------------------------------------
    _event(
        event="sign_up",
        applies_to=_SAAS,
        weight=95,
        title="Création de compte",
        why=(
            "C'est ta conversion principale : elle te dit quelles sources de trafic amènent de "
            "vrais utilisateurs."
        ),
        place="après la création réussie du compte",
        quick_win=True,
    ),
    _event(
        event="login",
        applies_to=_SAAS,
        weight=60,
        title="Connexion",
        why="Elle montre combien d'utilisateurs reviennent, un signal clé de rétention.",
        place="après une connexion réussie",
    ),
    _event(
        event="begin_trial",
        applies_to=_SAAS,
        weight=80,
        title="Démarrage d'un essai",
        why="Il mesure le passage de l'inscription à l'essai réel de ton produit.",
        place="au démarrage effectif de l'essai gratuit",
    ),
    _event(
        event="subscribe",
        applies_to=_SAAS,
        weight=90,
        title="Abonnement payant",
        why="C'est le moment où un utilisateur devient un client : sans lui, pas de rentabilité mesurable.",
        place="après la souscription à une offre payante",
    ),
    _event(
        event="tutorial_complete",
        applies_to=_SAAS,
        weight=50,
        title="Onboarding terminé",
        why="Les utilisateurs qui terminent l'onboarding restent plus longtemps : suis-le pour l'améliorer.",
        place="quand l'utilisateur termine les premières étapes guidées",
    ),
    # --- Contenu ------------------------------------------------------------
    _event(
        event="newsletter_signup",
        applies_to=_CONTENT,
        weight=80,
        title="Inscription à la newsletter",
        why="C'est la conversion principale d'un site de contenu : elle transforme un lecteur en audience.",
        place="après l'inscription réussie à la newsletter",
        quick_win=True,
    ),
    _auto_event(
        item_id="event_outbound_click",
        event="click",
        applies_to=_CONTENT,
        weight=40,
        title="Clics vers d'autres sites",
        why="Il montre vers quels sites tes lecteurs partent, utile pour tes partenariats et affiliations.",
        guide=(
            "Dans GA4 : Administration > Flux de données > ton flux web > « Mesures améliorées ».",
            "Vérifie que l'option « Clics sortants » est activée.",
            "Clique sur un lien externe de ton site, puis « Vérifier maintenant » le lendemain.",
        ),
    ),
    _auto_event(
        item_id="event_site_search",
        event="view_search_results",
        applies_to=_CONTENT,
        weight=35,
        title="Recherche interne",
        why="Ce que tes visiteurs cherchent te dit quel contenu il te manque.",
        guide=(
            "Dans GA4 : Administration > Flux de données > ton flux web > « Mesures améliorées ».",
            "Active « Recherche sur le site » et vérifie le paramètre d'URL de recherche (souvent « q » ou « s »).",
            "Fais une recherche sur ton site, puis « Vérifier maintenant » le lendemain.",
        ),
    ),
    _event(
        event="share",
        applies_to=_CONTENT,
        weight=30,
        title="Partage d'un contenu",
        why="Le partage mesure les contenus qui se diffusent d'eux-mêmes.",
        place="au clic sur un bouton de partage",
    ),
)

_CONVERSIONS: tuple[MeasurementItem, ...] = (
    MeasurementItem(
        id="key_events_marked",
        layer="conversions",
        applies_to=None,
        weight=90,
        quick_win=True,
        title="Événements clés (conversions) déclarés dans GA4",
        why=(
            "Tant qu'un événement n'est pas marqué comme « événement clé », GA4 ne le compte "
            "pas comme une conversion : les rapports et Google Ads ne s'en servent pas."
        ),
        check="key_events",
        arg=None,
        max_level="received",
        guide=(
            "Dans GA4 : Administration > Événements (ou « Événements clés »).",
            "Repère ton événement principal (achat, demande de contact, inscription).",
            "Active « Marquer comme événement clé ».",
            "Clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="conversion_value",
        layer="conversions",
        applies_to=_LEAD_SAAS,
        weight=50,
        quick_win=False,
        title="Valeur attribuée à tes conversions",
        why=(
            "Donner une valeur (même estimée) à un contact ou une inscription permet de "
            "comparer les sources de trafic par rentabilité et d'optimiser les campagnes."
        ),
        check="key_events_value",
        arg=None,
        max_level="received",
        guide=(
            "Estime la valeur moyenne d'une conversion (par exemple 50 € par contact).",
            "Dans GA4 > Événements clés, ouvre ton événement principal et renseigne la valeur "
            "par défaut.",
            "Clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
)

_ADS: tuple[MeasurementItem, ...] = (
    MeasurementItem(
        id="ads_ga4_link",
        layer="ads",
        applies_to=None,
        weight=70,
        quick_win=True,
        title="GA4 lié à Google Ads",
        why=(
            "Le lien permet à Google Ads de voir les conversions GA4 et de créer des audiences "
            "de remarketing à partir de tes visiteurs."
        ),
        check="ads_link",
        arg=None,
        max_level="received",
        guide=(
            "Dans GA4 : Administration > Association de produits > Liens Google Ads.",
            "Clique sur « Associer », choisis ton compte Google Ads et active la "
            "personnalisation des annonces.",
            "Clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="ads_conversion_tag",
        layer="ads",
        applies_to=None,
        weight=75,
        quick_win=False,
        title="Balise de conversion Google Ads",
        why=(
            "Elle indique à Google Ads quelles annonces ont mené à une vente ou un contact ; "
            "sans elle, les campagnes ne peuvent pas s'améliorer."
        ),
        check="ads_conversion_tag",
        arg=None,
        max_level="on_page",
        guide=(
            "Dans Google Ads : Objectifs > Conversions > Nouvelle action de conversion, choisis "
            "« Site web ».",
            "Note l'ID de conversion (AW-…) et le libellé de conversion.",
            "Saisis-les dans « Réglages Ads » sur cette page, génère « Mon conteneur GTM » et "
            "importe-le dans GTM.",
            "Clique sur « Vérifier maintenant » avec « en conditions réelles ».",
        ),
        actions=("guide", "gtm_container", "advisor"),
    ),
    MeasurementItem(
        id="ads_conversion_linker",
        layer="ads",
        applies_to=None,
        weight=55,
        quick_win=False,
        title="Conversion Linker",
        why=(
            "Il conserve l'origine de la visite publicitaire (clic sur une annonce) pour que la "
            "conversion lui soit bien attribuée, malgré les restrictions des navigateurs."
        ),
        check="manual",
        arg=None,
        max_level="on_page",
        guide=(
            "Dans GTM, crée une balise « Conversion Linker » déclenchée sur toutes les pages "
            "(elle est incluse dans « Mon conteneur GTM » si tu coches cette ligne).",
            "Publie le conteneur.",
            "Marque cette ligne comme faite.",
        ),
        actions=("guide", "gtm_container", "advisor"),
    ),
    MeasurementItem(
        id="ads_auto_tagging",
        layer="ads",
        applies_to=None,
        weight=60,
        quick_win=True,
        title="Balisage automatique (gclid)",
        why=(
            "Il ajoute un identifiant à chaque clic sur ton annonce ; sans lui, Google Ads ne "
            "peut pas relier les visites à tes conversions."
        ),
        check="manual",
        arg=None,
        max_level="on_page",
        guide=(
            "Dans Google Ads : Administration > Paramètres du compte > Suivi.",
            "Active « Balisage automatique du résultat des URL finales ».",
            "Marque cette ligne comme faite.",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="ads_remarketing",
        layer="ads",
        applies_to=None,
        weight=45,
        quick_win=False,
        title="Audiences de remarketing",
        why=(
            "Elles permettent de re-cibler les visiteurs qui n'ont pas converti, souvent le "
            "levier le moins cher pour ramener des clients."
        ),
        check="manual",
        arg=None,
        max_level="on_page",
        guide=(
            "Dans GA4 : Administration > Audiences > Nouvelle audience.",
            "Crée par exemple « Visiteurs ayant ajouté au panier sans acheter ».",
            "Vérifie que l'audience est partagée avec Google Ads (lien GA4 - Ads).",
            "Marque cette ligne comme faite.",
        ),
        actions=("guide", "advisor"),
    ),
)

_SEO: tuple[MeasurementItem, ...] = (
    MeasurementItem(
        id="gsc_property_linked",
        layer="seo",
        applies_to=None,
        weight=80,
        quick_win=True,
        title="Search Console connectée",
        why=(
            "Search Console te dit quelles pages Google indexe et sur quelles recherches tu "
            "apparais : sans elle, ton SEO est aveugle."
        ),
        check="gsc_linked",
        arg=None,
        max_level="received",
        guide=(
            "Vérifie ton site sur search.google.com/search-console (propriété de domaine).",
            "Dans « Connexions Google » de la plateforme, connecte ton compte puis choisis la "
            "propriété.",
            "Clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="gsc_sitemaps",
        layer="seo",
        applies_to=None,
        weight=60,
        quick_win=True,
        title="Sitemap envoyé à Google",
        why=(
            "Le sitemap liste les pages à indexer ; sans lui, Google peut mettre longtemps à "
            "découvrir tes nouvelles pages."
        ),
        check="gsc_sitemaps",
        arg=None,
        max_level="received",
        guide=(
            "Génère ou repère l'adresse de ton sitemap (souvent /sitemap.xml).",
            "Dans Search Console : Sitemaps > ajoute cette adresse.",
            "Clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="robots_txt",
        layer="seo",
        applies_to=None,
        weight=40,
        quick_win=True,
        title="robots.txt accessible",
        why=(
            "Ce fichier dit aux robots ce qu'ils peuvent explorer ; s'il est absent ou en "
            "erreur, l'exploration peut être perturbée."
        ),
        check="robots",
        arg=None,
        max_level="on_page",
        guide=(
            "Crée un fichier robots.txt à la racine du site (https://ton-site/robots.txt).",
            "Il doit répondre normalement (code 200) et pointer vers ton sitemap.",
            "Clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="tls_valid",
        layer="seo",
        applies_to=None,
        weight=85,
        quick_win=True,
        title="Certificat HTTPS valide",
        why=(
            "Sans certificat valide, les navigateurs affichent un avertissement qui fait fuir "
            "les visiteurs et pénalise ton référencement."
        ),
        check="tls",
        arg=None,
        max_level="on_page",
        guide=(
            "Renouvelle le certificat chez ton hébergeur.",
            "Active le renouvellement automatique (par exemple Let's Encrypt).",
            "Clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
)

ITEMS: tuple[MeasurementItem, ...] = (
    *_FOUNDATIONS,
    *_EVENTS,
    *_CONVERSIONS,
    *_ADS,
    *_SEO,
)
ITEMS_BY_ID: dict[str, MeasurementItem] = {item.id: item for item in ITEMS}


def is_applicable(
    item: MeasurementItem, types: tuple[str, ...] | list[str], uses_google_ads: bool | None
) -> bool:
    """Vrai si l'item concerne le site : types effectifs et réglage « publicité »."""
    if item.layer == "ads" and uses_google_ads is False:
        return False
    if item.applies_to is None:
        return True
    return bool(set(types) & set(item.applies_to))
```

- [ ] **Étape 4 : lancer les tests**

`.venv/Scripts/python.exe -m pytest tests/test_measurement_catalog.py -v` → tous verts ;
`uv run ruff check app tests` propre.

- [ ] **Étape 5 : commit**

```bash
git add backend/app/services/measurement backend/tests/test_measurement_catalog.py
git commit -m "feat(measurement): types et catalogue des items du plan de mesure"
```

---

### Tâche 3 : Détection du type de site

**Fichiers :**
- Créer : `backend/app/services/measurement/site_types.py`
- Test : `backend/tests/test_measurement_site_types.py`

**Interfaces :**
- Produit : `detect_site_types(html: str, stack: StackKind | None = None) ->
  list[dict]` (éléments `{"type", "confidence", "signals"}`, triés par confiance
  décroissante, jamais vide) ;
  `resolve_effective_types(detected: list[dict], confirmed: list[str] | None) ->
  list[str]`.

- [ ] **Étape 1 : écrire le test qui échoue**

```python
# backend/tests/test_measurement_site_types.py
from app.models.enums import StackKind
from app.services.measurement.site_types import detect_site_types, resolve_effective_types

_SHOP = """
<html><head><script type="application/ld+json">{"@type": "Product", "name": "T-shirt"}</script>
<script src="https://cdn.shopify.com/s/files/app.js"></script></head>
<body><button class="add-to-cart">Ajouter au panier</button><a href="/cart">Panier</a></body></html>
"""
_LEADS = """
<html><body><h1>Plombier à Lyon</h1><a href="tel:+33400000000">Appeler</a>
<form action="/contact"><input name="email"></form><p>Demandez un devis gratuit</p></body></html>
"""
_SAAS = """
<html><body><a href="/pricing">Tarifs</a><a href="/login">Connexion</a>
<button>Essai gratuit</button><a href="/signup">Créer un compte</a></body></html>
"""
_BLOG = """
<html><head><script type="application/ld+json">{"@type": "BlogPosting"}</script></head>
<body><article><h1>Mon article</h1></article><a href="/blog">Blog</a></body></html>
"""


def _types(html: str, stack: StackKind | None = None) -> list[str]:
    return [g["type"] for g in detect_site_types(html, stack)]


def test_ecommerce_is_detected_first() -> None:
    guesses = detect_site_types(_SHOP)
    assert guesses[0]["type"] == "ecommerce"
    assert guesses[0]["confidence"] >= 0.8
    assert guesses[0]["signals"]


def test_lead_gen_saas_and_content_are_detected() -> None:
    assert _types(_LEADS)[0] == "lead_gen"
    assert _types(_SAAS)[0] == "saas"
    assert _types(_BLOG)[0] == "content"


def test_woocommerce_stack_alone_counts_as_ecommerce() -> None:
    assert _types("<html><body>Bienvenue</body></html>", StackKind.WOOCOMMERCE)[0] == "ecommerce"


def test_multiple_types_can_be_returned() -> None:
    both = _SHOP.replace("</body>", '<article>x</article><a href="/blog">Blog</a></body>')
    types = _types(both)
    assert "ecommerce" in types and "content" in types


def test_unknown_site_falls_back_to_other() -> None:
    guesses = detect_site_types("<html><body>Bonjour</body></html>")
    assert [g["type"] for g in guesses] == ["other"]
    assert guesses[0]["confidence"] == 0.5


def test_confidence_is_capped_at_one() -> None:
    assert all(g["confidence"] <= 1.0 for g in detect_site_types(_SHOP * 3))


def test_resolve_effective_types() -> None:
    detected = [
        {"type": "ecommerce", "confidence": 0.8, "signals": []},
        {"type": "content", "confidence": 0.35, "signals": []},
    ]
    assert resolve_effective_types(detected, ["saas", "lead_gen"]) == ["saas", "lead_gen"]
    assert resolve_effective_types(detected, None) == ["ecommerce"]
    weak = [{"type": "content", "confidence": 0.35, "signals": []}]
    assert resolve_effective_types(weak, None) == ["content"]
    assert resolve_effective_types([], None) == ["other"]
    assert resolve_effective_types([{"type": "other", "confidence": 0.5, "signals": []}], None) == [
        "other"
    ]
```

Lancer → ÉCHEC (module absent).

- [ ] **Étape 2 : implémenter**

```python
# backend/app/services/measurement/site_types.py
"""Détection heuristique du type de site (fonction pure, testée sur des fixtures HTML)."""

from __future__ import annotations

import re
from typing import Any

from app.models.enums import StackKind

_JSONLD_TYPE = re.compile(r'"@type"\s*:\s*"([A-Za-z]+)"')
_MIN_CONFIDENCE = 0.3
_PICK_CONFIDENCE = 0.5

_WORDS_CART = ("add-to-cart", "add_to_cart", "ajouter au panier", "add to cart")
_WORDS_LEAD = (
    "demander un devis",
    "demandez un devis",
    "devis gratuit",
    "contactez-nous",
    "prendre rendez-vous",
    "prendre rdv",
)
_WORDS_SAAS = (
    "essai gratuit",
    "free trial",
    "créer un compte",
    "creer un compte",
    "sign up",
    "s'inscrire",
)


def _has_href(low: str, *needles: str) -> bool:
    return any(f'href="{n}' in low or f"href='{n}" in low for n in needles)


def detect_site_types(html: str, stack: StackKind | None = None) -> list[dict[str, Any]]:
    low = html.lower()
    scores: dict[str, float] = {"ecommerce": 0.0, "lead_gen": 0.0, "saas": 0.0, "content": 0.0}
    signals: dict[str, list[str]] = {key: [] for key in scores}

    def add(kind: str, points: float, why: str) -> None:
        scores[kind] += points
        signals[kind].append(why)

    jsonld = {match.lower() for match in _JSONLD_TYPE.findall(html)}

    # Boutique
    if stack == StackKind.WOOCOMMERCE:
        add("ecommerce", 0.6, "stack WooCommerce")
    if "cdn.shopify.com" in low or "shopify" in low:
        add("ecommerce", 0.6, "Shopify détecté")
    if "product" in jsonld:
        add("ecommerce", 0.35, "données structurées Product")
    if any(word in low for word in _WORDS_CART):
        add("ecommerce", 0.3, "bouton « ajouter au panier »")
    if _has_href(low, "/cart", "/panier", "/checkout"):
        add("ecommerce", 0.2, "lien vers panier ou paiement")

    # Prise de contact
    if "<form" in low:
        add("lead_gen", 0.2, "formulaire présent")
    if 'href="tel:' in low or "href='tel:" in low:
        add("lead_gen", 0.25, "lien téléphone")
    if 'href="mailto:' in low or "href='mailto:" in low:
        add("lead_gen", 0.1, "lien e-mail")
    if any(word in low for word in _WORDS_LEAD):
        add("lead_gen", 0.3, "vocabulaire de devis / contact")

    # SaaS
    if any(word in low for word in _WORDS_SAAS):
        add("saas", 0.3, "essai gratuit ou création de compte")
    if _has_href(low, "/pricing", "/tarifs"):
        add("saas", 0.3, "page de tarifs")
    if _has_href(low, "/login", "/signin", "/connexion"):
        add("saas", 0.2, "page de connexion")

    # Contenu
    if jsonld & {"article", "blogposting", "newsarticle"}:
        add("content", 0.4, "données structurées Article")
    if "<article" in low:
        add("content", 0.2, "balise article")
    if _has_href(low, "/blog"):
        add("content", 0.3, "section blog")

    guesses = [
        {
            "type": kind,
            "confidence": min(1.0, round(score, 2)),
            "signals": signals[kind],
        }
        for kind, score in scores.items()
        if score >= _MIN_CONFIDENCE
    ]
    guesses.sort(key=lambda g: g["confidence"], reverse=True)
    if not guesses:
        return [{"type": "other", "confidence": 0.5, "signals": []}]
    return guesses


def resolve_effective_types(
    detected: list[dict[str, Any]], confirmed: list[str] | None
) -> list[str]:
    """Types utilisés par le plan : la confirmation prime, sinon les types détectés
    avec une confiance suffisante, sinon le meilleur candidat, sinon « other »."""
    if confirmed:
        return list(confirmed)
    picked = [g["type"] for g in detected if g["confidence"] >= _PICK_CONFIDENCE]
    if picked:
        return [t for t in picked if t != "other"] or ["other"]
    if detected and detected[0]["confidence"] >= _MIN_CONFIDENCE and detected[0]["type"] != "other":
        return [detected[0]["type"]]
    return ["other"]
```

- [ ] **Étape 3 : lancer les tests** → verts ; `ruff` propre.

- [ ] **Étape 4 : commit**

```bash
git add backend/app/services/measurement/site_types.py backend/tests/test_measurement_site_types.py
git commit -m "feat(measurement): detection heuristique du type de site"
```

---

### Tâche 4 : Extension du navigateur headless

**Fichiers :**
- Modifier : `backend/app/services/gtm_headless.py`
- Test : `backend/tests/test_gtm_headless.py` (ajouts, sans toucher aux tests existants)

**Interfaces :**
- Produit : `GtmHeadlessResult` gagne `ga4_measurement_ids: tuple[str, ...] = ()`,
  `ads_requests: int = 0`, `consent_default_seen: bool = False` (valeurs par défaut,
  rétro-compatible) ; fonctions pures `_is_ga4_collect(url)`, `_ga4_id_from_url(url)`,
  `_is_ads_request(url)` ; `headless_result_to_dict` ajoute les clés
  `ga4_measurement_ids`, `ads_requests`, `consent_default_seen`.

- [ ] **Étape 1 : écrire les tests qui échouent** (à ajouter en fin de
  `backend/tests/test_gtm_headless.py`)

```python
from app.services.gtm_headless import (  # noqa: E402  (en haut du fichier si possible)
    _ga4_id_from_url,
    _is_ads_request,
    _is_ga4_collect,
)


def test_ga4_collect_detection_and_measurement_id() -> None:
    url = "https://www.google-analytics.com/g/collect?v=2&tid=G-ABC123XYZ&en=page_view"
    assert _is_ga4_collect(url)
    assert _ga4_id_from_url(url) == "G-ABC123XYZ"
    regional = "https://region1.analytics.google.com/g/collect?v=2&tid=G-ZZZ999"
    assert _is_ga4_collect(regional)
    assert _ga4_id_from_url(regional) == "G-ZZZ999"


def test_non_collect_requests_are_ignored() -> None:
    assert not _is_ga4_collect("https://www.googletagmanager.com/gtm.js?id=GTM-AAAA111")
    assert not _is_ga4_collect("https://www.google-analytics.com/analytics.js")
    assert _ga4_id_from_url("https://example.com/x") is None


def test_ads_request_detection() -> None:
    assert _is_ads_request("https://www.googleadservices.com/pagead/conversion/123/?label=x")
    assert _is_ads_request("https://googleads.g.doubleclick.net/pagead/viewthroughconversion/1/")
    assert not _is_ads_request("https://www.googletagmanager.com/gtag/js?id=G-1")


def test_headless_result_dict_exposes_new_fields_with_defaults() -> None:
    result = GtmHeadlessResult(
        gtm_js_loaded=True,
        containers_initialised=("GTM-ABCD",),
        datalayer_present=True,
        gtm_events=(),
        requests_before_consent=True,
        csp_console_errors=(),
        findings=(),
        checked_at=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
    )
    out = headless_result_to_dict(result)
    assert out["ga4_measurement_ids"] == []
    assert out["ads_requests"] == 0
    assert out["consent_default_seen"] is False

    full = GtmHeadlessResult(
        gtm_js_loaded=True,
        containers_initialised=("GTM-ABCD",),
        datalayer_present=True,
        gtm_events=("page_view",),
        requests_before_consent=True,
        csp_console_errors=(),
        findings=(),
        checked_at=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        ga4_measurement_ids=("G-ABC123XYZ",),
        ads_requests=2,
        consent_default_seen=True,
    )
    out = headless_result_to_dict(full)
    assert out["ga4_measurement_ids"] == ["G-ABC123XYZ"]
    assert out["ads_requests"] == 2
    assert out["consent_default_seen"] is True
```
(`datetime`, `UTC`, `GtmHeadlessResult`, `headless_result_to_dict` sont déjà importés
en tête de ce fichier ; placer les nouveaux imports avec les existants.)

Lancer → ÉCHEC (`ImportError: _ga4_id_from_url`).

- [ ] **Étape 2 : modifier `gtm_headless.py`**

En haut du module, ajouter l'import et les constantes :

```python
from urllib.parse import parse_qs, urlparse
...
_GA4_HOSTS = ("google-analytics.com", "analytics.google.com")
_ADS_HOSTS = ("googleadservices.com", "googleads.g.doubleclick.net")
```

Ajouter les fonctions pures (après `_is_gtm_csp_violation`) :

```python
def _is_ga4_collect(url: str) -> bool:
    return "/g/collect" in url and any(host in url for host in _GA4_HOSTS)


def _ga4_id_from_url(url: str) -> str | None:
    values = parse_qs(urlparse(url).query).get("tid")
    return values[0] if values else None


def _is_ads_request(url: str) -> bool:
    return any(host in url for host in _ADS_HOSTS)
```

Dans la dataclass `GtmHeadlessResult`, ajouter **après** `error` :

```python
    ga4_measurement_ids: tuple[str, ...] = ()
    ads_requests: int = 0
    consent_default_seen: bool = False
```

Dans `headless_result_to_dict`, ajouter au dictionnaire retourné :

```python
        "ga4_measurement_ids": list(result.ga4_measurement_ids),
        "ads_requests": result.ads_requests,
        "consent_default_seen": result.consent_default_seen,
```

Dans `verify_gtm`, déclarer avec les autres listes :

```python
    ga4_ids: list[str] = []
    ads_requests = 0
    consent_default_seen = False
```
remplacer `_on_request` par :

```python
                def _on_request(request: Any) -> None:
                    nonlocal ads_requests
                    url = request.url
                    if _GTM_HOST_HINT in url:
                        requests_gtm.append(url)
                    if _is_ga4_collect(url):
                        tid = _ga4_id_from_url(url)
                        if tid:
                            ga4_ids.append(tid)
                    if _is_ads_request(url):
                        ads_requests += 1
```
et, juste après le calcul de `gtm_events` (dans le `try`), ajouter :

```python
                consent_default_seen = bool(
                    await page.evaluate(
                        "(window.dataLayer || []).some("
                        "e => e && e[0] === 'consent' && e[1] === 'default')"
                    )
                )
```
Enfin, dans le `return GtmHeadlessResult(...)` final, ajouter :

```python
        ga4_measurement_ids=tuple(dict.fromkeys(ga4_ids)),
        ads_requests=ads_requests,
        consent_default_seen=consent_default_seen,
```
(`nonlocal` exige que `ads_requests` et `consent_default_seen` soient définies dans la
fonction englobante `verify_gtm` avant `_on_request`, ce que fait la déclaration
ci-dessus ; `consent_default_seen` est ensuite réaffectée dans le même scope.)

- [ ] **Étape 3 : lancer les tests**

`.venv/Scripts/python.exe -m pytest tests/test_gtm_headless.py tests/test_audit_endpoints.py tests/test_advisor_tools.py tests/test_advisor_chat.py -v`
→ tous verts (les tests existants construisent `GtmHeadlessResult` sans les nouveaux
champs). `ruff` propre. **`verify_gtm` n'est pas exécuté** (Chromium).

- [ ] **Étape 4 : commit**

```bash
git add backend/app/services/gtm_headless.py backend/tests/test_gtm_headless.py
git commit -m "feat(headless): capture collecte GA4, requetes Ads et Consent Mode par defaut"
```

---

### Tâche 5 : Lecteur Google (GA4 Data, GA4 Admin, Search Console)

**Fichiers :**
- Créer : `backend/app/services/measurement/google_reader.py`
- Créer : `backend/app/services/measurement/google_access.py`
- Test : `backend/tests/test_measurement_google_reader.py`

**Interfaces :**
- Produit : `GoogleReadError(reason: str)` ; protocole `GoogleReader` avec
  `gsc_state: str` (`"linked" | "not_linked" | "needs_reauth"`) et méthodes
  async `event_stats() -> dict[str, dict[str, float]]`,
  `key_events() -> list[dict]`, `ads_links_count() -> int`,
  `measurement_id() -> str | None`, `sitemaps_count() -> int` — chacune lève
  `GoogleReadError` avec une `reason` parmi `ga4_not_connected`,
  `gsc_not_connected`, `token_unavailable`, `permission_or_api_disabled`,
  `not_found`, `quota`, `network`, `api_error` ;
  `HttpGoogleReader` ; `parse_event_stats(payload)` ;
  `build_reader(session, website, *, oauth, cipher, http_client=None)`.
- Les stats d'événement ont la forme `{"purchase": {"count": 12.0, "revenue": 340.0,
  "value": 0.0}}`.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_measurement_google_reader.py
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.enums import ResourceType
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.security.token_crypto import load_token_cipher
from app.services.connections import upsert_google_connection
from app.services.google_oauth.base import GoogleTokenResponse, GoogleUserInfo
from app.services.google_oauth.mock import MockGoogleOAuthClient
from app.services.measurement.google_access import build_reader
from app.services.measurement.google_reader import (
    GoogleReadError,
    HttpGoogleReader,
    parse_event_stats,
)
from tests.conftest import owner_workspace_id


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _reader(handler, **overrides) -> HttpGoogleReader:
    args = {
        "ga4_token": "tok-ga4",
        "ga4_property": "properties/123456",
        "gsc_token": "tok-gsc",
        "gsc_site": "sc-domain:exemple.fr",
        "gsc_state": "linked",
        "client": _client(handler),
    }
    args.update(overrides)
    return HttpGoogleReader(**args)


def test_parse_event_stats() -> None:
    payload = {
        "rows": [
            {
                "dimensionValues": [{"value": "purchase"}],
                "metricValues": [{"value": "12"}, {"value": "340.5"}, {"value": "0"}],
            },
            {
                "dimensionValues": [{"value": "page_view"}],
                "metricValues": [{"value": "900"}, {"value": "0"}, {"value": "0"}],
            },
            {"dimensionValues": [], "metricValues": []},
        ]
    }
    stats = parse_event_stats(payload)
    assert stats["purchase"] == {"count": 12.0, "revenue": 340.5, "value": 0.0}
    assert stats["page_view"]["count"] == 900.0
    assert parse_event_stats({}) == {}


async def test_event_stats_calls_run_report() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "dimensionValues": [{"value": "generate_lead"}],
                        "metricValues": [{"value": "4"}, {"value": "0"}, {"value": "0"}],
                    }
                ]
            },
        )

    stats = await _reader(handler).event_stats()
    assert stats["generate_lead"]["count"] == 4.0
    assert seen["url"].endswith("properties/123456:runReport")
    assert seen["auth"] == "Bearer tok-ga4"


async def test_key_events_ads_links_and_measurement_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/keyEvents"):
            return httpx.Response(
                200,
                json={
                    "keyEvents": [
                        {"eventName": "purchase", "defaultValue": {"numericValue": 0}},
                        {"eventName": "generate_lead", "defaultValue": {"numericValue": 50}},
                    ]
                },
            )
        if path.endswith("/googleAdsLinks"):
            return httpx.Response(200, json={"googleAdsLinks": [{"name": "x"}]})
        if path.endswith("/dataStreams"):
            return httpx.Response(
                200,
                json={
                    "dataStreams": [
                        {"type": "IOS_APP_DATA_STREAM"},
                        {
                            "type": "WEB_DATA_STREAM",
                            "webStreamData": {"measurementId": "G-ABC123XYZ"},
                        },
                    ]
                },
            )
        return httpx.Response(404)

    reader = _reader(handler)
    events = await reader.key_events()
    assert [e["eventName"] for e in events] == ["purchase", "generate_lead"]
    assert await reader.ads_links_count() == 1
    assert await reader.measurement_id() == "G-ABC123XYZ"


async def test_empty_admin_lists_are_valid_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    reader = _reader(handler)
    assert await reader.key_events() == []
    assert await reader.ads_links_count() == 0
    assert await reader.measurement_id() is None


async def test_sitemaps_count_quotes_the_site_url() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["raw"] = str(request.url)
        return httpx.Response(200, json={"sitemap": [{"path": "https://exemple.fr/sitemap.xml"}]})

    assert await _reader(handler).sitemaps_count() == 1
    assert "sc-domain%3Aexemple.fr/sitemaps" in seen["raw"]


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (401, "token_unavailable"),
        (403, "permission_or_api_disabled"),
        (404, "not_found"),
        (429, "quota"),
        (500, "api_error"),
    ],
)
async def test_http_errors_map_to_reasons(status: int, reason: str) -> None:
    reader = _reader(lambda request: httpx.Response(status, json={}))
    with pytest.raises(GoogleReadError) as excinfo:
        await reader.event_stats()
    assert excinfo.value.reason == reason


async def test_network_error_maps_to_network_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(GoogleReadError) as excinfo:
        await _reader(handler).event_stats()
    assert excinfo.value.reason == "network"


async def test_missing_connections_raise_dedicated_reasons() -> None:
    reader = _reader(
        lambda request: httpx.Response(200, json={}),
        ga4_token=None,
        ga4_property=None,
        gsc_token=None,
        gsc_site=None,
        gsc_state="not_linked",
    )
    with pytest.raises(GoogleReadError) as ga4:
        await reader.event_stats()
    assert ga4.value.reason == "ga4_not_connected"
    with pytest.raises(GoogleReadError) as gsc:
        await reader.sitemaps_count()
    assert gsc.value.reason == "gsc_not_connected"

    expired = _reader(
        lambda request: httpx.Response(200, json={}), ga4_token=None, gsc_token=None
    )
    with pytest.raises(GoogleReadError) as stale:
        await expired.key_events()
    assert stale.value.reason == "token_unavailable"


async def test_build_reader_resolves_links_and_tokens(
    db_session: AsyncSession, make_user
) -> None:
    user = await make_user(sub="mgr-user")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain="mgr.test", display_name="MGR")
    db_session.add(site)
    await db_session.flush()

    cipher = load_token_cipher(get_settings())
    connection = await upsert_google_connection(
        db_session,
        workspace_id=workspace_id,
        userinfo=GoogleUserInfo(sub="google-sub-dev-agence", email="dev.agence@gmail.com"),
        token=GoogleTokenResponse(
            access_token="at",
            refresh_token="mock-refresh|google-sub-dev-agence",
            expires_in=3599,
            scopes=("openid", "email"),
        ),
        cipher=cipher,
    )
    db_session.add(
        WebsiteGoogleLink(
            website_id=site.id,
            google_connection_id=connection.id,
            resource_type=ResourceType.GA4_PROPERTY,
            resource_id="properties/447213908",
        )
    )
    db_session.add(
        WebsiteGoogleLink(
            website_id=site.id,
            google_connection_id=connection.id,
            resource_type=ResourceType.GSC_SITE,
            resource_id="sc-domain:mgr.test",
        )
    )
    await db_session.flush()

    reader = await build_reader(
        db_session, site, oauth=MockGoogleOAuthClient(), cipher=cipher
    )
    assert reader.gsc_state == "linked"
    assert reader.ga4_property == "properties/447213908"
    assert reader.ga4_token and reader.gsc_token


async def test_build_reader_without_links(db_session: AsyncSession, make_user) -> None:
    user = await make_user(sub="mgr-empty")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain="mgr-empty.test", display_name="E")
    db_session.add(site)
    await db_session.flush()

    reader = await build_reader(
        db_session,
        site,
        oauth=MockGoogleOAuthClient(),
        cipher=load_token_cipher(get_settings()),
    )
    assert reader.gsc_state == "not_linked"
    assert reader.ga4_property is None
```

Lancer → ÉCHEC (modules absents).

- [ ] **Étape 2 : implémenter `google_reader.py`**

```python
# backend/app/services/measurement/google_reader.py
"""Lectures Google pour le plan de mesure (GA4 Data, GA4 Admin, Search Console).

Lecture seule, scopes déjà demandés. Toute erreur devient une `GoogleReadError` avec
une `reason` stable : le moteur de vérification la traduit en « non vérifiable », il
ne l'interprète jamais comme « manquant ».
"""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import quote

import httpx

from app.services.ga4 import _RUN_REPORT_URL, _metric, _property_number

_ADMIN = "https://analyticsadmin.googleapis.com/v1beta/properties/{pid}"
_SITEMAPS = "https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/sitemaps"
_TIMEOUT = httpx.Timeout(20.0)


class GoogleReadError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class GoogleReader(Protocol):
    gsc_state: str

    async def event_stats(self) -> dict[str, dict[str, float]]: ...

    async def key_events(self) -> list[dict[str, Any]]: ...

    async def ads_links_count(self) -> int: ...

    async def measurement_id(self) -> str | None: ...

    async def sitemaps_count(self) -> int: ...


def parse_event_stats(payload: Any) -> dict[str, dict[str, float]]:
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    stats: dict[str, dict[str, float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        dims = row.get("dimensionValues") or []
        metrics = row.get("metricValues") or []
        if not dims or not isinstance(dims[0], dict):
            continue
        name = dims[0].get("value")
        if not isinstance(name, str) or not name:
            continue
        stats[name] = {
            "count": _metric(metrics, 0),
            "revenue": _metric(metrics, 1),
            "value": _metric(metrics, 2),
        }
    return stats


def _raise_for_status(response: httpx.Response) -> None:
    code = response.status_code
    if code < 400:
        return
    if code == 401:
        raise GoogleReadError("token_unavailable")
    if code == 403:
        raise GoogleReadError("permission_or_api_disabled")
    if code == 404:
        raise GoogleReadError("not_found")
    if code == 429:
        raise GoogleReadError("quota")
    raise GoogleReadError("api_error")


class HttpGoogleReader:
    def __init__(
        self,
        *,
        ga4_token: str | None,
        ga4_property: str | None,
        gsc_token: str | None,
        gsc_site: str | None,
        gsc_state: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.ga4_token = ga4_token
        self.ga4_property = ga4_property
        self.gsc_token = gsc_token
        self.gsc_site = gsc_site
        self.gsc_state = gsc_state
        self._client = client

    # -- helpers ------------------------------------------------------------
    def _ga4(self) -> tuple[str, str]:
        if not self.ga4_property:
            raise GoogleReadError("ga4_not_connected")
        if not self.ga4_token:
            raise GoogleReadError("token_unavailable")
        return self.ga4_token, _property_number(self.ga4_property)

    def _gsc(self) -> tuple[str, str]:
        if not self.gsc_site:
            raise GoogleReadError("gsc_not_connected")
        if not self.gsc_token:
            raise GoogleReadError("token_unavailable")
        return self.gsc_token, self.gsc_site

    async def _request(
        self, method: str, url: str, token: str, *, json: dict[str, Any] | None = None
    ) -> Any:
        owns = self._client is None
        http = self._client or httpx.AsyncClient(timeout=_TIMEOUT)
        try:
            response = await http.request(
                method, url, json=json, headers={"Authorization": f"Bearer {token}"}
            )
        except httpx.HTTPError as exc:
            raise GoogleReadError("network") from exc
        finally:
            if owns:
                await http.aclose()
        _raise_for_status(response)
        try:
            return response.json()
        except ValueError as exc:
            raise GoogleReadError("api_error") from exc

    # -- lectures -----------------------------------------------------------
    async def event_stats(self) -> dict[str, dict[str, float]]:
        token, pid = self._ga4()
        body = {
            "dateRanges": [{"startDate": "30daysAgo", "endDate": "today"}],
            "dimensions": [{"name": "eventName"}],
            "metrics": [
                {"name": "eventCount"},
                {"name": "totalRevenue"},
                {"name": "eventValue"},
            ],
        }
        payload = await self._request("POST", _RUN_REPORT_URL.format(pid=pid), token, json=body)
        return parse_event_stats(payload)

    async def key_events(self) -> list[dict[str, Any]]:
        token, pid = self._ga4()
        payload = await self._request("GET", _ADMIN.format(pid=pid) + "/keyEvents", token)
        events = payload.get("keyEvents", []) if isinstance(payload, dict) else []
        return [event for event in events if isinstance(event, dict)]

    async def ads_links_count(self) -> int:
        token, pid = self._ga4()
        payload = await self._request("GET", _ADMIN.format(pid=pid) + "/googleAdsLinks", token)
        links = payload.get("googleAdsLinks", []) if isinstance(payload, dict) else []
        return len(links)

    async def measurement_id(self) -> str | None:
        token, pid = self._ga4()
        payload = await self._request("GET", _ADMIN.format(pid=pid) + "/dataStreams", token)
        streams = payload.get("dataStreams", []) if isinstance(payload, dict) else []
        for stream in streams:
            if not isinstance(stream, dict) or stream.get("type") != "WEB_DATA_STREAM":
                continue
            web = stream.get("webStreamData") or {}
            measurement_id = web.get("measurementId") if isinstance(web, dict) else None
            if isinstance(measurement_id, str) and measurement_id:
                return measurement_id
        return None

    async def sitemaps_count(self) -> int:
        token, site = self._gsc()
        url = _SITEMAPS.format(site=quote(site, safe=""))
        payload = await self._request("GET", url, token)
        sitemaps = payload.get("sitemap", []) if isinstance(payload, dict) else []
        return len(sitemaps)
```

- [ ] **Étape 3 : implémenter `google_access.py`**

```python
# backend/app/services/measurement/google_access.py
"""Résout, pour un site, les jetons GA4 / Search Console à partir des liaisons
`website_google_links` (même logique que `RealAuditProbe`)."""

from __future__ import annotations

from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ConnectionStatus, ResourceType
from app.models.google_connection import GoogleConnection
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.security.token_crypto import TokenCipher, TokenCryptoError
from app.services.connections import decrypt_refresh_token
from app.services.google_oauth import GoogleOAuthClient, GoogleOAuthError, InvalidGrantError
from app.services.measurement.google_reader import HttpGoogleReader


async def _access_token(
    connection: GoogleConnection,
    oauth: GoogleOAuthClient,
    cipher: TokenCipher,
    cache: dict[UUID, str | None],
) -> str | None:
    if connection.id in cache:
        return cache[connection.id]
    token: str | None = None
    if connection.status == ConnectionStatus.ACTIVE:
        try:
            refresh_token = decrypt_refresh_token(connection, cipher=cipher)
            response = await oauth.refresh_access_token(refresh_token=refresh_token)
            token = response.access_token
        except InvalidGrantError:
            connection.status = ConnectionStatus.NEEDS_REAUTH
        except (GoogleOAuthError, TokenCryptoError):
            token = None
    cache[connection.id] = token
    return token


async def build_reader(
    session: AsyncSession,
    website: Website,
    *,
    oauth: GoogleOAuthClient,
    cipher: TokenCipher,
    http_client: httpx.AsyncClient | None = None,
) -> HttpGoogleReader:
    rows = (
        (
            await session.execute(
                select(WebsiteGoogleLink, GoogleConnection)
                .join(
                    GoogleConnection,
                    WebsiteGoogleLink.google_connection_id == GoogleConnection.id,
                )
                .where(
                    WebsiteGoogleLink.website_id == website.id,
                    WebsiteGoogleLink.resource_type.in_(
                        (ResourceType.GA4_PROPERTY, ResourceType.GSC_SITE)
                    ),
                )
            )
        )
        .tuples()
        .all()
    )

    cache: dict[UUID, str | None] = {}
    ga4_token: str | None = None
    ga4_property: str | None = None
    gsc_token: str | None = None
    gsc_site: str | None = None
    gsc_state = "not_linked"
    for link, connection in rows:
        token = await _access_token(connection, oauth, cipher, cache)
        if link.resource_type == ResourceType.GA4_PROPERTY:
            ga4_property, ga4_token = link.resource_id, token
        else:
            gsc_site, gsc_token = link.resource_id, token
            gsc_state = "linked" if token else "needs_reauth"

    return HttpGoogleReader(
        ga4_token=ga4_token,
        ga4_property=ga4_property,
        gsc_token=gsc_token,
        gsc_site=gsc_site,
        gsc_state=gsc_state,
        client=http_client,
    )
```

- [ ] **Étape 4 : lancer les tests** → verts ; `ruff` propre.

- [ ] **Étape 5 : commit**

```bash
git add backend/app/services/measurement/google_reader.py backend/app/services/measurement/google_access.py backend/tests/test_measurement_google_reader.py
git commit -m "feat(measurement): lecteur Google GA4 Data/Admin et Search Console en lecture seule"
```

---

### Tâche 6 : Vérifications (moteur pur)

**Fichiers :**
- Créer : `backend/app/services/measurement/checks.py`
- Test : `backend/tests/test_measurement_checks.py`

**Interfaces :**
- Consomme : `MeasurementItem`, `Outcome` (Tâche 2), `GtmCheck`
  (`app.services.gtm_check`).
- Produit : `HeadlessFacts` (avec `from_result`, `to_dict`, `from_dict`),
  `Facts`, `html_has_event(html, name)`, `evaluate(item, facts) -> Outcome`.
- Règle centrale : l'état est le **niveau de preuve le plus haut atteint** ;
  `received` n'apparaît que si GA4 a fourni la preuve ; une preuve inaccessible
  donne `unverifiable` avec une `reason`, jamais `missing`.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_measurement_checks.py
from datetime import UTC, datetime

from app.services.gtm_check import GtmCheck
from app.services.gtm_headless import GtmHeadlessResult
from app.services.measurement.catalog import ITEMS_BY_ID
from app.services.measurement.checks import Facts, HeadlessFacts, evaluate, html_has_event


def _gtm(**kw) -> GtmCheck:
    base = {
        "containers": ("GTM-AAAA111",),
        "snippet_form": "standard",
        "snippet_in_head": True,
        "data_layer_name": "dataLayer",
    }
    base.update(kw)
    return GtmCheck(**base)


def _headless(**kw) -> HeadlessFacts:
    base = {
        "gtm_js_loaded": True,
        "containers": ("GTM-AAAA111",),
        "datalayer_events": (),
        "ga4_ids": (),
        "ads_requests": 0,
        "consent_default_seen": False,
        "checked_at": "2026-09-24T12:00:00+00:00",
    }
    base.update(kw)
    return HeadlessFacts(**base)


def _state(item_id: str, facts: Facts) -> str:
    return evaluate(ITEMS_BY_ID[item_id], facts).state


def test_html_has_event_patterns() -> None:
    assert html_has_event('dataLayer.push({event: "purchase"})', "purchase")
    assert html_has_event("dataLayer.push({ 'event' : 'purchase' })", "purchase")
    assert html_has_event("gtag('event', 'generate_lead', {})", "generate_lead")
    assert not html_has_event('var x = "purchase";', "purchase")
    assert not html_has_event('dataLayer.push({event: "purchase_x"})', "purchase")


# ---- fondations -------------------------------------------------------------
def test_gtm_installed_states() -> None:
    assert _state("gtm_installed", Facts(gtm=_gtm())) == "on_page"
    assert _state("gtm_installed", Facts(gtm=GtmCheck(snippet_form="absent"))) == "missing"
    assert (
        _state("gtm_installed", Facts(gtm=GtmCheck(containers=("GTM-A1B2C3",), snippet_form="noscript_only")))
        == "missing"
    )
    unverifiable = evaluate(ITEMS_BY_ID["gtm_installed"], Facts(page_error="fetch_error"))
    assert unverifiable.state == "unverifiable" and unverifiable.reason == "fetch_error"


def test_gtm_installed_but_not_loaded_in_a_real_browser_is_missing() -> None:
    facts = Facts(gtm=_gtm(), headless=_headless(gtm_js_loaded=False))
    outcome = evaluate(ITEMS_BY_ID["gtm_installed"], facts)
    assert outcome.state == "missing"
    assert outcome.reason == "gtm_not_loaded_in_browser"


def test_gtm_in_head() -> None:
    assert _state("gtm_in_head", Facts(gtm=_gtm(snippet_in_head=True))) == "on_page"
    assert _state("gtm_in_head", Facts(gtm=_gtm(snippet_in_head=False))) == "missing"
    assert _state("gtm_in_head", Facts(gtm=_gtm(snippet_in_head=None))) == "unverifiable"
    assert _state("gtm_in_head", Facts(gtm=GtmCheck(snippet_form="absent"))) == "missing"


def test_ga4_tag_levels() -> None:
    hardcoded = _gtm(ga4_tags=("G-AAAA1111",))
    # GA4 connecté : reçu > présent > manquant
    assert (
        _state("ga4_tag", Facts(gtm=hardcoded, ga4_stats={"page_view": {"count": 50.0}}))
        == "received"
    )
    assert _state("ga4_tag", Facts(gtm=hardcoded, ga4_stats={})) == "on_page"
    assert _state("ga4_tag", Facts(gtm=_gtm(), ga4_stats={})) == "missing"
    # GA4 non connecté : jamais « reçu »
    assert _state("ga4_tag", Facts(gtm=hardcoded, ga4_reason="ga4_not_connected")) == "on_page"
    seen = Facts(gtm=_gtm(), headless=_headless(ga4_ids=("G-AAAA1111",)))
    assert _state("ga4_tag", seen) == "on_page"
    assert _state("ga4_tag", Facts(gtm=_gtm(), headless=_headless())) == "missing"
    undecided = evaluate(ITEMS_BY_ID["ga4_tag"], Facts(gtm=_gtm(), ga4_reason="ga4_not_connected"))
    assert undecided.state == "unverifiable" and undecided.reason == "headless_not_run"


def test_no_double_tracking() -> None:
    assert _state("no_double_tracking", Facts(gtm=_gtm(ga4_tags=("G-AAAA1111",)))) == "missing"
    assert _state("no_double_tracking", Facts(gtm=_gtm())) == "on_page"
    assert (
        _state("no_double_tracking", Facts(gtm=GtmCheck(snippet_form="absent"))) == "not_applicable"
    )


def test_consent_mode() -> None:
    cmp_only = Facts(
        page_html="<html></html>", gtm=_gtm(consent_platform="cookiebot"), headless=_headless()
    )
    assert _state("consent_mode", cmp_only) == "missing"
    complete = Facts(
        page_html="<html></html>",
        gtm=_gtm(consent_platform="cookiebot"),
        headless=_headless(consent_default_seen=True),
    )
    assert _state("consent_mode", complete) == "on_page"
    in_html = Facts(
        page_html="gtag('consent', 'default', {})", gtm=_gtm(consent_platform="axeptio")
    )
    assert _state("consent_mode", in_html) == "on_page"
    no_cmp = Facts(page_html="<html></html>", gtm=_gtm(), headless=_headless())
    assert _state("consent_mode", no_cmp) == "missing"
    unknown = evaluate(
        ITEMS_BY_ID["consent_mode"],
        Facts(page_html="<html></html>", gtm=_gtm(consent_platform="didomi")),
    )
    assert unknown.state == "unverifiable" and unknown.reason == "headless_not_run"


def test_datalayer_standard() -> None:
    assert _state("datalayer_standard", Facts(gtm=_gtm())) == "on_page"
    assert _state("datalayer_standard", Facts(gtm=_gtm(data_layer_name="appLayer"))) == "missing"
    assert (
        _state("datalayer_standard", Facts(gtm=GtmCheck(snippet_form="absent"))) == "not_applicable"
    )


# ---- événements -------------------------------------------------------------
def test_event_levels_with_ga4() -> None:
    received = Facts(ga4_stats={"generate_lead": {"count": 4.0}})
    assert _state("event_generate_lead", received) == "received"
    found_in_code = Facts(
        page_html='dataLayer.push({event: "generate_lead"})', ga4_stats={}
    )
    assert _state("event_generate_lead", found_in_code) == "on_page"
    assert _state("event_generate_lead", Facts(ga4_stats={})) == "missing"


def test_event_without_ga4_is_never_received() -> None:
    facts = Facts(page_html='gtag("event", "generate_lead")', ga4_reason="ga4_not_connected")
    assert _state("event_generate_lead", facts) == "on_page"
    undecided = evaluate(ITEMS_BY_ID["event_generate_lead"], Facts(ga4_reason="ga4_not_connected"))
    assert undecided.state == "unverifiable"
    assert undecided.reason == "ga4_not_connected"


def test_event_seen_in_headless_datalayer_counts_as_on_page() -> None:
    facts = Facts(
        ga4_stats={}, headless=_headless(datalayer_events=("view_item",)), page_html=""
    )
    assert _state("event_view_item", facts) == "on_page"


def test_purchase_params() -> None:
    ok = Facts(ga4_stats={"purchase": {"count": 3.0, "revenue": 120.0, "value": 0.0}})
    assert _state("purchase_params", ok) == "received"
    zero = Facts(ga4_stats={"purchase": {"count": 3.0, "revenue": 0.0, "value": 0.0}})
    assert _state("purchase_params", zero) == "missing"
    none = evaluate(ITEMS_BY_ID["purchase_params"], Facts(ga4_stats={}))
    assert none.state == "unverifiable" and none.reason == "purchase_not_received"
    off = evaluate(ITEMS_BY_ID["purchase_params"], Facts(ga4_reason="ga4_not_connected"))
    assert off.state == "unverifiable" and off.reason == "ga4_not_connected"


# ---- conversions ------------------------------------------------------------
def test_key_events_depend_on_the_site_type() -> None:
    events = [{"eventName": "generate_lead", "defaultValue": {"numericValue": 50}}]
    lead = Facts(key_events=events, effective_types=("lead_gen",))
    assert _state("key_events_marked", lead) == "received"
    assert _state("conversion_value", lead) == "received"
    shop = Facts(key_events=events, effective_types=("ecommerce",))
    assert _state("key_events_marked", shop) == "missing"
    no_value = Facts(
        key_events=[{"eventName": "generate_lead"}], effective_types=("lead_gen",)
    )
    assert _state("conversion_value", no_value) == "missing"
    down = evaluate(ITEMS_BY_ID["key_events_marked"], Facts(key_events_reason="quota"))
    assert down.state == "unverifiable" and down.reason == "quota"


# ---- publicité --------------------------------------------------------------
def test_ads_link_and_conversion_tag() -> None:
    assert _state("ads_ga4_link", Facts(ads_links_count=1)) == "received"
    assert _state("ads_ga4_link", Facts(ads_links_count=0)) == "missing"
    assert _state("ads_ga4_link", Facts(ads_links_reason="ga4_not_connected")) == "unverifiable"

    in_html = Facts(page_html="gtag('config', 'AW-123456789')")
    assert _state("ads_conversion_tag", in_html) == "on_page"
    seen = Facts(page_html="", headless=_headless(ads_requests=2))
    assert _state("ads_conversion_tag", seen) == "on_page"
    absent = Facts(page_html="", headless=_headless())
    assert _state("ads_conversion_tag", absent) == "missing"
    undecided = evaluate(ITEMS_BY_ID["ads_conversion_tag"], Facts(page_html=""))
    assert undecided.state == "unverifiable" and undecided.reason == "headless_not_run"


def test_manual_items_need_the_owner_confirmation() -> None:
    item = ITEMS_BY_ID["ads_auto_tagging"]
    todo = evaluate(item, Facts())
    assert todo.state == "unverifiable" and todo.reason == "manual_check"
    done = evaluate(item, Facts(manual_done=frozenset({"ads_auto_tagging"})))
    assert done.state == "on_page"
    assert done.evidence == {"manual_done": True}


# ---- SEO --------------------------------------------------------------------
def test_seo_checks() -> None:
    assert _state("gsc_property_linked", Facts(gsc_state="linked")) == "received"
    assert _state("gsc_property_linked", Facts(gsc_state="not_linked")) == "missing"
    stale = evaluate(ITEMS_BY_ID["gsc_property_linked"], Facts(gsc_state="needs_reauth"))
    assert stale.state == "unverifiable" and stale.reason == "connection_needs_reauth"

    assert _state("gsc_sitemaps", Facts(sitemaps_count=2)) == "received"
    assert _state("gsc_sitemaps", Facts(sitemaps_count=0)) == "missing"
    assert _state("gsc_sitemaps", Facts(sitemaps_reason="gsc_not_connected")) == "unverifiable"

    assert _state("robots_txt", Facts(robots_ok=True)) == "on_page"
    assert _state("robots_txt", Facts(robots_ok=False)) == "missing"
    assert _state("robots_txt", Facts(robots_ok=None)) == "unverifiable"

    assert _state("tls_valid", Facts(ssl_status="valid")) == "on_page"
    assert _state("tls_valid", Facts(ssl_status="expiring_soon")) == "on_page"
    assert _state("tls_valid", Facts(ssl_status="expired")) == "missing"
    assert _state("tls_valid", Facts(ssl_status=None)) == "unverifiable"


def test_headless_facts_roundtrip_and_conversion() -> None:
    result = GtmHeadlessResult(
        gtm_js_loaded=True,
        containers_initialised=("GTM-AAAA111",),
        datalayer_present=True,
        gtm_events=("page_view",),
        requests_before_consent=True,
        csp_console_errors=(),
        findings=(),
        checked_at=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        ga4_measurement_ids=("G-ABC123XYZ",),
        ads_requests=1,
        consent_default_seen=True,
    )
    facts = HeadlessFacts.from_result(result)
    assert facts.ga4_ids == ("G-ABC123XYZ",)
    assert HeadlessFacts.from_dict(facts.to_dict()) == facts
    assert HeadlessFacts.from_dict({}) is None
    assert HeadlessFacts.from_dict({"gtm_js_loaded": True}) is not None  # tolère l'ancien format
```

Lancer → ÉCHEC (module absent).

- [ ] **Étape 2 : implémenter `checks.py`**

```python
# backend/app/services/measurement/checks.py
"""Moteur de vérification : `evaluate(item, facts) -> Outcome`, fonction pure.

L'état d'un item est le niveau de preuve le plus haut atteint (`received` > `on_page`
> `missing`). Une preuve inaccessible donne `unverifiable` avec une `reason` — jamais
`missing`, jamais « fait ».
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.services.gtm_check import GtmCheck
from app.services.gtm_headless import GtmHeadlessResult
from app.services.measurement.types import MeasurementItem, Outcome

_AW_ID = re.compile(r"AW-\d{6,}")
_CONSENT_DEFAULT = re.compile(r"""['"]consent['"]\s*,\s*['"]default['"]""")

# Événements clés attendus selon le type de site.
_KEY_EVENTS_BY_TYPE: dict[str, frozenset[str]] = {
    "ecommerce": frozenset({"purchase"}),
    "lead_gen": frozenset({"generate_lead"}),
    "saas": frozenset({"sign_up", "begin_trial", "subscribe"}),
    "content": frozenset({"newsletter_signup"}),
}

_PAGE_KINDS = frozenset({"gtm_installed", "gtm_in_head", "no_double", "datalayer"})


@dataclass(frozen=True, slots=True)
class HeadlessFacts:
    gtm_js_loaded: bool
    containers: tuple[str, ...]
    datalayer_events: tuple[str, ...]
    ga4_ids: tuple[str, ...]
    ads_requests: int
    consent_default_seen: bool
    checked_at: str  # ISO 8601

    @classmethod
    def from_result(cls, result: GtmHeadlessResult) -> HeadlessFacts:
        return cls(
            gtm_js_loaded=result.gtm_js_loaded,
            containers=tuple(result.containers_initialised),
            datalayer_events=tuple(result.gtm_events),
            ga4_ids=tuple(result.ga4_measurement_ids),
            ads_requests=result.ads_requests,
            consent_default_seen=result.consent_default_seen,
            checked_at=result.checked_at.isoformat(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "gtm_js_loaded": self.gtm_js_loaded,
            "containers": list(self.containers),
            "datalayer_events": list(self.datalayer_events),
            "ga4_ids": list(self.ga4_ids),
            "ads_requests": self.ads_requests,
            "consent_default_seen": self.consent_default_seen,
            "checked_at": self.checked_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> HeadlessFacts | None:
        if not data:
            return None
        return cls(
            gtm_js_loaded=bool(data.get("gtm_js_loaded", False)),
            containers=tuple(data.get("containers", ())),
            datalayer_events=tuple(data.get("datalayer_events", ())),
            ga4_ids=tuple(data.get("ga4_ids", ())),
            ads_requests=int(data.get("ads_requests", 0)),
            consent_default_seen=bool(data.get("consent_default_seen", False)),
            checked_at=str(data.get("checked_at", "")),
        )


@dataclass(frozen=True, slots=True)
class Facts:
    """Tout ce que les vérifications ont le droit de savoir sur un site."""

    page_html: str | None = None
    page_error: str | None = None
    gtm: GtmCheck | None = None
    headless: HeadlessFacts | None = None
    ga4_stats: dict[str, dict[str, float]] | None = None
    ga4_reason: str | None = None
    key_events: list[dict[str, Any]] | None = None
    key_events_reason: str | None = None
    ads_links_count: int | None = None
    ads_links_reason: str | None = None
    gsc_state: str = "not_linked"
    sitemaps_count: int | None = None
    sitemaps_reason: str | None = None
    robots_ok: bool | None = None
    ssl_status: str | None = None
    effective_types: tuple[str, ...] = ("other",)
    manual_done: frozenset[str] = field(default_factory=frozenset)


def html_has_event(html: str, name: str) -> bool:
    n = re.escape(name)
    pattern = (
        rf"""(?:['"]?event['"]?\s*:\s*['"]{n}['"]"""
        rf"""|gtag\(\s*['"]event['"]\s*,\s*['"]{n}['"])"""
    )
    return re.search(pattern, html) is not None


def _unverifiable(reason: str) -> Outcome:
    return Outcome("unverifiable", {}, reason)


# ---- fondations ---------------------------------------------------------------
def _gtm_installed(item: MeasurementItem, f: Facts) -> Outcome:
    gtm = f.gtm
    if gtm is None:
        return _unverifiable(f.page_error or "page_unavailable")
    installed = gtm.snippet_form in ("standard", "custom_loader") and bool(gtm.containers)
    evidence: dict[str, Any] = {
        "containers": list(gtm.containers),
        "snippet_form": gtm.snippet_form,
    }
    if f.headless is not None:
        evidence["headless_loaded"] = f.headless.gtm_js_loaded
        if installed and not f.headless.gtm_js_loaded:
            return Outcome("missing", evidence, "gtm_not_loaded_in_browser")
    return Outcome("on_page" if installed else "missing", evidence, None)


def _gtm_in_head(item: MeasurementItem, f: Facts) -> Outcome:
    gtm = f.gtm
    if gtm is None:
        return _unverifiable(f.page_error or "page_unavailable")
    if not gtm.containers:
        return Outcome("missing", {}, "gtm_absent")
    if gtm.snippet_in_head is True:
        return Outcome("on_page", {"snippet_in_head": True}, None)
    if gtm.snippet_in_head is False:
        return Outcome("missing", {"snippet_in_head": False}, None)
    return _unverifiable("position_unknown")


def _ga4_tag(item: MeasurementItem, f: Facts) -> Outcome:
    hardcoded = tuple(f.gtm.ga4_tags) if f.gtm else ()
    seen = f.headless.ga4_ids if f.headless else ()
    evidence: dict[str, Any] = {}
    if hardcoded:
        evidence["hardcoded_ids"] = list(hardcoded)
    if seen:
        evidence["seen_ids"] = list(seen)
    on_page = bool(hardcoded or seen)

    if f.ga4_stats is not None:
        page_views = f.ga4_stats.get("page_view", {}).get("count", 0.0)
        if page_views > 0:
            return Outcome("received", {**evidence, "page_views_30d": int(page_views)}, None)
        return Outcome("on_page" if on_page else "missing", evidence, None)
    if on_page:
        return Outcome("on_page", evidence, None)
    if f.headless is not None:
        return Outcome("missing", evidence, None)
    return _unverifiable("headless_not_run")


def _no_double(item: MeasurementItem, f: Facts) -> Outcome:
    gtm = f.gtm
    if gtm is None:
        return _unverifiable(f.page_error or "page_unavailable")
    hardcoded, has_gtm = bool(gtm.ga4_tags), bool(gtm.containers)
    if hardcoded and has_gtm:
        return Outcome(
            "missing", {"hardcoded_ids": list(gtm.ga4_tags), "containers": list(gtm.containers)}, None
        )
    if not hardcoded and not has_gtm:
        return Outcome("not_applicable", {}, "no_tracking_found")
    return Outcome("on_page", {}, None)


def _consent(item: MeasurementItem, f: Facts) -> Outcome:
    if f.gtm is None:
        return _unverifiable(f.page_error or "page_unavailable")
    cmp_name = f.gtm.consent_platform
    in_html = bool(f.page_html and _CONSENT_DEFAULT.search(f.page_html))
    in_browser = bool(f.headless and f.headless.consent_default_seen)
    default_seen = in_html or in_browser
    evidence = {"cmp": cmp_name, "consent_default": default_seen}
    if cmp_name and default_seen:
        return Outcome("on_page", evidence, None)
    if cmp_name and f.headless is None:
        return Outcome("unverifiable", evidence, "headless_not_run")
    return Outcome("missing", evidence, None)


def _datalayer(item: MeasurementItem, f: Facts) -> Outcome:
    gtm = f.gtm
    if gtm is None:
        return _unverifiable(f.page_error or "page_unavailable")
    if not gtm.containers:
        return Outcome("not_applicable", {}, "gtm_absent")
    evidence = {"data_layer_name": gtm.data_layer_name}
    return Outcome("on_page" if gtm.data_layer_name == "dataLayer" else "missing", evidence, None)


# ---- événements ---------------------------------------------------------------
def _on_page_event(name: str, f: Facts) -> str | None:
    if f.page_html and html_has_event(f.page_html, name):
        return "html"
    if f.headless and name in f.headless.datalayer_events:
        return "headless_datalayer"
    return None


def _event(item: MeasurementItem, f: Facts) -> Outcome:
    name = item.arg or ""
    found_in = _on_page_event(name, f)
    evidence: dict[str, Any] = {"found_in": found_in} if found_in else {}
    if f.ga4_stats is not None:
        count = f.ga4_stats.get(name, {}).get("count", 0.0)
        if count > 0:
            return Outcome("received", {**evidence, "ga4_count_30d": int(count)}, None)
        if found_in:
            return Outcome("on_page", {**evidence, "ga4_count_30d": 0}, None)
        return Outcome("missing", {"ga4_count_30d": 0}, None)
    if found_in:
        return Outcome("on_page", evidence, None)
    return _unverifiable(f.ga4_reason or "ga4_not_connected")


def _purchase_params(item: MeasurementItem, f: Facts) -> Outcome:
    if f.ga4_stats is None:
        return _unverifiable(f.ga4_reason or "ga4_not_connected")
    purchase = f.ga4_stats.get("purchase", {})
    if purchase.get("count", 0.0) <= 0:
        return _unverifiable("purchase_not_received")
    evidence = {
        "purchases_30d": int(purchase["count"]),
        "revenue_30d": purchase.get("revenue", 0.0),
    }
    if purchase.get("revenue", 0.0) > 0 or purchase.get("value", 0.0) > 0:
        return Outcome("received", evidence, None)
    return Outcome("missing", evidence, None)


# ---- conversions --------------------------------------------------------------
def _expected_key_events(types: tuple[str, ...]) -> frozenset[str]:
    names: set[str] = set()
    for site_type in types:
        names |= _KEY_EVENTS_BY_TYPE.get(site_type, frozenset())
    return frozenset(names)


def _key_events(item: MeasurementItem, f: Facts) -> Outcome:
    if f.key_events is None:
        return _unverifiable(f.key_events_reason or "ga4_not_connected")
    declared = [e.get("eventName") for e in f.key_events if e.get("eventName")]
    expected = _expected_key_events(f.effective_types)
    matching = [name for name in declared if name in expected] if expected else declared
    evidence = {"key_events": declared}
    return Outcome("received" if matching else "missing", evidence, None)


def _key_events_value(item: MeasurementItem, f: Facts) -> Outcome:
    if f.key_events is None:
        return _unverifiable(f.key_events_reason or "ga4_not_connected")
    expected = _expected_key_events(f.effective_types)
    valued = [
        e.get("eventName")
        for e in f.key_events
        if (not expected or e.get("eventName") in expected)
        and float((e.get("defaultValue") or {}).get("numericValue", 0) or 0) > 0
    ]
    return Outcome("received" if valued else "missing", {"valued_events": valued}, None)


# ---- publicité ----------------------------------------------------------------
def _ads_link(item: MeasurementItem, f: Facts) -> Outcome:
    if f.ads_links_count is None:
        return _unverifiable(f.ads_links_reason or "ga4_not_connected")
    evidence = {"ads_links": f.ads_links_count}
    return Outcome("received" if f.ads_links_count > 0 else "missing", evidence, None)


def _ads_conversion_tag(item: MeasurementItem, f: Facts) -> Outcome:
    ids = sorted(set(_AW_ID.findall(f.page_html or "")))
    ads_seen = bool(f.headless and f.headless.ads_requests > 0)
    evidence: dict[str, Any] = {}
    if ids:
        evidence["ads_ids"] = ids
    if ads_seen:
        evidence["ads_requests"] = f.headless.ads_requests if f.headless else 0
    if ids or ads_seen:
        return Outcome("on_page", evidence, None)
    if f.headless is not None:
        return Outcome("missing", evidence, None)
    return _unverifiable("headless_not_run")


def _manual(item: MeasurementItem, f: Facts) -> Outcome:
    if item.id in f.manual_done:
        return Outcome("on_page", {"manual_done": True}, None)
    return _unverifiable("manual_check")


# ---- SEO ----------------------------------------------------------------------
def _gsc_linked(item: MeasurementItem, f: Facts) -> Outcome:
    if f.gsc_state == "linked":
        return Outcome("received", {}, None)
    if f.gsc_state == "needs_reauth":
        return _unverifiable("connection_needs_reauth")
    return Outcome("missing", {}, None)


def _gsc_sitemaps(item: MeasurementItem, f: Facts) -> Outcome:
    if f.sitemaps_count is None:
        return _unverifiable(f.sitemaps_reason or "gsc_not_connected")
    evidence = {"sitemaps": f.sitemaps_count}
    return Outcome("received" if f.sitemaps_count > 0 else "missing", evidence, None)


def _robots(item: MeasurementItem, f: Facts) -> Outcome:
    if f.robots_ok is None:
        return _unverifiable("not_checked")
    return Outcome("on_page" if f.robots_ok else "missing", {"robots_ok": f.robots_ok}, None)


def _tls(item: MeasurementItem, f: Facts) -> Outcome:
    if f.ssl_status is None:
        return _unverifiable("not_checked")
    ok = f.ssl_status in ("valid", "expiring_soon")
    return Outcome("on_page" if ok else "missing", {"ssl_status": f.ssl_status}, None)


_CHECKS: dict[str, Callable[[MeasurementItem, Facts], Outcome]] = {
    "gtm_installed": _gtm_installed,
    "gtm_in_head": _gtm_in_head,
    "ga4_tag": _ga4_tag,
    "no_double": _no_double,
    "consent": _consent,
    "datalayer": _datalayer,
    "event": _event,
    "purchase_params": _purchase_params,
    "key_events": _key_events,
    "key_events_value": _key_events_value,
    "ads_link": _ads_link,
    "ads_conversion_tag": _ads_conversion_tag,
    "manual": _manual,
    "gsc_linked": _gsc_linked,
    "gsc_sitemaps": _gsc_sitemaps,
    "robots": _robots,
    "tls": _tls,
}


def evaluate(item: MeasurementItem, facts: Facts) -> Outcome:
    if item.check in _PAGE_KINDS and facts.page_error is not None and facts.gtm is None:
        return _unverifiable(facts.page_error)
    return _CHECKS[item.check](item, facts)
```

- [ ] **Étape 3 : lancer les tests** → verts ; `ruff` propre (ligne longue : reformater
  au besoin, la limite du projet est celle de `pyproject.toml`).

- [ ] **Étape 4 : commit**

```bash
git add backend/app/services/measurement/checks.py backend/tests/test_measurement_checks.py
git commit -m "feat(measurement): moteur de verification pur (present sur la page / recu par GA4)"
```

---

### Tâche 7 : Snippets d'événements

**Fichiers :**
- Créer : `backend/app/services/measurement/event_snippets.py`
- Test : `backend/tests/test_measurement_snippets.py`

**Interfaces :**
- Consomme : `snippet_library.get_snippets`, `SnippetEvent`, `StackKind`.
- Produit : `ItemSnippet(language, code, target_path, instructions)` ;
  `snippet_for_event(event: str, stack: StackKind | None) -> ItemSnippet | None`
  (renvoie `None` pour un événement inconnu). `purchase` et `generate_lead`
  réutilisent les snippets par stack de la bibliothèque ; les autres événements
  et `consent_default` sont génériques (JavaScript).

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_measurement_snippets.py
import pytest

from app.models.enums import StackKind
from app.services.measurement.catalog import ITEMS
from app.services.measurement.event_snippets import snippet_for_event


def test_every_snippet_item_resolves_to_a_snippet() -> None:
    for item in ITEMS:
        if "snippet" in item.actions:
            snippet = snippet_for_event(item.snippet_event or "", StackKind.NEXTJS)
            assert snippet is not None, item.id
            assert snippet.code.strip() and snippet.instructions.strip(), item.id


def test_purchase_and_lead_reuse_the_stack_library() -> None:
    nextjs = snippet_for_event("purchase", StackKind.NEXTJS)
    wordpress = snippet_for_event("purchase", StackKind.WORDPRESS)
    assert nextjs is not None and wordpress is not None
    assert nextjs.code != wordpress.code
    lead = snippet_for_event("generate_lead", StackKind.NEXTJS)
    assert lead is not None and "generate_lead" in lead.code


@pytest.mark.parametrize(
    "event",
    ["view_item", "add_to_cart", "begin_checkout"],
)
def test_ecommerce_events_push_an_items_array(event: str) -> None:
    snippet = snippet_for_event(event, None)
    assert snippet is not None
    assert f'event: "{event}"' in snippet.code
    assert "items" in snippet.code and "ecommerce" in snippet.code


@pytest.mark.parametrize(
    ("event", "selector"),
    [
        ("click_to_call", 'a[href^="tel:"]'),
        ("click_email", 'a[href^="mailto:"]'),
        ("click_whatsapp", "wa.me"),
    ],
)
def test_link_events_listen_to_clicks(event: str, selector: str) -> None:
    snippet = snippet_for_event(event, None)
    assert snippet is not None
    assert selector in snippet.code
    assert f'event: "{event}"' in snippet.code


@pytest.mark.parametrize(
    "event",
    ["sign_up", "login", "begin_trial", "subscribe", "tutorial_complete", "newsletter_signup", "share"],
)
def test_simple_events_push_the_event_name(event: str) -> None:
    snippet = snippet_for_event(event, None)
    assert snippet is not None
    assert f'event: "{event}"' in snippet.code
    assert "__" not in snippet.code  # aucun marqueur de gabarit non remplacé


def test_consent_default_snippet_denies_by_default() -> None:
    snippet = snippet_for_event("consent_default", None)
    assert snippet is not None
    assert "'consent', 'default'" in snippet.code
    assert "analytics_storage: 'denied'" in snippet.code
    assert "ad_user_data: 'denied'" in snippet.code
    assert "wait_for_update" in snippet.code


def test_unknown_event_returns_none() -> None:
    assert snippet_for_event("does_not_exist", None) is None
```

Lancer → ÉCHEC (module absent).

- [ ] **Étape 2 : implémenter**

```python
# backend/app/services/measurement/event_snippets.py
"""Snippets d'instrumentation `dataLayer.push` pour les événements du catalogue.

`purchase` et `generate_lead` réutilisent la bibliothèque par stack ; les autres
événements sont fournis en JavaScript générique (à adapter au framework par
l'utilisateur, c'est dit dans les instructions).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import StackKind
from app.services.snippet_library import SnippetEvent, get_snippets


@dataclass(frozen=True, slots=True)
class ItemSnippet:
    language: str
    code: str
    target_path: str
    instructions: str


_GENERIC_NOTE = (
    "Snippet JavaScript générique : adapte-le à ton framework (composant, hook, "
    "gestionnaire d'événement) ou transmets-le à ton développeur."
)

_ECOM = """// À déclencher __WHEN__
window.dataLayer = window.dataLayer || [];
window.dataLayer.push({ ecommerce: null });
window.dataLayer.push({
  event: "__EVENT__",
  ecommerce: {
    currency: "EUR",
    value: 0, // montant total concerné
    items: [
      { item_id: "SKU123", item_name: "Nom du produit", price: 0, quantity: 1 },
    ],
  },
});
"""

_SIMPLE = """// À déclencher __WHEN__
window.dataLayer = window.dataLayer || [];
window.dataLayer.push({
  event: "__EVENT__",__PARAMS__
});
"""

_LINK = """// À charger sur toutes les pages
document.addEventListener("click", (e) => {
  const link = e.target.closest('__SELECTOR__');
  if (!link) return;
  window.dataLayer = window.dataLayer || [];
  window.dataLayer.push({ event: "__EVENT__", link_url: link.href });
});
"""

_CONSENT = """// À placer AVANT le snippet Google Tag Manager, dans le <head>
window.dataLayer = window.dataLayer || [];
function gtag() { dataLayer.push(arguments); }
gtag('consent', 'default', {
  ad_storage: 'denied',
  ad_user_data: 'denied',
  ad_personalization: 'denied',
  analytics_storage: 'denied',
  wait_for_update: 500,
});
// Ta bannière de consentement doit ensuite appeler gtag('consent', 'update', {...})
// quand le visiteur accepte.
"""

_ECOM_WHEN = {
    "view_item": "au chargement d'une fiche produit",
    "add_to_cart": "au clic sur « ajouter au panier »",
    "begin_checkout": "à l'ouverture de la page de paiement",
}

_SIMPLE_EVENTS: dict[str, tuple[str, str]] = {
    "sign_up": ("après la création réussie du compte", '\n  method: "email", // ou "google", …'),
    "login": ("après une connexion réussie", '\n  method: "email",'),
    "begin_trial": ("au démarrage effectif de l'essai", '\n  plan: "pro", // nom de l\'offre'),
    "subscribe": (
        "après la souscription à une offre payante",
        '\n  value: 0, // montant de l\'abonnement\n  currency: "EUR",',
    ),
    "tutorial_complete": ("quand l'utilisateur termine l'onboarding", ""),
    "newsletter_signup": ("après l'inscription réussie à la newsletter", ""),
    "share": (
        "au clic sur un bouton de partage",
        '\n  method: "twitter", // réseau utilisé\n  content_type: "article",',
    ),
}

_LINK_EVENTS: dict[str, str] = {
    "click_to_call": 'a[href^="tel:"]',
    "click_email": 'a[href^="mailto:"]',
    "click_whatsapp": 'a[href*="wa.me"], a[href*="whatsapp.com"]',
}


def _from_library(event: SnippetEvent, stack: StackKind | None) -> ItemSnippet | None:
    entries = get_snippets(stack, event)
    if not entries:
        return None
    first = entries[0]
    return ItemSnippet(first.language, first.code, first.target_path, first.instructions)


def snippet_for_event(event: str, stack: StackKind | None) -> ItemSnippet | None:
    if event == "purchase":
        return _from_library(SnippetEvent.PURCHASE, stack)
    if event == "generate_lead":
        return _from_library(SnippetEvent.LEAD, stack)
    if event in _ECOM_WHEN:
        code = _ECOM.replace("__WHEN__", _ECOM_WHEN[event]).replace("__EVENT__", event)
        return ItemSnippet("js", code, "assets/analytics.js", _GENERIC_NOTE)
    if event in _SIMPLE_EVENTS:
        when, params = _SIMPLE_EVENTS[event]
        code = (
            _SIMPLE.replace("__WHEN__", when)
            .replace("__EVENT__", event)
            .replace("__PARAMS__", params)
        )
        return ItemSnippet("js", code, "assets/analytics.js", _GENERIC_NOTE)
    if event in _LINK_EVENTS:
        code = _LINK.replace("__SELECTOR__", _LINK_EVENTS[event]).replace("__EVENT__", event)
        return ItemSnippet(
            "js",
            code,
            "assets/analytics.js",
            "À charger une seule fois sur toutes les pages du site. " + _GENERIC_NOTE,
        )
    if event == "consent_default":
        return ItemSnippet(
            "js",
            _CONSENT,
            "<head> (avant le snippet GTM)",
            "À placer avant le snippet Google Tag Manager. Si ta bannière de consentement "
            "envoie déjà cet état par défaut, ne l'ajoute pas en double.",
        )
    return None
```

- [ ] **Étape 3 : lancer les tests** → verts ; `ruff` propre.

- [ ] **Étape 4 : commit**

```bash
git add backend/app/services/measurement/event_snippets.py backend/tests/test_measurement_snippets.py
git commit -m "feat(measurement): snippets dataLayer pour les evenements du catalogue"
```

---

### Tâche 8 : Conteneur GTM sur mesure

**Fichiers :**
- Modifier : `backend/app/services/gtm_generator.py` (ajout, sans toucher
  `build_gtm_container`)
- Test : `backend/tests/test_gtm_selected_container.py`

**Interfaces :**
- Consomme : helpers internes de `gtm_generator` (`_custom_event_trigger`,
  `_ga4_event_tag`, `_dlv_variable`, `_built_in_variables`, `_short_code`,
  `_numeric_id`, `_IMPORT_METADATA`, `_FINGERPRINT`, `_ALL_PAGES_TRIGGER_ID`).
- Produit : `build_selected_container(*, domain, stack, item_ids,
  ga4_measurement_id, ads_conversion_id, ads_conversion_label, import_mode="merge",
  export_time=None) -> tuple[dict, list[str]]` (conteneur + avertissements).
  Événements pris en charge : `event_view_item`, `event_add_to_cart`,
  `event_begin_checkout`, `event_purchase` (e-commerce, `sendEcommerceData`),
  `event_generate_lead`, `event_sign_up`, `event_login`, `event_begin_trial`,
  `event_subscribe`, `event_tutorial_complete`, `event_newsletter_signup`,
  `event_share` (événements personnalisés), `event_click_to_call`,
  `event_click_email`, `event_click_whatsapp` (déclencheurs de clic sur lien).
  `ga4_tag` ajoute la balise de configuration GA4 ; `ads_conversion_tag` ajoute la
  balise `awct` ; `ads_conversion_linker` (ou la balise Ads) ajoute `gclidw`.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_gtm_selected_container.py
import json

from app.models.enums import StackKind
from app.services.gtm_generator import build_selected_container


def _build(item_ids, **kw):
    args = {
        "domain": "exemple.fr",
        "stack": StackKind.NEXTJS,
        "item_ids": item_ids,
        "ga4_measurement_id": "G-ABC123XYZ",
        "ads_conversion_id": None,
        "ads_conversion_label": None,
    }
    args.update(kw)
    return build_selected_container(**args)


def _names(container: dict, key: str) -> list[str]:
    return [entry["name"] for entry in container["containerVersion"][key]]


def test_only_selected_events_are_generated() -> None:
    container, warnings = _build(["ga4_tag", "event_purchase", "event_generate_lead"])
    tags = _names(container, "tag")
    assert "GA4 Configuration" in tags
    assert "GA4 - purchase" in tags and "GA4 - generate_lead" in tags
    assert "GA4 - view_item" not in tags
    assert warnings == []
    json.dumps(container)  # sérialisable


def test_ids_are_unique_and_triggers_are_referenced() -> None:
    container, _ = _build(
        ["event_view_item", "event_add_to_cart", "event_click_to_call", "event_sign_up"]
    )
    version = container["containerVersion"]
    for key, id_key in (("tag", "tagId"), ("trigger", "triggerId"), ("variable", "variableId")):
        ids = [entry[id_key] for entry in version[key]]
        assert len(ids) == len(set(ids)), key
    trigger_ids = {t["triggerId"] for t in version["trigger"]} | {"2147479553"}
    for tag in version["tag"]:
        assert set(tag["firingTriggerId"]) <= trigger_ids


def test_ecommerce_events_send_ecommerce_data() -> None:
    container, _ = _build(["event_purchase"])
    tag = next(t for t in container["containerVersion"]["tag"] if t["name"] == "GA4 - purchase")
    keys = {p["key"]: p.get("value") for p in tag["parameter"]}
    assert keys["sendEcommerceData"] == "true"


def test_link_click_events_use_link_click_triggers() -> None:
    container, _ = _build(["event_click_to_call", "event_click_whatsapp"])
    triggers = {t["name"]: t for t in container["containerVersion"]["trigger"]}
    tel = triggers["Clic - click_to_call"]
    assert tel["type"] == "linkClick"
    assert tel["filter"][0]["type"] == "startsWith"
    assert tel["filter"][0]["parameter"][1]["value"] == "tel:"
    wa = triggers["Clic - click_whatsapp"]
    assert wa["filter"][0]["type"] == "contains"


def test_ads_conversion_tag_uses_the_provided_ids_and_first_key_event() -> None:
    container, warnings = _build(
        ["ga4_tag", "event_generate_lead", "ads_conversion_tag"],
        ads_conversion_id="AW-123456789",
        ads_conversion_label="AbCdEfGhIjK",
    )
    tags = {t["name"]: t for t in container["containerVersion"]["tag"]}
    ads = tags["Google Ads - Conversion"]
    params = {p["key"]: p.get("value") for p in ads["parameter"]}
    assert ads["type"] == "awct"
    assert params["conversionId"] == "123456789"
    assert params["conversionLabel"] == "AbCdEfGhIjK"
    lead_trigger = next(
        t["triggerId"]
        for t in container["containerVersion"]["trigger"]
        if t["name"] == "CE - generate_lead"
    )
    assert ads["firingTriggerId"] == [lead_trigger]
    assert "Conversion Linker" in tags
    assert tags["Conversion Linker"]["type"] == "gclidw"
    assert warnings == []


def test_ads_tag_without_ids_warns_and_is_skipped() -> None:
    container, warnings = _build(["ads_conversion_tag", "event_view_item"])
    assert "Google Ads - Conversion" not in _names(container, "tag")
    assert len(warnings) == 1
    assert "Réglages Ads" in warnings[0]


def test_ads_tag_without_a_key_event_warns() -> None:
    container, warnings = _build(
        ["ads_conversion_tag"],
        ads_conversion_id="AW-123456789",
        ads_conversion_label="AbCdEfGhIjK",
    )
    assert "Google Ads - Conversion" not in _names(container, "tag")
    assert any("événement clé" in w for w in warnings)


def test_conversion_linker_alone() -> None:
    container, _ = _build(["ads_conversion_linker"])
    assert "Conversion Linker" in _names(container, "tag")


def test_missing_measurement_id_uses_a_placeholder_and_warns() -> None:
    container, warnings = _build(["ga4_tag"], ga4_measurement_id=None)
    config = next(t for t in container["containerVersion"]["tag"] if t["name"] == "GA4 Configuration")
    assert config["parameter"][0]["value"] == "G-XXXXXXXXXX"
    assert any("ID de mesure" in w for w in warnings)


def test_events_without_ga4_tag_still_get_a_configuration_tag() -> None:
    container, _ = _build(["event_login"])
    assert "GA4 Configuration" in _names(container, "tag")


def test_import_metadata_and_mode() -> None:
    merge, _ = _build(["ga4_tag"])
    assert merge["importMetadata"]["mode"] == "merge"
    overwrite, _ = _build(["ga4_tag"], import_mode="overwrite")
    assert overwrite["importMetadata"]["mode"] == "overwrite"
```

Lancer → ÉCHEC (`ImportError: build_selected_container`).

- [ ] **Étape 2 : implémenter** (ajouter à la fin de `gtm_generator.py`, après
  `import_metadata`)

```python
# --------------------------------------------------------------------------- #
#  Conteneur sur mesure (plan de mesure)                                        #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _Recipe:
    event: str
    kind: str  # "custom_event" | "link_click"
    ecommerce: bool = False
    params: tuple[tuple[str, str], ...] = ()  # (paramètre GA4, variable dataLayer)
    link_op: str | None = None  # opérateur de filtre GTM pour "link_click"
    link_value: str | None = None


_RECIPES: dict[str, _Recipe] = {
    "event_view_item": _Recipe("view_item", "custom_event", ecommerce=True),
    "event_add_to_cart": _Recipe("add_to_cart", "custom_event", ecommerce=True),
    "event_begin_checkout": _Recipe("begin_checkout", "custom_event", ecommerce=True),
    "event_purchase": _Recipe("purchase", "custom_event", ecommerce=True),
    "event_generate_lead": _Recipe(
        "generate_lead", "custom_event", params=(("form_id", "{{dlv - form_id}}"),)
    ),
    "event_sign_up": _Recipe("sign_up", "custom_event"),
    "event_login": _Recipe("login", "custom_event"),
    "event_begin_trial": _Recipe("begin_trial", "custom_event"),
    "event_subscribe": _Recipe("subscribe", "custom_event"),
    "event_tutorial_complete": _Recipe("tutorial_complete", "custom_event"),
    "event_newsletter_signup": _Recipe("newsletter_signup", "custom_event"),
    "event_share": _Recipe("share", "custom_event"),
    "event_click_to_call": _Recipe(
        "click_to_call",
        "link_click",
        params=(("link_url", "{{Click URL}}"),),
        link_op="startsWith",
        link_value="tel:",
    ),
    "event_click_email": _Recipe(
        "click_email",
        "link_click",
        params=(("link_url", "{{Click URL}}"),),
        link_op="startsWith",
        link_value="mailto:",
    ),
    "event_click_whatsapp": _Recipe(
        "click_whatsapp",
        "link_click",
        params=(("link_url", "{{Click URL}}"),),
        link_op="contains",
        link_value="wa.me",
    ),
}

# Événements sur lesquels déclencher la conversion Ads, par ordre de préférence.
_ADS_KEY_EVENTS = ("event_purchase", "event_generate_lead", "event_sign_up", "event_subscribe")


def _event_params(params: tuple[tuple[str, str], ...]) -> list[dict] | None:
    if not params:
        return None
    return [
        {
            "type": "list",
            "key": "eventParameters",
            "list": [
                {
                    "type": "map",
                    "map": [
                        {"type": "template", "key": "name", "value": name},
                        {"type": "template", "key": "value", "value": value},
                    ],
                }
                for name, value in params
            ],
        }
    ]


def _link_click_trigger(base: dict, trigger_id: str, recipe: _Recipe) -> dict:
    return {
        **base,
        "triggerId": trigger_id,
        "name": f"Clic - {recipe.event}",
        "type": "linkClick",
        "waitForTags": [{"type": "boolean", "key": "waitForTags", "value": "false"}],
        "checkValidation": [{"type": "boolean", "key": "checkValidation", "value": "false"}],
        "filter": [
            {
                "type": recipe.link_op,
                "parameter": [
                    {"type": "template", "key": "arg0", "value": "{{Click URL}}"},
                    {"type": "template", "key": "arg1", "value": recipe.link_value},
                ],
            }
        ],
        "fingerprint": _FINGERPRINT,
    }


def build_selected_container(
    *,
    domain: str,
    stack: StackKind = StackKind.UNKNOWN,
    item_ids: list[str],
    ga4_measurement_id: str | None,
    ads_conversion_id: str | None,
    ads_conversion_label: str | None,
    import_mode: ImportMode = "merge",
    export_time: str | None = None,
) -> tuple[dict, list[str]]:
    """Conteneur GTM limité aux items choisis. Renvoie `(conteneur, avertissements)`."""
    if import_mode not in _IMPORT_METADATA:
        raise ValueError(f"import_mode inconnu : {import_mode!r}")

    selected = set(item_ids)
    warnings: list[str] = []
    account_id = _numeric_id(f"acct:{domain}", 10)
    container_id = _numeric_id(f"cont:{domain}", 9)
    public_id = f"GTM-{_short_code(domain, 7)}"
    base = {"accountId": account_id, "containerId": container_id}

    measurement_id = ga4_measurement_id or "G-XXXXXXXXXX"
    if not ga4_measurement_id:
        warnings.append(
            "ID de mesure GA4 inconnu : remplace G-XXXXXXXXXX par l'ID de ton flux de données "
            "avant de publier (ou connecte GA4 pour qu'il soit renseigné automatiquement)."
        )

    recipes = [(item_id, _RECIPES[item_id]) for item_id in item_ids if item_id in _RECIPES]
    wants_config = "ga4_tag" in selected or bool(recipes)

    triggers: list[dict] = []
    tags: list[dict] = []
    next_trigger = 10
    next_tag = 2
    trigger_by_item: dict[str, str] = {}

    if wants_config:
        config_triggers = [_ALL_PAGES_TRIGGER_ID]
        if stack in _SPA_STACKS:
            triggers.append(
                {
                    **base,
                    "triggerId": str(next_trigger),
                    "name": "History Change (SPA)",
                    "type": "historyChange",
                    "fingerprint": _FINGERPRINT,
                }
            )
            config_triggers.append(str(next_trigger))
            next_trigger += 1
        tags.append(
            {
                **base,
                "tagId": "1",
                "name": "GA4 Configuration",
                "type": "googtag",
                "parameter": [
                    {"type": "template", "key": "tagId", "value": measurement_id},
                    {
                        "type": "list",
                        "key": "configSettingsTable",
                        "list": [
                            {
                                "type": "map",
                                "map": [
                                    {
                                        "type": "template",
                                        "key": "parameter",
                                        "value": "send_page_view",
                                    },
                                    {
                                        "type": "template",
                                        "key": "parameterValue",
                                        "value": "true",
                                    },
                                ],
                            }
                        ],
                    },
                ],
                "fingerprint": _FINGERPRINT,
                "firingTriggerId": config_triggers,
                "tagFiringOption": "oncePerEvent",
                "monitoringMetadata": {"type": "map"},
                "consentSettings": {"consentStatus": "notSet"},
            }
        )

    for item_id, recipe in recipes:
        trigger_id = str(next_trigger)
        next_trigger += 1
        if recipe.kind == "link_click":
            triggers.append(_link_click_trigger(base, trigger_id, recipe))
        else:
            triggers.append(
                _custom_event_trigger(base, trigger_id, f"CE - {recipe.event}", recipe.event)
            )
        trigger_by_item[item_id] = trigger_id
        tags.append(
            _ga4_event_tag(
                base,
                str(next_tag),
                f"GA4 - {recipe.event}",
                recipe.event,
                trigger_id,
                ecommerce=recipe.ecommerce,
                extra_params=_event_params(recipe.params),
            )
        )
        next_tag += 1

    ads_selected = "ads_conversion_tag" in selected
    if ads_selected:
        numeric_id = (ads_conversion_id or "").removeprefix("AW-")
        key_event = next((k for k in _ADS_KEY_EVENTS if k in trigger_by_item), None)
        if not numeric_id or not ads_conversion_label:
            warnings.append(
                "Balise Ads ignorée : renseigne l'ID de conversion (AW-…) et le libellé dans "
                "« Réglages Ads »."
            )
        elif key_event is None:
            warnings.append(
                "Balise Ads ignorée : sélectionne aussi ton événement clé (achat, demande de "
                "contact, inscription ou abonnement) pour que la conversion se déclenche."
            )
        else:
            parameter = [
                {"type": "template", "key": "conversionId", "value": numeric_id},
                {"type": "template", "key": "conversionLabel", "value": ads_conversion_label},
            ]
            if _RECIPES[key_event].ecommerce:
                parameter += [
                    {"type": "template", "key": "conversionValue", "value": "{{dlv - value}}"},
                    {"type": "template", "key": "currencyCode", "value": "{{dlv - currency}}"},
                ]
            tags.append(
                {
                    **base,
                    "tagId": str(next_tag),
                    "name": "Google Ads - Conversion",
                    "type": "awct",
                    "parameter": parameter,
                    "fingerprint": _FINGERPRINT,
                    "firingTriggerId": [trigger_by_item[key_event]],
                    "tagFiringOption": "oncePerEvent",
                    "consentSettings": {"consentStatus": "notSet"},
                }
            )
            next_tag += 1

    ads_tag_added = any(t["name"] == "Google Ads - Conversion" for t in tags)
    if "ads_conversion_linker" in selected or ads_tag_added:
        tags.append(
            {
                **base,
                "tagId": str(next_tag),
                "name": "Conversion Linker",
                "type": "gclidw",
                "parameter": [],
                "fingerprint": _FINGERPRINT,
                "firingTriggerId": [_ALL_PAGES_TRIGGER_ID],
                "tagFiringOption": "oncePerEvent",
                "consentSettings": {"consentStatus": "notSet"},
            }
        )
        next_tag += 1

    variables = [
        _dlv_variable(base, "1", "dlv - value", "ecommerce.value"),
        _dlv_variable(base, "2", "dlv - currency", "ecommerce.currency"),
        _dlv_variable(base, "3", "dlv - items", "ecommerce.items"),
        _dlv_variable(base, "4", "dlv - form_id", "form_id"),
        {
            **base,
            "variableId": "5",
            "name": "Const - GA4 Measurement ID",
            "type": "c",
            "parameter": [{"type": "template", "key": "value", "value": measurement_id}],
            "fingerprint": _FINGERPRINT,
        },
    ]

    manager_url = (
        f"https://tagmanager.google.com/#/container/accounts/{account_id}"
        f"/containers/{container_id}/workspaces?apiLink=container"
    )
    description = (
        f"Genere par Control Center pour {domain} (plan de mesure). "
        f"Import : {_IMPORT_METADATA[import_mode]['gtm_option']}. "
        "Verifiez en mode Apercu avant de publier."
    )

    container = {
        "exportFormatVersion": 2,
        "exportTime": export_time or datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "containerVersion": {
            "path": f"accounts/{account_id}/containers/{container_id}/versions/0",
            **base,
            "containerVersionId": "0",
            "name": f"Control Center - plan de mesure - {domain}",
            "description": description,
            "container": {
                "path": f"accounts/{account_id}/containers/{container_id}",
                **base,
                "name": domain,
                "publicId": public_id,
                "usageContext": ["WEB"],
                "fingerprint": _FINGERPRINT,
                "tagManagerUrl": manager_url,
                "features": {
                    "supportUserPermissions": True,
                    "supportEnvironments": True,
                    "supportWorkspaces": True,
                    "supportGtagConfigs": True,
                },
            },
            "tag": tags,
            "trigger": triggers,
            "variable": variables,
            "builtInVariable": _built_in_variables(base),
            "fingerprint": _FINGERPRINT,
            "tagManagerUrl": manager_url,
        },
        "importMetadata": _IMPORT_METADATA[import_mode],
    }
    return container, warnings
```
Ajouter `from dataclasses import dataclass` aux imports en tête de `gtm_generator.py`
(à côté de `from datetime import UTC, datetime`).

- [ ] **Étape 3 : lancer les tests**

`.venv/Scripts/python.exe -m pytest tests/test_gtm_selected_container.py tests/test_gtm_generator.py -v`
→ verts (les tests existants de `build_gtm_container` sont inchangés). `ruff` propre.

- [ ] **Étape 4 : commit**

```bash
git add backend/app/services/gtm_generator.py backend/tests/test_gtm_selected_container.py
git commit -m "feat(measurement): conteneur GTM sur mesure (evenements, conversion Ads, Conversion Linker)"
```

- [ ] **Étape 5 (contrôle manuel, à faire par le propriétaire avant mise en ligne) :**
  générer un conteneur avec `ga4_tag`, un événement e-commerce, un clic sur lien
  et `ads_conversion_tag`, l'importer en mode « Fusionner » dans un conteneur GTM
  de **test** et confirmer que l'import réussit et que les balises `awct` et
  `gclidw` s'affichent correctement. Noter le résultat dans le compte rendu de la
  tâche ; en cas d'échec d'import, corriger les paramètres de ces deux types de
  balise avant de continuer.

---

### Tâche 9 : Service de plan (collecte, rafraîchissement, vue) et dépendances

**Fichiers :**
- Créer : `backend/app/services/measurement/fetch.py`
- Créer : `backend/app/services/measurement/service.py`
- Modifier : `backend/app/api/deps.py`
- Test : `backend/tests/test_measurement_service.py`

**Interfaces :**
- Consomme : catalogue, `evaluate`/`Facts`/`HeadlessFacts` (Tâche 6),
  `detect_site_types`/`resolve_effective_types` (Tâche 3), `GoogleReader`/
  `GoogleReadError` (Tâche 5), `snippet_for_event` (Tâche 7), `analyze_gtm`,
  `PageSnapshot`.
- Produit :
  - `fetch.py` : `PageFetcher = Callable[..., Awaitable[PageSnapshot | None]]`,
    `fetch_page_safe(url, *, allow_insecure=False) -> PageSnapshot | None`
    (jamais d'exception réseau).
  - `service.py` : `COOLDOWN = timedelta(minutes=5)` ; `RefreshResult(headless_ran,
    headless_skipped, headless_error)` ; `refresh_plan(session, website, *, fetcher,
    reader, verifier, run_headless, now=None) -> RefreshResult` (ne commit pas) ;
    `build_plan_view(session, website) -> dict` (forme décrite ci-dessous) ;
    `get_or_create_profile(session, website_id) -> WebsiteProfile`.
  - `deps.py` : `get_page_fetcher()` → `fetch_page_safe` ;
    `get_measurement_reader_factory(oauth, cipher)` → callable
    `(session, website) -> GoogleReader` ; alias `PageFetcherDep`,
    `ReaderFactoryDep`.
- Forme de `build_plan_view` :
  `{"website_id": UUID, "profile": {"detected_types": [...], "confirmed_types":
  [...]|None, "effective_types": [...], "needs_confirmation": bool, "params":
  {...}}, "ga4_connected": bool, "last_checked_at": datetime|None,
  "overall_done": int, "overall_total": int, "overall_percent": int,
  "layers": [{"layer", "total", "done"}], "items": [{"id", "layer", "title",
  "why", "weight", "quick_win", "max_level", "state", "done", "partial",
  "reason", "evidence", "checked_at", "guide", "actions", "snippet"}]}`.
- « Fait » : `state == "received"` **ou** (`state == "on_page"` et
  `max_level == "on_page"`). « Partiel » : `state == "on_page"` et
  `max_level == "received"`. Les états `not_applicable` et `dismissed` sont exclus
  des totaux.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_measurement_service.py
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import StackKind
from app.models.measurement_item_status import MeasurementItemStatus
from app.models.website import Website
from app.models.website_profile import WebsiteProfile
from app.services.gtm_headless import GtmHeadlessResult
from app.services.measurement.google_reader import GoogleReadError
from app.services.measurement.service import (
    COOLDOWN,
    build_plan_view,
    refresh_plan,
)
from app.services.page_fetch import PageSnapshot
from tests.conftest import owner_workspace_id

_SHOP_HTML = """
<html><head>
<script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':1,event:'gtm.js'});
var j=d.createElement(s);j.src='https://www.googletagmanager.com/gtm.js?id='+i;})
(window,document,'script','dataLayer','GTM-AAAA111');</script>
<script src="https://cdn.shopify.com/app.js"></script></head>
<body><button class="add-to-cart">Ajouter au panier</button></body></html>
"""


def _snapshot(url: str, html: str, status: int = 200, ctype: str = "text/html") -> PageSnapshot:
    return PageSnapshot(
        url=url,
        final_url=url,
        status=status,
        html=html,
        headers={"content-type": ctype},
        redirected=False,
        history=(),
    )


class _Fetcher:
    def __init__(self, html: str | None = _SHOP_HTML, robots_status: int = 200) -> None:
        self.html = html
        self.robots_status = robots_status
        self.calls: list[str] = []

    async def __call__(self, url: str, *, allow_insecure: bool = False):
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            return _snapshot(url, "User-agent: *", self.robots_status, "text/plain")
        if self.html is None:
            return None
        return _snapshot(url, self.html)


class _Reader:
    gsc_state = "not_linked"

    def __init__(self, **kw) -> None:
        self.stats = kw.get("stats")
        self.key = kw.get("key")
        self.ads = kw.get("ads")
        self.sitemaps = kw.get("sitemaps")
        self.gsc_state = kw.get("gsc_state", "not_linked")
        self.reason = kw.get("reason", "ga4_not_connected")

    async def event_stats(self):
        if self.stats is None:
            raise GoogleReadError(self.reason)
        return self.stats

    async def key_events(self):
        if self.key is None:
            raise GoogleReadError(self.reason)
        return self.key

    async def ads_links_count(self):
        if self.ads is None:
            raise GoogleReadError(self.reason)
        return self.ads

    async def measurement_id(self):
        raise GoogleReadError(self.reason)

    async def sitemaps_count(self):
        if self.sitemaps is None:
            raise GoogleReadError("gsc_not_connected")
        return self.sitemaps


class _Verifier:
    def __init__(self, error: str | None = None) -> None:
        self.calls = 0
        self.error = error

    async def __call__(self, url: str) -> GtmHeadlessResult:
        self.calls += 1
        return GtmHeadlessResult(
            gtm_js_loaded=self.error is None,
            containers_initialised=("GTM-AAAA111",) if self.error is None else (),
            datalayer_present=True,
            gtm_events=("view_item",),
            requests_before_consent=True,
            csp_console_errors=(),
            findings=(),
            checked_at=datetime.now(UTC),
            error=self.error,
            ga4_measurement_ids=("G-ABC123XYZ",),
            ads_requests=0,
            consent_default_seen=False,
        )


async def _site(db_session: AsyncSession, make_user, domain: str) -> Website:
    user = await make_user(sub=f"svc-{domain}")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(
        workspace_id=workspace_id,
        domain=domain,
        display_name=domain,
        detected_stack=StackKind.GENERIC,
        ssl_status="valid",
    )
    db_session.add(site)
    await db_session.flush()
    return site


def _item(view: dict, item_id: str) -> dict:
    return next(item for item in view["items"] if item["id"] == item_id)


async def test_refresh_persists_states_and_detects_the_site_type(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-shop.test")
    await refresh_plan(
        db_session,
        site,
        fetcher=_Fetcher(),
        reader=_Reader(),
        verifier=_Verifier(),
        run_headless=False,
    )
    view = await build_plan_view(db_session, site)

    assert view["profile"]["effective_types"] == ["ecommerce"]
    assert view["profile"]["needs_confirmation"] is True
    assert _item(view, "gtm_installed")["state"] == "on_page"
    assert _item(view, "gtm_installed")["done"] is True
    assert _item(view, "event_purchase")["state"] == "unverifiable"
    assert _item(view, "event_purchase")["reason"] == "ga4_not_connected"
    assert _item(view, "event_generate_lead")["state"] == "not_applicable"
    assert _item(view, "robots_txt")["state"] == "on_page"
    assert _item(view, "tls_valid")["state"] == "on_page"
    assert view["last_checked_at"] is not None
    assert view["overall_total"] > 0
    assert view["ga4_connected"] is False


async def test_ga4_data_upgrades_events_to_received_and_computes_progress(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-received.test")
    reader = _Reader(
        stats={
            "page_view": {"count": 400.0},
            "purchase": {"count": 5.0, "revenue": 250.0, "value": 0.0},
        },
        key=[{"eventName": "purchase"}],
        ads=0,
        sitemaps=1,
        gsc_state="linked",
    )
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=reader, verifier=_Verifier(), run_headless=False
    )
    view = await build_plan_view(db_session, site)

    assert _item(view, "event_purchase")["state"] == "received"
    assert _item(view, "event_purchase")["evidence"]["ga4_count_30d"] == 5
    assert _item(view, "purchase_params")["state"] == "received"
    assert _item(view, "key_events_marked")["state"] == "received"
    assert _item(view, "ads_ga4_link")["state"] == "missing"
    assert _item(view, "gsc_property_linked")["state"] == "received"
    assert _item(view, "gsc_sitemaps")["state"] == "received"
    assert _item(view, "ga4_tag")["state"] == "received"
    layers = {layer["layer"]: layer for layer in view["layers"]}
    assert layers["seo"]["done"] >= 3
    assert view["overall_percent"] == round(100 * view["overall_done"] / view["overall_total"])
    assert view["ga4_connected"] is False  # aucune liaison GA4 en base dans ce test


async def test_confirmed_types_prevail_and_change_applicability(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-confirm.test")
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(), run_headless=False
    )
    profile = await db_session.get(WebsiteProfile, site.id)
    profile.confirmed_types = ["lead_gen"]
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(), run_headless=False
    )
    view = await build_plan_view(db_session, site)
    assert view["profile"]["effective_types"] == ["lead_gen"]
    assert view["profile"]["needs_confirmation"] is False
    assert _item(view, "event_purchase")["state"] == "not_applicable"
    assert _item(view, "event_generate_lead")["state"] != "not_applicable"


async def test_uses_google_ads_false_disables_the_ads_layer(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-ads.test")
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(), run_headless=False
    )
    profile = await db_session.get(WebsiteProfile, site.id)
    profile.params = {"uses_google_ads": False}
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(), run_headless=False
    )
    view = await build_plan_view(db_session, site)
    assert _item(view, "ads_ga4_link")["state"] == "not_applicable"
    assert _item(view, "ads_auto_tagging")["state"] == "not_applicable"


async def test_unreachable_site_makes_page_items_unverifiable(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-down.test")
    await refresh_plan(
        db_session,
        site,
        fetcher=_Fetcher(html=None),
        reader=_Reader(),
        verifier=_Verifier(),
        run_headless=False,
    )
    view = await build_plan_view(db_session, site)
    gtm = _item(view, "gtm_installed")
    assert gtm["state"] == "unverifiable" and gtm["reason"] == "fetch_error"
    assert _item(view, "tls_valid")["state"] == "on_page"  # ne dépend pas de la page


async def test_headless_runs_once_then_cooldown_and_result_is_reused(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-headless.test")
    verifier = _Verifier()
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    first = await refresh_plan(
        db_session,
        site,
        fetcher=_Fetcher(),
        reader=_Reader(),
        verifier=verifier,
        run_headless=True,
        now=now,
    )
    assert first.headless_ran is True and verifier.calls == 1
    view = await build_plan_view(db_session, site)
    assert _item(view, "ga4_tag")["state"] == "on_page"  # vu par le navigateur

    second = await refresh_plan(
        db_session,
        site,
        fetcher=_Fetcher(),
        reader=_Reader(),
        verifier=verifier,
        run_headless=True,
        now=now + timedelta(minutes=2),
    )
    assert second.headless_skipped is True and verifier.calls == 1

    third = await refresh_plan(
        db_session,
        site,
        fetcher=_Fetcher(),
        reader=_Reader(),
        verifier=verifier,
        run_headless=True,
        now=now + COOLDOWN + timedelta(seconds=1),
    )
    assert third.headless_ran is True and verifier.calls == 2

    # Sans headless, le dernier résultat conservé est réutilisé (pas de « clignotement »).
    await refresh_plan(
        db_session,
        site,
        fetcher=_Fetcher(),
        reader=_Reader(),
        verifier=verifier,
        run_headless=False,
        now=now + timedelta(hours=1),
    )
    view = await build_plan_view(db_session, site)
    assert _item(view, "ga4_tag")["state"] == "on_page"


async def test_headless_error_keeps_the_previous_result(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-headless-err.test")
    result = await refresh_plan(
        db_session,
        site,
        fetcher=_Fetcher(),
        reader=_Reader(),
        verifier=_Verifier(error="TimeoutError: boom"),
        run_headless=True,
    )
    assert result.headless_ran is False
    assert result.headless_error == "TimeoutError: boom"
    profile = await db_session.get(WebsiteProfile, site.id)
    assert profile.headless_result is None


async def test_dismissed_and_manual_done_survive_a_refresh(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-persist.test")
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(), run_headless=False
    )
    rows = {
        row.item_id: row
        for row in (
            await db_session.execute(
                select(MeasurementItemStatus).where(MeasurementItemStatus.website_id == site.id)
            )
        ).scalars()
    }
    rows["robots_txt"].dismissed_at = datetime.now(UTC)
    rows["ads_auto_tagging"].evidence = {"manual_done": True}
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(), run_headless=False
    )
    view = await build_plan_view(db_session, site)
    assert _item(view, "robots_txt")["state"] == "dismissed"
    assert _item(view, "ads_auto_tagging")["state"] == "on_page"
    assert _item(view, "ads_auto_tagging")["done"] is True


async def test_view_before_any_refresh_is_all_unknown(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-empty.test")
    view = await build_plan_view(db_session, site)
    assert view["last_checked_at"] is None
    assert view["profile"]["effective_types"] == ["other"]
    assert all(item["state"] == "unknown" for item in view["items"])
    assert view["overall_done"] == 0


async def test_view_orders_by_layer_then_weight_and_ships_snippets(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-order.test")
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(), run_headless=False
    )
    view = await build_plan_view(db_session, site)
    layers = [item["layer"] for item in view["items"]]
    order = ["foundations", "events", "conversions", "ads", "seo"]
    assert layers == sorted(layers, key=order.index)
    foundations = [i["weight"] for i in view["items"] if i["layer"] == "foundations"]
    assert foundations == sorted(foundations, reverse=True)
    purchase = _item(view, "event_purchase")
    assert purchase["snippet"] is not None and "purchase" in purchase["snippet"]["code"]
    assert _item(view, "gtm_installed")["snippet"] is None
```

Lancer → ÉCHEC (modules absents).

- [ ] **Étape 2 : créer `fetch.py`**

```python
# backend/app/services/measurement/fetch.py
from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

from app.services.page_fetch import PageSnapshot, fetch_page

PageFetcher = Callable[..., Awaitable[PageSnapshot | None]]


async def fetch_page_safe(url: str, *, allow_insecure: bool = False) -> PageSnapshot | None:
    """`fetch_page` qui ne lève jamais : `None` si le site est injoignable."""
    try:
        return await fetch_page(url, allow_insecure=allow_insecure)
    except httpx.HTTPError:
        return None
```

- [ ] **Étape 3 : créer `service.py`**

```python
# backend/app/services/measurement/service.py
"""Orchestration du plan de mesure : collecte des faits, évaluation du catalogue,
persistance de l'état courant et construction de la vue API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ResourceType
from app.models.measurement_item_status import MeasurementItemStatus
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.models.website_profile import WebsiteProfile
from app.services.gtm_check import analyze_gtm
from app.services.gtm_headless import GtmHeadlessVerifier
from app.services.measurement.catalog import (
    ITEMS,
    LAYER_ORDER,
    is_applicable,
)
from app.services.measurement.checks import Facts, HeadlessFacts, evaluate
from app.services.measurement.event_snippets import snippet_for_event
from app.services.measurement.fetch import PageFetcher
from app.services.measurement.google_reader import GoogleReader, GoogleReadError
from app.services.measurement.site_types import detect_site_types, resolve_effective_types
from app.services.measurement.types import MeasurementItem, Outcome

COOLDOWN = timedelta(minutes=5)

ReaderFactory = Callable[[AsyncSession, Website], Awaitable[GoogleReader]]

_DEAD_TOKEN_REASONS = frozenset({"ga4_not_connected", "token_unavailable"})


@dataclass(frozen=True, slots=True)
class RefreshResult:
    headless_ran: bool = False
    headless_skipped: bool = False
    headless_error: str | None = None


async def get_or_create_profile(session: AsyncSession, website_id: Any) -> WebsiteProfile:
    profile = await session.get(WebsiteProfile, website_id)
    if profile is None:
        profile = WebsiteProfile(website_id=website_id, detected_types=[], params={})
        session.add(profile)
        await session.flush()
    return profile


async def _safe(call: Callable[[], Awaitable[Any]]) -> tuple[Any, str | None]:
    try:
        return await call(), None
    except GoogleReadError as exc:
        return None, exc.reason


def _page_facts(page: Any) -> tuple[str | None, str | None]:
    """(html, erreur) à partir d'un `PageSnapshot` ou de `None`."""
    if page is None:
        return None, "fetch_error"
    if page.status >= 400:
        return None, "http_error"
    if "html" not in page.headers.get("content-type", "").lower():
        return None, "non_html"
    return page.html, None


async def refresh_plan(
    session: AsyncSession,
    website: Website,
    *,
    fetcher: PageFetcher,
    reader: GoogleReader,
    verifier: GtmHeadlessVerifier,
    run_headless: bool,
    now: datetime | None = None,
) -> RefreshResult:
    """Recalcule et enregistre l'état de chaque item. Ne fait pas de commit."""
    now = now or datetime.now(UTC)
    profile = await get_or_create_profile(session, website.id)

    base_url = f"https://{website.domain}"
    insecure = website.allow_insecure_probe
    page = await fetcher(base_url, allow_insecure=insecure)
    html, page_error = _page_facts(page)
    gtm = analyze_gtm(page) if html is not None and page is not None else None

    if html is not None and not profile.confirmed_types:
        profile.detected_types = detect_site_types(html, website.detected_stack)
    effective = tuple(resolve_effective_types(profile.detected_types, profile.confirmed_types))

    robots = await fetcher(f"{base_url}/robots.txt", allow_insecure=insecure)
    robots_ok = None if robots is None else robots.status == 200

    # -- navigateur headless (action explicite, délai de 5 minutes) ---------------
    headless = HeadlessFacts.from_dict(profile.headless_result)
    ran = skipped = False
    error: str | None = None
    if run_headless:
        last = profile.headless_checked_at
        if last is not None and now - last < COOLDOWN:
            skipped = True
        else:
            result = await verifier(base_url)
            if result.error is None:
                headless = HeadlessFacts.from_result(result)
                profile.headless_result = headless.to_dict()
                profile.headless_checked_at = now
                ran = True
            else:
                error = result.error

    # -- lectures Google -------------------------------------------------------
    ga4_stats, ga4_reason = await _safe(reader.event_stats)
    if ga4_reason in _DEAD_TOKEN_REASONS:
        key_events, key_reason = None, ga4_reason
        ads_count, ads_reason = None, ga4_reason
    else:
        key_events, key_reason = await _safe(reader.key_events)
        ads_count, ads_reason = await _safe(reader.ads_links_count)
    sitemaps, sitemaps_reason = await _safe(reader.sitemaps_count)

    # -- état précédent (marquages manuels, items écartés) ----------------------
    existing = {
        row.item_id: row
        for row in (
            await session.execute(
                select(MeasurementItemStatus).where(MeasurementItemStatus.website_id == website.id)
            )
        ).scalars()
    }
    manual_done = frozenset(
        item_id for item_id, row in existing.items() if row.evidence.get("manual_done") is True
    )

    facts = Facts(
        page_html=html,
        page_error=page_error,
        gtm=gtm,
        headless=headless,
        ga4_stats=ga4_stats,
        ga4_reason=ga4_reason,
        key_events=key_events,
        key_events_reason=key_reason,
        ads_links_count=ads_count,
        ads_links_reason=ads_reason,
        gsc_state=reader.gsc_state,
        sitemaps_count=sitemaps,
        sitemaps_reason=sitemaps_reason,
        robots_ok=robots_ok,
        ssl_status=website.ssl_status,
        effective_types=effective,
        manual_done=manual_done,
    )

    uses_ads = profile.params.get("uses_google_ads")
    for item in ITEMS:
        row = existing.get(item.id)
        if not is_applicable(item, effective, uses_ads):
            # Le marquage manuel survit à un passage en « non concerné ».
            kept = {"manual_done": True} if item.id in manual_done else {}
            outcome = Outcome("not_applicable", kept, None)
        elif row is not None and row.dismissed_at is not None:
            outcome = Outcome("dismissed", dict(row.evidence), None)
        else:
            outcome = evaluate(item, facts)
        if row is None:
            session.add(
                MeasurementItemStatus(
                    website_id=website.id,
                    item_id=item.id,
                    state=outcome.state,
                    evidence=outcome.evidence,
                    reason=outcome.reason,
                    checked_at=now,
                )
            )
        else:
            row.state = outcome.state
            row.evidence = outcome.evidence
            row.reason = outcome.reason
            row.checked_at = now
    await session.flush()
    return RefreshResult(headless_ran=ran, headless_skipped=skipped, headless_error=error)


# ---------------------------------------------------------------------------
#  Vue API
# ---------------------------------------------------------------------------


def _is_done(item: MeasurementItem, state: str) -> bool:
    return state == "received" or (state == "on_page" and item.max_level == "on_page")


def _snippet_dict(item: MeasurementItem, website: Website) -> dict[str, str] | None:
    if "snippet" not in item.actions or not item.snippet_event:
        return None
    snippet = snippet_for_event(item.snippet_event, website.detected_stack)
    if snippet is None:
        return None
    return {
        "language": snippet.language,
        "code": snippet.code,
        "target_path": snippet.target_path,
        "instructions": snippet.instructions,
    }


async def build_plan_view(session: AsyncSession, website: Website) -> dict[str, Any]:
    profile = await session.get(WebsiteProfile, website.id)
    detected = list(profile.detected_types) if profile else []
    confirmed = list(profile.confirmed_types) if profile and profile.confirmed_types else None
    params = dict(profile.params) if profile else {}
    effective = resolve_effective_types(detected, confirmed)

    rows = {
        row.item_id: row
        for row in (
            await session.execute(
                select(MeasurementItemStatus).where(MeasurementItemStatus.website_id == website.id)
            )
        ).scalars()
    }
    ga4_linked = (
        await session.execute(
            select(WebsiteGoogleLink.id).where(
                WebsiteGoogleLink.website_id == website.id,
                WebsiteGoogleLink.resource_type == ResourceType.GA4_PROPERTY,
            )
        )
    ).first() is not None

    ordered = sorted(ITEMS, key=lambda i: (LAYER_ORDER.index(i.layer), -i.weight))
    items: list[dict[str, Any]] = []
    layer_totals: dict[str, dict[str, int]] = {
        layer: {"total": 0, "done": 0} for layer in LAYER_ORDER
    }
    last_checked: datetime | None = None
    for item in ordered:
        row = rows.get(item.id)
        state = row.state if row else "unknown"
        done = _is_done(item, state)
        partial = state == "on_page" and item.max_level == "received"
        if state not in ("not_applicable", "dismissed"):
            layer_totals[item.layer]["total"] += 1
            layer_totals[item.layer]["done"] += 1 if done else 0
        if row is not None and (last_checked is None or row.checked_at > last_checked):
            last_checked = row.checked_at
        items.append(
            {
                "id": item.id,
                "layer": item.layer,
                "title": item.title,
                "why": item.why,
                "weight": item.weight,
                "quick_win": item.quick_win,
                "max_level": item.max_level,
                "state": state,
                "done": done,
                "partial": partial,
                "reason": row.reason if row else None,
                "evidence": dict(row.evidence) if row else {},
                "checked_at": row.checked_at if row else None,
                "guide": list(item.guide),
                "actions": list(item.actions),
                "snippet": _snippet_dict(item, website),
            }
        )

    overall_total = sum(t["total"] for t in layer_totals.values())
    overall_done = sum(t["done"] for t in layer_totals.values())
    return {
        "website_id": website.id,
        "profile": {
            "detected_types": detected,
            "confirmed_types": confirmed,
            "effective_types": effective,
            "needs_confirmation": confirmed is None,
            "params": {
                "ads_conversion_id": params.get("ads_conversion_id"),
                "ads_conversion_label": params.get("ads_conversion_label"),
                "uses_google_ads": params.get("uses_google_ads"),
                "ga4_measurement_id": params.get("ga4_measurement_id"),
            },
        },
        "ga4_connected": ga4_linked,
        "last_checked_at": last_checked,
        "overall_done": overall_done,
        "overall_total": overall_total,
        "overall_percent": round(100 * overall_done / overall_total) if overall_total else 0,
        "layers": [
            {"layer": layer, "total": layer_totals[layer]["total"], "done": layer_totals[layer]["done"]}
            for layer in LAYER_ORDER
        ],
        "items": items,
    }
```

- [ ] **Étape 4 : dépendances dans `backend/app/api/deps.py`**

Ajouter aux imports :

```python
from app.models.website import Website
from app.services.measurement.fetch import PageFetcher, fetch_page_safe
from app.services.measurement.google_access import build_reader
from app.services.measurement.google_reader import GoogleReader
from app.services.measurement.service import ReaderFactory
```
(`Website` peut déjà être importé : ne pas dupliquer ; `AsyncSession` l'est déjà.)

Ajouter, avec les autres `get_*` :

```python
def get_page_fetcher() -> PageFetcher:
    # Fetch HTTP léger, jamais d'exception réseau (None si injoignable).
    return fetch_page_safe


def get_measurement_reader_factory(
    oauth: GoogleClientDep, cipher: TokenCipherDep
) -> ReaderFactory:
    async def _factory(session: AsyncSession, website: Website) -> GoogleReader:
        return await build_reader(session, website, oauth=oauth, cipher=cipher)

    return _factory
```
et, avec les alias `...Dep` (après leur définition) :

```python
PageFetcherDep = Annotated[PageFetcher, Depends(get_page_fetcher)]
ReaderFactoryDep = Annotated[ReaderFactory, Depends(get_measurement_reader_factory)]
```
Attention à l'ordre : `get_measurement_reader_factory` utilise `GoogleClientDep` et
`TokenCipherDep` dans sa **signature** ; il doit donc être défini **après** ces
deux alias (à placer sous le bloc des alias `...Dep` existants, avant
`_session_user_id`). Ne pas importer `service` depuis `deps` si cela crée un cycle :
`ReaderFactory` est défini dans `service.py`, qui n'importe pas `deps`.

- [ ] **Étape 5 : lancer les tests**

`.venv/Scripts/python.exe -m pytest tests/test_measurement_service.py -v` puis la suite
complète `pytest -W error -q` (vérifie l'absence de cycle d'import via `app.main`).
`ruff` propre.

- [ ] **Étape 6 : commit**

```bash
git add backend/app/services/measurement backend/app/api/deps.py backend/tests/test_measurement_service.py
git commit -m "feat(measurement): service de plan (collecte, rafraichissement, vue) et dependances"
```

---

### Tâche 10 : API du plan de mesure

**Fichiers :**
- Créer : `backend/app/api/v1/endpoints/measurement.py`
- Modifier : `backend/app/api/v1/router.py`
- Test : `backend/tests/test_measurement_endpoints.py`

**Interfaces :**
- Consomme : `refresh_plan`, `build_plan_view`, `get_or_create_profile`,
  `ITEMS_BY_ID`, `build_selected_container`, `owned_website`, `require_owner`,
  `GtmHeadlessVerifierDep`, `PageFetcherDep`, `ReaderFactoryDep`.
- Produit (préfixe `/api/v1`) :
  - `GET /websites/{id}/measurement-plan` → `PlanOut` (membres).
  - `POST /websites/{id}/measurement-plan/refresh?headless=false` → `PlanOut` +
    `headless_skipped`, `headless_error` (membres).
  - `PATCH /websites/{id}/measurement-plan/profile` → `PlanOut` (**propriétaire**) ;
    corps : `confirmed_types`, `uses_google_ads`, `ads_conversion_id`
    (`^AW-\d{6,}$`), `ads_conversion_label` (`^[A-Za-z0-9_-]{6,}$`),
    `ga4_measurement_id` (`^G-[A-Z0-9]{6,}$`) — champ absent = inchangé, `null` =
    effacer.
  - `PATCH /websites/{id}/measurement-plan/items/{item_id}` → `PlanOut`
    (**propriétaire**) ; corps : `dismissed`, `manual_done` (uniquement pour les
    items `manual`, sinon 400) ; item inconnu → 404.
  - `POST /websites/{id}/measurement-plan/gtm-container` →
    `{container, warnings, filename}` (membres) ; corps : `item_ids`,
    `import_mode` (`merge` par défaut) ; item inconnu → 400.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_measurement_endpoints.py
from datetime import UTC, datetime

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_gtm_headless_verifier,
    get_measurement_reader_factory,
    get_page_fetcher,
)
from app.main import app
from app.models.user import User
from app.models.website import Website
from app.models.workspace_member import WorkspaceMember
from app.services.gtm_headless import GtmHeadlessResult
from app.services.measurement.google_reader import GoogleReadError
from app.services.page_fetch import PageSnapshot
from tests.conftest import owner_workspace_id

_HTML = """<html><head><script>(function(w,d,s,l,i){})(window,document,'script','dataLayer','GTM-AAAA111');
</script><script src="https://www.googletagmanager.com/gtm.js?id=GTM-AAAA111"></script></head>
<body><a href="tel:+33400000000">Appeler</a><form action="/contact"></form>
<p>Demandez un devis gratuit</p></body></html>"""


class _Reader:
    gsc_state = "not_linked"

    async def event_stats(self):
        raise GoogleReadError("ga4_not_connected")

    async def key_events(self):
        raise GoogleReadError("ga4_not_connected")

    async def ads_links_count(self):
        raise GoogleReadError("ga4_not_connected")

    async def measurement_id(self):
        return "G-ABC123XYZ"

    async def sitemaps_count(self):
        raise GoogleReadError("gsc_not_connected")


async def _fetcher(url: str, *, allow_insecure: bool = False):
    ctype = "text/plain" if url.endswith("robots.txt") else "text/html"
    return PageSnapshot(
        url=url,
        final_url=url,
        status=200,
        html=_HTML,
        headers={"content-type": ctype},
        redirected=False,
        history=(),
    )


async def _verifier(url: str) -> GtmHeadlessResult:
    return GtmHeadlessResult(
        gtm_js_loaded=True,
        containers_initialised=("GTM-AAAA111",),
        datalayer_present=True,
        gtm_events=(),
        requests_before_consent=True,
        csp_console_errors=(),
        findings=(),
        checked_at=datetime.now(UTC),
        ga4_measurement_ids=("G-ABC123XYZ",),
    )


@pytest_asyncio.fixture
def measurement_overrides():
    async def _factory(session, website):
        return _Reader()

    app.dependency_overrides[get_page_fetcher] = lambda: _fetcher
    app.dependency_overrides[get_measurement_reader_factory] = lambda: _factory
    app.dependency_overrides[get_gtm_headless_verifier] = lambda: _verifier
    yield
    for dep in (get_page_fetcher, get_measurement_reader_factory, get_gtm_headless_verifier):
        app.dependency_overrides.pop(dep, None)


async def _site(db_session: AsyncSession, user: User, domain: str) -> Website:
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=domain, display_name=domain, ssl_status="valid")
    db_session.add(site)
    await db_session.flush()
    return site


def _url(site: Website, suffix: str = "") -> str:
    return f"/api/v1/websites/{site.id}/measurement-plan{suffix}"


async def test_endpoints_require_authentication(db_client: AsyncClient) -> None:
    fake = "00000000-0000-0000-0000-000000000000"
    assert (await db_client.get(f"/api/v1/websites/{fake}/measurement-plan")).status_code == 401


async def test_get_before_refresh_then_refresh(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-refresh.test")

    empty = (await client.get(_url(site))).json()
    assert empty["last_checked_at"] is None
    assert all(item["state"] == "unknown" for item in empty["items"])

    resp = await client.post(_url(site, "/refresh"))
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["profile"]["effective_types"] == ["lead_gen"]
    assert plan["profile"]["needs_confirmation"] is True
    by_id = {item["id"]: item for item in plan["items"]}
    assert by_id["gtm_installed"]["state"] == "on_page"
    assert by_id["event_generate_lead"]["state"] == "unverifiable"
    assert by_id["event_generate_lead"]["reason"] == "ga4_not_connected"
    assert plan["headless_skipped"] is False
    assert {"layer", "total", "done"} <= set(plan["layers"][0])


async def test_refresh_with_headless_then_cooldown(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-headless.test")

    first = (await client.post(_url(site, "/refresh"), params={"headless": "true"})).json()
    assert first["headless_skipped"] is False
    by_id = {item["id"]: item for item in first["items"]}
    assert by_id["ga4_tag"]["state"] == "on_page"

    second = (await client.post(_url(site, "/refresh"), params={"headless": "true"})).json()
    assert second["headless_skipped"] is True


async def test_owner_can_confirm_types_and_set_ads_params(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-profile.test")

    resp = await client.patch(
        _url(site, "/profile"),
        json={
            "confirmed_types": ["ecommerce", "content"],
            "ads_conversion_id": "AW-123456789",
            "ads_conversion_label": "AbCdEfGhIjK",
            "uses_google_ads": True,
            "ga4_measurement_id": "G-ABC123XYZ",
        },
    )
    assert resp.status_code == 200, resp.text
    profile = resp.json()["profile"]
    assert profile["confirmed_types"] == ["ecommerce", "content"]
    assert profile["needs_confirmation"] is False
    assert profile["params"]["ads_conversion_id"] == "AW-123456789"
    assert profile["params"]["uses_google_ads"] is True

    cleared = await client.patch(_url(site, "/profile"), json={"ads_conversion_id": None})
    assert cleared.json()["profile"]["params"]["ads_conversion_id"] is None
    assert cleared.json()["profile"]["params"]["ads_conversion_label"] == "AbCdEfGhIjK"


async def test_profile_validation(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-validate.test")
    for body in (
        {"confirmed_types": ["unknown_type"]},
        {"ads_conversion_id": "123"},
        {"ads_conversion_label": "x"},
        {"ga4_measurement_id": "UA-1234"},
    ):
        assert (await client.patch(_url(site, "/profile"), json=body)).status_code == 422, body


async def test_non_owner_member_can_read_but_not_edit(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, make_user, measurement_overrides
) -> None:
    client, user = authed_client
    other_owner = await make_user(sub="mpe-other-owner")
    other_ws = await owner_workspace_id(db_session, other_owner)
    site = Website(workspace_id=other_ws, domain="mpe-shared.test", display_name="Shared")
    db_session.add(site)
    db_session.add(WorkspaceMember(workspace_id=other_ws, user_id=user.id, role="member"))
    await db_session.flush()

    assert (await client.get(_url(site))).status_code == 200
    assert (await client.post(_url(site, "/refresh"))).status_code == 200
    assert (
        await client.patch(_url(site, "/profile"), json={"confirmed_types": ["saas"]})
    ).status_code == 403
    assert (
        await client.patch(_url(site, "/items/robots_txt"), json={"dismissed": True})
    ).status_code == 403


async def test_stranger_gets_404(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, make_user, measurement_overrides
) -> None:
    client, _ = authed_client
    stranger = await make_user(sub="mpe-stranger")
    site = await _site(db_session, stranger, "mpe-private.test")
    assert (await client.get(_url(site))).status_code == 404


async def test_dismiss_and_manual_done(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-items.test")
    await client.post(_url(site, "/refresh"))

    dismissed = await client.patch(_url(site, "/items/robots_txt"), json={"dismissed": True})
    assert dismissed.status_code == 200
    by_id = {i["id"]: i for i in dismissed.json()["items"]}
    assert by_id["robots_txt"]["state"] == "dismissed"

    restored = await client.patch(_url(site, "/items/robots_txt"), json={"dismissed": False})
    assert {i["id"]: i for i in restored.json()["items"]}["robots_txt"]["state"] == "unknown"
    refreshed = (await client.post(_url(site, "/refresh"))).json()
    assert {i["id"]: i for i in refreshed["items"]}["robots_txt"]["state"] == "on_page"

    done = await client.patch(_url(site, "/items/ads_auto_tagging"), json={"manual_done": True})
    item = {i["id"]: i for i in done.json()["items"]}["ads_auto_tagging"]
    assert item["state"] == "on_page" and item["done"] is True
    after = (await client.post(_url(site, "/refresh"))).json()
    assert {i["id"]: i for i in after["items"]}["ads_auto_tagging"]["done"] is True

    assert (
        await client.patch(_url(site, "/items/gtm_installed"), json={"manual_done": True})
    ).status_code == 400
    assert (
        await client.patch(_url(site, "/items/does_not_exist"), json={"dismissed": True})
    ).status_code == 404


async def test_gtm_container_endpoint(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-container.test")

    resp = await client.post(
        _url(site, "/gtm-container"),
        json={"item_ids": ["ga4_tag", "event_generate_lead", "event_click_to_call"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == "gtm-plan-mpe-container.test.json"
    tags = [t["name"] for t in body["container"]["containerVersion"]["tag"]]
    assert "GA4 - generate_lead" in tags and "GA4 - click_to_call" in tags
    config = next(
        t for t in body["container"]["containerVersion"]["tag"] if t["name"] == "GA4 Configuration"
    )
    assert config["parameter"][0]["value"] == "G-ABC123XYZ"  # lu depuis GA4 (lecteur factice)
    assert body["warnings"] == []

    bad = await client.post(_url(site, "/gtm-container"), json={"item_ids": ["nope"]})
    assert bad.status_code == 400
```

Lancer → ÉCHEC (404 : routes absentes).

- [ ] **Étape 2 : créer l'endpoint**

```python
# backend/app/api/v1/endpoints/measurement.py
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, field_validator

from app.api.deps import (
    CurrentUserDep,
    GtmHeadlessVerifierDep,
    PageFetcherDep,
    ReaderFactoryDep,
    SessionDep,
)
from app.models.enums import StackKind
from app.models.measurement_item_status import MeasurementItemStatus
from app.services.gtm_generator import build_selected_container
from app.services.measurement.catalog import ITEMS_BY_ID
from app.services.measurement.google_reader import GoogleReadError
from app.services.measurement.service import (
    build_plan_view,
    get_or_create_profile,
    refresh_plan,
)
from app.services.workspaces import owned_website, require_owner

router = APIRouter(tags=["measurement"])

SiteTypeName = Literal["ecommerce", "lead_gen", "saas", "content", "other"]
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
    last_checked_at: datetime | None
    overall_done: int
    overall_total: int
    overall_percent: int
    layers: list[LayerProgressOut]
    items: list[ItemOut]
    headless_skipped: bool = False
    headless_error: str | None = None


# ---- schémas d'entrée --------------------------------------------------------
class ProfilePatch(BaseModel):
    confirmed_types: list[SiteTypeName] | None = None
    uses_google_ads: bool | None = None
    ads_conversion_id: str | None = None
    ads_conversion_label: str | None = None
    ga4_measurement_id: str | None = None

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


class ContainerBody(BaseModel):
    item_ids: list[str]
    import_mode: Literal["merge", "overwrite"] = "merge"


class ContainerOut(BaseModel):
    container: dict[str, Any]
    warnings: list[str]
    filename: str


# ---- endpoints ---------------------------------------------------------------
@router.get("/websites/{website_id}/measurement-plan", response_model=PlanOut)
async def get_measurement_plan(
    website_id: UUID, user: CurrentUserDep, session: SessionDep
) -> PlanOut:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    return PlanOut(**await build_plan_view(session, site))


@router.post("/websites/{website_id}/measurement-plan/refresh", response_model=PlanOut)
async def refresh_measurement_plan(
    website_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    fetcher: PageFetcherDep,
    reader_factory: ReaderFactoryDep,
    verifier: GtmHeadlessVerifierDep,
    headless: Annotated[bool, Query()] = False,
) -> PlanOut:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
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


@router.patch("/websites/{website_id}/measurement-plan/profile", response_model=PlanOut)
async def patch_measurement_profile(
    website_id: UUID, body: ProfilePatch, user: CurrentUserDep, session: SessionDep
) -> PlanOut:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    await require_owner(session, workspace_id=site.workspace_id, user_id=user.id)

    profile = await get_or_create_profile(session, site.id)
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
    await session.commit()
    return PlanOut(**await build_plan_view(session, site))


@router.patch("/websites/{website_id}/measurement-plan/items/{item_id}", response_model=PlanOut)
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

    now = datetime.now(UTC)
    row = await session.get(MeasurementItemStatus, (site.id, item_id))
    if row is None:
        row = MeasurementItemStatus(
            website_id=site.id, item_id=item_id, state="unknown", evidence={}, checked_at=now
        )
        session.add(row)
    if body.dismissed is True:
        row.dismissed_at = now
        row.state = "dismissed"
    elif body.dismissed is False:
        row.dismissed_at = None
        row.state = "unknown"
    if body.manual_done is not None:
        row.evidence = {**row.evidence, "manual_done": body.manual_done}
        row.state = "on_page" if body.manual_done else "unverifiable"
        row.reason = None if body.manual_done else "manual_check"
        row.checked_at = now
    await session.commit()
    return PlanOut(**await build_plan_view(session, site))


@router.post("/websites/{website_id}/measurement-plan/gtm-container", response_model=ContainerOut)
async def build_measurement_container(
    website_id: UUID,
    body: ContainerBody,
    user: CurrentUserDep,
    session: SessionDep,
    reader_factory: ReaderFactoryDep,
) -> ContainerOut:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    unknown = [item_id for item_id in body.item_ids if item_id not in ITEMS_BY_ID]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"items inconnus : {', '.join(unknown)}",
        )

    profile = await get_or_create_profile(session, site.id)
    measurement_id: str | None = profile.params.get("ga4_measurement_id")
    if not measurement_id:
        reader = await reader_factory(session, site)
        try:
            measurement_id = await reader.measurement_id()
        except GoogleReadError:
            measurement_id = None

    container, warnings = build_selected_container(
        domain=site.domain,
        stack=site.detected_stack or StackKind.UNKNOWN,
        item_ids=body.item_ids,
        ga4_measurement_id=measurement_id,
        ads_conversion_id=profile.params.get("ads_conversion_id"),
        ads_conversion_label=profile.params.get("ads_conversion_label"),
        import_mode=body.import_mode,
    )
    await session.commit()  # get_or_create_profile a pu créer la ligne
    return ContainerOut(
        container=container, warnings=warnings, filename=f"gtm-plan-{site.domain}.json"
    )
```
Enregistrer le routeur dans `backend/app/api/v1/router.py` : ajouter `measurement` à
l'import des modules d'endpoints (ordre alphabétique) et
`api_router.include_router(measurement.router)` après `connections.router`.

- [ ] **Étape 3 : lancer les tests**

`.venv/Scripts/python.exe -m pytest tests/test_measurement_endpoints.py -v` puis la suite
complète `pytest -W error -q` ; `uv run ruff check app tests` propre ;
`uv run alembic check` propre.

- [ ] **Étape 4 : commit**

```bash
git add backend/app/api/v1/endpoints/measurement.py backend/app/api/v1/router.py backend/tests/test_measurement_endpoints.py
git commit -m "feat(measurement): API du plan de mesure (lecture, verification, profil, items, conteneur GTM)"
```

---

### Tâche 11 : Client frontend (types, appels, hook propriétaire)

**Fichiers :**
- Créer : `frontend/lib/api/measurement.ts`
- Créer : `frontend/lib/api/use-is-owner.ts`
- Créer : `frontend/components/plan/labels.ts`

**Interfaces :**
- Consomme : `apiGet`, `apiPost`, `apiPostSlow`, `apiPatch` (`lib/api/client.ts`),
  `GET /workspaces/mine`.
- Produit : types `MeasurementPlanDto`, `MeasurementItemDto`, etc. ;
  `fetchMeasurementPlan`, `refreshMeasurementPlan`, `patchMeasurementProfile`,
  `patchMeasurementItem`, `buildMeasurementContainer` ; hook
  `useIsOwner(realWorkspaceId)` ; libellés français dans `labels.ts`.

- [ ] **Étape 1 : créer `frontend/lib/api/measurement.ts`**

```ts
import { apiGet, apiPatch, apiPost, apiPostSlow } from "./client";

export type MeasurementState =
  | "unknown"
  | "missing"
  | "on_page"
  | "received"
  | "unverifiable"
  | "not_applicable"
  | "dismissed";

export type MeasurementLayer =
  | "foundations"
  | "events"
  | "conversions"
  | "ads"
  | "seo";

export type SiteType = "ecommerce" | "lead_gen" | "saas" | "content" | "other";

export interface MeasurementSnippetDto {
  language: string;
  code: string;
  target_path: string;
  instructions: string;
}

export interface MeasurementItemDto {
  id: string;
  layer: MeasurementLayer;
  title: string;
  why: string;
  weight: number;
  quick_win: boolean;
  max_level: "on_page" | "received";
  state: MeasurementState;
  done: boolean;
  partial: boolean;
  reason: string | null;
  evidence: Record<string, unknown>;
  checked_at: string | null;
  guide: string[];
  actions: ("guide" | "snippet" | "gtm_container" | "advisor" | "pr")[];
  snippet: MeasurementSnippetDto | null;
}

export interface TypeGuessDto {
  type: SiteType;
  confidence: number;
  signals: string[];
}

export interface MeasurementProfileDto {
  detected_types: TypeGuessDto[];
  confirmed_types: SiteType[] | null;
  effective_types: SiteType[];
  needs_confirmation: boolean;
  params: {
    ads_conversion_id: string | null;
    ads_conversion_label: string | null;
    uses_google_ads: boolean | null;
    ga4_measurement_id: string | null;
  };
}

export interface MeasurementLayerProgressDto {
  layer: MeasurementLayer;
  total: number;
  done: number;
}

export interface MeasurementPlanDto {
  website_id: string;
  profile: MeasurementProfileDto;
  ga4_connected: boolean;
  last_checked_at: string | null;
  overall_done: number;
  overall_total: number;
  overall_percent: number;
  layers: MeasurementLayerProgressDto[];
  items: MeasurementItemDto[];
  headless_skipped: boolean;
  headless_error: string | null;
}

export interface MeasurementProfilePatch {
  confirmed_types?: SiteType[] | null;
  uses_google_ads?: boolean | null;
  ads_conversion_id?: string | null;
  ads_conversion_label?: string | null;
  ga4_measurement_id?: string | null;
}

export interface MeasurementContainerDto {
  container: Record<string, unknown>;
  warnings: string[];
  filename: string;
}

const base = (websiteId: string) => `/websites/${websiteId}/measurement-plan`;

export function fetchMeasurementPlan(websiteId: string): Promise<MeasurementPlanDto> {
  return apiGet<MeasurementPlanDto>(base(websiteId));
}

/** Le mode « en conditions réelles » lance un vrai navigateur : délai long. */
export function refreshMeasurementPlan(
  websiteId: string,
  headless = false,
): Promise<MeasurementPlanDto> {
  return apiPostSlow<MeasurementPlanDto>(
    `${base(websiteId)}/refresh?headless=${headless ? "true" : "false"}`,
    undefined,
  );
}

export function patchMeasurementProfile(
  websiteId: string,
  body: MeasurementProfilePatch,
): Promise<MeasurementPlanDto> {
  return apiPatch<MeasurementPlanDto>(`${base(websiteId)}/profile`, body);
}

export function patchMeasurementItem(
  websiteId: string,
  itemId: string,
  body: { dismissed?: boolean; manual_done?: boolean },
): Promise<MeasurementPlanDto> {
  return apiPatch<MeasurementPlanDto>(`${base(websiteId)}/items/${itemId}`, body);
}

export function buildMeasurementContainer(
  websiteId: string,
  itemIds: string[],
): Promise<MeasurementContainerDto> {
  return apiPost<MeasurementContainerDto>(`${base(websiteId)}/gtm-container`, {
    item_ids: itemIds,
  });
}
```

- [ ] **Étape 2 : créer `frontend/lib/api/use-is-owner.ts`**

```ts
"use client";

import { useEffect, useState } from "react";

import { apiGet } from "./client";

interface WorkspaceMineDto {
  id: string;
  name: string;
  role: string;
}

/** Vrai si l'utilisateur courant est propriétaire du workspace donné. */
export function useIsOwner(realWorkspaceId: string | undefined): boolean {
  const [isOwner, setIsOwner] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void apiGet<WorkspaceMineDto[]>("/workspaces/mine")
      .then((mine) => {
        if (cancelled) return;
        setIsOwner(mine.some((w) => w.id === realWorkspaceId && w.role === "owner"));
      })
      .catch(() => {
        if (!cancelled) setIsOwner(false);
      });
    return () => {
      cancelled = true;
    };
  }, [realWorkspaceId]);

  return isOwner;
}
```

- [ ] **Étape 3 : créer `frontend/components/plan/labels.ts`**

```ts
import type {
  MeasurementItemDto,
  MeasurementLayer,
  SiteType,
} from "@/lib/api/measurement";

export const LAYER_LABEL: Record<MeasurementLayer, string> = {
  foundations: "Fondations",
  events: "Événements clés",
  conversions: "Conversions",
  ads: "Publicité Google Ads",
  seo: "Base SEO",
};

export const SITE_TYPE_LABEL: Record<SiteType, string> = {
  ecommerce: "Boutique en ligne",
  lead_gen: "Prise de contact / devis",
  saas: "Logiciel (SaaS)",
  content: "Contenu / blog",
  other: "Autre",
};

export const REASON_LABEL: Record<string, string> = {
  ga4_not_connected: "Connecte un compte GA4 (page « Connexions Google ») pour aller plus loin.",
  headless_not_run: "Lance la vérification « en conditions réelles » pour trancher.",
  manual_check: "À vérifier à la main, puis à marquer comme fait.",
  token_unavailable: "Le compte Google doit être reconnecté.",
  connection_needs_reauth: "Le compte Google doit être reconnecté.",
  permission_or_api_disabled: "Droits ou API Google insuffisants pour lire cette donnée.",
  quota: "Quota Google atteint, réessaie plus tard.",
  network: "Réseau indisponible, réessaie.",
  api_error: "Erreur de l'API Google, réessaie plus tard.",
  not_found: "Ressource Google introuvable.",
  fetch_error: "Le site est injoignable.",
  http_error: "Le site a répondu par une erreur.",
  non_html: "La page d'accueil n'est pas une page web.",
  page_unavailable: "Page indisponible.",
  gtm_absent: "GTM n'est pas installé.",
  gtm_not_loaded_in_browser:
    "GTM est dans le code mais ne se charge pas dans un vrai navigateur.",
  purchase_not_received: "Aucun achat reçu par GA4 pour l'instant.",
  position_unknown: "Position du snippet indéterminée.",
  no_tracking_found: "Aucun suivi trouvé sur la page.",
  not_checked: "Pas encore vérifié.",
  gsc_not_connected: "Connecte Search Console (page « Connexions Google »).",
};

export function stateLabel(item: MeasurementItemDto): string {
  if (item.done) return item.max_level === "on_page" ? "En place" : "Reçu par GA4";
  switch (item.state) {
    case "received":
      return "Reçu par GA4";
    case "on_page":
      return "Présent sur la page";
    case "missing":
      return "Manquant";
    case "unverifiable":
      return "À confirmer";
    case "not_applicable":
      return "Non concerné";
    case "dismissed":
      return "Écarté";
    default:
      return "Pas encore vérifié";
  }
}

/** Classe de la pastille de statut : uniquement des couleurs de statut. */
export function stateDotClass(item: MeasurementItemDto): string {
  if (item.done) return "bg-ok";
  if (item.partial) return "bg-warn";
  if (item.state === "missing") return "bg-danger";
  return "bg-ink-faint";
}
```

- [ ] **Étape 4 : vérifier**

`cd frontend && npm run lint && npm run build` → 0 erreur / 0 warning.

- [ ] **Étape 5 : commit**

```bash
git add frontend/lib/api/measurement.ts frontend/lib/api/use-is-owner.ts frontend/components/plan/labels.ts
git commit -m "feat(frontend): client API du plan de mesure et libelles"
```

---

### Tâche 12 : Page « Plan de mesure »

**Fichiers :**
- Créer : `frontend/app/(shell)/plan/page.tsx`
- Créer : `frontend/components/plan/plan-view.tsx`, `plan-progress.tsx`,
  `profile-confirm.tsx`, `plan-item-row.tsx`, `item-drawer.tsx`,
  `ads-settings.tsx`, `container-builder.tsx`
- Modifier : `frontend/lib/shell/routes.ts`

**Interfaces :**
- Consomme : `lib/api/measurement.ts`, `useIsOwner`, `useShell` (`workspace`),
  `PageShell`, `Sheet*`, `CopyButton`, `saveBlob` (`lib/api/client.ts`),
  `toast` (`sonner`).
- Produit : route `/plan`, entrée « Plan de mesure » dans la navigation.
- Un site de démo (sans `workspace.websiteId`) affiche un message d'invitation à
  ajouter un site réel.

- [ ] **Étape 1 : route et page**

Dans `frontend/lib/shell/routes.ts`, ajouter `ClipboardCheck` à l'import `lucide-react`
et insérer, **après** l'entrée `/overview` :

```ts
  {
    href: "/plan",
    label: "Plan de mesure",
    crumb: "Plan de mesure",
    icon: ClipboardCheck,
  },
```

```tsx
// frontend/app/(shell)/plan/page.tsx
import type { Metadata } from "next";

import { PlanView } from "@/components/plan/plan-view";

export const metadata: Metadata = { title: "Plan de mesure" };

export default function PlanPage() {
  return <PlanView />;
}
```

- [ ] **Étape 2 : `plan-progress.tsx`**

```tsx
"use client";

import type { MeasurementPlanDto } from "@/lib/api/measurement";

import { LAYER_LABEL } from "./labels";

export function PlanProgress({ plan }: { plan: MeasurementPlanDto }) {
  return (
    <section className="rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div className="space-y-1">
          <p className="text-sm font-medium text-ink">Avancement de ta mesure</p>
          <p className="text-xs text-ink-muted">
            {plan.overall_done} point{plan.overall_done > 1 ? "s" : ""} en place sur{" "}
            {plan.overall_total}
          </p>
        </div>
        <p className="font-mono text-3xl font-semibold tabular-nums text-ink">
          {plan.overall_percent}%
        </p>
      </div>
      <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
        <div
          className="h-full rounded-full bg-ok transition-all"
          style={{ width: `${plan.overall_percent}%` }}
        />
      </div>
      <ul className="mt-4 grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-5">
        {plan.layers.map((layer) => (
          <li key={layer.layer} className="space-y-1">
            <p className="text-2xs text-ink-faint">{LAYER_LABEL[layer.layer]}</p>
            <p className="font-mono text-xs tabular-nums text-ink-muted">
              {layer.done}/{layer.total}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Étape 3 : `profile-confirm.tsx`**

```tsx
"use client";

import { useState } from "react";
import { toast } from "sonner";

import { ApiError } from "@/lib/api/client";
import {
  patchMeasurementProfile,
  type MeasurementPlanDto,
  type SiteType,
} from "@/lib/api/measurement";
import { cn } from "@/lib/utils";

import { SITE_TYPE_LABEL } from "./labels";

const ALL_TYPES: SiteType[] = ["ecommerce", "lead_gen", "saas", "content", "other"];

export function ProfileConfirm({
  websiteId,
  plan,
  isOwner,
  onChanged,
}: {
  websiteId: string;
  plan: MeasurementPlanDto;
  isOwner: boolean;
  onChanged: (plan: MeasurementPlanDto) => void;
}) {
  const [selected, setSelected] = useState<SiteType[]>(plan.profile.effective_types);
  const [saving, setSaving] = useState(false);

  const detected = plan.profile.detected_types;

  function toggle(type: SiteType) {
    setSelected((current) =>
      current.includes(type) ? current.filter((t) => t !== type) : [...current, type],
    );
  }

  async function confirm() {
    if (selected.length === 0) {
      toast.error("Choisis au moins un type de site.");
      return;
    }
    setSaving(true);
    try {
      onChanged(await patchMeasurementProfile(websiteId, { confirmed_types: selected }));
      toast("Type de site confirmé", { description: "Le plan a été ajusté." });
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Confirmation impossible");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="space-y-3 rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
      <div className="space-y-1">
        <p className="text-sm font-medium text-ink">Quel type de site est-ce ?</p>
        <p className="max-w-2xl text-xs leading-relaxed text-ink-muted">
          {detected.length > 0 && detected[0].type !== "other"
            ? "On a deviné le type de ton site. Confirme-le pour que le plan cible les bons événements : "
            : "On n'a pas pu deviner le type de ton site. Choisis-le pour que le plan cible les bons événements : "}
          un site peut être de plusieurs types.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {ALL_TYPES.map((type) => (
          <button
            key={type}
            type="button"
            disabled={!isOwner}
            onClick={() => toggle(type)}
            className={cn(
              "inline-flex h-8 items-center rounded-lg border px-3 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60",
              selected.includes(type)
                ? "border-ink/40 bg-white/[0.08] text-ink"
                : "border-white/[0.08] bg-white/[0.03] text-ink-muted hover:bg-white/[0.06] hover:text-ink",
            )}
          >
            {SITE_TYPE_LABEL[type]}
          </button>
        ))}
      </div>
      {isOwner ? (
        <button
          type="button"
          disabled={saving}
          onClick={() => void confirm()}
          className="inline-flex h-9 items-center rounded-lg bg-zinc-100 px-4 text-xs font-medium text-zinc-950 shadow-sm transition-colors hover:bg-zinc-200 disabled:opacity-60"
        >
          Confirmer
        </button>
      ) : (
        <p className="text-xs text-ink-faint">
          Seul le propriétaire du workspace peut confirmer le type de site.
        </p>
      )}
    </section>
  );
}
```

- [ ] **Étape 4 : `plan-item-row.tsx`**

```tsx
"use client";

import { ChevronRight } from "lucide-react";

import type { MeasurementItemDto } from "@/lib/api/measurement";
import { cn } from "@/lib/utils";

import { REASON_LABEL, stateDotClass, stateLabel } from "./labels";

export function PlanItemRow({
  item,
  onOpen,
  selectable,
  selected,
  onToggle,
}: {
  item: MeasurementItemDto;
  onOpen: () => void;
  selectable: boolean;
  selected: boolean;
  onToggle: () => void;
}) {
  const muted = item.state === "not_applicable" || item.state === "dismissed";
  return (
    <div
      className={cn(
        "flex items-center gap-3 border-t border-white/[0.05] px-4 py-3 first:border-t-0 hover:bg-white/[0.02]",
        muted && "opacity-50",
      )}
    >
      {selectable && (
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          aria-label={`Inclure « ${item.title} » dans mon conteneur GTM`}
          className="size-3.5 shrink-0 accent-zinc-200"
        />
      )}
      <button
        type="button"
        onClick={onOpen}
        className="flex min-w-0 flex-1 items-center gap-3 text-left"
      >
        <span className={cn("size-1.5 shrink-0 rounded-full", stateDotClass(item))} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-ink">
            {item.title}
            {item.quick_win && !item.done && (
              <span className="ml-2 rounded border border-hairline px-1.5 py-0.5 text-2xs font-normal text-ink-muted">
                Gain rapide
              </span>
            )}
          </span>
          <span className="block truncate text-xs text-ink-muted">
            {item.reason && !item.done
              ? (REASON_LABEL[item.reason] ?? item.reason)
              : item.why}
          </span>
        </span>
        <span className="shrink-0 text-xs text-ink-muted">{stateLabel(item)}</span>
        <ChevronRight className="size-4 shrink-0 text-ink-faint" />
      </button>
    </div>
  );
}
```

- [ ] **Étape 5 : `item-drawer.tsx`**

```tsx
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { ApiError } from "@/lib/api/client";
import {
  patchMeasurementItem,
  type MeasurementItemDto,
  type MeasurementPlanDto,
} from "@/lib/api/measurement";

import { CopyButton } from "../backlog/copy-button";
import { REASON_LABEL, stateLabel } from "./labels";

export function ItemDrawer({
  item,
  websiteId,
  isOwner,
  domain,
  onClose,
  onChanged,
}: {
  item: MeasurementItemDto | null;
  websiteId: string;
  isOwner: boolean;
  domain: string;
  onClose: () => void;
  onChanged: (plan: MeasurementPlanDto) => void;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function patch(body: { dismissed?: boolean; manual_done?: boolean }) {
    if (!item) return;
    setBusy(true);
    try {
      onChanged(await patchMeasurementItem(websiteId, item.id, body));
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Action impossible");
    } finally {
      setBusy(false);
    }
  }

  function askAdvisor() {
    if (!item) return;
    const prompt =
      `Sur le site ${domain}, la ligne « ${item.title} » de mon plan de mesure est ` +
      `« ${stateLabel(item)} ». Explique-moi simplement pourquoi ça compte et ce que je ` +
      `dois faire concrètement, étape par étape.`;
    router.push(`/conseiller?prompt=${encodeURIComponent(prompt)}`);
  }

  const isManual = item?.guide.some((step) => step.startsWith("Marque cette ligne comme faite"));

  return (
    <Sheet open={item !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
        {item && (
          <>
            <SheetHeader>
              <SheetTitle className="text-base text-ink">{item.title}</SheetTitle>
              <SheetDescription className="text-xs text-ink-muted">
                {stateLabel(item)}
                {item.reason && !item.done
                  ? ` — ${REASON_LABEL[item.reason] ?? item.reason}`
                  : ""}
              </SheetDescription>
            </SheetHeader>

            <div className="space-y-6 px-4 pb-6">
              <section className="space-y-1">
                <h3 className="text-xs font-medium text-ink">Pourquoi ça compte</h3>
                <p className="text-xs leading-relaxed text-ink-muted">{item.why}</p>
              </section>

              {Object.keys(item.evidence).length > 0 && (
                <section className="space-y-1">
                  <h3 className="text-xs font-medium text-ink">Ce qu'on a constaté</h3>
                  <dl className="space-y-1 rounded-lg border border-hairline bg-white/[0.02] p-3 font-mono text-2xs text-ink-muted">
                    {Object.entries(item.evidence).map(([key, value]) => (
                      <div key={key} className="flex gap-2">
                        <dt className="shrink-0 text-ink-faint">{key}</dt>
                        <dd className="min-w-0 break-words">{JSON.stringify(value)}</dd>
                      </div>
                    ))}
                  </dl>
                </section>
              )}

              {item.actions.includes("guide") && (
                <section className="space-y-2">
                  <h3 className="text-xs font-medium text-ink">Comment faire</h3>
                  <ol className="list-decimal space-y-1.5 pl-4 text-xs leading-relaxed text-ink-muted">
                    {item.guide.map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ol>
                </section>
              )}

              {item.snippet && (
                <section className="space-y-2">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-medium text-ink">Snippet</h3>
                    <CopyButton text={item.snippet.code} />
                  </div>
                  <p className="text-2xs text-ink-faint">
                    Fichier suggéré : {item.snippet.target_path}
                  </p>
                  <pre className="max-h-72 overflow-auto rounded-lg border border-hairline bg-white/[0.02] p-3 font-mono text-2xs leading-relaxed text-ink-muted">
                    {item.snippet.code}
                  </pre>
                  <p className="text-2xs leading-relaxed text-ink-faint">
                    {item.snippet.instructions}
                  </p>
                </section>
              )}

              <div className="flex flex-wrap gap-2 border-t border-white/[0.06] pt-4">
                {item.actions.includes("advisor") && (
                  <button
                    type="button"
                    onClick={askAdvisor}
                    className="inline-flex h-8 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink"
                  >
                    Demander au conseiller
                  </button>
                )}
                {item.actions.includes("pr") && (
                  <button
                    type="button"
                    disabled
                    className="inline-flex h-8 items-center rounded-lg border border-white/[0.08] px-2.5 text-xs text-ink-faint opacity-60"
                  >
                    Ouvrir une PR (bientôt)
                  </button>
                )}
                {isOwner && isManual && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void patch({ manual_done: !item.done })}
                    className="inline-flex h-8 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink disabled:opacity-60"
                  >
                    {item.done ? "Marquer comme à refaire" : "Marquer comme fait"}
                  </button>
                )}
                {isOwner && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void patch({ dismissed: item.state !== "dismissed" })}
                    className="inline-flex h-8 items-center rounded-lg border border-white/[0.08] px-2.5 text-xs text-ink-faint transition-colors hover:text-ink disabled:opacity-60"
                  >
                    {item.state === "dismissed" ? "Rétablir cette ligne" : "Écarter cette ligne"}
                  </button>
                )}
              </div>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
```

- [ ] **Étape 6 : `ads-settings.tsx`**

```tsx
"use client";

import { useState } from "react";
import { toast } from "sonner";

import { ApiError } from "@/lib/api/client";
import {
  patchMeasurementProfile,
  type MeasurementPlanDto,
} from "@/lib/api/measurement";

const INPUT =
  "h-9 w-full rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 text-xs text-ink placeholder:text-ink-faint focus:border-ink/40 focus:outline-none disabled:opacity-60";

export function AdsSettings({
  websiteId,
  plan,
  isOwner,
  onChanged,
}: {
  websiteId: string;
  plan: MeasurementPlanDto;
  isOwner: boolean;
  onChanged: (plan: MeasurementPlanDto) => void;
}) {
  const params = plan.profile.params;
  const [usesAds, setUsesAds] = useState(params.uses_google_ads !== false);
  const [convId, setConvId] = useState(params.ads_conversion_id ?? "");
  const [label, setLabel] = useState(params.ads_conversion_label ?? "");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      onChanged(
        await patchMeasurementProfile(websiteId, {
          uses_google_ads: usesAds,
          ads_conversion_id: convId.trim() || null,
          ads_conversion_label: label.trim() || null,
        }),
      );
      toast("Réglages Ads enregistrés");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Enregistrement impossible");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="space-y-3 rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
      <div className="space-y-1">
        <p className="text-sm font-medium text-ink">Réglages Google Ads</p>
        <p className="max-w-2xl text-xs leading-relaxed text-ink-muted">
          Si tu ne fais pas de publicité Google, désactive cette couche. Sinon, renseigne l'ID et le
          libellé de ta conversion (Google Ads &gt; Objectifs &gt; Conversions) pour les inclure
          dans « Mon conteneur GTM ».
        </p>
      </div>
      <label className="flex items-center gap-2 text-xs text-ink-muted">
        <input
          type="checkbox"
          checked={usesAds}
          disabled={!isOwner}
          onChange={(event) => setUsesAds(event.target.checked)}
          className="size-3.5 accent-zinc-200"
        />
        Je fais de la publicité Google Ads
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        <input
          className={INPUT}
          placeholder="ID de conversion (AW-123456789)"
          value={convId}
          disabled={!isOwner || !usesAds}
          onChange={(event) => setConvId(event.target.value)}
        />
        <input
          className={INPUT}
          placeholder="Libellé de conversion"
          value={label}
          disabled={!isOwner || !usesAds}
          onChange={(event) => setLabel(event.target.value)}
        />
      </div>
      {isOwner ? (
        <button
          type="button"
          disabled={saving}
          onClick={() => void save()}
          className="inline-flex h-9 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-3.5 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink disabled:opacity-60"
        >
          Enregistrer
        </button>
      ) : (
        <p className="text-xs text-ink-faint">Seul le propriétaire peut modifier ces réglages.</p>
      )}
    </section>
  );
}
```

- [ ] **Étape 7 : `container-builder.tsx`**

```tsx
"use client";

import { useState } from "react";
import { toast } from "sonner";

import { ApiError, saveBlob } from "@/lib/api/client";
import {
  buildMeasurementContainer,
  type MeasurementItemDto,
} from "@/lib/api/measurement";

export function ContainerBuilder({
  websiteId,
  items,
  selectedIds,
  onSelectMissing,
  onClear,
}: {
  websiteId: string;
  items: MeasurementItemDto[];
  selectedIds: string[];
  onSelectMissing: () => void;
  onClear: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const selectable = items.filter((item) => item.actions.includes("gtm_container"));

  async function generate() {
    setBusy(true);
    try {
      const result = await buildMeasurementContainer(websiteId, selectedIds);
      saveBlob(
        new Blob([JSON.stringify(result.container, null, 2)], { type: "application/json" }),
        result.filename,
      );
      setWarnings(result.warnings);
      toast("Conteneur GTM généré", {
        description: "Importe-le dans GTM : Administration > Importer un conteneur > Fusionner.",
      });
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Génération impossible");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-3 rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
      <div className="space-y-1">
        <p className="text-sm font-medium text-ink">Mon conteneur GTM</p>
        <p className="max-w-2xl text-xs leading-relaxed text-ink-muted">
          Coche les lignes à mettre en place (case à gauche des lignes concernées) : on génère un
          seul fichier à importer dans GTM, avec les balises et déclencheurs correspondants.{" "}
          {selectable.length} ligne{selectable.length > 1 ? "s" : ""} concernée
          {selectable.length > 1 ? "s" : ""}.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onSelectMissing}
          className="inline-flex h-8 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink"
        >
          Cocher les lignes manquantes
        </button>
        {selectedIds.length > 0 && (
          <button
            type="button"
            onClick={onClear}
            className="text-xs text-ink-faint underline hover:text-ink"
          >
            Tout décocher
          </button>
        )}
        <button
          type="button"
          disabled={busy || selectedIds.length === 0}
          onClick={() => void generate()}
          className="inline-flex h-9 items-center rounded-lg bg-zinc-100 px-4 text-xs font-medium text-zinc-950 shadow-sm transition-colors hover:bg-zinc-200 disabled:opacity-50"
        >
          Générer ({selectedIds.length})
        </button>
      </div>
      {warnings.length > 0 && (
        <ul className="space-y-1 text-xs text-warn">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
```

- [ ] **Étape 8 : `plan-view.tsx`**

```tsx
"use client";

import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { PageShell } from "@/components/shell/page-shell";
import { ApiError } from "@/lib/api/client";
import {
  fetchMeasurementPlan,
  refreshMeasurementPlan,
  type MeasurementItemDto,
  type MeasurementLayer,
  type MeasurementPlanDto,
} from "@/lib/api/measurement";
import { useIsOwner } from "@/lib/api/use-is-owner";
import { useShell } from "@/lib/shell/shell-context";

import { AdsSettings } from "./ads-settings";
import { ContainerBuilder } from "./container-builder";
import { ItemDrawer } from "./item-drawer";
import { LAYER_LABEL } from "./labels";
import { PlanItemRow } from "./plan-item-row";
import { PlanProgress } from "./plan-progress";
import { ProfileConfirm } from "./profile-confirm";

const LAYERS: MeasurementLayer[] = ["foundations", "events", "conversions", "ads", "seo"];

export function PlanView() {
  const { workspace } = useShell();
  const websiteId = workspace.websiteId;
  const isOwner = useIsOwner(workspace.realWorkspaceId);

  const [plan, setPlan] = useState<MeasurementPlanDto | null>(null);
  const [status, setStatus] = useState<"loading" | "loaded" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [realConditions, setRealConditions] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  const refresh = useCallback(
    async (id: string, headless: boolean) => {
      setRefreshing(true);
      try {
        const next = await refreshMeasurementPlan(id, headless);
        setPlan(next);
        if (next.headless_skipped) {
          toast("Vérification réelle déjà faite il y a moins de 5 minutes", {
            description: "Les autres vérifications ont été relancées.",
          });
        }
        if (next.headless_error) {
          toast.error("Le navigateur de vérification a échoué", {
            description: next.headless_error,
          });
        }
      } catch (err) {
        toast.error(err instanceof ApiError ? err.message : "Vérification impossible");
      } finally {
        setRefreshing(false);
      }
    },
    [],
  );

  const load = useCallback(
    async (id: string) => {
      setStatus("loading");
      setError(null);
      try {
        const current = await fetchMeasurementPlan(id);
        setPlan(current);
        setStatus("loaded");
        if (current.last_checked_at === null) await refresh(id, false);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Erreur inconnue");
        setStatus("error");
      }
    },
    [refresh],
  );

  useEffect(() => {
    if (!websiteId) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(websiteId);
  }, [websiteId, load]);

  const byLayer = useMemo(() => {
    const groups = new Map<MeasurementLayer, MeasurementItemDto[]>();
    for (const layer of LAYERS) groups.set(layer, []);
    for (const item of plan?.items ?? []) {
      if (item.state === "not_applicable") continue;
      groups.get(item.layer)?.push(item);
    }
    return groups;
  }, [plan]);

  if (!websiteId) {
    return (
      <PageShell
        title="Plan de mesure"
        subtitle="Ce qu'il faut mettre en place pour mesurer ton trafic et tes conversions."
      >
        <p className="text-xs text-ink-muted">
          Ajoute un site réel pour obtenir son plan de mesure (les sites de démonstration n'en ont
          pas).
        </p>
      </PageShell>
    );
  }

  if (status === "loading" && !plan) return null;

  if (status === "error" || !plan) {
    return (
      <PageShell title="Plan de mesure">
        <div className="space-y-3">
          <p className="text-xs text-ink-muted">
            Impossible de charger le plan de mesure{error ? ` : ${error}` : "."}
          </p>
          <button
            type="button"
            onClick={() => void load(websiteId)}
            className="inline-flex h-9 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-3.5 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink"
          >
            Réessayer
          </button>
        </div>
      </PageShell>
    );
  }

  const openItem = plan.items.find((item) => item.id === openId) ?? null;
  const selectableIds = plan.items
    .filter((item) => item.actions.includes("gtm_container") && item.state !== "not_applicable")
    .map((item) => item.id);
  const missingIds = plan.items
    .filter(
      (item) =>
        item.actions.includes("gtm_container") &&
        item.state !== "not_applicable" &&
        item.state !== "dismissed" &&
        !item.done,
    )
    .map((item) => item.id);

  return (
    <PageShell
      title="Plan de mesure"
      subtitle="Ce qu'il faut mettre en place pour mesurer ton trafic et tes conversions, dans l'ordre. Chaque « fait » est prouvé."
      actions={
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-ink-muted">
            <input
              type="checkbox"
              checked={realConditions}
              onChange={(event) => setRealConditions(event.target.checked)}
              className="size-3.5 accent-zinc-200"
            />
            En conditions réelles
          </label>
          <button
            type="button"
            disabled={refreshing}
            onClick={() => void refresh(websiteId, realConditions)}
            className="inline-flex h-9 items-center gap-2 rounded-lg bg-zinc-100 px-4 text-xs font-medium text-zinc-950 shadow-sm transition-colors hover:bg-zinc-200 disabled:opacity-60"
          >
            {refreshing && <Loader2 className="size-3.5 animate-spin" />}
            Vérifier maintenant
          </button>
        </div>
      }
    >
      {plan.profile.needs_confirmation && (
        <ProfileConfirm
          websiteId={websiteId}
          plan={plan}
          isOwner={isOwner}
          onChanged={setPlan}
        />
      )}

      <PlanProgress plan={plan} />

      {!plan.ga4_connected && (
        <p className="text-xs text-ink-muted">
          GA4 n'est pas connecté : les lignes ne peuvent pas passer à « Reçu par GA4 ». Connecte-le
          dans « Connexions Google » pour obtenir une preuve fiable.
        </p>
      )}

      {LAYERS.map((layer) => {
        const items = byLayer.get(layer) ?? [];
        if (items.length === 0) return null;
        return (
          <section key={layer} className="space-y-2">
            <h2 className="text-sm font-medium text-ink">{LAYER_LABEL[layer]}</h2>
            <div className="overflow-hidden rounded-xl border border-white/[0.08] bg-surface/30">
              {items.map((item) => (
                <PlanItemRow
                  key={item.id}
                  item={item}
                  onOpen={() => setOpenId(item.id)}
                  selectable={selectableIds.includes(item.id)}
                  selected={selectedIds.includes(item.id)}
                  onToggle={() =>
                    setSelectedIds((current) =>
                      current.includes(item.id)
                        ? current.filter((id) => id !== item.id)
                        : [...current, item.id],
                    )
                  }
                />
              ))}
            </div>
          </section>
        );
      })}

      <ContainerBuilder
        websiteId={websiteId}
        items={plan.items}
        selectedIds={selectedIds}
        onSelectMissing={() => setSelectedIds(missingIds)}
        onClear={() => setSelectedIds([])}
      />

      <AdsSettings
        key={JSON.stringify(plan.profile.params)}
        websiteId={websiteId}
        plan={plan}
        isOwner={isOwner}
        onChanged={setPlan}
      />

      <ItemDrawer
        item={openItem}
        websiteId={websiteId}
        isOwner={isOwner}
        domain={workspace.domain}
        onClose={() => setOpenId(null)}
        onChanged={setPlan}
      />
    </PageShell>
  );
}
```

- [ ] **Étape 9 : vérifier**

`cd frontend && npm run lint && npm run build` → 0 erreur / 0 warning ; la route
`/plan` apparaît dans la liste des routes.

- [ ] **Étape 10 : vérification dans le navigateur** (voir aussi Tâche 14). Démarrer
  le backend et le frontend (`scripts/dev.sh`, ou l'aperçu intégré), s'inscrire,
  ajouter un site réel, ouvrir `/plan` : le plan se calcule à l'ouverture, le type
  de site est proposé, les lignes s'affichent groupées par couche, un tiroir
  s'ouvre avec explication / guide / snippet, « Vérifier maintenant » fonctionne,
  « Cocher les lignes manquantes » puis « Générer » télécharge un JSON. Arrêter les
  serveurs ensuite.

- [ ] **Étape 11 : commit**

```bash
git add frontend/app/\(shell\)/plan frontend/components/plan frontend/lib/shell/routes.ts
git commit -m "feat(frontend): page Plan de mesure (progression, lignes par couche, tiroir, conteneur GTM)"
```

---

### Tâche 13 : Carte d'avancement (vue d'ensemble) et préremplissage du conseiller

**Fichiers :**
- Créer : `frontend/components/overview/plan-progress-card.tsx`
- Modifier : `frontend/components/overview/overview-view.tsx`
- Modifier : `frontend/components/conseiller/advisor-view.tsx`

**Interfaces :**
- Consomme : `fetchMeasurementPlan` (Tâche 11), `workspace.websiteId`.
- Produit : carte cliquable vers `/plan` sur la vue d'ensemble ; le conseiller lit
  `?prompt=` et préremplit `chatInput` une seule fois.

- [ ] **Étape 1 : `plan-progress-card.tsx`**

```tsx
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { fetchMeasurementPlan, type MeasurementPlanDto } from "@/lib/api/measurement";

export function PlanProgressCard({ websiteId }: { websiteId: string | undefined }) {
  const [plan, setPlan] = useState<MeasurementPlanDto | null>(null);

  useEffect(() => {
    if (!websiteId) return;
    let cancelled = false;
    void fetchMeasurementPlan(websiteId)
      .then((current) => {
        if (!cancelled) setPlan(current);
      })
      .catch(() => {
        if (!cancelled) setPlan(null);
      });
    return () => {
      cancelled = true;
    };
  }, [websiteId]);

  if (!websiteId || plan === null) return null;

  const started = plan.last_checked_at !== null;
  return (
    <Link
      href="/plan"
      className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm transition-colors hover:bg-white/[0.03]"
    >
      <div className="space-y-1">
        <p className="text-sm font-medium text-ink">Plan de mesure</p>
        <p className="text-xs text-ink-muted">
          {started
            ? `${plan.overall_done} point${plan.overall_done > 1 ? "s" : ""} en place sur ${plan.overall_total}. Ouvre le plan pour voir la suite.`
            : "Découvre ce qu'il faut mettre en place pour mesurer ton trafic et tes conversions."}
        </p>
      </div>
      {started && (
        <p className="font-mono text-2xl font-semibold tabular-nums text-ink">
          {plan.overall_percent}%
        </p>
      )}
    </Link>
  );
}
```

- [ ] **Étape 2 : brancher dans `overview-view.tsx`**

Ajouter l'import `import { PlanProgressCard } from "./plan-progress-card";` et insérer
`<PlanProgressCard websiteId={workspace.websiteId} />` juste **après**
`<StackConfirmPrompt />` et avant la `<section className="grid …">` des métriques.

- [ ] **Étape 3 : préremplissage dans `advisor-view.tsx`**

Dans `AdvisorPanel`, juste après la déclaration `const [chatInput, setChatInput] =
useState("");`, ajouter :

```tsx
  useEffect(() => {
    const prompt = new URLSearchParams(window.location.search).get("prompt");
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (prompt) setChatInput(prompt);
  }, []);
```
(`useEffect` est déjà importé ; aucun nouvel import.) Le texte est seulement placé
dans le champ de saisie : l'utilisateur relit et envoie lui-même.

- [ ] **Étape 4 : vérifier**

`cd frontend && npm run lint && npm run build` → 0 erreur / 0 warning. Vérification
dans le navigateur : la carte apparaît sur `/overview` pour un site réel et mène à
`/plan` ; depuis un tiroir, « Demander au conseiller » ouvre `/conseiller` avec le
champ prérempli.

- [ ] **Étape 5 : commit**

```bash
git add frontend/components/overview frontend/components/conseiller/advisor-view.tsx
git commit -m "feat(frontend): carte d'avancement sur la vue d'ensemble et prompt prerempli du conseiller"
```

---

### Tâche 14 : Vérification finale et mémoire

**Fichiers :** aucun changement de code attendu.

- [ ] **Étape 1 : suite backend complète, deux fois**

```bash
cd backend
.venv/Scripts/python.exe -m pytest -W error -q
.venv/Scripts/python.exe -m pytest -W error -q
uv run ruff check app tests
uv run alembic check
```
Attendu : même nombre de tests verts sur les deux passages (394 + les nouveaux
tests du lot), 0 erreur `ruff`, `alembic check` propre.

- [ ] **Étape 2 : frontend**

```bash
cd frontend
npm run build
npm run lint
```
Attendu : 0 erreur / 0 warning ; routes `/plan` présente.

- [ ] **Étape 3 : vérification de bout en bout dans le navigateur**

Avec `scripts/dev.sh` (vérifier d'abord qu'aucun processus orphelin n'occupe les
ports 8020 / 4000 ; ne tuer que ce qu'on a démarré soi-même), sur un vrai site
(par exemple `qaopscareer.com`, où `generate_lead` est connu comme manquant) :
1. Le plan se calcule à l'ouverture de `/plan`, le type de site est proposé.
2. Les lignes « GTM installé » et « balise GA4 » reflètent la réalité du site.
3. Sans GA4 connecté, aucune ligne d'événement n'affiche « Reçu par GA4 ».
4. « En conditions réelles » lance le navigateur headless (Chromium installé) et
   améliore les lignes GA4 / Consent Mode / Ads ; un second clic dans les 5 minutes
   affiche le message de délai.
5. « Cocher les lignes manquantes » puis « Générer » télécharge un JSON valide.
6. Un utilisateur non propriétaire voit le plan mais ne peut pas confirmer le type,
   écarter une ligne ni modifier les réglages Ads.
Consigner les constats (et toute anomalie) dans le compte rendu.

- [ ] **Étape 4 : contrôle manuel du conteneur GTM** (voir Tâche 8, étape 5) :
  import réel en mode « Fusionner » dans un conteneur GTM de test, résultat noté.

- [ ] **Étape 5 : mémoire du projet**

Ajouter une section « Plan de mesure guidé (lot A) » à
`C:\Users\DELL\.claude\projects\C--Users-DELL-Downloads-Guiili\memory\project-control-center.md`
(état, décisions, arbitrages par rapport à la spec, tests, points ouverts) et
mettre à jour la ligne correspondante de `MEMORY.md`.

- [ ] **Étape 6 : rapport à l'utilisateur** : nombre de tests, résultat build/lint,
  constats du contrôle navigateur, résultat de l'import GTM de test, rappel que le
  déploiement Cloud Run reste à valider par lui (nouvelle migration à appliquer :
  `alembic upgrade head` est déjà exécuté au démarrage du conteneur), et que le
  contenu du catalogue (titres, explications, guides) est à relire.
