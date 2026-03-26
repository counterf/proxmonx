"""API routes package -- re-exports for backward compatibility.

All route modules register their own APIRouter instances.  Import them
and the shared dependency placeholders from this package so that
``main.py`` can keep its existing ``from app.api.routes import ...``
import line unchanged.
"""

from app.api.helpers import _get_config_store, _get_scheduler, _get_settings  # noqa: F401

from app.api.routes.guests import router as guests_router  # noqa: F401
from app.api.routes.guests import GuestConfigSaveRequest  # noqa: F401
from app.api.helpers import _AppConfigBase  # noqa: F401
from app.api.routes.settings import router as settings_router  # noqa: F401
from app.api.routes.custom_apps import router as custom_apps_router  # noqa: F401

# Re-export _keep_or_replace for tests
from app.api.helpers import _keep_or_replace  # noqa: F401

# Composite router that includes all sub-routers
from fastapi import APIRouter

router = APIRouter()
router.include_router(guests_router)
router.include_router(settings_router)
router.include_router(custom_apps_router)
