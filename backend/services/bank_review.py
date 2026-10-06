"""
Context Guard — The Bank's Consent Desk (simulated)

A request for bank-held records is not the platform's to grant. The record sits with
the bank, so the bank decides whether the purpose the requester gave is one it can act
on. This module stands in for that decision the same way `services/mock_banks.py`
stands in for the bank's data.

The reviewer is deliberately neither a rubber stamp nor a black box. It refuses a
justification too thin to act on, refuses a purpose it cannot connect to a lawful
basis, refuses where its own consent record has lapsed, asks for clarification when
the platform has never actually asked it for anything on the case, and otherwise
approves — saying in its own words what it checked.

Every outcome carries the bank's written statement. That statement is recorded on the
request and in the audit trail whether or not any screen renders it.
"""

from datetime import datetime

from config import BANKS

# A justification has to clear a floor before a consent desk can act on it.
MIN_STATEMENT_WORDS = 25

# Purposes a bank can act on without a court order.
LAWFUL_PURPOSES = (
    "investigation", "suspicion", "verify", "verification", "consent", "fiu",
    "aml", "money laundering", "source of funds", "ownership", "regulatory",
    "report", "escalation",
)

# Most of what a consent desk holds it will release once a lawful purpose is stated.
# Some items carry their own test: the desk wants the statement to name the basis it is
# being asked for, because it has to point at something when a customer complains. When
# an item fails its own test the desk releases the rest rather than the whole request —
# a partial release it can defend, not a blanket refusal.
ITEM_TESTS = {
    "bank_beneficial_ownership": (
        ("ownership", "beneficial", "ubo"),
        "We are not releasing the beneficial ownership file: the statement does not say "
        "why ownership is being asked about. Name the ownership question and we will reconsider.",
    ),
    "bank_source_of_funds": (
        ("source of funds", "source of fund", "source-of-funds", "salary", "onboarding",
         "declaration", "provenance"),
        "We are not releasing the source-of-funds declaration: the statement does not say "
        "what its provenance is being tested against.",
    ),
}


def _now():
    return datetime.utcnow().isoformat()


def reviewer_for(case):
    """The bank that answers for this case, and the desk that signs the answer."""
    bank_ids = case.get("bank_ids") or list(BANKS.keys())
    bank_id = bank_ids[0]
    bank = BANKS.get(bank_id, {})
    name = bank.get("name", bank_id)
    return {
        "id": f"bank_consent_desk:{bank_id}",
        "name": f"{name} — consent desk",
        "role": "bank",
        "bank_id": bank_id,
        "bank_name": name,
    }


def _consent_evidence(db, case):
    """What the bank already told the platform on this case, with its consent state."""
    evidence = []
    for report in db.bank_reports.find({"case_id": case["id"]}):
        data = report.get("data") or {}
        bank_id = report.get("responding_bank")
        evidence.append({
            "bank_id": bank_id,
            "bank_name": (report.get("responding_bank_name")
                          or BANKS.get(bank_id, {}).get("name") or bank_id),
            "consent_status": data.get("consent_status"),
            "request_id": report.get("request_id"),
        })
    return evidence


