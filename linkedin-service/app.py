from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timezone, timedelta
from linkedin_service import (
    LinkedInService,
    LinkedInCaptchaError,
    LinkedInAuthError,
    LinkedInSearchError,
    LinkedInSearchEmptyError,
)
from redis_sessions import (
    ensure_session, 
    close_session, 
    get_number_of_active_sessions,
    store_service_in_session,
    mark_session_pending_2fa,
    get_session_service,
    get_session_status,
    get_all_sessions_info,
    init_redis,
    cleanup_expired_sessions,
    SESSION_TTL_SECONDS
)
from logger import logger
from settings import LINKEDIN_SERVICE_PORT, LOCK_TIMEOUT_SECONDS

# Shorter TTL for app approval (5 minutes) - users typically approve quickly
APP_APPROVAL_TTL_SECONDS = 300


app = Flask(__name__)
CORS(app)  # Enable CORS for cross-origin requests

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _skey(key) -> str:
    return str(key)


# Initialize Redis on startup
init_redis()


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": _now_iso(),
        "active_sessions": get_number_of_active_sessions()
    })


@app.route('/sessions', methods=['GET'])
def list_sessions():
    """List all active sessions (for debugging/monitoring)"""
    return jsonify({
        "status": "success",
        "timestamp": _now_iso(),
        "sessions": get_all_sessions_info(),
        "count": get_number_of_active_sessions()
    })


@app.route('/sessions/cleanup', methods=['POST'])
def cleanup_sessions():
    """Clean up expired sessions"""
    count = cleanup_expired_sessions()
    return jsonify({
        "status": "success",
        "cleaned_up": count
    })

@app.route('/session/create', methods=['POST'])
def create_session():
    """Create a new LinkedIn session"""
    try:
        data = request.get_json() or {}
        
        # Validate required fields
        required = "outreach_profile_id"
        if required not in data:
            return jsonify({
                "status": "error", 
                "error": f"Missing required field: {required}"
            }), 400
        
        outreach_profile_id = data['outreach_profile_id']

        # Create session key
        session_key = str(outreach_profile_id)
        # Create session
        session = ensure_session(session_key)
        logger.info(f"[create_session] Active session for {outreach_profile_id} ({session})")
        
        return jsonify({
            "status": "success",
            "session_key": session_key,
        })

    except Exception as e:
        logger.exception(f"[create_session] Error creating session: {e}")
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500


@app.route('/session/<session_key>/logout', methods=['POST'])
def logout_session(session_key: str):
    """Logout and close a LinkedIn session"""
    session_key = _skey(session_key)
    service = ensure_session(session_key)
    if service is None:
        logger.warning(f"[logout_session] Session {session_key} not found")
        return jsonify({
            "status": "error",
            "error": "Session not found"
        }), 404

    session_status = get_session_status(session_key)
    logger.info(f"[logout_session] Closing session {session_key} with status {session_status}")
    
    status = close_session(session_key)
    if not status:
        logger.error(f"[logout_session] Failed to close session {session_key}")
        return jsonify({"status": "error", "error": "Failed to close session"}), 500
    
    logger.info(f"[logout_session] Session {session_key} closed successfully (was {session_status})")
    return jsonify({
        "status": "success",
        "session_key": session_key
    })



