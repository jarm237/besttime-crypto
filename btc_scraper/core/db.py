import os
import certifi
import sqlite3
import json
import uuid
import time
from typing import Any, Mapping
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError, PyMongoError
from btc_scraper.core.config import MONGODB_URI

# Kiểm tra chế độ paper/demo để tránh kết nối MongoDB Atlas từ xa
def _is_paper_mode() -> bool:
    explicit_env = os.getenv("BTC_RUNTIME_ENVIRONMENT", "").lower()
    if explicit_env == "paper":
        return True
    try:
        from btc_scraper.core.paths import runtime_environment
        if runtime_environment().lower() == "paper":
            return True
    except Exception:
        pass
    dry_run = os.getenv("AUTO_TRADE_DRY_RUN", "").lower() in ("true", "1", "yes")
    live_enabled = os.getenv("LIVE_TRADING_ENABLED", "").lower() in ("true", "1", "yes")
    if dry_run or not live_enabled:
        return True
    return False

_paper_mode = _is_paper_mode()

if _paper_mode:
    # Ở chế độ paper: không kết nối remote MongoDB Atlas, không block network
    client = None
    _raw_db = None
else:
    _db_uri = MONGODB_URI or "mongodb://localhost:27017/"
    if "mongodb+srv://" in _db_uri or "mongodb.net" in _db_uri:
        client = MongoClient(_db_uri, tls=True, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=2000)
    else:
        client = MongoClient(_db_uri, serverSelectionTimeoutMS=2000)
    _raw_db = client['besttime_crypto']


class CircuitBreakerCursor:
    def __init__(self, collection, filter_spec=None, projection=None, *args, **kwargs):
        self.cb_col = collection
        self.filter_spec = filter_spec or {}
        self.projection = projection
        self.args = args
        self.kwargs = kwargs
        self._sort_args = kwargs.get("sort") or None
        self._limit_val = kwargs.get("limit") or None
        self._skip_val = kwargs.get("skip") or None
        self._fallback_docs = None

    def sort(self, *args, **kwargs):
        self._sort_args = (args, kwargs)
        return self

    def limit(self, n: int):
        self._limit_val = n
        return self

    def skip(self, n: int):
        self._skip_val = n
        return self

    def _get_documents(self):
        if self._fallback_docs is not None:
            return self._fallback_docs

        if self.cb_col.is_mongo_down() or self.cb_col.collection is None:
            self._fallback_docs = self.cb_col._local_find(
                self.filter_spec,
                self.projection,
                self._sort_args,
                self._limit_val,
                self._skip_val
            )
            return self._fallback_docs

        try:
            cursor = self.cb_col.collection.find(
                self.filter_spec,
                self.projection,
                *self.args,
                **self.kwargs
            )
            if self._sort_args:
                if isinstance(self._sort_args, tuple):
                    cursor = cursor.sort(*self._sort_args[0], **self._sort_args[1])
                else:
                    cursor = cursor.sort(self._sort_args)
            if self._limit_val is not None:
                cursor = cursor.limit(self._limit_val)
            if self._skip_val is not None:
                cursor = cursor.skip(self._skip_val)
            docs = list(cursor)
            self.cb_col.record_mongo_success()
            return docs
        except (ConnectionFailure, ServerSelectionTimeoutError, PyMongoError) as exc:
            self.cb_col.record_mongo_failure(exc)
            self._fallback_docs = self.cb_col._local_find(
                self.filter_spec,
                self.projection,
                self._sort_args,
                self._limit_val,
                self._skip_val
            )
            return self._fallback_docs

    def __iter__(self):
        return iter(self._get_documents())

    def __len__(self):
        return len(self._get_documents())

    def __getitem__(self, index):
        return self._get_documents()[index]


class FakeResult:
    def __init__(self, inserted_id=None, inserted_ids=None, modified_count=0, matched_count=0, upserted_id=None):
        self.inserted_id = inserted_id
        self.inserted_ids = inserted_ids or []
        self.modified_count = modified_count
        self.matched_count = matched_count
        self.upserted_id = upserted_id


