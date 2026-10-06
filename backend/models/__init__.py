"""
Context Guard — MongoDB Models
Document schemas and CRUD operations for all collections.
"""

from datetime import datetime
from bson import ObjectId


# ── Serialization helpers ────────────────────────────────────────────────────

def serialize_doc(doc):
    """Convert MongoDB document to JSON-safe dict."""
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize_doc(d) for d in doc]
    result = {}
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, dict):
            result[key] = serialize_doc(value)
        elif isinstance(value, list):
            result[key] = [serialize_doc(v) if isinstance(v, dict) else v for v in value]
        else:
            result[key] = value
    return result


# ── Transaction ──────────────────────────────────────────────────────────────

def create_transaction(db, txn):
    """Insert a transaction into the database."""
    txn["created_at"] = datetime.utcnow()
    result = db.transactions.insert_one(txn)
    txn["_id"] = result.inserted_id
    return txn


def get_transactions_by_case(db, case_id):
    """Get all transactions for a case."""
    return list(db.transactions.find({"case_id": case_id}).sort("timestamp", 1))


def get_transactions_by_entity(db, entity_id):
    """Get all transactions for an entity."""
    return list(db.transactions.find({"entity_id": entity_id}).sort("timestamp", 1))


def get_all_transactions(db):
    """Get all transactions."""
    return list(db.transactions.find().sort("timestamp", 1))


# ── Entity ───────────────────────────────────────────────────────────────────

def upsert_entity(db, entity):
    """Insert or update an entity."""
    entity["updated_at"] = datetime.utcnow()
    if "_id" in entity:
        del entity["_id"]
    db.entities.update_one(
        {"id": entity["id"]},
        {"$set": entity},
        upsert=True
    )
    return entity


def get_entity(db, entity_id):
    """Get an entity by ID."""
    return db.entities.find_one({"id": entity_id})


def get_all_entities(db):
    """Get all entities."""
    return list(db.entities.find())


# ── Case ─────────────────────────────────────────────────────────────────────

def create_case(db, case):
    """Insert a new case."""
    case["created_at"] = datetime.utcnow()
    case["updated_at"] = datetime.utcnow()
    result = db.cases.insert_one(case)
    case["_id"] = result.inserted_id
    return case


def update_case(db, case_id, updates):
    """Update a case by ID."""
    updates["updated_at"] = datetime.utcnow()
    db.cases.update_one({"id": case_id}, {"$set": updates})
    return db.cases.find_one({"id": case_id})


def get_case(db, case_id):
    """Get a case by ID."""
    return db.cases.find_one({"id": case_id})


def get_all_cases(db):
    """Get all cases."""
    return list(db.cases.find().sort("created_at", -1))


# ── Bank Report ──────────────────────────────────────────────────────────────

def create_bank_report(db, report):
    """Insert a bank report."""
    report["created_at"] = datetime.utcnow()
    result = db.bank_reports.insert_one(report)
    report["_id"] = result.inserted_id
    return report


def get_reports_by_case(db, case_id):
    """Get all bank reports for a case."""
    return list(db.bank_reports.find({"case_id": case_id}))


# ── Decision ─────────────────────────────────────────────────────────────────

def create_decision(db, decision):
    """Insert a decision."""
    decision["created_at"] = datetime.utcnow()
    result = db.decisions.insert_one(decision)
    decision["_id"] = result.inserted_id
    return decision


def get_decision_by_case(db, case_id):
    """Get the latest decision for a case."""
    return db.decisions.find_one(
        {"case_id": case_id},
        sort=[("created_at", -1)]
    )


# ── Graph Edge ───────────────────────────────────────────────────────────────

def create_graph_edge(db, edge):
    """Insert a graph edge (relationship)."""
    edge["created_at"] = datetime.utcnow()
    edge["updated_at"] = datetime.utcnow()
    result = db.graph_edges.insert_one(edge)
    edge["_id"] = result.inserted_id
    return edge


def get_edges_for_entity(db, entity_id):
    """Get all edges involving an entity."""
    return list(db.graph_edges.find({
        "$or": [{"source": entity_id}, {"target": entity_id}]
    }))


def get_all_edges(db):
    """Get all graph edges."""
    return list(db.graph_edges.find())


def get_edges_by_type(db, edge_type):
    """Get edges of a specific type."""
    return list(db.graph_edges.find({"edge_type": edge_type}))