@app.route('/session/<session_key>/profile/fetch', methods=['POST'])
def fetch_profile(session_key: str):
    """Fetch LinkedIn profile information"""
    session_key = _skey(session_key)
    session = ensure_session(session_key)
    if session is None:
        return jsonify({
            "status": "error",
            "error": "Session not found"
        }), 404

    data = request.get_json() or {} 
    # Validate required fields
    required = ["email", "password", "outreach_profile_id", "target_profile_url"]
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({
            "status": "error", 
            "error": f"Missing required fields: {', '.join(missing)}"
        }), 400

    email = data['email']
    password = data['password']
    outreach_profile_id = data['outreach_profile_id']
    cookies = data.get('cookies', None)
    user_agent = data.get('user_agent', None)
    target_profile_url = data['target_profile_url']

    service = LinkedInService(email, password, cookies, user_agent)
    service.set_outreach_profile_id(outreach_profile_id)
    try:
        # Attempt login
        login_success = service.login()
        if not login_success:
            logger.error(f"[fetch_profile] Login failed for {target_profile_url}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "Login failed"
                }), 401
    except LinkedInAuthError as e:
        error_str = str(e)
        if "2FA_PIN_REQUIRED" in error_str:
            # User needs to enter a PIN code (traditional 2FA)
            logger.warning(f"[fetch_profile] 2FA PIN required for {target_profile_url}, keeping session alive")
            store_service_in_session(session_key, service)
            mark_session_pending_2fa(session_key)
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=SESSION_TTL_SECONDS)).isoformat()
            logger.info(f"[fetch_profile] Session {session_key} marked pending_2fa (PIN), expires at {expires_at}")
            return jsonify({
                "status": "error",
                "error": "2fa_pin_required",
                "error_type": "2fa_pin",
                "message": "Please enter the verification code sent to your email or phone.",
                "session_key": session_key,
                "expires_at": expires_at
            }), 401
        elif "2FA_APP_APPROVAL" in error_str:
            # User needs to approve on LinkedIn app (push notification)
            # Use shorter TTL (5 min) since users typically approve quickly
            logger.warning(f"[fetch_profile] 2FA App approval required for {target_profile_url}, keeping session alive")
            store_service_in_session(session_key, service)
            mark_session_pending_2fa(session_key)
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=APP_APPROVAL_TTL_SECONDS)).isoformat()
            logger.info(f"[fetch_profile] Session {session_key} marked pending_2fa (App Approval), expires at {expires_at} (5 min TTL)")
            return jsonify({
                "status": "error",
                "error": "2fa_app_approval",
                "error_type": "2fa_app",
                "message": "Check your LinkedIn app and tap 'Yes' to approve the sign-in request. You have 5 minutes to approve.",
                "session_key": session_key,
                "expires_at": expires_at
            }), 401
        elif "2FA_REQUIRED" in error_str:
            # Legacy/generic 2FA (fallback)
            logger.warning(f"[fetch_profile] 2FA required for {target_profile_url}, keeping session alive")
            store_service_in_session(session_key, service)
            mark_session_pending_2fa(session_key)
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=SESSION_TTL_SECONDS)).isoformat()
            logger.info(f"[fetch_profile] Session {session_key} marked pending_2fa, expires at {expires_at}")
            return jsonify({
                "status": "error",
                "error": "2fa_required",
                "error_type": "2fa",
                "message": "Two-factor authentication required.",
                "session_key": session_key,
                "expires_at": expires_at
            }), 401
        elif "ACCOUNT_RESTRICTED" in error_str:
            logger.error(f"[fetch_profile] Account restricted for {target_profile_url}: {e}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "account_restricted",
                "message": error_str.replace("ACCOUNT_RESTRICTED: ", "")
            }), 403
        elif "INVALID_CREDENTIALS" in error_str:
            logger.error(f"[fetch_profile] Invalid credentials for {target_profile_url}: {e}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "invalid_credentials",
                "message": error_str.replace("INVALID_CREDENTIALS: ", "")
            }), 401
        elif "CAPTCHA_FAILED" in error_str:
            logger.error(f"[fetch_profile] Captcha failed for {target_profile_url}: {e}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "captcha_failed",
                "message": error_str.replace("CAPTCHA_FAILED: ", "")
            }), 423
        elif "CHECKPOINT_ACTION_REQUIRED" in error_str:
            checkpoint_context = service.get_last_checkpoint_context()
            message = error_str.split(":", 1)[-1].strip() if ":" in error_str else "LinkedIn requires additional verification."
            logger.error(f"[fetch_profile] Manual checkpoint verification required for {target_profile_url}: {message}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "checkpoint_action_required",
                "message": message,
                "checkpoint_context": checkpoint_context
            }), 423
        elif "CHECKPOINT_UNKNOWN" in error_str:
            checkpoint_context = service.get_last_checkpoint_context()
            message = error_str.split(":", 1)[-1].strip() if ":" in error_str else "LinkedIn presented an unknown challenge."
            logger.error(f"[fetch_profile] Unknown checkpoint encountered for {target_profile_url}: {message}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "checkpoint_unknown",
                "message": message,
                "checkpoint_context": checkpoint_context
            }), 423
        else:
            logger.error(f"[fetch_profile] Authentication error for {target_profile_url}: {e}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "auth_failed",
                "message": error_str
            }), 401
    
    try:
        # Fetch profile data
        profile_data = service.fetch_profile_info(target_profile_url)
        if not profile_data:
            logger.error(f"[fetch_profile] Failed to fetch profile for {target_profile_url}")
            service.close()
            return jsonify({
                "status": "error",
                "message": "Failed to fetch profile data"
            }), 400

        logger.info(f"[fetch_profile] Profile fetched successfully for {target_profile_url}")
        session_data = service.get_session_data()
        cookies = session_data.get('cookies', None)
        user_agent = session_data.get('user_agent', None)
        logger.info(f"[fetch_profile] Session data fetched successfully for {target_profile_url}")
        service.close()
        return jsonify({
            "status": "success",
            "profile_data": profile_data,
            "cookies": cookies,
            "user_agent": user_agent
        })
    except LinkedInAuthError as e:
        error_str = str(e)
        if "2FA_PIN_REQUIRED" in error_str:
            logger.warning(f"[fetch_profile] 2FA PIN required during profile fetch for {target_profile_url}, keeping session alive")
            store_service_in_session(session_key, service)
            mark_session_pending_2fa(session_key)
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=SESSION_TTL_SECONDS)).isoformat()
            logger.info(f"[fetch_profile] Session {session_key} marked pending_2fa (PIN), expires at {expires_at}")
            return jsonify({
                "status": "error",
                "error": "2fa_pin_required",
                "error_type": "2fa_pin",
                "message": "Please enter the verification code sent to your email or phone.",
                "session_key": session_key,
                "expires_at": expires_at
            }), 401
        elif "2FA_APP_APPROVAL" in error_str:
            # Use shorter TTL (5 min) for app approval
            logger.warning(f"[fetch_profile] 2FA App approval required during profile fetch for {target_profile_url}, keeping session alive")
            store_service_in_session(session_key, service)
            mark_session_pending_2fa(session_key)
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=APP_APPROVAL_TTL_SECONDS)).isoformat()
            logger.info(f"[fetch_profile] Session {session_key} marked pending_2fa (App Approval), expires at {expires_at} (5 min TTL)")
            return jsonify({
                "status": "error",
                "error": "2fa_app_approval",
                "error_type": "2fa_app",
                "message": "Check your LinkedIn app and tap 'Yes' to approve the sign-in request. You have 5 minutes to approve.",
                "session_key": session_key,
                "expires_at": expires_at
            }), 401
        elif "2FA_REQUIRED" in error_str:
            logger.warning(f"[fetch_profile] 2FA required during profile fetch for {target_profile_url}, keeping session alive")
            store_service_in_session(session_key, service)
            mark_session_pending_2fa(session_key)
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=SESSION_TTL_SECONDS)).isoformat()
            logger.info(f"[fetch_profile] Session {session_key} marked pending_2fa, expires at {expires_at}")
            return jsonify({
                "status": "error",
                "error": "2fa_required",
                "error_type": "2fa",
                "message": "Two-factor authentication required.",
                "session_key": session_key,
                "expires_at": expires_at
            }), 401
        elif "ACCOUNT_RESTRICTED" in error_str:
            logger.error(f"[fetch_profile] Account restricted during profile fetch for {target_profile_url}: {e}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "account_restricted",
                "message": error_str.replace("ACCOUNT_RESTRICTED: ", "")
            }), 403
        elif "INVALID_CREDENTIALS" in error_str:
            logger.error(f"[fetch_profile] Invalid credentials during profile fetch for {target_profile_url}: {e}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "invalid_credentials",
                "message": error_str.replace("INVALID_CREDENTIALS: ", "")
            }), 401
        elif "CAPTCHA_FAILED" in error_str:
            logger.error(f"[fetch_profile] Captcha failed during profile fetch for {target_profile_url}: {e}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "captcha_failed",
                "message": error_str.replace("CAPTCHA_FAILED: ", "")
            }), 423
        elif "CHECKPOINT_ACTION_REQUIRED" in error_str:
            checkpoint_context = service.get_last_checkpoint_context()
            message = error_str.split(":", 1)[-1].strip() if ":" in error_str else "LinkedIn requires additional verification."
            logger.error(f"[fetch_profile] Manual checkpoint verification required during profile fetch for {target_profile_url}: {message}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "checkpoint_action_required",
                "message": message,
                "checkpoint_context": checkpoint_context
            }), 423
        elif "CHECKPOINT_UNKNOWN" in error_str:
            checkpoint_context = service.get_last_checkpoint_context()
            message = error_str.split(":", 1)[-1].strip() if ":" in error_str else "LinkedIn presented an unknown challenge."
            logger.error(f"[fetch_profile] Unknown checkpoint encountered during profile fetch for {target_profile_url}: {message}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "checkpoint_unknown",
                "message": message,
                "checkpoint_context": checkpoint_context
            }), 423
        else:
            logger.error(f"[fetch_profile] Authentication error during profile fetch for {target_profile_url}: {e}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "auth_failed",
                "message": error_str
            }), 401
    except Exception as e:
        logger.error(f"[fetch_profile] Error fetching profile {target_profile_url} for session {session_key}: {e}")
        service.close()
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route('/session/<session_key>/profile/contact-info', methods=['POST'])
def fetch_contact_info(session_key: str):
    """Fetch LinkedIn contact info details"""
    session_key = _skey(session_key)
    session = ensure_session(session_key)
    if session is None:
        return jsonify({
            "status": "error",
            "error": "Session not found"
        }), 404

    data = request.get_json() or {}
    required = ["email", "password", "outreach_profile_id", "target_profile_url"]
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({
            "status": "error",
            "error": f"Missing required fields: {', '.join(missing)}"
        }), 400

    email = data["email"]
    password = data["password"]
    outreach_profile_id = data["outreach_profile_id"]
    target_profile_url = data["target_profile_url"]
    cookies = data.get("cookies")
    user_agent = data.get("user_agent")

    service = LinkedInService(email, password, cookies, user_agent)
    service.set_outreach_profile_id(outreach_profile_id)

    try:
        login_success = service.login()
        if not login_success:
            logger.error(f"[fetch_contact_info] Login failed for {target_profile_url}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "Login failed"
            }), 401

        contact_info = service.fetch_contact_info(target_profile_url)
        session_data = service.get_session_data()
        service.close()
        return jsonify({
            "status": "success",
            "contact_info": contact_info,
            "cookies": session_data.get("cookies"),
            "user_agent": session_data.get("user_agent"),
        })
    except LinkedInCaptchaError as exc:
        logger.warning(f"[fetch_contact_info] Captcha detected while fetching {target_profile_url}: {exc}")
        service.close()
        return jsonify({
            "status": "error",
            "error": "captcha_required",
            "message": str(exc)
        }), 423
    except LinkedInAuthError as exc:
        logger.error(f"[fetch_contact_info] Authentication error for {target_profile_url}: {exc}")
        service.close()
        return jsonify({
            "status": "error",
            "error": "auth_failed",
            "message": str(exc)
        }), 401
    except Exception as exc:
        logger.exception(f"[fetch_contact_info] Unexpected error: {exc}")
        service.close()
        return jsonify({
            "status": "error",
            "error": str(exc)
        }), 500


