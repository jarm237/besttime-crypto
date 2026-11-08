import os
import pytest
import sqlite3
import json
import tempfile
import uuid
from pymongo.errors import ServerSelectionTimeoutError

from btc_scraper.core.db import CircuitBreakerCollection, CircuitBreakerCursor, CircuitBreakerDatabase, FakeResult


class FakeMongoCollection:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.docs = []

    def insert_one(self, doc, *args, **kwargs):
        if self.should_fail:
            raise ServerSelectionTimeoutError("Fake connection failure")
        self.docs.append(dict(doc))
        class FakeRes:
            inserted_id = str(uuid.uuid4())
        return FakeRes()

    def insert_many(self, docs, *args, **kwargs):
        if self.should_fail:
            raise ServerSelectionTimeoutError("Fake connection failure")
        self.docs.extend([dict(d) for d in docs])
        class FakeRes:
            inserted_ids = [str(uuid.uuid4()) for _ in docs]
        return FakeRes()

    def update_one(self, filter, update, *args, **kwargs):
        if self.should_fail:
            raise ServerSelectionTimeoutError("Fake connection failure")
        class FakeRes:
            modified_count = 1
        return FakeRes()

    def update_many(self, filter, update, *args, **kwargs):
        if self.should_fail:
            raise ServerSelectionTimeoutError("Fake connection failure")
        class FakeRes:
            modified_count = 1
        return FakeRes()

    def find(self, *args, **kwargs):
        if self.should_fail:
            raise ServerSelectionTimeoutError("Fake connection failure")
        return iter(self.docs)


@pytest.fixture
def temp_db_path(tmp_path):
    db_file = tmp_path / "test_fallback_buffer.db"
    return str(db_file)


def test_insert_and_read_single_document(temp_db_path):
    fake_mongo = FakeMongoCollection(should_fail=True)
    cb = CircuitBreakerCollection(fake_mongo, "test_db", "test_col", sqlite_path=temp_db_path)

    res = cb.insert_one({"id": "doc1", "coin": "BTC", "status": "open", "price": 50000.0})
    assert res.inserted_id == "doc1"

    docs = list(cb.find())
    assert len(docs) == 1
    assert docs[0]["id"] == "doc1"
    assert docs[0]["coin"] == "BTC"
    assert docs[0]["status"] == "open"


def test_insert_many_and_read_multiple_documents(temp_db_path):
    fake_mongo = FakeMongoCollection(should_fail=True)
    cb = CircuitBreakerCollection(fake_mongo, "test_db", "test_col", sqlite_path=temp_db_path)

    items = [
        {"id": "doc1", "coin": "BTC", "val": 10},
        {"id": "doc2", "coin": "ETH", "val": 20},
        {"id": "doc3", "coin": "SOL", "val": 30},
    ]
    res = cb.insert_many(items)
    assert len(res.inserted_ids) == 3

    # Must not crash with AttributeError: 'str' object has no attribute 'get'
    docs = list(cb.find())
    assert len(docs) == 3
    coins = {d["coin"] for d in docs}
    assert coins == {"BTC", "ETH", "SOL"}


def test_update_one_match_and_no_match(temp_db_path):
    fake_mongo = FakeMongoCollection(should_fail=True)
    cb = CircuitBreakerCollection(fake_mongo, "test_db", "test_col", sqlite_path=temp_db_path)

    cb.insert_one({"id": "p1", "coin": "BTC", "status": "open"})

    # Update match
    res_match = cb.update_one({"id": "p1"}, {"$set": {"status": "closed", "pnl": 100.0}})
    assert res_match.modified_count == 1

    doc = cb.find_one({"id": "p1"})
    assert doc is not None
    assert doc["status"] == "closed"
    assert doc["pnl"] == 100.0

    # Update no-match: modified_count must be 0
    res_nomatch = cb.update_one({"id": "p999"}, {"$set": {"status": "closed"}})
    assert res_nomatch.modified_count == 0


def test_update_many(temp_db_path):
    fake_mongo = FakeMongoCollection(should_fail=True)
    cb = CircuitBreakerCollection(fake_mongo, "test_db", "test_col", sqlite_path=temp_db_path)

    cb.insert_one({"id": "p1", "type": "spot", "status": "open"})
    cb.insert_one({"id": "p2", "type": "spot", "status": "open"})
    cb.insert_one({"id": "p3", "type": "futures", "status": "open"})

    res = cb.update_many({"type": "spot"}, {"$set": {"status": "paused"}})
    assert res.modified_count == 2

    paused = list(cb.find({"status": "paused"}))
    assert len(paused) == 2
    assert {p["id"] for p in paused} == {"p1", "p2"}


def test_find_equality_filter_and_projection(temp_db_path):
    fake_mongo = FakeMongoCollection(should_fail=True)
    cb = CircuitBreakerCollection(fake_mongo, "test_db", "test_col", sqlite_path=temp_db_path)

    cb.insert_one({"id": "a1", "status": "open", "symbol": "BTC"})
    cb.insert_one({"id": "a2", "status": "closed", "symbol": "ETH"})
    cb.insert_one({"id": "a3", "status": "open", "symbol": "SOL"})

    # Filter
    open_docs = list(cb.find({"status": "open"}, {"_id": 0}))
    assert len(open_docs) == 2
    for d in open_docs:
        assert d["status"] == "open"
        assert "_id" not in d


