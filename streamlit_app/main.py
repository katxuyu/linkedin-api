from __future__ import annotations

import copy
import hashlib
import json
import time
from datetime import datetime
from typing import Optional

import pandas as pd
import streamlit as st

from app.crud_sync import (
    LOGIN_CODE_STATUS_FAILED,
    LOGIN_CODE_STATUS_PENDING,
    LOGIN_CODE_STATUS_SUCCEEDED,
    LOGIN_CODE_STATUS_TIMED_OUT,
)
from streamlit_app import data_access

MAX_VERIFICATION_WINDOW = 30 * 60  # 30 minutes
AUTO_REFRESH_SECONDS = 60  # 1 minute
STATUS_LABELS = {
    LOGIN_CODE_STATUS_PENDING.lower(): ("Pending", "⏳"),
    LOGIN_CODE_STATUS_SUCCEEDED.lower(): ("Success", "✅"),
    LOGIN_CODE_STATUS_FAILED.lower(): ("Failed", "❌"),
    LOGIN_CODE_STATUS_TIMED_OUT.lower(): ("Timed out", "⌛"),
    "rescheduled": ("Rescheduled", "🔁"),
    "submitted": ("Submitted", "✉️"),
    "code_rejected": ("Code rejected", "⚠️"),
}

DEFAULT_CAMPAIGN_CONFIG = {
    "base_url": "http://localhost:8000",
    "li_service_url": "http://localhost:5001",
    "admin_email": "admin@admin.com",
    "admin_password": "ChangeMe123!",
    "user_email": "ops@example.com",
    "user_password": "SecurePassword123!",
    "outreach_linkedin_email": "",
    "outreach_linkedin_password": "",
    "outreach_linkedin_url": "",
    "campaign_template_name": "Streamlit Campaign",
    "campaign_template_description": "Generated via Streamlit control panel",
    "campaign_run_label": "Streamlit run",
    "gohighlevel_account_id": "",
}

DEFAULT_CAMPAIGN_STEPS = [
    {
        "step_number": 1,
        "action": "send_connection",
        "delay_seconds": 30,
        "note": "Hello {{name}}, let's connect!",
        "message": "",
    },
    {
        "step_number": 2,
        "action": "send_message",
        "delay_seconds": 60,
        "note": "",
        "message": "Great to connect, {{name}}! Following up.",
    },
]

CAMPAIGN_JSON_TEMPLATE = json.dumps(
    {**DEFAULT_CAMPAIGN_CONFIG, "steps": DEFAULT_CAMPAIGN_STEPS},
    indent=2,
)

TARGETS_CSV_TEMPLATE = "url,name,last_name,title\nhttps://www.linkedin.com/in/example/,Jane,Doe,Marketing Director\n"

CONFIG_WIDGET_PREFIX = "campaign_config_"


def _prime_campaign_config_widgets(config: dict) -> None:
    for field, default in DEFAULT_CAMPAIGN_CONFIG.items():
        state_key = f"{CONFIG_WIDGET_PREFIX}{field}"
        if state_key not in st.session_state:
            st.session_state[state_key] = config.get(field, default) or ""


def _apply_uploaded_campaign_config(payload: dict) -> None:
    for field, value in payload.items():
        if field == "steps" and isinstance(value, list):
            st.session_state["campaign_steps"] = value
            continue
        state_key = f"{CONFIG_WIDGET_PREFIX}{field}"
        if field in DEFAULT_CAMPAIGN_CONFIG or state_key in st.session_state:
            st.session_state[state_key] = value if value is not None else ""

def _ensure_campaign_config() -> dict:
    if "campaign_config" not in st.session_state:
        st.session_state["campaign_config"] = copy.deepcopy(DEFAULT_CAMPAIGN_CONFIG)
    return st.session_state["campaign_config"]


def _ensure_campaign_steps() -> list:
    if "campaign_steps" not in st.session_state:
        st.session_state["campaign_steps"] = copy.deepcopy(DEFAULT_CAMPAIGN_STEPS)
    return st.session_state["campaign_steps"]


def _ensure_campaign_state() -> dict:
    if "campaign_state" not in st.session_state:
        st.session_state["campaign_state"] = {
            "services": {},
            "admin_token": None,
            "registration_key": None,
            "user_token": None,
            "ghl_authorization_url": None,
            "ghl_client_state": None,
            "ghl_account_id": None,
            "ghl_accounts": [],
            "ghl_accounts_loaded": False,
            "ghl_accounts_error": None,
            "outreach_profile_id": None,
            "campaign_template_id": None,
            "existing_outreach_profiles": [],
            "existing_outreach_error": None,
        }
    return st.session_state["campaign_state"]


def _append_campaign_log(level: str, message: str) -> None:
    logs = st.session_state.setdefault("campaign_logs", [])
    logs.append(
        {"timestamp": datetime.utcnow().isoformat(timespec="seconds"), "level": level, "message": message}
    )


def _reset_campaign_flow() -> None:
    st.session_state.pop("campaign_state", None)
    st.session_state.pop("campaign_logs", None)


def _parse_targets_csv(file_buffer) -> tuple[list[dict], pd.DataFrame]:
    df = pd.read_csv(file_buffer).fillna("")
    if "url" not in df.columns:
        raise ValueError("CSV must include a 'url' column.")
    targets: list[dict] = []
    for _, row in df.iterrows():
        url = str(row["url"]).strip()
        if not url:
            continue
        variables = {
            col: str(row[col]).strip()
            for col in df.columns
            if col != "url" and str(row[col]).strip()
        }
        targets.append({"url": url, "variables": variables})
    if not targets:
        raise ValueError("No valid targets found in CSV.")
    return targets, df


def _build_steps_payload(step_rows: list[dict]) -> list[dict]:
    payload: list[dict] = []
    for index, row in enumerate(step_rows, start=1):
        step_number = int(row.get("step_number") or index)
        action = (row.get("action") or "send_connection").strip() or "send_connection"
        delay_seconds_raw = row.get("delay_seconds") or row.get("delay")
        try:
            delay_seconds = max(int(delay_seconds_raw), 1)
        except (TypeError, ValueError):
            delay_seconds = 30
        entry = {
            "step_number": step_number,
            "action": action,
            "delay_timestamp": f"{delay_seconds}s",
        }
        note = (row.get("note") or "").strip()
        message = (row.get("message") or "").strip()
        if action == "send_connection":
            if note:
                entry["additional_note_template"] = note
        else:
            if message:
                entry["message_template"] = message
            elif note:
                entry["message_template"] = note
        payload.append(entry)
    return payload


STEP_STATUS_META = {
    "done": ("✅", "Complete"),
    "ready": ("➡️", "Ready"),
    "blocked": ("⛔", "Blocked"),
}


def _step_status_badge(status: str) -> str:
    icon, label = STEP_STATUS_META.get(status, ("ℹ️", "Pending"))
    return f"{icon} {label}"