@app.route('/session/<session_key>/search/scrape', methods=['POST'])
def scrape_search_results(session_key: str):
    """Scrape LinkedIn search results into lead data."""
    session_key = _skey(session_key)
    session = ensure_session(session_key)
    if session is None:
        return jsonify({
            "status": "error",
            "error": "Session not found"
        }), 404

    data = request.get_json() or {}
    required = ["email", "password", "outreach_profile_id", "search_url"]
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({
            "status": "error",
            "error": f"Missing required fields: {', '.join(missing)}"
        }), 400

    email = data["email"]
    password = data["password"]
    outreach_profile_id = data["outreach_profile_id"]
    search_url = data["search_url"]
    max_results = int(data.get("max_results", 50))
    cookies = data.get("cookies")
    user_agent = data.get("user_agent")

    service = LinkedInService(email, password, cookies, user_agent)
    service.set_outreach_profile_id(outreach_profile_id)

    try:
        if not service.login():
            logger.error(f"[scrape_search_results] Login failed for search {search_url}")
            return jsonify({
                "status": "error",
                "error": "Login failed"
            }), 401

        leads = service.scrape_search_results(search_url, max_results=max_results)
        session_data = service.get_session_data() or {}
        logger.info(f"[scrape_search_results] Scraped {len(leads)} leads for {search_url}")
        return jsonify({
            "status": "success",
            "total": len(leads),
            "leads": leads,
            "cookies": session_data.get("cookies"),
            "user_agent": session_data.get("user_agent"),
        })
    except LinkedInCaptchaError as exc:
        logger.warning(f"[scrape_search_results] Captcha detected: {exc}")
        return jsonify({
            "status": "error",
            "error": "captcha_required",
            "message": str(exc)
        }), 423
    except LinkedInAuthError as exc:
        logger.error(f"[scrape_search_results] Authentication error: {exc}")
        return jsonify({
            "status": "error",
            "error": "auth_failed",
            "message": str(exc)
        }), 401
    except LinkedInSearchEmptyError as exc:
        logger.info(f"[scrape_search_results] No results for {search_url}: {exc}")
        session_data = service.get_session_data() or {}
        return jsonify({
            "status": "success",
            "total": 0,
            "leads": [],
            "message": str(exc),
            "cookies": session_data.get("cookies"),
            "user_agent": session_data.get("user_agent"),
        }), 200
    except LinkedInSearchError as exc:
        logger.error(f"[scrape_search_results] Search scraping error: {exc}")
        return jsonify({
            "status": "error",
            "error": "search_failed",
            "message": str(exc)
        }), 502
    except Exception as exc:
        logger.exception(f"[scrape_search_results] Unexpected error: {exc}")
        return jsonify({
            "status": "error",
            "error": "unexpected_error",
            "message": str(exc)
        }), 500
    finally:
        service.close()