def test_sort_ascending_and_descending(temp_db_path):
    fake_mongo = FakeMongoCollection(should_fail=True)
    cb = CircuitBreakerCollection(fake_mongo, "test_db", "test_col", sqlite_path=temp_db_path)

    cb.insert_one({"id": "1", "score": 30})
    cb.insert_one({"id": "2", "score": 10})
    cb.insert_one({"id": "3", "score": 50})

    # Sort ascending
    asc = list(cb.find().sort("score", 1))
    assert [d["score"] for d in asc] == [10, 30, 50]

    # Sort descending
    desc = list(cb.find().sort("score", -1))
    assert [d["score"] for d in desc] == [50, 30, 10]


def test_skip_and_limit(temp_db_path):
    fake_mongo = FakeMongoCollection(should_fail=True)
    cb = CircuitBreakerCollection(fake_mongo, "test_db", "test_col", sqlite_path=temp_db_path)

    for i in range(10):
        cb.insert_one({"id": str(i), "rank": i})

    res = list(cb.find().sort("rank", 1).skip(3).limit(4))
    assert len(res) == 4
    assert [d["rank"] for d in res] == [3, 4, 5, 6]


def test_count_documents(temp_db_path):
    fake_mongo = FakeMongoCollection(should_fail=True)
    cb = CircuitBreakerCollection(fake_mongo, "test_db", "test_col", sqlite_path=temp_db_path)

    cb.insert_one({"id": "1", "cat": "A"})
    cb.insert_one({"id": "2", "cat": "B"})
    cb.insert_one({"id": "3", "cat": "A"})

    assert cb.count_documents() == 3
    assert cb.count_documents({"cat": "A"}) == 2
    assert cb.count_documents({"cat": "C"}) == 0


def test_unsupported_mongo_operator_raises(temp_db_path):
    fake_mongo = FakeMongoCollection(should_fail=True)
    cb = CircuitBreakerCollection(fake_mongo, "test_db", "test_col", sqlite_path=temp_db_path)

    with pytest.raises(NotImplementedError):
        list(cb.find({"val": {"$unsupported_op": 123}}))

    with pytest.raises(NotImplementedError):
        cb.update_one({"id": "1"}, {"$inc": {"count": 1}})


def test_malformed_buffered_record_does_not_break_store(temp_db_path):
    fake_mongo = FakeMongoCollection(should_fail=True)
    cb = CircuitBreakerCollection(fake_mongo, "test_db", "test_col", sqlite_path=temp_db_path)

    cb.insert_one({"id": "good_1", "val": 100})

    # Manually inject malformed row into SQLite
    conn = sqlite3.connect(temp_db_path)
    conn.execute(
        "INSERT INTO fallback_buffer (db_name, col_name, operation, data) VALUES (?, ?, ?, ?)",
        ("test_db", "test_col", "insert_one", "{corrupted json ...")
    )
    conn.commit()
    conn.close()

    cb.insert_one({"id": "good_2", "val": 200})

    # Should gracefully skip the malformed row and return the valid ones
    docs = list(cb.find())
    assert len(docs) == 2
    assert {d["id"] for d in docs} == {"good_1", "good_2"}


def test_database_restart_reopen_persists_state(temp_db_path):
    fake_mongo = FakeMongoCollection(should_fail=True)
    cb1 = CircuitBreakerCollection(fake_mongo, "test_db", "test_col", sqlite_path=temp_db_path)

    cb1.insert_one({"id": "p1", "coin": "BTC", "status": "open"})
    cb1.update_one({"id": "p1"}, {"$set": {"status": "closed", "pnl": 50.0}})

    # Create a new collection instance pointing to the same sqlite file
    cb2 = CircuitBreakerCollection(fake_mongo, "test_db", "test_col", sqlite_path=temp_db_path)
    docs = list(cb2.find())
    assert len(docs) == 1
    assert docs[0]["id"] == "p1"
    assert docs[0]["status"] == "closed"
    assert docs[0]["pnl"] == 50.0


# ── Call-pattern tests matching real paper callers ──────────────────────────

