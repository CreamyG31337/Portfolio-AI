# Flask & Supabase Authentication Guide

## The Problem: Expired Tokens & PostgREST 401

In Flask applications using Supabase, you may encounter:
1. **Direct HTTP requests work** with fresh tokens.
2. **Flask fails** with `auth.uid()` returning `NULL` or 401 errors when the access token cookie is expired.

### Root Cause
Supabase JWT access tokens have a short lifetime (typically 1 hour). When a user logs in, the token is stored in a cookie. If the user returns to the Flask app after 1 hour:
- The cookie contains an **expired** token.
- When this token is sent in the `Authorization` header, PostgREST validation **fails early**.
- It returns `401 Unauthorized` (PGRST301: JWT cryptographic operation failed) **before** your SQL function is even executed.
- This happens even if your SQL function is designed to handle NULL `auth.uid()`.

## The Solution: "No Auth Header + Explicit UUID" Pattern

 To reliably handle expired tokens in Flask without complex refresh logic, use the following pattern for RPC calls:

1.  **Modify SQL Function**: Ensure your RPC function accepts an optional `user_uuid` parameter.
    ```sql
    CREATE FUNCTION my_func(user_uuid UUID DEFAULT NULL) ...
    BEGIN
      target_uuid := COALESCE(user_uuid, auth.uid()); -- Use explicit if provided
      ...
    END;
    ```

2.  **Python HTTP Fallback**: If the standard RPC call fails, fallback to a direct HTTP request that **omits the Authorization header**.

    ```python
    # Standard RPC call failed? Try fallback!
    headers = {
        "apikey": supabase_anon_key,
        "Content-Type": "application/json"
        # CRITICAL: Do NOT send Authorization header here!
    }
    
    payload = {
        "user_uuid": str(user_id),  # Pass explicit UUID
        ...other_params
    }
    
    requests.post(f"{url}/rest/v1/rpc/my_func", headers=headers, json=payload)
    ```

### Why This Works
- By **omitting** the `Authorization` header, PostgREST treats the request as "Anonymous".
- Anonymous requests **succeed** HTTP validation (200 OK).
- The SQL function receives `auth.uid()` as `NULL` (which is expected for anon).
- But it receives your explicit `user_uuid` correctly.
- The `COALESCE` logic uses your explicit UUID.

## Implementation Locations
- **Write**: `user_preferences.py` -> `set_user_preference` (Fixed)
- **Read**: `user_preferences.py` -> `get_user_preference` (Needs SQL update)