def _render_step_header(title: str, description: str, status: str) -> None:
    header_cols = st.columns([0.75, 0.25])
    header_cols[0].markdown(f"**{title}**")
    header_cols[1].markdown(
        f"<div style='text-align:right'>{_step_status_badge(status)}</div>",
        unsafe_allow_html=True,
    )
    if description:
        st.caption(description)


def _resolve_step_status(
    tracker: dict,
    key: str,
    *,
    dependencies: Optional[list[str]] = None,
    ready: bool = True,
) -> str:
    dependencies = dependencies or []
    if tracker.get(key):
        return "done"
    if not ready or any(not tracker.get(dep) for dep in dependencies):
        return "blocked"
    return "ready"


def _force_wizard_rerun() -> None:
    st.session_state["auto_refresh_anchor"] = time.time()
    st.rerun()


def format_remaining(seconds: int) -> str:
    minutes = seconds // 60
    secs = seconds % 60
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


st.set_page_config(page_title="LinkedIn Verification Control Panel", layout="wide")
st.title("LinkedIn 2FA & Scraping Control Panel")
st.caption("Monitor pending verification requests, track errors, and review target sync status.")


def _ensure_auto_refresh():
    anchor = st.session_state.setdefault("auto_refresh_anchor", time.time())
    elapsed = time.time() - anchor
    if elapsed >= AUTO_REFRESH_SECONDS:
        st.session_state["auto_refresh_anchor"] = time.time()
        st.rerun()
    return max(0, int(AUTO_REFRESH_SECONDS - elapsed))


next_refresh_countdown = _ensure_auto_refresh()
top_controls = st.columns([1, 3, 2])
if top_controls[0].button("🔄 Refresh dashboard", use_container_width=True):
    st.session_state["auto_refresh_anchor"] = time.time()
    st.rerun()
top_controls[1].info("Auto-refresh keeps data fresh for ops monitoring.")
top_controls[2].metric("Next auto-refresh", format_remaining(next_refresh_countdown))
st.divider()


with st.sidebar:
    operator_name = st.text_input(
        "Your name or initials",
        value=st.session_state.get("operator_name", ""),
        help="Used to attribute manual code submissions.",
    ).strip()
    st.session_state["operator_name"] = operator_name
    st.write("---")
    st.caption("Need help? Check the Errors & History tab for recent system messages.")


(
    pending_tab,
    errors_tab,
    targets_tab,
    campaign_health_tab,
    ops_tab,
    campaign_launcher_tab,
) = st.tabs(
    [
        "Pending Manual Codes",
        "Errors & Verification History",
        "Target Connection Status",
        "Campaign Health",
        "Ops Systems",
        "Campaign Launcher",
    ]
)


with pending_tab:
    header_cols = st.columns([2, 1])
    with header_cols[0]:
        st.subheader("Manual Verification Queue")
    with header_cols[1]:
        if st.button("Refresh tab", key="refresh_pending_tab"):
            st.session_state["auto_refresh_anchor"] = time.time()
            st.rerun()

    search_text = st.text_input(
        "Filter by outreach email or target name",
        key="pending_search",
        placeholder="e.g., ops@example.com or Jane Doe",
    ).strip()

    pending_requests = data_access.get_pending_requests(search_text or None)
    if not pending_requests:
        st.success("No pending manual verification requests. 🎉")
    else:
        for request in pending_requests:
            progress_value = 1.0 - min(request["remaining_seconds"], MAX_VERIFICATION_WINDOW) / MAX_VERIFICATION_WINDOW
            badge = f"Request #{request['id']} · Outreach #{request['outreach_id']}"
            with st.container(border=True):
                st.markdown(f"**{badge}**")
                cols = st.columns(4)
                cols[0].metric("Outreach Email", request["outreach_email"])
                cols[1].metric("Target", request.get("target_name") or "N/A")
                cols[2].metric("Time Remaining", format_remaining(request["remaining_seconds"]))
                cols[3].metric("Reason", request.get("pending_reason") or "Login checkpoint")

                st.progress(progress_value, text="Verification window progress")

                code_key = f"code_{request['id']}"
                code_value = st.text_input(
                    "LinkedIn verification code",
                    key=code_key,
                    max_chars=8,
                    help="Enter the 2FA or SMS code shown in the LinkedIn session.",
                ).strip()

                submit_disabled = not code_value or not operator_name
                if not operator_name:
                    st.warning("Provide your name/initials in the sidebar before submitting codes.", icon="⚠️")

                submit_key = f"submit_{request['id']}"
                if st.button("Submit code", key=submit_key, type="primary", disabled=submit_disabled):
                    try:
                        attempt_id = data_access.submit_manual_code(request["id"], code_value, operator_name)
                        st.toast("Code submitted. Worker is processing the login.", icon="📨")
                        st.session_state.setdefault("recent_submission_ids", set()).add(attempt_id)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed to submit verification code: {exc}")

    st.markdown("### Submitted Codes Status")
    st.caption("Entries refresh automatically. Use dismiss to hide resolved successes.")
    dismissed_attempts = st.session_state.setdefault("dismissed_attempt_ids", set())
    recent_attempts = data_access.get_recent_attempts(
        operator_filter=operator_name or None,
        limit=40,
    )
    display_attempts = [
        attempt for attempt in recent_attempts if attempt["attempt_id"] not in dismissed_attempts
    ]

    def _status_display(status: str) -> str:
        if not status:
            return "ℹ️ N/A"
        normalized = status.lower()
        label, icon = STATUS_LABELS.get(normalized, (status.replace("_", " ").title(), "ℹ️"))
        return f"{icon} {label}"

    if display_attempts:
        attempt_df = pd.DataFrame(
            [
                {
                    "Attempt #": item["attempt_id"],
                    "Request #": item["request_id"],
                    "Outreach": item["outreach_email"],
                    "Target": item["target_label"],
                    "Submitted By": item["submitted_by"],
                    "Submitted At (UTC)": item["submitted_at"],
                    "Status": _status_display(item["attempt_result"] or item["request_status"]),
                    "Notes": item["status_detail"]
                    or item["attempt_error"]
                    or item["attempt_result"]
                    or "",
                }
                for item in display_attempts
            ]
        )
        column_config = {}
        try:
            column_config["Target"] = st.column_config.TextColumn("Target (name/url)", width="medium")
        except AttributeError:
            column_config = {}
        st.dataframe(
            attempt_df,
            use_container_width=True,
            hide_index=True,
            column_config=column_config or None,
        )

        for item in display_attempts:
            if item["request_status"] != LOGIN_CODE_STATUS_PENDING:
                if st.button(
                    f"Dismiss attempt #{item['attempt_id']}",
                    key=f"dismiss_{item['attempt_id']}",
                    help="Remove this entry from the local view (data stays in history).",
                ):
                    dismissed_attempts.add(item["attempt_id"])
                    st.session_state["dismissed_attempt_ids"] = dismissed_attempts
                    st.rerun()
    else:
        st.info("No manual code submissions recorded yet.")