def test_etf_flow_upsert_with_set_on_insert(temp_db_path):
    """Matches parsebot_farside_collector.py upsert pattern."""
    fake_mongo = FakeMongoCollection(should_fail=True)
    cb = CircuitBreakerCollection(fake_mongo, "besttime_crypto", "alternative_data_etf_flows", sqlite_path=temp_db_path)

    filt = {"source": "parsebot_farside", "symbol": "BTC", "flow_date": "2026-10-30"}
    update_1 = {
        "$setOnInsert": {"created_at": "2026-10-30T00:00:00Z"},
        "$set": {"total_flow_usd_m": 150.0, "status": "ok"},
    }

    # First call: doc does not exist, upsert creates it
    res1 = cb.update_one(filt, update_1, upsert=True)
    assert res1.upserted_id is not None
    assert res1.modified_count == 0

    doc1 = cb.find_one(filt)
    assert doc1 is not None
    assert doc1["source"] == "parsebot_farside"
    assert doc1["symbol"] == "BTC"
    assert doc1["flow_date"] == "2026-10-30"
    assert doc1["created_at"] == "2026-10-30T00:00:00Z"
    assert doc1["total_flow_usd_m"] == 150.0

    # Second call: doc exists, update modifies $set fields but preserves created_at
    update_2 = {
        "$setOnInsert": {"created_at": "2026-10-31T99:99:99Z"},
        "$set": {"total_flow_usd_m": 250.0, "status": "updated"},
    }
    res2 = cb.update_one(filt, update_2, upsert=True)
    assert res2.modified_count == 1

    doc2 = cb.find_one(filt)
    assert doc2 is not None
    assert doc2["created_at"] == "2026-10-30T00:00:00Z"  # Preserved from initial insert!
    assert doc2["total_flow_usd_m"] == 250.0
    assert doc2["status"] == "updated"


def test_alternative_quality_range_and_in_queries(temp_db_path):
    """Matches alternative_quality.py query patterns ($gte, $gt, $in, $regex)."""
    fake_mongo = FakeMongoCollection(should_fail=True)
    cb = CircuitBreakerCollection(fake_mongo, "besttime_crypto", "alternative_data_fetch_logs", sqlite_path=temp_db_path)

    cb.insert_many([
        {"source": "parsebot_farside", "symbol": "BTC", "mode": "recent", "fetched_at": "2026-10-30T10:00:00Z", "error": None, "status": "ok"},
        {"source": "parsebot_farside", "symbol": "ETH", "mode": "all", "fetched_at": "2026-10-30T12:00:00Z", "error": "401 Unauthorized", "status": "error"},
        {"source": "parsebot_farside", "symbol": "SOL", "mode": "recent", "fetched_at": "2026-10-30T14:00:00Z", "error": "402 Payment Required", "status": "error"},
        {"source": "parsebot_farside", "symbol": "DOGE", "mode": "recent", "fetched_at": "2026-10-30T16:00:00Z", "error": None, "status": "ok"},
    ])

    # $in query
    in_docs = list(cb.find({"symbol": {"$in": ["BTC", "ETH", "SOL"]}}))
    assert len(in_docs) == 3
    assert {d["symbol"] for d in in_docs} == {"BTC", "ETH", "SOL"}

    # $gte query on ISO dates
    gte_docs = list(cb.find({"fetched_at": {"$gte": "2026-10-30T12:00:00Z"}}))
    assert len(gte_docs) == 3
    assert {d["symbol"] for d in gte_docs} == {"ETH", "SOL", "DOGE"}

    # $gt query
    gt_docs = list(cb.find({"fetched_at": {"$gt": "2026-10-30T12:00:00Z"}}))
    assert len(gt_docs) == 2
    assert {d["symbol"] for d in gt_docs} == {"SOL", "DOGE"}

    # $regex error matching
    auth_errors = list(cb.find({
        "fetched_at": {"$gte": "2026-10-30T00:00:00Z"},
        "error": {"$regex": "401|403|Unauthorized", "$options": "i"}
    }))
    assert len(auth_errors) == 1
    assert auth_errors[0]["symbol"] == "ETH"


def test_db_name_isolation(temp_db_path):
    """Ensures collections with the same name across different db_names are strictly isolated."""
    fake_mongo = FakeMongoCollection(should_fail=True)
    cb_db1 = CircuitBreakerCollection(fake_mongo, "db_alpha", "shared_col", sqlite_path=temp_db_path)
    cb_db2 = CircuitBreakerCollection(fake_mongo, "db_beta", "shared_col", sqlite_path=temp_db_path)

    cb_db1.insert_one({"id": "d1", "owner": "alpha"})
    cb_db2.insert_one({"id": "d2", "owner": "beta"})

    alpha_docs = list(cb_db1.find())
    assert len(alpha_docs) == 1
    assert alpha_docs[0]["owner"] == "alpha"

    beta_docs = list(cb_db2.find())
    assert len(beta_docs) == 1
    assert beta_docs[0]["owner"] == "beta"


def test_no_mongo_client_instantiation_in_paper_mode():
    """Verifies that in paper mode, db.py never instantiates MongoClient or contacts Atlas."""
    import sys
    import subprocess

    code = """
import os
os.environ["BTC_RUNTIME_ENVIRONMENT"] = "paper"
os.environ["AUTO_TRADE_DRY_RUN"] = "true"
os.environ["LIVE_TRADING_ENABLED"] = "false"
import pymongo

def forbid_mongo(*args, **kwargs):
    raise AssertionError("MongoClient must not be instantiated in paper mode!")

pymongo.MongoClient = forbid_mongo

from btc_scraper.core import db
assert db._paper_mode is True, "Expected _paper_mode to be True"
assert db.client is None, "Expected client to be None"
assert db._raw_db is None, "Expected _raw_db to be None"
"""
    res = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Subprocess failed with stderr:\n{res.stderr}"
