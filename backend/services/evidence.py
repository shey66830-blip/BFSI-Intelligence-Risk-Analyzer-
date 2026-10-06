"""
Context Guard — Case Evidence Vault

Every case carries its own evidence area, organised into folders. Evidence is
append-only in spirit: an item is never silently overwritten. Correcting something
files a new version and marks the previous one `superseded`, so the history of what
was known, and when, survives.

Access levels
-------------
    case              visible to anyone who can see the case
    compliance_only   visible to compliance officers and administrators
    restricted        listed as a locked placeholder unless an active authorisation
                      covers this case and the requester
"""

import uuid
from datetime import datetime

FOLDERS = [
    ("analyst_reports", "Analyst Reports", "Submitted analyst investigation reports."),
    ("bank_reports", "Bank Reports", "Structured responses returned by the banks."),
    ("transaction_evidence", "Transaction Evidence", "Specific transactions marked as relevant."),
    ("behavioral_graph", "Behavioural Graph Evidence", "Baseline and deviation snapshots."),
    ("network_evidence", "Network Evidence", "Relationships between accounts, devices and beneficiaries."),
    ("timeline", "Timeline", "Reconstructed sequence of events for the case."),
    ("compliance_notes", "Compliance Notes", "Review notes recorded by the compliance officer."),
    ("supporting_documents", "Supporting Documents", "Invoices, claims and other documents."),
    ("restricted_information", "Restricted Information", "Subject information released under an authorisation."),
]

FOLDER_KEYS = [key for key, _, _ in FOLDERS]

EVIDENCE_TYPES = [
    "transaction", "bank_response", "graph_snapshot", "analyst_report", "compliance_note",
    "risk_signal", "document", "correspondence", "subject_information", "external_reference",
    "timeline_entry",
]

ACCESS_LEVELS = ("case", "compliance_only", "restricted")

STATUSES = ("active", "superseded", "withdrawn")

# Where a record came from. Provenance answers the question a reviewer asks second —
# after "what does this say" — which is "how do you know, and who put it there".
PROVENANCE_ORIGINS = {
    "analyst_entry": "filed by an investigation analyst",
    "compliance_entry": "filed by a compliance officer",
    "administrator_entry": "filed by an organisation administrator",
    "bank_response": "returned by a bank",
    "bank_release": "released by a bank under an authorisation",
    "pipeline": "produced by the investigation pipeline",
    "baseline": "restated from records already held on the case",
    "automatic": "filed automatically by the platform",
}


def _now():
    return datetime.utcnow().isoformat()


def _default_origin(user):
    return {
        "analyst": "analyst_entry",
        "compliance": "compliance_entry",
        "admin": "administrator_entry",
    }.get((user or {}).get("role"), "automatic")


def provenance_block(origin, actor, source=None, **refs):
    """The chain a record carries: where it came from, who filed it, what it points back to.

    Provenance is recorded at creation and never rewritten. A correction does not edit
    it — it files a new item that names what it supersedes, so the custody history
    survives the correction.
    """
    at = _now()
    person = {
        "id": (actor or {}).get("id"),
        "name": (actor or {}).get("name") or "System",
        "role": (actor or {}).get("role") or "system",
    }
    return {
        "origin": origin,
        "origin_label": PROVENANCE_ORIGINS.get(origin, origin),
        "source": source,
        "filed_by": person,
        "filed_at": at,
        "case_id": refs.get("case_id"),
        "request_id": refs.get("request_id"),
        "authorization_id": refs.get("authorization_id"),
        "related_report_id": refs.get("related_report_id"),
        "related_transaction_id": refs.get("related_transaction_id"),
        "chain": [{
            "step": "filed", "at": at, "actor": person["name"],
            "detail": f"Filed as {PROVENANCE_ORIGINS.get(origin, origin)}",
        }],
    }


def append_custody(db, item, step, actor, detail):
    """Add a step to an item's custody chain (a supersede, a reorganisation, a release)."""
    entry = {
        "step": step, "at": _now(),
        "actor": (actor or {}).get("name") or "System",
        "detail": detail,
    }
    db.case_evidence.update_one({"id": item["id"]}, {"$push": {"provenance.chain": entry}})
    return entry


