import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from llm_pop_quiz_bench.core import mongo_db


class FakeCollection:
    def __init__(self, index_names):
        self.index_names = index_names
        self.create_calls = []

    def index_information(self):
        return {name: {} for name in self.index_names}

    def create_index(self, keys, **kwargs):
        self.create_calls.append((keys, kwargs))
        return kwargs.get("name")


class FakeDatabase:
    def __init__(self):
        self.collections = {
            "quizzes": FakeCollection({"_id_", "quiz_id_1"}),
            "runs": FakeCollection({"_id_", "run_id_1", "quiz_id_1", "created_at_1"}),
            "results": FakeCollection({"_id_", "run_id_1_model_id_1"}),
            "assets": FakeCollection({"_id_", "run_id_1"}),
            "audit": FakeCollection({"_id_", "ip_1", "run_id_1"}),
            "outcomes": FakeCollection({"_id_", "run_id_1"}),
        }

    def __getitem__(self, name):
        return self.collections[name]


class FakeClient:
    def __init__(self):
        self.database = FakeDatabase()

    def __getitem__(self, name):
        return self.database


def test_existing_indexes_are_not_recreated(monkeypatch):
    monkeypatch.setattr(mongo_db, "PYMONGO_AVAILABLE", True)
    client = FakeClient()

    mongo_db.MongoDatabase(client)

    assert all(
        not collection.create_calls
        for collection in client.database.collections.values()
    )


def test_missing_index_is_created(monkeypatch):
    monkeypatch.setattr(mongo_db, "PYMONGO_AVAILABLE", True)
    client = FakeClient()
    client.database.collections["quizzes"].index_names.remove("quiz_id_1")

    mongo_db.MongoDatabase(client)

    assert client.database.collections["quizzes"].create_calls == [
        ("quiz_id", {"name": "quiz_id_1", "unique": True})
    ]