@app.route('/session/<session_key>/connection', methods=['POST'])
def send_connection_request(session_key: str):
    """Send connection request to a LinkedIn profile"""
    session_key = _skey(session_key)
    session = ensure_session(session_key)
    if session is None:
        return jsonify({
            "status": "error",
            "error": "Session not found"
        }), 404

    data = request.get_json() or {} 
    # Validate required fields
    required = ["email", "password", "outreach_profile_id", "target_profile_url"]
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({
            "status": "error", 
            "error": f"Missing required fields: {', '.join(missing)}"
        }), 400

    email = data['email']
    password = data['password']
    outreach_profile_id = data['outreach_profile_id']
    cookies = data.get('cookies', None)
    user_agent = data.get('user_agent', None)
    target_profile_url = data['target_profile_url']
    additional_note = data.get('additional_note', '')

    service = LinkedInService(email, password, cookies, user_agent)
    service.set_outreach_profile_id(outreach_profile_id)
    try:
        # Attempt login
        login_success = service.login()
        if not login_success:
            logger.error(f"[send_connection_request] Login failed for {target_profile_url}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "Login failed"
                }), 401
    except LinkedInAuthError as e:
        if "2FA_REQUIRED" in str(e):
            logger.warning(f"[send_connection_request] 2FA required for {target_profile_url}, keeping session alive")
            store_service_in_session(session_key, service)
            mark_session_pending_2fa(session_key)
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=SESSION_TTL_SECONDS)).isoformat()
            logger.info(f"[send_connection_request] Session {session_key} marked pending_2fa, expires at {expires_at}")
            return jsonify({
                "status": "error",
                "error": "2fa_required",
                "session_key": session_key,
                "expires_at": expires_at
            }), 401
        else:
            logger.error(f"[send_connection_request] Authentication error for {target_profile_url}: {e}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "auth_failed"
            }), 401

    try:
        # Send connection request
        success = service.send_connection_request(target_profile_url, additional_note)
        if not success:
            error_code = service.get_last_connect_error() or "connection_request_failed"
            logger.error(f"[send_connection_request] Failed to send connection request to {target_profile_url}: {error_code}")
            service.close()
            return jsonify({
                "status": "error",
                "error": error_code
            })

        logger.info(f"[send_connection_request] Connection request sent successfully to {target_profile_url}")
        session_data = service.get_session_data()
        cookies = session_data.get('cookies', None)
        user_agent = session_data.get('user_agent', None)
        logger.info(f"[send_connection_request] Session data fetched successfully for {target_profile_url}")
        service.close()
        return jsonify({
            "status": "success",
            "target_profile_url": target_profile_url,
            "cookies": cookies,
            "user_agent": user_agent
        })
    except LinkedInAuthError as e:
        if "2FA_REQUIRED" in str(e):
            logger.warning(f"[send_connection_request] 2FA required during connection request for {target_profile_url}, keeping session alive")
            store_service_in_session(session_key, service)
            mark_session_pending_2fa(session_key)
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=SESSION_TTL_SECONDS)).isoformat()
            logger.info(f"[send_connection_request] Session {session_key} marked pending_2fa, expires at {expires_at}")
            return jsonify({
                "status": "error",
                "error": "2fa_required",
                "session_key": session_key,
                "expires_at": expires_at
            }), 401
        else:
            logger.error(f"[send_connection_request] Authentication error during connection request for {target_profile_url}: {e}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "auth_failed"
            }), 401
    except Exception as e:
        logger.error(f"[send_connection_request] Error sending connection request to {target_profile_url}: {e}")
        service.close()
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route('/session/<session_key>/messages/send', methods=['POST'])
def send_message(session_key: str):
    """Send message to a LinkedIn profile"""
    session_key = _skey(session_key)
    session = ensure_session(session_key)
    if session is None:
        return jsonify({
            "status": "error",
            "error": "Session not found"
        }), 404

    data = request.get_json() or {} 
    # Validate required fields
    required = ["email", "password", "outreach_profile_id", "target_profile_url", "message"]
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({
            "status": "error", 
            "error": f"Missing required fields: {', '.join(missing)}"
        }), 400

    email = data['email']
    password = data['password']
    outreach_profile_id = data['outreach_profile_id']
    cookies = data.get('cookies', None)
    user_agent = data.get('user_agent', None)
    target_profile_url = data['target_profile_url']
    message = data['message']

    service = LinkedInService(email, password, cookies, user_agent)
    service.set_outreach_profile_id(outreach_profile_id)
    try:
        # Attempt login
        login_success = service.login()
        if not login_success:
            logger.error(f"[send_message] Login failed for {target_profile_url}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "Login failed"
                }), 401

        # Send message
        success = service.send_message(target_profile_url, message)
        if not success:
            logger.error(f"[send_message] Failed to send message to {target_profile_url}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "Failed to send message"
            }), 400
        logger.info(f"[send_message] Message sent successfully to {target_profile_url}")
        session_data = service.get_session_data()
        cookies = session_data.get('cookies', None)
        user_agent = session_data.get('user_agent', None)
        logger.info(f"[send_message] Session data fetched successfully for {target_profile_url}")
        service.close()
        return jsonify({
            "status": "success",
            "target_profile_url": target_profile_url,
            "cookies": cookies,
            "user_agent": user_agent
        })
    except Exception as e:
        logger.error(f"[send_message] Error sending message to {target_profile_url} for session {session_key}: {e}")
        service.close()
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route('/session/<session_key>/pin/submit', methods=['POST'])
def submit_pin(session_key: str):
    """Submit a PIN/verification code for 2FA"""
    session_key = _skey(session_key)
    
    service = get_session_service(session_key)
    if service is None:
        return jsonify({
            "status": "error",
            "error": "Session not found or expired"
        }), 404
    
    status = get_session_status(session_key)
    if status != "pending_2fa":
        return jsonify({
            "status": "error",
            "error": f"Session not in pending_2fa state (current: {status})"
        }), 400

    data = request.get_json() or {}
    required = ["pin"]
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({
            "status": "error",
            "error": f"Missing required fields: {', '.join(missing)}"
        }), 400

    pin = data['pin']

    try:
        success = service.submit_pin(pin)
        if not success:
            logger.error(f"[submit_pin] PIN submission failed")
            close_session(session_key)
            return jsonify({
                "status": "error",
                "error": "PIN submission failed"
            }), 400

        logger.info(f"[submit_pin] PIN submitted successfully")
        session_data = service.get_session_data()
        cookies = session_data.get('cookies', None)
        user_agent = session_data.get('user_agent', None)
        close_session(session_key)
        return jsonify({
            "status": "success",
            "cookies": cookies,
            "user_agent": user_agent
        })
    except Exception as e:
        logger.error(f"[submit_pin] Error submitting PIN: {e}")
        close_session(session_key)
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route('/session/<session_key>/app-approval/check', methods=['GET'])
def check_app_approval(session_key: str):
    """
    Check the status of a pending app approval (push notification 2FA).
    
    This endpoint is called by the frontend to poll for approval status
    after the user has been prompted to approve on their LinkedIn app.
    
    Returns:
        - status: "approved" | "rejected" | "pending" | "expired" | "error"
        - message: Human-readable message
        - cookies/user_agent: Only if approved (for session persistence)
    """
    session_key = _skey(session_key)
    
    service = get_session_service(session_key)
    if service is None:
        return jsonify({
            "status": "expired",
            "error": "Session not found or expired. Please start a new verification.",
            "message": "Session expired. Please start a new verification."
        }), 404
    
    status = get_session_status(session_key)
    if status != "pending_2fa":
        return jsonify({
            "status": "error",
            "error": f"Session not in pending_2fa state (current: {status})",
            "message": f"Session is not waiting for approval (status: {status})"
        }), 400

    try:
        result = service.check_app_approval_status()
        logger.info(f"[check_app_approval] Session {session_key} status: {result['status']}")
        
        if result["status"] == "approved":
            # User approved - get session data and close
            session_data = service.get_session_data()
            cookies = session_data.get('cookies', None)
            user_agent = session_data.get('user_agent', None)
            close_session(session_key)
            return jsonify({
                "status": "approved",
                "message": result.get("message", "Successfully authenticated!"),
                "cookies": cookies,
                "user_agent": user_agent
            })
        elif result["status"] == "rejected":
            # User rejected - close session
            close_session(session_key)
            return jsonify({
                "status": "rejected",
                "message": result.get("message", "Sign-in request was denied."),
                "error": "User rejected the sign-in request"
            }), 403
        elif result["status"] == "expired":
            close_session(session_key)
            return jsonify({
                "status": "expired",
                "message": result.get("message", "Session expired."),
                "error": "Browser session expired"
            }), 410
        elif result["status"] == "error":
            # Check if state changed to PIN
            if result.get("details") == "state_changed_to_pin":
                return jsonify({
                    "status": "state_changed",
                    "new_state": "2fa_pin_required",
                    "message": result.get("message", "LinkedIn is now asking for a PIN code."),
                    "error": "State changed to PIN entry"
                }), 409
            return jsonify({
                "status": "error",
                "message": result.get("message", "Error checking approval status"),
                "error": result.get("message", "Unknown error")
            }), 500
        elif result["status"] == "checkpoint_action_required":
            checkpoint_context = result.get("context") or service.get_last_checkpoint_context()
            close_session(session_key)
            return jsonify({
                "status": "checkpoint_action_required",
                "message": result.get("message", "LinkedIn requires additional verification."),
                "checkpoint_context": checkpoint_context,
            }), 423
        else:
            # Still pending
            return jsonify({
                "status": "pending",
                "message": result.get("message", "Waiting for approval on LinkedIn app...")
            })
            
    except Exception as e:
        logger.error(f"[check_app_approval] Error checking approval status: {e}")
        return jsonify({
            "status": "error",
            "error": str(e),
            "message": f"Error checking approval: {str(e)}"
        }), 500


