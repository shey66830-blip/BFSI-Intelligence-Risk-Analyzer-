"""
Context Guard — Investigation Updates & Notifications

Two related but distinct things:

* **Investigation updates** belong to a case. They are the running record of what
  changed — a report submitted, a bank response filed, a risk score moved. They are
  structured, not a chat channel.
* **Notifications** belong to one user. They are the nudge: "a report is waiting for
  you". Reading a notification does not acknowledge the underlying update.

Both are written from the same place so a case event can never notify without also
leaving a record on the case.
"""

import uuid
from datetime import datetime

UPDATE_TYPES = {
    "analyst_report": {"label": "New analyst report", "audience": ["compliance", "admin"]},
    "analyst_report_revised": {"label": "Analyst report amended", "audience": ["compliance", "admin"]},
    "finding": {"label": "New finding", "audience": ["compliance", "admin"]},
    "transaction_identified": {"label": "New transaction identified", "audience": ["compliance", "admin"]},
    "graph_relationship": {"label": "New graph relationship", "audience": ["compliance", "admin"]},
    "bank_report": {"label": "New bank report", "audience": ["compliance", "admin", "analyst"]},
    "evidence_added": {"label": "Evidence added", "audience": ["compliance", "admin"]},
    "risk_change": {"label": "Risk score changed", "audience": ["compliance", "admin"]},
    "status_change": {"label": "Investigation status changed", "audience": ["compliance", "admin", "analyst"]},
    "compliance_note": {"label": "Compliance note", "audience": ["analyst", "admin"]},
    "clarification": {"label": "Clarification requested", "audience": ["analyst"]},
    "access_request": {"label": "Access request created", "audience": ["admin"]},
    "access_decision": {"label": "Access request decided", "audience": ["compliance"]},
    "restricted_released": {"label": "Restricted information released", "audience": ["compliance", "admin"]},
}


def _now():
    return datetime.utcnow().isoformat()


# ── Investigation updates ────────────────────────────────────────────────────

def post(db, case, user, update_type, title, description, metadata=None,
         notify=True, system=False):
    """Record an update on a case and notify the roles that care about it."""
    spec = UPDATE_TYPES.get(update_type, {"label": update_type, "audience": ["compliance", "admin"]})

    update = {
        "id": f"UPD-{uuid.uuid4().hex[:8].upper()}",
        "case_id": case["id"],
        "case_title": case.get("title"),
        "type": update_type,
        "type_label": spec["label"],
        "title": title,
        "description": description,
        "metadata": metadata or {},
        "submitted_by": None if system else (user or {}).get("id"),
        "submitted_by_name": "Context Guard" if system else (user or {}).get("name"),
        "submitted_by_role": "system" if system else (user or {}).get("role"),
        "created_at": _now(),
        "acknowledged_by": None,
        "acknowledged_by_name": None,
        "acknowledged_at": None,
        "acknowledgement_note": None,
    }
    db.investigation_updates.insert_one(update)

    if notify:
        # Never notify the person who caused the event about their own action.
        audience = [role for role in spec["audience"] if role != (user or {}).get("role")]
        notify_roles(
            db, audience,
            notification_type=update_type,
            title=f"{spec['label']} — {case.get('title') or case['id']}",
            body=description,
            case_id=case["id"],
            link=f"case:{case['id']}",
            severity="high" if update_type in ("analyst_report", "access_request") else "normal",
        )

    update.pop("_id", None)
    return update


def list_updates(db, case_ids=None, acknowledged=None, limit=100):
    q = {}
    if case_ids is not None:
        q["case_id"] = {"$in": list(case_ids)}
    if acknowledged is True:
        q["acknowledged_at"] = {"$ne": None}
    if acknowledged is False:
        q["acknowledged_at"] = None
    for item in db.investigation_updates.find(q).sort("created_at", -1).limit(limit):
        pass
    return list(db.investigation_updates.find(q).sort("created_at", -1).limit(limit))


def acknowledge(db, update, user, note=None):
    db.investigation_updates.update_one({"id": update["id"]}, {"$set": {
        "acknowledged_by": user["id"],
        "acknowledged_by_name": user["name"],
        "acknowledged_at": _now(),
        "acknowledgement_note": note,
    }})
    return db.investigation_updates.find_one({"id": update["id"]})


def unacknowledged_count(db, case_ids=None):
    return db.investigation_updates.count_documents(_case_filter(case_ids, {"acknowledged_at": None}))


def _case_filter(case_ids, extra):
    if case_ids is None:
        return dict(extra)
    return {**extra, "case_id": {"$in": list(case_ids)}}


# ── Notifications ────────────────────────────────────────────────────────────

def notify_user(db, user_id, notification_type, title, body, case_id=None, link=None,
                severity="normal"):
    doc = {
        "id": f"NTF-{uuid.uuid4().hex[:8].upper()}",
        "user_id": user_id,
        "type": notification_type,
        "title": title,
        "body": body,
        "case_id": case_id,
        "link": link,
        "severity": severity,
        "created_at": _now(),
        "read_at": None,
    }
    db.notifications.insert_one(doc)
    return doc


def notify_roles(db, roles, notification_type, title, body, case_id=None, link=None,
                 severity="normal"):
    """Notify every active user holding one of these roles."""
    if not roles:
        return []
    recipients = db.users.find({"role": {"$in": list(roles)}, "status": "active"},
                               {"id": 1, "assigned_case_ids": 1, "role": 1})
    sent = []
    for recipient in recipients:
        # An analyst is only told about cases they actually hold.
        if recipient.get("role") == "analyst" and case_id:
            if case_id not in (recipient.get("assigned_case_ids") or []):
                continue
        sent.append(notify_user(db, recipient["id"], notification_type, title, body,
                                case_id=case_id, link=link, severity=severity))
    return sent


def _notification_filter(user_id, unread_only=False):
    q = {"user_id": user_id}
    if unread_only:
        q["read_at"] = None
    return q


def list_notifications(db, user_id, unread_only=False, limit=50, offset=0):
    cursor = (db.notifications.find(_notification_filter(user_id, unread_only))
              .sort("created_at", -1).skip(max(0, offset or 0)).limit(limit))
    for doc in cursor:
        doc.pop("_id", None)
        yield doc


def all_notifications(db, user_id, unread_only=False, limit=50, offset=0):
    return list(list_notifications(db, user_id, unread_only, limit, offset))


def notification_count(db, user_id, unread_only=False):
    """How many notifications this identity has, so a page can say what it is a page of."""
    return db.notifications.count_documents(_notification_filter(user_id, unread_only))


def unread_count(db, user_id):
    return db.notifications.count_documents({"user_id": user_id, "read_at": None})


def mark_read(db, notification_id, user_id):
    db.notifications.update_one(
        {"id": notification_id, "user_id": user_id},
        {"$set": {"read_at": _now()}},
    )
    return db.notifications.find_one({"id": notification_id, "user_id": user_id})


def mark_all_read(db, user_id):
    result = db.notifications.update_many(
        {"user_id": user_id, "read_at": None},
        {"$set": {"read_at": _now()}},
    )
    return result.modified_count