with errors_tab:
    header_cols = st.columns([2, 1])
    with header_cols[0]:
        st.subheader("Recent Verification Attempts & Scraping Errors")
    with header_cols[1]:
        if st.button("Refresh tab", key="refresh_errors_tab"):
            st.session_state["auto_refresh_anchor"] = time.time()
            st.rerun()

    error_filter = st.text_input(
        "Filter by outreach, target, or event type",
        key="error_search",
        placeholder="e.g., outreach email, target name, timeout",
    ).strip()

    history_rows = data_access.get_verification_history(error_filter or None)
    if history_rows:
        history_df = pd.DataFrame(history_rows)
        st.dataframe(history_df, use_container_width=True)
    else:
        st.info("No recent verification attempts or scraping errors recorded.")


with targets_tab:
    header_cols = st.columns([2, 1])
    with header_cols[0]:
        st.subheader("Target Connection & Sync Status")
    with header_cols[1]:
        if st.button("Refresh tab", key="refresh_targets_tab"):
            st.session_state["auto_refresh_anchor"] = time.time()
            st.rerun()

    target_filter = st.text_input(
        "Search targets or outreach profiles",
        key="target_search",
        placeholder="e.g., outreach email or target name",
    ).strip()

    target_rows = data_access.get_target_statuses(target_filter or None)
    if target_rows:
        target_df = pd.DataFrame(target_rows)
        if "target_name" in target_df.columns:
            target_df = target_df.drop(columns=["target_name"])
        column_config = {}
        try:
            column_config["target_url"] = st.column_config.LinkColumn("LinkedIn URL")
        except AttributeError:
            column_config = None
        st.dataframe(
            target_df,
            use_container_width=True,
            column_config=column_config,
        )
    else:
        st.info("No target records match the current filter.")


with campaign_health_tab:
    header_cols = st.columns([2, 1])
    with header_cols[0]:
        st.subheader("Campaign Health Snapshot")
    with header_cols[1]:
        if st.button("Refresh tab", key="refresh_campaigns_tab"):
            st.session_state["auto_refresh_anchor"] = time.time()
            st.rerun()

    snapshot_tab, failures_tab = st.tabs(["Snapshot", "Failures & Errors"])

    with snapshot_tab:
        show_history = st.checkbox(
            "Show historical runs (include prior duplicates)",
            value=False,
            key="campaign_snapshot_history",
        )
        snapshot_rows = data_access.get_campaign_snapshot(include_all=show_history)
        if snapshot_rows:
            active_count = sum(1 for row in snapshot_rows if row["status"] == "active")
            completed_count = sum(1 for row in snapshot_rows if row["status"] == "completed")
            queued_steps_total = sum(row.get("queued_steps", 0) for row in snapshot_rows)
            summary_cols = st.columns(3)
            summary_cols[0].metric("Active campaigns", active_count)
            summary_cols[1].metric("Completed campaigns", completed_count)
            summary_cols[2].metric("Queued steps", queued_steps_total)

            snapshot_records = []
            for row in snapshot_rows:
                progress_pct = int(round(row["progress"] * 100))
                snapshot_records.append(
                    {
                        "Campaign": row["campaign_name"],
                        "Outreach": row["outreach_email"],
                        "Target": row["target_label"],
                        "Status": row["status"].title(),
                        "Done": row["completed_steps"],
                        "Queued": row.get("queued_steps", row.get("scheduled_steps", 0)),
                        "Remaining": row["pending_steps"],
                        "Total Steps": row["total_steps"],
                        "Progress (%)": progress_pct,
                        "Last Activity": row["last_step_at"] or row["started_at"],
                        "Next Action": row["next_run_at"] or "—",
                    }
                )
            snapshot_df = pd.DataFrame(snapshot_records)
            column_config = {}
            try:
                column_config["Progress (%)"] = st.column_config.ProgressColumn(
                    "Progress",
                    min_value=0,
                    max_value=100,
                    format="%d%%",
                )
            except AttributeError:
                column_config = None
            st.dataframe(
                snapshot_df,
                use_container_width=True,
                hide_index=True,
                column_config=column_config,
            )
        else:
            st.info("No campaign runs recorded yet.")

    with failures_tab:
        failures = data_access.get_campaign_failures()
        status_counts = failures.get("status_counts", {})
        failed_steps_total = sum(status_counts.values())
        error_count = status_counts.get("error", 0) + status_counts.get("errored", 0)
        summary_cols = st.columns(3)
        summary_cols[0].metric("Failed campaigns", failures.get("failed_campaigns", 0))
        summary_cols[1].metric("Failed steps", failed_steps_total)
        summary_cols[2].metric("Errored steps", error_count)

        failure_rows = failures.get("rows", [])
        if failure_rows:
            failure_df = pd.DataFrame(
                [
                    {
                        "Campaign": row["campaign"],
                        "Outreach": row["outreach_email"],
                        "Target": row["target_display"],
                        "LinkedIn URL": row["target_url"],
                        "Step": row["step_number"],
                        "Action": row["action"],
                        "Status": row["status"].title(),
                        "Updated": row["updated_at"],
                        "Details": row["details"],
                    }
                    for row in failure_rows
                ]
            )
            column_config = {}
            try:
                column_config["LinkedIn URL"] = st.column_config.LinkColumn("LinkedIn URL")
            except AttributeError:
                column_config = None
            st.dataframe(
                failure_df,
                use_container_width=True,
                hide_index=True,
                column_config=column_config,
            )
        else:
            st.success("No failed or errored campaign steps recorded.")

    st.markdown("### Actions Throughput (last 24h)")
    throughput = data_access.get_action_throughput()
    if throughput:
        throughput_df = pd.DataFrame(throughput)
        throughput_df["bucket"] = pd.to_datetime(throughput_df["bucket"])
        throughput_df = throughput_df.set_index("bucket")
        st.line_chart(throughput_df)
    else:
        st.info("No recent actions to plot.")

    st.markdown("### Success Metrics")
    metrics = data_access.get_campaign_success_metrics()
    metric_cols = st.columns(4)
    metric_cols[0].metric("Total runs", metrics["total_runs"])
    metric_cols[1].metric("Completed", f"{metrics['completed_runs']} ({metrics['completed_pct']}%)")
    metric_cols[2].metric("Responses", f"{metrics['responses']} ({metrics['response_pct']}%)")
    metric_cols[3].metric("Contacts synced", metrics["contacts_synced"], delta=f"- pending {metrics['pending_syncs']}")

    st.markdown("### Latest Target Timelines")
    timeline_rows = data_access.get_target_timelines()
    if timeline_rows:
        timeline_df = pd.DataFrame(timeline_rows)
        st.dataframe(timeline_df, use_container_width=True, hide_index=True)
    else:
        st.info("No campaign step history yet.")