def review(db, case, request):
    """Decide a bank-held request. Returns the decision, with the bank's statement."""
    statement = (request.get("statement") or "").strip()
    words = len(statement.split())
    reviewer = reviewer_for(case)
    evidence = _consent_evidence(db, case)
    labels = ", ".join(request.get("resource_labels") or [])

    base = {
        "bank_id": reviewer["bank_id"],
        "bank_name": reviewer["bank_name"],
        "reviewer": reviewer["name"],
        "reviewed_at": _now(),
        "request_id": request["id"],
        "requested_items": labels,
        "consent_records": evidence,
    }

    if words < MIN_STATEMENT_WORDS:
        return {**base, "outcome": "rejected", "approved_keys": [], "refused_keys": [],
                "statement": (f"The justification supplied is {words} words. That is not enough "
                              f"for us to release records on — we have to be able to show why "
                              f"the stated purpose required it. Resubmit with the purpose, the "
                              f"period and the specific items you need."),
                "reasons": ["justification too thin to assess"]}

    purpose_hits = [term for term in LAWFUL_PURPOSES if term in statement.lower()]
    if not purpose_hits:
        return {**base, "outcome": "rejected", "approved_keys": [], "refused_keys": [],
                "statement": ("The request does not state a purpose we can act on. We release "
                              "customer records for an investigation, a verification or a "
                              "regulatory referral — not on request for general interest."),
                "reasons": ["no lawful purpose stated"]}

    if not evidence:
        return {**base, "outcome": "clarification_requested",
                "approved_keys": [], "refused_keys": [],
                "statement": ("We hold nothing against this case: no structured request from the "
                              "platform has reached us. Send us the request first, then ask for "
                              "the underlying records."),
                "reasons": ["no prior request on this case"]}

    lapsed = sorted({e["bank_name"] or e["bank_id"] for e in evidence
                     if e["consent_status"] and not str(e["consent_status"]).startswith("active")})
    if lapsed:
        return {**base, "outcome": "rejected", "approved_keys": [], "refused_keys": [],
                "statement": (f"Our consent record is no longer active for {', '.join(lapsed)}. "
                              f"Records cannot be released against lapsed consent; re-establish it "
                              f"and we will reconsider the request."),
                "reasons": ["consent lapsed"]}

    # The request may ask for several things at once. Each is tested against its own
    # condition; the desk releases what it can and says plainly what it will not.
    requested = request.get("resource_keys") or []
    label_by_key = dict(zip(request.get("resource_keys") or [],
                            request.get("resource_labels") or []))
    approved_keys, refused_keys, refusals = [], [], []
    for key in requested:
        condition = ITEM_TESTS.get(key)
        if condition is None or any(term in statement.lower() for term in condition[0]):
            approved_keys.append(key)
        else:
            refused_keys.append(key)
            refusals.append(condition[1])

    scope = (f"the request states a purpose we can act on ({', '.join(purpose_hits[:3])}), "
             f"it is scoped to case {case['id']}, and our consent record for this subject is "
             f"active")

    if refused_keys and not approved_keys:
        return {**base, "outcome": "rejected", "approved_keys": [], "refused_keys": refused_keys,
                "statement": "We cannot release anything against this request. " + " ".join(refusals),
                "reasons": ["item conditions not met"]}

    if refused_keys:
        approved_labels = ", ".join(label_by_key.get(k, k) for k in approved_keys)
        refused_labels = ", ".join(label_by_key.get(k, k) for k in refused_keys)
        return {**base, "outcome": "partially_approved",
                "approved_keys": approved_keys, "refused_keys": refused_keys,
                "statement": (f"Partly approved. {scope}. Releasing: {approved_labels}. We are "
                              f"not releasing: {refused_labels}. " + " ".join(refusals) +
                              f" The rest of the request stands as submitted."),
                "reasons": ["item conditions not met"], "policy_refs": purpose_hits}

    return {**base, "outcome": "approved", "approved_keys": approved_keys, "refused_keys": [],
            "statement": (f"Approved. The request states a purpose we can act on "
                          f"({', '.join(purpose_hits[:3])}), it is scoped to case {case['id']}, and "
                          f"our consent record for this subject is active. Releasing: {labels}."),
            "reasons": [], "policy_refs": purpose_hits}


def release(db, case, authorization):
    """What the bank hands over once it has approved. Derived from what it holds."""
    keys = authorization.get("resources") or []
    bank_id = str(authorization.get("approved_by") or "").split(":")[-1]
    bank_name = str(authorization.get("approved_by_name") or "").split(" — ")[0]
    entity_ids = case.get("entity_ids") or []
    txns = list(db.transactions.find({"entity_id": {"$in": entity_ids}})) if entity_ids else []
    records = []

    if "bank_ledger_detail" in keys:
        own = [t for t in txns if t.get("bank_id") == bank_id] or txns
        records.append({
            "resource": "bank_ledger_detail",
            "title": f"Ledger extract — {bank_name}",
            "note": (f"Statement lines as held by the bank, released under "
                     f"{authorization['request_id']}."),
            "rows": [{"reference": t.get("id"), "date": t.get("timestamp"),
                      "amount": t.get("amount"), "type": t.get("type") or t.get("description"),
                      "bank": BANKS.get(t.get("bank_id"), {}).get("name", t.get("bank_id"))}
                     for t in own],
        })

    if "bank_counterparty_detail" in keys:
        seen = {}
        for t in txns:
            counterparty = t.get("counterparty")
            if counterparty and counterparty != "Unknown":
                seen.setdefault(counterparty, t.get("bank_id"))
        records.append({
            "resource": "bank_counterparty_detail",
            "title": f"Counterparty detail — {bank_name}",
            "note": "Counterparties as recorded on the bank's own ledgers.",
            "rows": [{"counterparty": name,
                      "recorded_by": BANKS.get(bank, {}).get("name", bank)}
                     for name, bank in seen.items()],
        })

    if "bank_beneficial_ownership" in keys:
        records.append({
            "resource": "bank_beneficial_ownership",
            "title": f"Beneficial ownership on file — {bank_name}",
            "note": "Declarations and registry references the bank holds against the entity.",
            "rows": [{"entity_id": entity,
                      "registry_reference": f"UBO-{str(entity)[-6:].upper()}",
                      "declaration_on_file": True}
                     for entity in entity_ids],
        })

    if "bank_source_of_funds" in keys:
        records.append({
            "resource": "bank_source_of_funds",
            "title": f"Source-of-funds declaration — {bank_name}",
            "note": "What the customer told the bank, in the bank's own record.",
            "rows": [{"entity_id": entity,
                      "declaration": ("Stated at onboarding as salary and business receipts; "
                                      "the declaration is held on file.")}
                     for entity in entity_ids],
        })

    return records