class CircuitBreakerCollection:
    _mongo_down: bool = False
    _last_failure_time: float = 0.0
    _retry_interval_sec: float = 60.0

    @classmethod
    def is_mongo_down(cls) -> bool:
        if not cls._mongo_down:
            return False
        if time.time() - cls._last_failure_time > cls._retry_interval_sec:
            return False
        return True

    @classmethod
    def record_mongo_failure(cls, exc: Exception = None):
        cls._mongo_down = True
        cls._last_failure_time = time.time()

    @classmethod
    def record_mongo_success(cls):
        cls._mongo_down = False
        cls._last_failure_time = 0.0

    def __init__(self, collection, db_name, col_name, sqlite_path=None):
        self.collection = collection
        self.db_name = db_name
        self.col_name = col_name
        self.sqlite_db = self._resolve_sqlite_db(sqlite_path)
        self._init_sqlite()

    def _resolve_sqlite_db(self, sqlite_path=None) -> str:
        if sqlite_path:
            return sqlite_path
        explicit = os.getenv("BTC_FALLBACK_BUFFER_DB")
        if explicit:
            return explicit
        try:
            from btc_scraper.core.paths import build_data_path
            return str(build_data_path("fallback_buffer.db"))
        except Exception:
            return os.path.join(os.path.dirname(__file__), "..", "data", "fallback_buffer.db")

    def _init_sqlite(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.sqlite_db)), exist_ok=True)
        conn = sqlite3.connect(self.sqlite_db)
        try:
            conn.execute('''CREATE TABLE IF NOT EXISTS fallback_buffer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                db_name TEXT,
                col_name TEXT,
                operation TEXT,
                data TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            conn.commit()
        finally:
            conn.close()

    def _buffer_operation(self, operation: str, data: list):
        conn = sqlite3.connect(self.sqlite_db)
        try:
            for doc in data:
                doc_to_save = dict(doc) if isinstance(doc, dict) else doc
                if isinstance(doc_to_save, dict) and '_id' in doc_to_save:
                    doc_to_save['_id'] = str(doc_to_save['_id'])
                conn.execute(
                    'INSERT INTO fallback_buffer (db_name, col_name, operation, data) VALUES (?, ?, ?, ?)',
                    (self.db_name, self.col_name, operation, json.dumps(doc_to_save, default=str))
                )
            conn.commit()
        finally:
            conn.close()

    def insert_one(self, document, *args, **kwargs):
        if not self.is_mongo_down() and self.collection is not None:
            try:
                res = self.collection.insert_one(document, *args, **kwargs)
                self.record_mongo_success()
                return res
            except (ConnectionFailure, ServerSelectionTimeoutError, PyMongoError) as exc:
                self.record_mongo_failure(exc)

        doc_id = str(document.get("id") or document.get("_id") or uuid.uuid4())
        doc_copy = dict(document)
        if "_id" not in doc_copy:
            doc_copy["_id"] = doc_id
        self._buffer_operation('insert_one', [doc_copy])
        return FakeResult(inserted_id=doc_id)

    def insert_many(self, documents, *args, **kwargs):
        if not self.is_mongo_down() and self.collection is not None:
            try:
                res = self.collection.insert_many(documents, *args, **kwargs)
                self.record_mongo_success()
                return res
            except (ConnectionFailure, ServerSelectionTimeoutError, PyMongoError) as exc:
                self.record_mongo_failure(exc)

        docs_to_store = []
        inserted_ids = []
        for d in documents:
            doc_copy = dict(d)
            doc_id = str(doc_copy.get("id") or doc_copy.get("_id") or uuid.uuid4())
            if "_id" not in doc_copy:
                doc_copy["_id"] = doc_id
            docs_to_store.append(doc_copy)
            inserted_ids.append(doc_id)
        self._buffer_operation('insert_one', docs_to_store)
        return FakeResult(inserted_ids=inserted_ids)

    def update_one(self, filter, update, upsert=False, *args, **kwargs):
        if not self.is_mongo_down() and self.collection is not None:
            try:
                res = self.collection.update_one(filter, update, upsert=upsert, *args, **kwargs)
                self.record_mongo_success()
                return res
            except (ConnectionFailure, ServerSelectionTimeoutError, PyMongoError) as exc:
                self.record_mongo_failure(exc)

        for op in update.keys():
            if op.startswith("$") and op not in ("$set", "$setOnInsert"):
                raise NotImplementedError(f"Mongo update operator '{op}' is not supported by local paper SQLite fallback")

        current_docs = self._local_find(filter_spec=filter)
        if not current_docs:
            if upsert:
                new_doc = {}
                for k, v in (filter or {}).items():
                    if not k.startswith("$"):
                        new_doc[k] = v
                if "$setOnInsert" in update and isinstance(update["$setOnInsert"], dict):
                    new_doc.update(update["$setOnInsert"])
                if "$set" in update and isinstance(update["$set"], dict):
                    new_doc.update(update["$set"])
                doc_id = str(new_doc.get("id") or new_doc.get("_id") or uuid.uuid4())
                if "_id" not in new_doc:
                    new_doc["_id"] = doc_id
                self._buffer_operation('insert_one', [new_doc])
                return FakeResult(upserted_id=doc_id, modified_count=0, matched_count=0)
            return FakeResult(modified_count=0, matched_count=0)

        self._buffer_operation('update_one', [{'filter': filter, 'update': update}])
        return FakeResult(modified_count=1, matched_count=1)

    def update_many(self, filter, update, upsert=False, *args, **kwargs):
        if not self.is_mongo_down() and self.collection is not None:
            try:
                res = self.collection.update_many(filter, update, upsert=upsert, *args, **kwargs)
                self.record_mongo_success()
                return res
            except (ConnectionFailure, ServerSelectionTimeoutError, PyMongoError) as exc:
                self.record_mongo_failure(exc)

        for op in update.keys():
            if op.startswith("$") and op not in ("$set", "$setOnInsert"):
                raise NotImplementedError(f"Mongo update operator '{op}' is not supported by local paper SQLite fallback")

        current_docs = self._local_find(filter_spec=filter)
        if not current_docs:
            if upsert:
                new_doc = {}
                for k, v in (filter or {}).items():
                    if not k.startswith("$"):
                        new_doc[k] = v
                if "$setOnInsert" in update and isinstance(update["$setOnInsert"], dict):
                    new_doc.update(update["$setOnInsert"])
                if "$set" in update and isinstance(update["$set"], dict):
                    new_doc.update(update["$set"])
                doc_id = str(new_doc.get("id") or new_doc.get("_id") or uuid.uuid4())
                if "_id" not in new_doc:
                    new_doc["_id"] = doc_id
                self._buffer_operation('insert_one', [new_doc])
                return FakeResult(upserted_id=doc_id, modified_count=0, matched_count=0)
            return FakeResult(modified_count=0, matched_count=0)

        self._buffer_operation('update_many', [{'filter': filter, 'update': update}])
        return FakeResult(modified_count=len(current_docs), matched_count=len(current_docs))

    def find(self, filter=None, projection=None, *args, **kwargs):
        return CircuitBreakerCursor(self, filter, projection, *args, **kwargs)

    def find_one(self, filter=None, projection=None, *args, **kwargs):
        cursor = self.find(filter, projection, *args, **kwargs)
        cursor.limit(1)
        docs = list(cursor)
        return docs[0] if docs else None

    def count_documents(self, filter=None, *args, **kwargs):
        cursor = self.find(filter, *args, **kwargs)
        return len(cursor)

    @staticmethod
    def _match_document(doc: dict, filter_spec: dict | None) -> bool:
        if not filter_spec:
            return True
        for k, v in filter_spec.items():
            if k == "$or":
                if not isinstance(v, list) or not any(CircuitBreakerCollection._match_document(doc, sub) for sub in v):
                    return False
                continue
            if k == "$and":
                if not isinstance(v, list) or not all(CircuitBreakerCollection._match_document(doc, sub) for sub in v):
                    return False
                continue
            if k.startswith("$"):
                raise NotImplementedError(f"Mongo query operator '{k}' is not supported by local paper SQLite fallback")

            actual = doc.get(k)
            if isinstance(v, dict):
                for op, target in v.items():
                    if op == "$gte":
                        if actual is None or not (actual >= target):
                            return False
                    elif op == "$gt":
                        if actual is None or not (actual > target):
                            return False
                    elif op == "$lte":
                        if actual is None or not (actual <= target):
                            return False
                    elif op == "$lt":
                        if actual is None or not (actual < target):
                            return False
                    elif op == "$in":
                        if not isinstance(target, (list, tuple, set)) or actual not in target:
                            return False
                    elif op == "$ne":
                        if actual == target:
                            return False
                    elif op == "$regex":
                        import re
                        pattern = target
                        options = v.get("$options", "")
                        flags = re.IGNORECASE if "i" in options else 0
                        if actual is None or not re.search(pattern, str(actual), flags):
                            return False
                    elif op == "$options":
                        continue
                    else:
                        raise NotImplementedError(f"Mongo query operator '{op}' is not supported by local paper SQLite fallback")
            else:
                if actual != v:
                    return False
        return True

    def _local_find(self, filter_spec=None, projection=None, sort_args=None, limit_val=None, skip_val=None):
        filter_spec = filter_spec or {}
        for k, v in filter_spec.items():
            if k.startswith("$") and k not in ("$or", "$and"):
                raise NotImplementedError(f"Mongo query operator '{k}' is not supported by local paper SQLite fallback")
            if isinstance(v, dict):
                for op in v.keys():
                    if op.startswith("$") and op not in ("$gte", "$gt", "$lte", "$lt", "$in", "$ne", "$regex", "$options"):
                        raise NotImplementedError(f"Mongo query operator '{op}' is not supported by local paper SQLite fallback")

        conn = sqlite3.connect(self.sqlite_db)
        try:
            cur = conn.cursor()
            cur.execute(
                'SELECT id, operation, data FROM fallback_buffer WHERE db_name = ? AND col_name = ? ORDER BY id ASC',
                (self.db_name, self.col_name)
            )
            rows = cur.fetchall()
        finally:
            conn.close()

        docs_map = {}
        for row_id, op, data_str in rows:
            try:
                payload = json.loads(data_str)
            except Exception:
                continue

            if op in ('insert_one', 'insert_many'):
                if isinstance(payload, list):
                    for item in payload:
                        if isinstance(item, dict):
                            doc_id = str(item.get('id') or item.get('_id') or uuid.uuid4())
                            docs_map[doc_id] = dict(item)
                elif isinstance(payload, dict):
                    doc_id = str(payload.get('id') or payload.get('_id') or row_id)
                    docs_map[doc_id] = dict(payload)
            elif op == 'update_one':
                if not isinstance(payload, dict):
                    continue
                filt = payload.get('filter', {})
                update = payload.get('update', {})
                set_data = update.get('$set', update if not any(k.startswith('$') for k in update) else {})
                for doc_id, doc in list(docs_map.items()):
                    if self._match_document(doc, filt):
                        doc.update(set_data)
                        break
            elif op == 'update_many':
                if not isinstance(payload, dict):
                    continue
                filt = payload.get('filter', {})
                update = payload.get('update', {})
                set_data = update.get('$set', update if not any(k.startswith('$') for k in update) else {})
                for doc_id, doc in list(docs_map.items()):
                    if self._match_document(doc, filt):
                        doc.update(set_data)

        # Apply filtering
        results = []
        for doc in docs_map.values():
            if self._match_document(doc, filter_spec):
                res = dict(doc)
                if projection:
                    if projection.get('_id') == 0:
                        res.pop('_id', None)
                    positive_keys = [pk for pk, pv in projection.items() if pk != '_id' and pv == 1]
                    if positive_keys:
                        keys_to_remove = [k for k in res if k not in positive_keys and k != '_id']
                        for kr in keys_to_remove:
                            res.pop(kr, None)
                results.append(res)

        # Apply sort
        if sort_args:
            if isinstance(sort_args, tuple):
                args, kwargs = sort_args
                sort_spec = args[0] if args else None
                direction = args[1] if len(args) > 1 else 1
            else:
                sort_spec = sort_args
                direction = 1

            if isinstance(sort_spec, str):
                results.sort(key=lambda x: (x.get(sort_spec) is not None, x.get(sort_spec)), reverse=(direction == -1))
            elif isinstance(sort_spec, list):
                for item in reversed(sort_spec):
                    if isinstance(item, tuple):
                        k, d = item
                    elif isinstance(item, str):
                        k, d = item, 1
                    else:
                        continue
                    results.sort(key=lambda x: (x.get(k) is not None, x.get(k)), reverse=(d == -1))

        if skip_val:
            results = results[skip_val:]
        if limit_val:
            results = results[:limit_val]

        return results

    def __getattr__(self, name):
        if self.collection is None:
            raise AttributeError(f"CircuitBreakerCollection: '{name}' unavailable in local paper mode")
        return getattr(self.collection, name)


class CircuitBreakerDatabase:
    def __init__(self, raw_db=None, db_name="besttime_crypto"):
        self._db = raw_db
        self._db_name = db_name
        self._collections = {}

    def __getitem__(self, col_name: str) -> CircuitBreakerCollection:
        if col_name not in self._collections:
            raw_col = self._db[col_name] if self._db is not None else None
            self._collections[col_name] = CircuitBreakerCollection(raw_col, self._db_name, col_name)
        return self._collections[col_name]

    def __getattr__(self, name: str):
        if self._db is not None:
            return getattr(self._db, name)
        return self[name]


# Database instance
db = CircuitBreakerDatabase(_raw_db, 'besttime_crypto')

# Collections
positions_col = db['positions']
closed_positions_col = db['closed_positions']
closed_trades_col = db['closed_trades']
alternative_data_etf_flows_col = db['alternative_data_etf_flows']
alternative_data_fetch_logs_col = db['alternative_data_fetch_logs']

# Tạo Index để tối ưu (chỉ chạy khi không ở paper mode và có kết nối MongoDB thật)
if _raw_db is not None:
    try:
        _raw_db['positions'].create_index("id", unique=True)
        _raw_db['positions'].create_index([("coin", 1), ("status", 1)])
        _raw_db['closed_positions'].create_index("id")
        _raw_db['closed_positions'].create_index("coin")
        _raw_db['closed_trades'].create_index("id")
        _raw_db['alternative_data_etf_flows'].create_index([("source", 1), ("symbol", 1), ("flow_date", -1)], unique=True)
        _raw_db['alternative_data_etf_flows'].create_index([("symbol", 1), ("status", 1), ("fetched_at", -1)])
        _raw_db['alternative_data_fetch_logs'].create_index([("source", 1), ("endpoint", 1), ("fetched_at", -1)])
    except Exception as e:
        CircuitBreakerCollection.record_mongo_failure(e)
        print(f"Warning: Failed to create MongoDB index. Error: {e}")