with ops_tab:
    header_cols = st.columns([2, 1])
    with header_cols[0]:
        st.subheader("Operational Systems Monitor")
    with header_cols[1]:
        if st.button("Refresh tab", key="refresh_ops_tab"):
            st.session_state["auto_refresh_anchor"] = time.time()
            st.rerun()

    st.markdown("### Outreach Seat Locks")
    locks = data_access.get_outreach_locks()
    if "error" in locks and locks["error"]:
        st.error(f"Unable to read Redis locks: {locks['error']}")
    else:
        lock_cols = st.columns(2)
        lock_cols[0].write("Session Locks")
        session_df = pd.DataFrame(locks["session_locks"])
        if session_df.empty:
            lock_cols[0].info("No active session locks.")
        else:
            lock_cols[0].dataframe(session_df, use_container_width=True, hide_index=True)
        lock_cols[1].write("Login Code Locks")
        code_df = pd.DataFrame(locks["login_code_locks"])
        if code_df.empty:
            lock_cols[1].info("No login code locks.")
        else:
            lock_cols[1].dataframe(code_df, use_container_width=True, hide_index=True)

    st.markdown("### Celery Queue Depth")
    celery_counts = data_access.get_celery_queue_depths()
    if "error" in celery_counts:
        st.error(f"Celery queue not available: {celery_counts['error']}")
    else:
        if celery_counts:
            queue_cols = st.columns(len(celery_counts))
            for idx, (queue_name, count) in enumerate(celery_counts.items()):
                queue_cols[idx].metric(queue_name, count if count >= 0 else "n/a")
        else:
            st.info("No Celery queues configured.")

    st.markdown("### Core Service Health")
    health_rows = data_access.get_system_health()
    if health_rows:
        health_df = pd.DataFrame(health_rows)
        st.dataframe(health_df, use_container_width=True, hide_index=True)
    else:
        st.info("No health data available.")

    st.markdown("### Resource Snapshot")
    resources = data_access.get_resource_snapshot()
    resource_cols = st.columns(3)
    resource_cols[0].metric("CPU %", resources["cpu_percent"] if resources["cpu_percent"] is not None else "n/a")
    resource_cols[1].metric("RAM %", resources["memory_percent"] if resources["memory_percent"] is not None else "n/a")
    resource_cols[2].metric(
        "Load Avg",
        " / ".join(f"{val:.2f}" for val in resources["load_avg"]) if resources["load_avg"] else "n/a",
    )

    st.markdown("### GoHighLevel Account Status")
    ghl_health = data_access.get_gohighlevel_account_health()
    ghl_cols = st.columns(4)
    ghl_cols[0].metric("Total accounts", ghl_health["total"])
    ghl_cols[1].metric("Active", ghl_health["active"])
    ghl_cols[2].metric("Expiring soon", ghl_health["expiring_within_days"])
    ghl_cols[3].metric("Expired", ghl_health["expired"])
    sample_accounts = ghl_health.get("sample") or []
    if sample_accounts:
        st.dataframe(pd.DataFrame(sample_accounts), use_container_width=True, hide_index=True)
    else:
        st.info("No GoHighLevel accounts stored.")

    st.markdown("### n8n Webhook Monitor")
    n8n_status = data_access.get_n8n_status()
    if not n8n_status.get("enabled"):
        st.warning(n8n_status.get("detail", "n8n webhook disabled."))
    else:
        status_icon = "✅" if n8n_status.get("ok") else "⚠️"
        st.write(
            f"{status_icon} n8n responded with HTTP {n8n_status.get('status_code')} "
            f"- {n8n_status.get('detail', '')}"
        )
        history = data_access.get_n8n_webhook_events()
        if history:
            st.dataframe(pd.DataFrame(history), use_container_width=True, hide_index=True)
        else:
            st.info("No n8n webhook events logged yet.")

    st.markdown("### Recent Alerts & Rate Limits")
    alerts = data_access.get_recent_alerts()
    if alerts:
        alert_df = pd.DataFrame(alerts)
        st.dataframe(alert_df, use_container_width=True, hide_index=True)
    else:
        st.success("No recent alerts recorded.")

    st.markdown("### Manual Actions Queue")
    manual_tasks = data_access.get_manual_action_queue()
    if manual_tasks:
        manual_df = pd.DataFrame(manual_tasks)
        st.dataframe(manual_df, use_container_width=True, hide_index=True)
    else:
        st.info("No manual follow-ups waiting.")

    st.markdown("### Ops Notes & Audit Trail")
    outreach_profiles = data_access.list_outreach_profiles()
    outreach_options = {profile["linkedin_email"]: profile["id"] for profile in outreach_profiles}
    with st.form("ops_note_form"):
        selected_email = st.selectbox(
            "Outreach profile",
            list(outreach_options.keys()) or ["—"],
            disabled=not outreach_options,
        )
        note_text = st.text_area("Note", placeholder="Document pause reasons, warnings, etc.")
        submit = st.form_submit_button("Add note")
        if submit:
            if not outreach_options:
                st.warning("No outreach profiles available.")
            elif not note_text.strip():
                st.warning("Note text is required.")
            else:
                try:
                    data_access.create_ops_note(
                        outreach_profile_id=outreach_options[selected_email],
                        note_text=note_text,
                        operator_name=operator_name or "streamlit",
                    )
                    st.success("Note recorded.")
                    st.session_state["auto_refresh_anchor"] = time.time()
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed to record note: {exc}")

    notes = data_access.get_ops_notes()
    if notes:
        notes_df = pd.DataFrame(notes)
        st.dataframe(notes_df, use_container_width=True, hide_index=True)
    else:
        st.info("No ops notes yet.")