def lineage(db, item):
    """Everything a reviewer needs to trace an item back to its source.

    Returns the provenance the item was filed with, the version links either side of
    it, and the stored records it points at — resolved, so a broken reference is
    visible rather than implied.
    """
    provenance = item.get("provenance") or provenance_block(
        "automatic", {"name": "Context Guard", "role": "system"},
        source=item.get("source"), case_id=item.get("case_id"))

    links = []
    for relation, field, collection in (
        ("related_transaction", "related_transaction_id", "transactions"),
        ("related_entity", "related_entity_id", "entities"),
        ("related_report", "related_report_id", "bank_reports"),
        ("related_evidence", "related_evidence_id", "case_evidence"),
        ("supersedes", "supersedes", "case_evidence"),
        ("superseded_by", "superseded_by", "case_evidence"),
    ):
        reference = item.get(field)
        if not reference:
            continue
        # Records are keyed differently by collection: transactions and evidence carry
        # `id`, while a bank report is keyed by the `request_id` that produced it.
        target = db[collection].find_one(
            {"$or": [{"id": reference}, {"request_id": reference}]},
            {"title": 1, "description": 1, "status": 1, "version": 1,
             "responding_bank_name": 1},
        )
        links.append({
            "relation": relation, "id": reference, "exists": target is not None,
            "title": ((target or {}).get("title") or (target or {}).get("description")
                      or (target or {}).get("responding_bank_name")),
            "status": (target or {}).get("status"),
            "version": (target or {}).get("version"),
        })

    return {
        "evidence_id": item["id"],
        "case_id": item.get("case_id"),
        "title": item.get("title"),
        "folder": item.get("folder"),
        "type": item.get("type"),
        "status": item.get("status"),
        "version": item.get("version"),
        "access_level": item.get("access_level"),
        "provenance": provenance,
        "links": links,
        "custody": provenance.get("chain", []),
    }


def _evidence_id():
    return f"EVD-{datetime.utcnow().strftime('%Y')}-{uuid.uuid4().hex[:6].upper()}"


# ── Storage ──────────────────────────────────────────────────────────────────

def add(db, case, user, payload, access_level=None, origin=None, refs=None):
    """File a new evidence item. Returns (item, error)."""
    folder = payload.get("folder") or "supporting_documents"
    if folder not in FOLDER_KEYS:
        return None, f"Unknown evidence folder: {folder}"

    level = access_level or payload.get("access_level") or "case"
    if level not in ACCESS_LEVELS:
        return None, f"Unknown access level: {level}"

    title = (payload.get("title") or "").strip()
    if not title:
        return None, "Evidence needs a title"

    item = {
        "id": _evidence_id(),
        "case_id": case["id"],
        "folder": folder,
        "type": payload.get("type") or "document",
        "title": title,
        "description": (payload.get("description") or "").strip(),
        "source": payload.get("source") or "analyst entry",
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_by_role": user["role"],
        "created_at": _now(),
        "related_transaction_id": payload.get("related_transaction_id"),
        "related_entity_id": payload.get("related_entity_id"),
        "related_report_id": payload.get("related_report_id"),
        "related_evidence_id": payload.get("related_evidence_id"),
        "status": "active",
        "version": 1,
        "supersedes": None,
        "access_level": level,
        "tags": payload.get("tags") or [],
        "payload": payload.get("payload") or {},
        "immutable": True,
        "provenance": payload.get("provenance") or provenance_block(
            origin or _default_origin(user), user,
            source=payload.get("source"),
            **{
                "case_id": case.get("id"),
                "request_id": payload.get("request_id"),
                "authorization_id": payload.get("authorization_id"),
                "related_report_id": payload.get("related_report_id"),
                "related_transaction_id": payload.get("related_transaction_id"),
                **(refs or {}),
            },
        ),
    }
    db.case_evidence.insert_one(item)
    return item, None


def get(db, evidence_id):
    return db.case_evidence.find_one({"id": evidence_id})


