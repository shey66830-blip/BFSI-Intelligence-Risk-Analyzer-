"""
Context Guard — Seed: Restricted Subject Information & Evidence Baselines

Synthetic restricted records exist so the authorisation workflow can be demonstrated.
Everything here is generated: the names, document references and contact details are
invented, and every record carries the standard "no determination of wrongdoing" notice.

Terminology is deliberate — these are *investigation subjects* / *persons of interest*,
not suspects.
"""

from datetime import datetime

from services import access, evidence

# Keyed by case, then subject. All values are synthetic.
DEMO_RESTRICTED = {
    "case_2": [
        {
            "subject_id": "e_rajesh",
            "subject_label": "Person of interest",
            "category": "identity",
            "title": "Registered identity particulars",
            "value": {
                "legal_name": "Rajesh Kumar",
                "date_of_birth": "1984-03-11",
                "document_reference": "SYNTH-ID-4471-PAN",
                "verification_status": "KYC verified on file",
            },
            "source": "synthetic onboarding record",
        },
        {
            "subject_id": "e_rajesh",
            "subject_label": "Person of interest",
            "category": "contact",
            "title": "Registered contact details",
            "value": {
                "telephone": "+91-98•••••221",
                "email": "r•••••@synthetic-mail.demo",
                "registered_address": "Flat 4B, Synth Residency, Chennai, IN",
                "alternate_contact": "not on file",
            },
            "source": "synthetic onboarding record",
        },
        {
            "subject_id": "e_rajesh",
            "subject_label": "Person of interest",
            "category": "documents",
            "title": "Hospital invoice and insurance claim",
            "value": {
                "documents": [
                    "synthetic-invoice-APL-4471.pdf",
                    "synthetic-claim-CLAIM-2026-09-1847.pdf",
                ],
                "note": "Synthetic documents generated for this demonstration.",
            },
            "source": "synthetic supporting documents",
        },
    ],
    "case_3": [
        {
            "subject_id": "e_vikram",
            "subject_label": "Person of interest",
            "category": "identity",
            "title": "Registered identity particulars",
            "value": {
                "legal_name": "Vikram Patel",
                "date_of_birth": "1991-07-02",
                "document_reference": "SYNTH-ID-8823-PAN",
                "verification_status": "KYC verified on file",
            },
            "source": "synthetic onboarding record",
        },
        {
            "subject_id": "e_vikram",
            "subject_label": "Person of interest",
            "category": "contact",
            "title": "Registered contact details",
            "value": {
                "telephone": "+91-90•••••772",
                "email": "v•••••@synthetic-mail.demo",
                "registered_address": "12 Synth Avenue, Delhi, IN",
            },
            "source": "synthetic onboarding record",
        },
        {
            "subject_id": "e_vikram",
            "subject_label": "Person of interest",
            "category": "external_reference",
            "title": "External registry references",
            "value": {
                "registry_reference": "SYNTH-REG-2024-88231",
                "prior_institution_reference": "SYN-EXT-0091 (synthetic)",
                "note": "References are invented for this demonstration and correspond to no "
                        "real registry or institution.",
            },
            "source": "synthetic external reference set",
        },
        {
            "subject_id": "e_meera",
            "subject_label": "Investigation subject",
            "category": "contact",
            "title": "Registered contact details",
            "value": {
                "telephone": "+91-91•••••305",
                "email": "m•••••@synthetic-mail.demo",
                "registered_address": "88 Synth Street, Bangalore, IN",
            },
            "source": "synthetic onboarding record",
        },
        {
            "subject_id": "e_vikram",
            "subject_label": "Person of interest",
            "category": "investigator_notes",
            "title": "Investigator note containing personal information",
            "value": {
                "note": "Synthetic note: the subject's stated occupation was checked against the "
                        "account profile during the previous review cycle. No adverse finding.",
                "recorded_by": "synthetic case file",
            },
            "source": "synthetic case notes",
        },
    ],
}


def ensure_restricted_information(db):
    """Create the synthetic restricted records if they are absent (idempotent)."""
    created = 0
    for case_id, records in DEMO_RESTRICTED.items():
        for record in records:
            exists = db.restricted_subject_information.find_one({
                "case_id": case_id, "title": record["title"], "category": record["category"],
            })
            if exists:
                continue
            access.add_subject_information(db, case_id, record)
            created += 1
    return created


def ensure_evidence_baselines(db):
    """File each seeded case's existing records into its vault (idempotent)."""
    filed = 0
    for case in db.cases.find({}):
        if db.case_evidence.count_documents({"case_id": case["id"]}) > 0:
            continue
        filed += len(evidence.file_case_baseline(db, case))
    return filed