with campaign_launcher_tab:
    st.subheader("Campaign Launch Wizard")
    st.caption(
        "End-to-end helper that mirrors the manual steps from `testing.ipynb`. "
        "Provide credentials (via UI or JSON import), upload your target CSV, then run each stage."
    )

    campaign_config = _ensure_campaign_config()
    _ensure_campaign_steps()
    _prime_campaign_config_widgets(campaign_config)
    campaign_state = _ensure_campaign_state()

    with st.expander("1. Environment & Credentials", expanded=True):
        st.markdown("##### Import / Export JSON configuration")
        config_upload = st.file_uploader("Import JSON config", type="json", key="campaign_config_upload")
        if config_upload is not None:
            uploaded_bytes = config_upload.getvalue()
            digest = hashlib.sha256(uploaded_bytes).hexdigest()
            if digest != st.session_state.get("campaign_config_upload_digest"):
                try:
                    data = json.loads(uploaded_bytes.decode("utf-8"))
                    if not isinstance(data, dict):
                        raise ValueError("JSON root must be an object.")
                    campaign_config.update(data)
                    _apply_uploaded_campaign_config(data)
                    st.session_state["campaign_config_upload_digest"] = digest
                    st.success(f"Configuration imported from {config_upload.name}. Fields updated.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed to import config: {exc}")

        config_cols = st.columns(2)
        campaign_config["base_url"] = config_cols[0].text_input(
            "FastAPI base URL",
            key="campaign_config_base_url",
            help="Used for all API calls (e.g., http://localhost:8000).",
        ).strip()
        campaign_config["li_service_url"] = config_cols[1].text_input(
            "LinkedIn microservice URL",
            key="campaign_config_li_service_url",
            help="Used when checking the Playwright microservice health.",
        ).strip()

        admin_cols = st.columns(2)
        campaign_config["admin_email"] = admin_cols[0].text_input(
            "Admin email",
            key="campaign_config_admin_email",
        ).strip()
        campaign_config["admin_password"] = admin_cols[1].text_input(
            "Admin password",
            key="campaign_config_admin_password",
            type="password",
        )

        user_cols = st.columns(2)
        campaign_config["user_email"] = user_cols[0].text_input(
            "Outreach user email",
            key="campaign_config_user_email",
        ).strip()
        campaign_config["user_password"] = user_cols[1].text_input(
            "Outreach user password",
            key="campaign_config_user_password",
            type="password",
        )

        outreach_cols = st.columns(3)
        campaign_config["outreach_linkedin_email"] = outreach_cols[0].text_input(
            "LinkedIn seat email",
            key="campaign_config_outreach_linkedin_email",
        ).strip()
        campaign_config["outreach_linkedin_password"] = outreach_cols[1].text_input(
            "LinkedIn seat password",
            key="campaign_config_outreach_linkedin_password",
            type="password",
        )
        campaign_config["outreach_linkedin_url"] = outreach_cols[2].text_input(
            "LinkedIn profile URL",
            key="campaign_config_outreach_linkedin_url",
        ).strip()

        template_cols = st.columns(2)
        campaign_config["campaign_template_name"] = template_cols[0].text_input(
            "Campaign template name",
            key="campaign_config_campaign_template_name",
        ).strip()
        campaign_config["campaign_template_description"] = template_cols[1].text_input(
            "Campaign template description",
            key="campaign_config_campaign_template_description",
        ).strip()

        campaign_config["campaign_run_label"] = st.text_input(
            "Campaign run label (for logging)",
            key="campaign_config_campaign_run_label",
        ).strip()

        export_cols = st.columns(2)
        export_cols[0].download_button(
            "Download JSON template",
            data=CAMPAIGN_JSON_TEMPLATE,
            file_name="campaign_config.template.json",
            mime="application/json",
        )
        updated_payload = {
            **campaign_config,
            "steps": [
                {
                    "step_number": row.get("step_number") or idx + 1,
                    "action": row.get("action") or "send_connection",
                    "delay_seconds": row.get("delay_seconds") or 30,
                    "note": row.get("note") or "",
                    "message": row.get("message") or "",
                }
                for idx, row in enumerate(st.session_state["campaign_steps"])
            ],
        }
        export_cols[1].download_button(
            "Download current config",
            data=json.dumps(updated_payload, indent=2),
            file_name="campaign_config.current.json",
            mime="application/json",
        )

    with st.expander("2. Campaign steps", expanded=True):
        steps_df = pd.DataFrame(st.session_state["campaign_steps"])
        edited_steps = st.data_editor(
            steps_df,
            num_rows="dynamic",
            hide_index=True,
            column_order=["step_number", "action", "delay_seconds", "note", "message"],
            column_config={
                "step_number": st.column_config.NumberColumn("Step #", min_value=1, default=1),
                "action": st.column_config.SelectboxColumn(
                    "Action",
                    options=["send_connection", "send_message"],
                    required=True,
                ),
                "delay_seconds": st.column_config.NumberColumn("Delay (seconds)", min_value=5, default=30),
                "note": st.column_config.TextColumn("Connection note"),
                "message": st.column_config.TextColumn("Message template"),
            },
            key="campaign_steps_editor",
        )
        st.session_state["campaign_steps"] = edited_steps.to_dict("records")
        st.info("Add/remove steps via +/trash icons. Delay is expressed in seconds (converted to the API-friendly `Xs`).")

    with st.expander("3. Target CSV upload", expanded=True):
        csv_cols = st.columns(2)
        csv_cols[0].download_button(
            "Download target CSV template",
            data=TARGETS_CSV_TEMPLATE,
            file_name="campaign_targets.template.csv",
            mime="text/csv",
        )
        csv_cols[1].markdown(
            "Template columns: `url` (required) plus any personalization columns (e.g., `name`, `last_name`)."
        )
        targets_upload = st.file_uploader("Upload targets CSV", type="csv", key="campaign_targets_upload")
        if targets_upload is not None:
            try:
                targets, df = _parse_targets_csv(targets_upload)
                st.session_state["campaign_targets"] = targets
                st.session_state["campaign_targets_df"] = df
                st.session_state["campaign_targets_filename"] = targets_upload.name
                st.success(f"Loaded {len(targets)} targets from CSV.")
            except Exception as exc:
                st.error(f"Failed to process CSV: {exc}")

        preview_df: Optional[pd.DataFrame] = st.session_state.get("campaign_targets_df")
        if preview_df is not None:
            filename = st.session_state.get("campaign_targets_filename") or "uploaded_targets.csv"
            st.caption(f"Previewing {len(preview_df)} targets from `{filename}`")
            st.dataframe(preview_df, use_container_width=True)
        else:
            st.info("Upload a CSV to preview targets.")

    with st.expander("4. Orchestrate & run", expanded=True):
        st.markdown("Follow the numbered cards below. Each card unlocks once its prerequisites succeed.")
        tracker = campaign_state.setdefault("wizard_steps", {})
        for key in ["services", "tokens", "ghl_auth", "ghl_tokens", "outreach", "template", "launched"]:
            tracker.setdefault(key, False)
        campaign_state.setdefault("existing_outreach_profiles", [])
        campaign_state.setdefault("existing_outreach_error", None)

        if (
            campaign_config.get("gohighlevel_location_id")
            and not campaign_state.get("ghl_location_id")
        ):
            campaign_state["ghl_location_id"] = (
                campaign_config.get("gohighlevel_location_id") or None
            )

        if campaign_state.get("ghl_location_id"):
            tracker["ghl_tokens"] = True
        if campaign_state.get("outreach_profile_id"):
            tracker["outreach"] = True

        targets = st.session_state.get("campaign_targets")
        targets_ready = bool(targets)

        step_titles = {
            "services": "Step 1 · Validate environment",
            "tokens": "Step 2 · Provision admin & user tokens",
            "ghl_tokens": "Step 3 · Connect GoHighLevel",
            "outreach": "Step 4 · Register outreach seat",
            "template": "Step 5 · Create campaign template",
            "launched": "Step 6 · Launch campaign",
        }
        step_hints = {
            "services": "Run the health check so Streamlit can talk to FastAPI and the LinkedIn microservice.",
            "tokens": "Log in as admin, mint a registration key, and issue user tokens.",
            "ghl_tokens": "Generate the OAuth URL, approve it, then exchange the returned code.",
            "outreach": "Register the LinkedIn seat and (optionally) link it to GoHighLevel.",
            "template": "Send the current step definitions to the API.",
            "launched": "Send the uploaded targets to the scheduler.",
        }

        step_statuses = {
            "services": _resolve_step_status(tracker, "services"),
            "tokens": _resolve_step_status(tracker, "tokens", dependencies=["services"]),
            "ghl_tokens": _resolve_step_status(tracker, "ghl_tokens", dependencies=["tokens"]),
            "outreach": _resolve_step_status(tracker, "outreach", dependencies=["tokens"]),
            "template": _resolve_step_status(tracker, "template", dependencies=["tokens", "outreach"]),
            "launched": _resolve_step_status(
                tracker,
                "launched",
                dependencies=["template", "outreach"],
                ready=targets_ready,
            ),
        }
        ordered_keys = ["services", "tokens", "ghl_tokens", "outreach", "template", "launched"]
        next_step_key = next((key for key in ordered_keys if step_statuses[key] == "ready"), None)
        if next_step_key:
            st.info(f"Next action: {step_titles[next_step_key]} — {step_hints[next_step_key]}")
        elif not targets_ready and tracker.get("template"):
            st.warning("Upload a target CSV in section 3 above to unlock the launch button.")
        else:
            st.success("All orchestration steps are complete. Re-run any card to refresh state.")

        # STEP 1
        with st.container(border=True):
            _render_step_header(
                "1️⃣ Validate environment",
                "Checks FastAPI and the LinkedIn microservice from inside this container.",
                step_statuses["services"],
            )
            if st.button("Run health check", key="btn_step1", use_container_width=True):
                try:
                    results = data_access.check_services(
                        campaign_config["base_url"],
                        campaign_config["li_service_url"],
                    )
                    campaign_state["services"] = results
                    ok = results["web"]["ok"] and results["linkedin_service"]["ok"]
                    tracker["services"] = ok
                    status_msg = (
                        f"Web API: {results['web']['detail']} | LinkedIn service: {results['linkedin_service']['detail']}"
                    )
                    _append_campaign_log("info", status_msg)
                    if ok:
                        st.toast(status_msg, icon="✅")
                        _force_wizard_rerun()
                    else:
                        st.error(status_msg)
                except Exception as exc:
                    tracker["services"] = False
                    _append_campaign_log("error", f"Service check failed: {exc}")
                    st.error(f"Service check failed: {exc}")
            if tracker.get("services"):
                st.caption("✅ Step 1 complete. Re-run if infrastructure changes.")
            else:
                st.caption("Click the button above to verify connectivity.")

        # STEP 2
        with st.container(border=True):
            _render_step_header(
                "2️⃣ Provision admin & user tokens",
                "Logs in as admin to mint a registration key, registers the outreach user, then grabs user tokens.",
                step_statuses["tokens"],
            )
            if step_statuses["tokens"] == "blocked":
                st.warning("Finish Step 1 first.")
            if st.button(
                "Provision tokens",
                key="btn_step2",
                disabled=step_statuses["tokens"] == "blocked",
                use_container_width=True,
            ):
                try:
                    admin_tokens = data_access.admin_login(
                        campaign_config["base_url"],
                        campaign_config["admin_email"],
                        campaign_config["admin_password"],
                    )
                    campaign_state["admin_token"] = admin_tokens.get("access_token")
                    registration_key = data_access.create_registration_key(
                        campaign_config["base_url"],
                        campaign_state["admin_token"],
                    )
                    campaign_state["registration_key"] = registration_key
                    reg_result = data_access.register_user(
                        campaign_config["base_url"],
                        campaign_config["user_email"],
                        campaign_config["user_password"],
                        registration_key,
                    )
                    user_tokens = data_access.user_login(
                        campaign_config["base_url"],
                        campaign_config["user_email"],
                        campaign_config["user_password"],
                    )
                    campaign_state["user_token"] = user_tokens.get("access_token")
                    tracker["tokens"] = True
                    _append_campaign_log(
                        "success",
                        f"User tokens ready (registration status: {reg_result.get('status')}).",
                    )
                    st.toast("Admin + user tokens ready.", icon="✅")
                    _force_wizard_rerun()
                except Exception as exc:
                    tracker["tokens"] = False
                    _append_campaign_log("error", f"Provisioning failed: {exc}")
                    st.error(f"Provisioning failed: {exc}")
            if tracker.get("tokens"):
                st.caption("✅ Step 2 complete. You can re-run to rotate tokens.")

        # STEP 3
        with st.container(border=True):
            _render_step_header(
                "3️⃣ GoHighLevel OAuth",
                "Request the OAuth link, approve it in a browser, then paste the returned `code` here.",
                step_statuses["ghl_tokens"],
            )
            if step_statuses["ghl_tokens"] == "blocked":
                st.warning("Complete Step 2 to unlock GoHighLevel.")

            auto_load_ready = tracker.get("tokens") and campaign_state.get("user_token")
            if auto_load_ready and not campaign_state.get("ghl_accounts_loaded"):
                try:
                    accounts = data_access.list_ghl_accounts(
                        campaign_config["base_url"],
                        campaign_state["user_token"],
                    )
                    campaign_state["ghl_accounts"] = accounts
                    campaign_state["ghl_accounts_loaded"] = True
                    campaign_state["ghl_accounts_error"] = None
                    if len(accounts) == 1 and not campaign_state.get("ghl_account_id"):
                        campaign_state["ghl_account_id"] = accounts[0].get("id")
                        tracker["ghl_tokens"] = True
                        st.toast(
                            f"Detected GoHighLevel account {campaign_state['ghl_account_id']}.",
                            icon="✅",
                        )
                        _force_wizard_rerun()
                except Exception as exc:
                    campaign_state["ghl_accounts_error"] = str(exc)
                    campaign_state["ghl_accounts_loaded"] = True

            if campaign_state.get("ghl_account_id"):
                st.info(
                    f"Using GoHighLevel account ID {campaign_state['ghl_account_id']}. "
                    "You can refresh/select another account or run OAuth again if needed."
                )
            if campaign_state.get("ghl_accounts_error"):
                st.warning(
                    f"Unable to auto-load GoHighLevel accounts: {campaign_state['ghl_accounts_error']}"
                )

            request_col, exchange_col = st.columns(2)
            with request_col:
                if st.button(
                    "Request authorization URL",
                    key="btn_request_ghl",
                    disabled=step_statuses["ghl_tokens"] == "blocked",
                    use_container_width=True,
                ):
                    try:
                        auth_info = data_access.build_ghl_auth_url(
                            campaign_config["base_url"],
                            campaign_state["user_token"],
                        )
                        campaign_state["ghl_authorization_url"] = auth_info.get("authorization_url")
                        campaign_state["ghl_client_state"] = auth_info.get("state") or auth_info.get("client_state")
                        tracker["ghl_auth"] = True
                        _append_campaign_log("info", "GoHighLevel authorization URL generated.")
                        st.success("Authorization URL ready. Open it, approve access, then paste the code on the right.")
                    except Exception as exc:
                        _append_campaign_log("error", f"GHL auth URL failed: {exc}")
                        st.error(f"Failed to request authorization URL: {exc}")
                if campaign_state.get("ghl_authorization_url"):
                    st.link_button(
                        "Open GoHighLevel authorization",
                        campaign_state["ghl_authorization_url"],
                        use_container_width=True,
                    )
                    st.caption("Complete the OAuth prompt, then copy the `code` query parameter from the redirect URL.")
            with exchange_col:
                campaign_state["ghl_manual_code"] = st.text_input(
                    "Authorization code",
                    value=campaign_state.get("ghl_manual_code", ""),
                    help="Paste the `code` value from the GoHighLevel redirect URL.",
                ).strip()
                exchange_disabled = step_statuses["ghl_tokens"] == "blocked" or not campaign_state.get("ghl_manual_code")
                if st.button(
                    "Exchange auth code",
                    key="btn_exchange_ghl",
                    disabled=exchange_disabled,
                    use_container_width=True,
                ):
                    try:
                        result = data_access.exchange_ghl_code(
                            campaign_config["base_url"],
                            campaign_state["user_token"],
                            campaign_state.get("ghl_manual_code"),
                            client_state=campaign_state.get("ghl_client_state"),
                        )
                        campaign_state["ghl_account_id"] = result.get("account_id")
                        tracker["ghl_tokens"] = True
                        _append_campaign_log("success", f"GoHighLevel account linked (id={campaign_state['ghl_account_id']}).")
                        st.toast("GoHighLevel tokens stored.", icon="✅")
                        _force_wizard_rerun()
                    except Exception as exc:
                        tracker["ghl_tokens"] = False
                        _append_campaign_log("error", f"GHL code exchange failed: {exc}")
                        st.error(f"Failed to exchange code: {exc}")

            st.markdown("##### Linked account selection")
            if st.button("Refresh GoHighLevel accounts", key="btn_refresh_ghl_accounts", use_container_width=True):
                try:
                    accounts = data_access.list_ghl_accounts(
                        campaign_config["base_url"],
                        campaign_state.get("user_token"),
                    )
                    campaign_state["ghl_accounts"] = accounts
                    campaign_state["ghl_accounts_loaded"] = True
                    campaign_state["ghl_accounts_error"] = None
                    st.success(f"Loaded {len(accounts)} account(s).")
                except Exception as exc:
                    campaign_state["ghl_accounts_error"] = str(exc)
                    st.error(f"Unable to list accounts: {exc}")

            gh_accounts = campaign_state.get("ghl_accounts") or []
            if gh_accounts:
                options = {
                    f"{acct.get('display_name') or acct.get('location_id')} (id={acct.get('id')})": acct.get("id")
                    for acct in gh_accounts
                }
                index = 0
                if campaign_state.get("ghl_account_id") in options.values():
                    index = list(options.values()).index(campaign_state["ghl_account_id"])
                selected_label = st.selectbox(
                    "Pick a GoHighLevel account for this campaign",
                    list(options.keys()),
                    index=index,
                )
                campaign_state["ghl_account_id"] = options[selected_label]
                tracker["ghl_tokens"] = True
            manual_account_input = st.text_input(
                "Override GoHighLevel location ID (optional)",
                value=str(campaign_state.get("ghl_location_id") or campaign_config.get("gohighlevel_location_id") or ""),
            ).strip()
            if manual_account_input:
                try:
                    campaign_state["ghl_location_id"] = manual_account_input
                    tracker["ghl_tokens"] = True
                except ValueError:
                    st.warning("GoHighLevel location ID must be a string.", icon="⚠️")
            if campaign_state.get("ghl_location_id"):
                st.info(f"Using GoHighLevel location ID {campaign_state['ghl_location_id']}")

        # STEP 4
        with st.container(border=True):
            _render_step_header(
                "4️⃣ Register outreach seat",
                "Registers the LinkedIn seat (and associates the chosen GoHighLevel account).",
                step_statuses["outreach"],
            )
            if step_statuses["outreach"] == "blocked":
                st.warning("Complete Steps 1-2 first.")

            existing_profiles = campaign_state.get("existing_outreach_profiles") or []
            existing_error = campaign_state.get("existing_outreach_error")
            can_fetch_existing = tracker.get("tokens") and campaign_state.get("user_token")
            load_cols = st.columns(2)
            if load_cols[0].button(
                "Load existing outreach seats",
                key="btn_load_outreach",
                disabled=not can_fetch_existing,
                use_container_width=True,
            ):
                if not can_fetch_existing:
                    st.warning("Provision user tokens first.")
                else:
                    try:
                        profiles = data_access.list_registered_outreach_profiles(
                            campaign_config["base_url"],
                            campaign_state["user_token"],
                        )
                        campaign_state["existing_outreach_profiles"] = profiles
                        campaign_state["existing_outreach_error"] = None
                        st.success(f"Loaded {len(profiles)} outreach seat(s).")
                    except Exception as exc:
                        campaign_state["existing_outreach_error"] = str(exc)
                        st.error(f"Unable to load outreach seats: {exc}")
            if existing_error:
                st.error(existing_error)

            if existing_profiles:
                options = {
                    f"{profile['linkedin_email']} (id={profile['id']})": profile
                    for profile in existing_profiles
                }
                option_labels = ["Select a seat"] + list(options.keys())
                selected_label = st.selectbox(
                    "Use existing outreach seat",
                    option_labels,
                    key="existing_outreach_select",
                )
                can_use_existing = selected_label != "Select a seat"
                if st.button(
                    "Use selected seat",
                    key="btn_use_existing_outreach",
                    disabled=not can_use_existing,
                    use_container_width=True,
                ):
                    selected_profile = options[selected_label]
                    campaign_state["outreach_profile_id"] = int(selected_profile["id"])
                    tracker["outreach"] = True
                    gh_id = selected_profile.get("gohighlevel_location_id")
                    if gh_id:
                        campaign_state["ghl_location_id"] = gh_id
                        tracker["ghl_tokens"] = True
                    st.toast(
                        f"Using outreach profile ID {campaign_state['outreach_profile_id']}.",
                        icon="✅",
                    )
                    _force_wizard_rerun()

            manual_outreach_input = st.text_input(
                "Manual outreach profile ID (optional)",
                value=str(campaign_state.get("outreach_profile_id") or ""),
                key="manual_outreach_id",
            ).strip()
            if manual_outreach_input:
                try:
                    campaign_state["outreach_profile_id"] = int(manual_outreach_input)
                    tracker["outreach"] = True
                except ValueError:
                    st.warning("Outreach profile ID must be a number.", icon="⚠️")

            if campaign_state.get("outreach_profile_id"):
                info_msg = f"Using outreach profile ID {campaign_state['outreach_profile_id']}"
                if campaign_state.get("ghl_account_id"):
                    info_msg += f" (GoHighLevel ID {campaign_state['ghl_account_id']})"
                st.info(info_msg)

            st.markdown("##### Register new seat")
            if st.button(
                "Register LinkedIn outreach seat",
                key="btn_register_outreach",
                disabled=step_statuses["outreach"] == "blocked",
                use_container_width=True,
            ):
                required_fields = [
                    campaign_config.get("outreach_linkedin_email"),
                    campaign_config.get("outreach_linkedin_password"),
                    campaign_config.get("outreach_linkedin_url"),
                ]
                if not all(required_fields):
                    st.warning("Fill in LinkedIn seat email/password/profile URL first.")
                else:
                    payload = {
                        "linkedin_email": campaign_config["outreach_linkedin_email"],
                        "linkedin_password": campaign_config["outreach_linkedin_password"],
                        "linkedin_url": campaign_config["outreach_linkedin_url"],
                    }
                    account_id = campaign_state.get("ghl_account_id")
                    if account_id:
                        payload["gohighlevel_account_id"] = account_id
                    try:
                        result = data_access.register_outreach_profile(
                            campaign_config["base_url"],
                            campaign_state["user_token"],
                            payload,
                        )
                        outreach_data = result.get("data") or {}
                        campaign_state["outreach_profile_id"] = outreach_data.get("id")
                        tracker["outreach"] = True
                        _append_campaign_log(
                            "success",
                            f"Outreach profile ready (id={campaign_state['outreach_profile_id']}).",
                        )
                        st.toast(
                            f"Outreach profile ID {campaign_state['outreach_profile_id']} ready.",
                            icon="✅",
                        )
                        _force_wizard_rerun()
                    except Exception as exc:
                        tracker["outreach"] = False
                        _append_campaign_log("error", f"Outreach registration failed: {exc}")
                        st.error(f"Failed to register outreach seat: {exc}")

        # STEP 5
        with st.container(border=True):
            _render_step_header(
                "5️⃣ Create or update campaign template",
                "Pushes the current step editor payload to FastAPI.",
                step_statuses["template"],
            )
            if step_statuses["template"] == "blocked":
                st.warning("Complete Steps 2 and 4 first.")
            if st.button(
                "Create / update template",
                key="btn_create_template",
                disabled=step_statuses["template"] == "blocked",
                use_container_width=True,
            ):
                steps_payload = _build_steps_payload(st.session_state["campaign_steps"])
                if not steps_payload:
                    st.warning("Add at least one campaign step.")
                else:
                    template_payload = {
                        "name": campaign_config.get("campaign_template_name") or "Streamlit Campaign",
                        "description": campaign_config.get("campaign_template_description") or "",
                        "steps": steps_payload,
                    }
                    try:
                        template_resp = data_access.create_campaign_template(
                            campaign_config["base_url"],
                            campaign_state["user_token"],
                            template_payload,
                        )
                        campaign_state["campaign_template_id"] = template_resp.get("id")
                        tracker["template"] = True
                        _append_campaign_log(
                            "success",
                            f"Campaign template ready (id={campaign_state['campaign_template_id']}).",
                        )
                        st.toast(
                            f"Template saved (id={campaign_state['campaign_template_id']}).",
                            icon="✅",
                        )
                        _force_wizard_rerun()
                    except Exception as exc:
                        tracker["template"] = False
                        _append_campaign_log("error", f"Template creation failed: {exc}")
                        st.error(f"Failed to create template: {exc}")

        # STEP 6
        with st.container(border=True):
            _render_step_header(
                "6️⃣ Launch campaign",
                "Schedules the uploaded targets using the template + outreach seat selected above.",
                step_statuses["launched"],
            )
            info_cols = st.columns(3)
            info_cols[0].metric("Targets loaded", len(targets) if targets else 0)
            info_cols[1].metric("Template ID", campaign_state.get("campaign_template_id") or "—")
            info_cols[2].metric("Outreach ID", campaign_state.get("outreach_profile_id") or "—")
            if not targets_ready:
                st.warning("Upload targets in section 3 before launching.")
            launch_disabled = step_statuses["launched"] == "blocked"
            if st.button("Run campaign", key="btn_run_campaign", disabled=launch_disabled, use_container_width=True):
                if not targets:
                    st.error("No targets loaded.")
                else:
                    template_id = campaign_state.get("campaign_template_id")
                    outreach_id = campaign_state.get("outreach_profile_id")
                    try:
                        payload = {
                            "campaign_template_id": int(template_id),
                            "outreach_profile_id": int(outreach_id),
                            "target_profiles": targets,
                        }
                    except (TypeError, ValueError):
                        st.error("Template ID and outreach profile ID must be numbers.")
                    else:
                        try:
                            result = data_access.run_campaign(
                                campaign_config["base_url"],
                                campaign_state["user_token"],
                                payload,
                            )
                            tracker["launched"] = True
                            _append_campaign_log("success", f"Campaign launched: {result.get('message')}")
                            st.toast("Campaign launch enqueued.", icon="✅")
                            st.session_state["campaign_last_launch_result"] = result
                            _force_wizard_rerun()
                        except Exception as exc:
                            tracker["launched"] = False
                            _append_campaign_log("error", f"Campaign launch failed: {exc}")
                            st.error(f"Failed to run campaign: {exc}")

        state_cols = st.columns([3, 1])
        state_cols[0].markdown("##### Runtime state")
        state_cols[0].json({k: v for k, v in campaign_state.items() if v})
        last_launch = st.session_state.get("campaign_last_launch_result")
        if last_launch:
            state_cols[0].markdown("##### Last launch response")
            state_cols[0].json(last_launch)
        if state_cols[1].button("Reset runtime state"):
            _reset_campaign_flow()
            st.success("Campaign runtime state cleared. Re-run steps as needed.")

        st.markdown("##### Activity log")
        logs = st.session_state.get("campaign_logs", [])
        if logs:
            for entry in reversed(logs[-50:]):
                st.write(f"{entry['timestamp']} · {entry['level'].upper()} · {entry['message']}")
        else:
            st.info("No activity yet. Run a step to see log output.")

