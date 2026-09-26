from copy import deepcopy
from contextlib import contextmanager
import importlib
import sys
import unittest
from unittest.mock import patch

from src.app import services


@contextmanager
def production_cosmos_module():
    module_name = "src.app.services.azure_cosmos_db"
    missing = object()
    previous_module = sys.modules.pop(module_name, None)
    previous_attribute = getattr(services, "azure_cosmos_db", missing)
    if hasattr(services, "azure_cosmos_db"):
        delattr(services, "azure_cosmos_db")
    try:
        module = importlib.import_module(module_name)
        yield module
    finally:
        sys.modules.pop(module_name, None)
        if previous_module is not None:
            sys.modules[module_name] = previous_module
        if previous_attribute is not missing:
            setattr(services, "azure_cosmos_db", previous_attribute)
        elif hasattr(services, "azure_cosmos_db"):
            delattr(services, "azure_cosmos_db")


class FakeUsersContainer:
    def __init__(self, user):
        self.user = deepcopy(user)

    def read_item(self, item, partition_key):
        assert item == self.user["id"]
        assert partition_key == self.user["userId"]
        return deepcopy(self.user)

    def patch_item(self, item, partition_key, patch_operations):
        assert item == self.user["id"]
        assert partition_key == self.user["userId"]
        for operation in patch_operations:
            self.user[operation["path"].lstrip("/")] = operation["value"]
        return deepcopy(self.user)


class UserPreferenceServiceTests(unittest.TestCase):
    def test_merges_preferences_without_replacing_profile_fields(self):
        container = FakeUsersContainer({
            "id": "tony",
            "userId": "tony",
            "tenantId": "marvel",
            "name": "Tony Stark",
            "email": "tony@stark.example",
            "address": {"city": "Malibu"},
            "createdAt": "2025-01-15T10:00:00Z",
            "preferences": {"budget": "luxury", "mobility": "car"},
        })

        with production_cosmos_module() as azure_cosmos_db:
            with patch.object(azure_cosmos_db, "users_container", container):
                result = azure_cosmos_db.update_user_preferences(
                    "tony",
                    "marvel",
                    {"dietary": "vegetarian"},
                )

        self.assertEqual(result["preferences"], {
            "budget": "luxury",
            "mobility": "car",
            "dietary": "vegetarian",
        })
        self.assertEqual(result["name"], "Tony Stark")
        self.assertEqual(result["email"], "tony@stark.example")
        self.assertEqual(result["address"], {"city": "Malibu"})
        self.assertEqual(result["createdAt"], "2025-01-15T10:00:00Z")
        self.assertIn("updatedAt", result)

    def test_omitted_fields_do_not_remove_known_or_unknown_preferences(self):
        container = FakeUsersContainer({
            "id": "tony",
            "userId": "tony",
            "tenantId": "marvel",
            "name": "Tony Stark",
            "createdAt": "2025-01-15T10:00:00Z",
            "preferences": {
                "budget": "luxury",
                "dietary": "vegetarian",
                "futurePreference": "quiet-floor",
            },
        })

        with production_cosmos_module() as azure_cosmos_db:
            with patch.object(azure_cosmos_db, "users_container", container):
                result = azure_cosmos_db.update_user_preferences(
                    "tony",
                    "marvel",
                    {"budget": "moderate"},
                )

        self.assertEqual(result["preferences"], {
            "budget": "moderate",
            "dietary": "vegetarian",
            "futurePreference": "quiet-floor",
        })


if __name__ == "__main__":
    unittest.main()
