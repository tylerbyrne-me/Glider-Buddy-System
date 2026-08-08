"""
Wave Glider platform package.

New Wave Glider–only business logic belongs here (e.g. ``summaries`` for left-nav
sensor cards). Existing WG pipelines remain under ``app.core``
(data/sync/stations/reporting) until a focused peel is justified.

Register the platform in ``app.core.platforms.registry`` before adding modules.
HTTP routers stay under ``app.routers`` (see ``app.routers.wave_glider``).
"""