@app.route('/session/<session_key>/app-approval/wait', methods=['POST'])
def wait_for_app_approval(session_key: str):
    """
    Wait for app approval with a timeout.
    
    This is a blocking endpoint that waits for the user to approve/reject
    on their LinkedIn app. Use for synchronous flows.
    
    Request body (optional):
        - timeout_seconds: Max time to wait (default: 60, max: 120)
        - poll_interval: Time between checks (default: 2.0)
    """
    session_key = _skey(session_key)
    
    service = get_session_service(session_key)
    if service is None:
        return jsonify({
            "status": "expired",
            "error": "Session not found or expired",
            "message": "Session expired. Please start a new verification."
        }), 404
    
    status = get_session_status(session_key)
    if status != "pending_2fa":
        return jsonify({
            "status": "error",
            "error": f"Session not in pending_2fa state (current: {status})"
        }), 400

    data = request.get_json() or {}
    timeout_seconds = min(int(data.get("timeout_seconds", 60)), 120)  # Max 2 minutes
    poll_interval = float(data.get("poll_interval", 2.0))

    try:
        result = service.wait_for_app_approval(
            timeout_seconds=timeout_seconds,
            poll_interval=poll_interval
        )
        logger.info(f"[wait_for_app_approval] Session {session_key} result: {result['status']}")
        
        if result["status"] == "approved":
            session_data = service.get_session_data()
            cookies = session_data.get('cookies', None)
            user_agent = session_data.get('user_agent', None)
            close_session(session_key)
            return jsonify({
                "status": "approved",
                "message": result.get("message", "Successfully authenticated!"),
                "cookies": cookies,
                "user_agent": user_agent
            })
        elif result["status"] == "rejected":
            close_session(session_key)
            return jsonify({
                "status": "rejected",
                "message": result.get("message", "Sign-in request was denied."),
                "error": "User rejected the sign-in request"
            }), 403
        elif result["status"] == "timeout":
            # Don't close session on timeout - user might still approve
            return jsonify({
                "status": "timeout",
                "message": result.get("message", "Approval not received in time."),
                "error": "Timeout waiting for approval"
            }), 408
        elif result["status"] == "checkpoint_action_required":
            checkpoint_context = result.get("context") or service.get_last_checkpoint_context()
            close_session(session_key)
            return jsonify({
                "status": "checkpoint_action_required",
                "message": result.get("message", "LinkedIn requires additional verification."),
                "checkpoint_context": checkpoint_context,
            }), 423
        else:
            return jsonify({
                "status": result["status"],
                "message": result.get("message", "Unknown status"),
                "error": result.get("message")
            }), 500
            
    except Exception as e:
        logger.error(f"[wait_for_app_approval] Error: {e}")
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route('/session/<session_key>/cancel', methods=['POST'])
def cancel_session(session_key: str):
    """Cancel a pending 2FA session"""
    session_key = _skey(session_key)
    
    status = get_session_status(session_key)
    if status is None:
        return jsonify({
            "status": "error",
            "error": "Session not found"
        }), 404
    
    logger.info(f"[cancel_session] Cancelling session {session_key} with status {status}")
    success = close_session(session_key)
    
    if success:
        return jsonify({
            "status": "success",
            "message": "Session cancelled and closed"
        })
    else:
        return jsonify({
            "status": "error",
            "error": "Failed to close session"
        }), 500