def list_items(db, case_id, include_compliance=True, include_restricted=False):
    """Evidence for a case, filtered by what the caller may see."""
    items = list(db.case_evidence.find({"case_id": case_id}).sort("created_at", -1))
    out = []
    for item in items:
        level = item.get("access_level", "case")
        if level == "compliance_only" and not include_compliance:
            continue
        if level == "restricted" and not include_restricted:
            # A locked placeholder: the existence and title are visible, the content is not.
            placeholder = {
                "id": item["id"],
                "case_id": item["case_id"],
                "folder": item["folder"],
                "type": item["type"],
                "title": item["title"],
                "description": item.get("description"),
                "source": item.get("source"),
                "created_by_name": item.get("created_by_name"),
                "created_at": item.get("created_at"),
                "status": item.get("status"),
                "version": item.get("version"),
                "access_level": "restricted",
                "locked": True,
                "redacted": ["payload", "created_by", "tags", "related_*"],
            }
            out.append(placeholder)
            continue
        item.pop("_id", None)
        item["locked"] = False
        out.append(item)
    return out


def supersede(db, item, user, payload):
    """File a corrected version and mark the previous one superseded."""
    if item.get("status") != "active":
        return None, f"This item is already {item.get('status')}"
    if item.get("access_level") == "restricted" and user.get("role") == "analyst":
        return None, "Restricted evidence cannot be versioned by an analyst"

    replacement, error = add(db, {"id": item["case_id"]}, user, {
        **{k: v for k, v in item.items() if k in (
            "folder", "type", "title", "description", "source", "related_transaction_id",
            "related_entity_id", "related_report_id", "tags", "access_level")},
        **payload,
    }, access_level=payload.get("access_level") or item.get("access_level"))
    if error:
        return None, error

    db.case_evidence.update_one(
        {"id": replacement["id"], "version": 1},
        {"$set": {"version": item.get("version", 1) + 1, "supersedes": item["id"],
                  "supersedes_version": item.get("version", 1)}},
    )
    db.case_evidence.update_one({"id": item["id"]}, {"$set": {
        "status": "superseded", "superseded_by": replacement["id"], "superseded_at": _now(),
    }})
    # Both ends of the correction are recorded, so the custody chain shows the edit as
    # an event rather than the previous version silently disappearing.
    append_custody(db, item, "superseded", user,
                   f"Superseded by {replacement['id']} (v{replacement.get('version')})")
    append_custody(db, replacement, "supersedes", user,
                   f"Files a corrected version of {item['id']} (v{item.get('version')})")
    return get(db, replacement["id"]), None


def update_metadata(db, item, user, payload):
    """Organise an item (folder, status, access level). Content stays immutable."""
    updates = {}
    if payload.get("folder"):
        if payload["folder"] not in FOLDER_KEYS:
            return None, f"Unknown evidence folder: {payload['folder']}"
        updates["folder"] = payload["folder"]
    if payload.get("access_level"):
        if payload["access_level"] not in ACCESS_LEVELS:
            return None, f"Unknown access level: {payload['access_level']}"
        updates["access_level"] = payload["access_level"]
    if payload.get("status"):
        if payload["status"] not in STATUSES:
            return None, f"Unknown status: {payload['status']}"
        updates["status"] = payload["status"]
    if payload.get("tags") is not None:
        updates["tags"] = list(payload["tags"])
    if payload.get("description") is not None:
        updates["description"] = str(payload["description"]).strip()

    if not updates:
        return get(db, item["id"]), None

    updates["updated_at"] = _now()
    updates["updated_by"] = user["id"]
    updates["updated_by_name"] = user["name"]
    db.case_evidence.update_one({"id": item["id"]}, {"$set": updates})
    append_custody(db, item, "organised", user,
                   "Reorganised: " + ", ".join(f"{k}={v}" for k, v in updates.items()
                                                if k not in ("updated_at", "updated_by",
                                                             "updated_by_name")))
    return get(db, item["id"]), None


# ── Vault summary ────────────────────────────────────────────────────────────

