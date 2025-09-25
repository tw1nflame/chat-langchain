from fastapi import Request, HTTPException
import httpx
from core.config import settings
from core.logging_config import app_logger


async def get_current_owner(request: Request) -> str:
    """Resolve the current owner's Supabase user id from Authorization header.

    Raises HTTPException(401) if not authenticated or if Supabase lookup fails.
    This centralizes the common logic used across endpoints.
    """
    auth = request.headers.get("authorization")
    # Extra debug: log a redacted preview of headers and whether supabase_url is set
    try:
        hdrs_preview = {k: ("<REDACTED>" if k.lower() in ("authorization", "cookie", "set-cookie") else (v[:100] + "..." if v and len(v) > 100 else v)) for k, v in dict(request.headers).items()}
        app_logger.info("get_current_owner_headers_preview", extra={"headers_preview": hdrs_preview, "supabase_url_configured": bool(settings.supabase_url)})
    except Exception:
        pass

    if not auth or not auth.lower().startswith("bearer ") or not settings.supabase_url:
        app_logger.warning("get_current_owner_unauthorized_missing_auth_or_config", extra={"has_auth_header": bool(auth), "supabase_url": settings.supabase_url})
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = auth.split(" ", 1)[1]
    try:
        token_len = len(token) if token else None
        headers = {"Authorization": f"Bearer {token}"}
        if getattr(settings, 'supabase_anon_key', None):
            headers['apikey'] = settings.supabase_anon_key
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.supabase_url.rstrip('/')}/auth/v1/user", headers=headers)
            rp = (resp.text[:1000] if resp.text else None)
            # Log supabase lookup centrally
            # Include the raw response preview so we can see Supabase errors (but cap size)
            app_logger.info("supabase_user_lookup", extra={
                "status_code": resp.status_code,
                "body_preview": rp,
                "supabase_url": settings.supabase_url,
                "authorization_token_len": token_len,
            })
            if resp.status_code == 200:
                data = resp.json()
                owner_id = data.get("id") or data.get("user", {}).get("id")
                if owner_id:
                    app_logger.info("resolved_owner_from_token", extra={"owner_id": owner_id})
                    return owner_id
                else:
                    app_logger.warning("supabase_user_lookup_no_owner_id", extra={"status_code": resp.status_code, "body_preview": rp})
    except Exception:
        app_logger.exception("supabase_user_lookup_failed")

    # Always return 401 when owner can't be determined
    raise HTTPException(status_code=401, detail="Unauthorized")