@app.route('/session/<session_key>/messages/get', methods=['POST'])
def get_messages(session_key: str):
    """Get all messages from a chat"""
    session_key = _skey(session_key)
    session = ensure_session(session_key)
    if session is None:
        return jsonify({
            "status": "error",
            "error": "Session not found"
        }), 404

    data = request.get_json() or {} 
    # Validate required fields
    required = ["email", "password", "outreach_profile_id", "target_profile_url"]
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({
            "status": "error", 
            "error": f"Missing required fields: {', '.join(missing)}"
        }), 400

    email = data['email']
    password = data['password']
    outreach_profile_id = data['outreach_profile_id']
    cookies = data.get('cookies', None)
    user_agent = data.get('user_agent', None)
    target_profile_url = data['target_profile_url']

    service = LinkedInService(email, password, cookies, user_agent)
    service.set_outreach_profile_id(outreach_profile_id)
    try:
        # Attempt login
        login_success = service.login()
        if not login_success:
            logger.error(f"[get_messages] Login failed for {target_profile_url}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "Login failed"
                }), 401
        # Get all messages
        messages = service.get_all_messages_from_chat(target_profile_url)
        if messages is False:
            logger.error(f"[get_messages] Failed to retrieve messages from {target_profile_url} for session {session_key}")
            service.close()
            return jsonify({
                "status": "error",
                "error": "Failed to retrieve messages"
            }), 400

        logger.info(f"[get_messages] Retrieved {len(messages)} messages from {target_profile_url}")
        session_data = service.get_session_data()
        cookies = session_data.get('cookies', None)
        user_agent = session_data.get('user_agent', None)
        logger.info(f"[get_messages] Session data fetched successfully for {target_profile_url}")
        service.close()
        return jsonify({
            "status": "success",
            "messages": messages,
            "message_count": len(messages),
            "target_profile_url": target_profile_url,
            "cookies": cookies,
            "user_agent": user_agent
        })
    except Exception as e:
        logger.error(f"[get_messages] Error retrieving messages from {target_profile_url} for session {session_key}: {e}")
        service.close()
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500



@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Endpoint not found",
        "status": "error"
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "error": "Internal server error",
        "status": "error"
    }), 500

if __name__ == '__main__':
    # from gevent import monkey
    # monkey.patch_all()
    logger.info(f"Starting LinkedIn microservice on port {LINKEDIN_SERVICE_PORT}")
    app.run(host='0.0.0.0', port=LINKEDIN_SERVICE_PORT, debug=False)