def vault_summary(db, case_id, include_compliance=True, include_restricted=True):
    """Folder tree with counts, for the vault UI."""
    items = db.case_evidence.find({"case_id": case_id})
    counts = {key: {"total": 0, "active": 0, "restricted": 0, "superseded": 0}
              for key in FOLDER_KEYS}
    for item in items:
        folder = item.get("folder")
        if folder not in counts:
            continue
        level = item.get("access_level", "case")
        if level == "compliance_only" and not include_compliance:
            continue
        bucket = counts[folder]
        bucket["total"] += 1
        if item.get("status") == "active":
            bucket["active"] += 1
        if item.get("status") == "superseded":
            bucket["superseded"] += 1
        if level == "restricted":
            bucket["restricted"] += 1

    return {
        "case_id": case_id,
        "total": sum(b["total"] for b in counts.values()),
        "folders": [
            {"key": key, "label": label, "description": description, **counts[key]}
            for key, label, description in FOLDERS
            if counts[key]["total"] > 0 or key in ("analyst_reports", "bank_reports",
                                                   "transaction_evidence", "network_evidence",
                                                   "timeline", "compliance_notes",
                                                   "supporting_documents", "restricted_information")
        ],
    }


# ── Automatic filing ─────────────────────────────────────────────────────────

def _already_filed(db, case_id, **match):
    return db.case_evidence.find_one({"case_id": case_id, **match}) is not None


def file_case_baseline(db, case):
    """File the case's existing stored evidence so the vault is not empty on day one.

    This restates records that already exist; it does not invent any, and it is
    idempotent — running it after every pipeline pass simply files what is new.
    """
    system = {"id": None, "name": "Context Guard", "role": "system"}
    filed = []

    for report in db.bank_reports.find({"case_id": case["id"]}):
        reference = report.get("id") or report.get("request_id")
        if _already_filed(db, case["id"], related_report_id=reference):
            continue
        item, error = add(db, case, system, {
            "folder": "bank_reports",
            "type": "bank_response",
            "title": f"{report.get('responding_bank_name') or report.get('responding_bank')} response",
            "description": (report.get("data", {}).get("recent_activity_summary")
                            or "Structured bank response."),
            "source": f"mock bank endpoint ({report.get('responding_bank')})",
            "related_report_id": reference,
            "request_id": report.get("request_id"),
            "payload": {"request_id": report.get("request_id"),
                        "status": report.get("status"),
                        "context": report.get("data", {}).get("additional_context")},
        }, origin="bank_response", refs={"case_id": case["id"],
                                          "request_id": report.get("request_id")})
        if item:
            filed.append(item)

    entity_ids = case.get("entity_ids", [])
    txns = list(db.transactions.find({"entity_id": {"$in": entity_ids}}))
    for txn in txns:
        # Large movements are the ones an investigator marks relevant, whatever the
        # channel — including the hospital payment at the centre of the demo.
        if txn.get("amount", 0) >= 200000:
            if _already_filed(db, case["id"], related_transaction_id=txn["id"]):
                continue
            item, _ = add(db, case, system, {
                "folder": "transaction_evidence",
                "type": "transaction",
                "title": f"{txn.get('type', 'debit').title()} ₹{txn.get('amount', 0):,.0f} — "
                         f"{txn.get('description')}",
                "description": f"{txn.get('counterparty')} · {str(txn.get('timestamp'))[:16]}",
                "source": f"transactions/{txn['id']}",
                "related_transaction_id": txn["id"],
                "payload": {"amount": txn.get("amount"), "category": txn.get("category")},
            }, origin="baseline", refs={"case_id": case["id"]})
            if item:
                filed.append(item)

    for finding in case.get("pipeline_findings", []) or []:
        if _already_filed(db, case["id"], folder="network_evidence", title=finding.get("title")):
            continue
        item, _ = add(db, case, system, {
            "folder": "network_evidence",
            "type": "graph_snapshot",
            "title": finding.get("title"),
            "description": f"Correlation finding ({finding.get('strength')})",
            "source": "pipeline.correlate_evidence",
            "payload": finding,
            "tags": [finding.get("kind", "correlation")],
        }, origin="pipeline", refs={"case_id": case["id"]})
        if item:
            filed.append(item)

    return filed
