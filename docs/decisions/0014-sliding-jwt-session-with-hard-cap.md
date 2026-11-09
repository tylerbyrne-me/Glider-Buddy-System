---
status: accepted
date: 2026-11-09
supersedes: null
---

# Title: Sliding JWT access tokens with a hard session cap

## Context

Station Offload pilots keep the offload form open for hours while waiting on a
long VM4 offload. The access JWT had a fixed lifetime from login with no
refresh, so shifts that started near token expiry lost unsaved notes when a
401 redirected to login. Security still wants a daily re-login (about 24h).

## Decision

1. Access tokens carry an `auth_time` claim set at original login.
2. `POST /api/auth/refresh` reissues a token with
   `exp = min(now + jwt_access_token_expire_minutes, auth_time + jwt_session_max_minutes)`.
3. The browser refreshes opportunistically when less than half the sliding
   lifetime remains (and on tab focus), at most once every 10 minutes.
4. Default `jwt_session_max_minutes` is 1440 (24h), matching the access TTL.
5. Offload forms also keep a localStorage draft so a hard-cap logout does not
   wipe in-progress notes after re-login.

## Alternatives considered

- **Idle timeout only** — would not help users who are actively typing across a
  fixed expiry boundary.
- **Unlimited sliding sessions** — rejected; operators accepted ~daily login.
- **Server-side draft store** — heavier than needed for short-lived form state;
  localStorage + deep-link `?station=` is enough for this workflow.

## Consequences

- Production should keep a stable `JWT_SECRET_KEY` across restarts; rotating it
  still logs everyone out immediately.
- Confirm live `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` / `JWT_SESSION_MAX_MINUTES` on
  deploy; a short access TTL with a matching max still works for active users.
- Legacy tokens without `auth_time` use `iat` (or `exp - access TTL`) as the cap
  anchor so existing sessions keep working after deploy.
