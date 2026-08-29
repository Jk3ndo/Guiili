from enum import StrEnum


class ConnectionStatus(StrEnum):
    ACTIVE = "active"
    NEEDS_REAUTH = "needs_reauth"
    REVOKED = "revoked"


class ResourceType(StrEnum):
    GA4_PROPERTY = "ga4_property"
    GTM_CONTAINER = "gtm_container"
    GSC_SITE = "gsc_site"


class SnapshotSource(StrEnum):
    PAGESPEED = "pagespeed"
    GA4 = "ga4"
    GSC = "gsc"
    COMPOSITE = "composite"


class IssueCategory(StrEnum):
    SEO = "seo"
    ANALYTICS = "analytics"
    CWV = "cwv"
    TRACKING = "tracking"
    OTHER = "other"


class IssueSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IssueStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    FIXED = "fixed"
    DISMISSED = "dismissed"


class AuditResult(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
