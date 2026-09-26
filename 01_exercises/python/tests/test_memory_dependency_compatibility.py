from __future__ import annotations

import unittest
from pathlib import Path


TREE_ROOT = Path(__file__).resolve().parents[2]
AGENT_MEMORY_PATH = TREE_ROOT / "python" / "src" / "app" / "services" / "agent_memory.py"
EXPECTED_MEMORY_DEPENDENCIES = {
    "prompty": "prompty==2.0.0b3",
    "azure-cosmos-agent-memory": "azure-cosmos-agent-memory==0.2.0b3",
}


class MemoryDependencyCompatibilityTests(unittest.TestCase):
    def test_memory_dependencies_are_pinned_to_the_verified_pair(self):
        requirements_paths = sorted(TREE_ROOT.rglob("requirements.txt"))
        self.assertTrue(requirements_paths, f"No requirements.txt files found under {TREE_ROOT}")

        for requirements_path in requirements_paths:
            declarations = {
                package_name: []
                for package_name in EXPECTED_MEMORY_DEPENDENCIES
            }
            for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                for package_name in EXPECTED_MEMORY_DEPENDENCIES:
                    normalized_line = line.lower()
                    package_suffix = normalized_line.removeprefix(package_name)
                    if normalized_line == package_name or (
                        package_suffix != normalized_line
                        and package_suffix[0] in " [<>=!~@;"
                    ):
                        declarations[package_name].append(raw_line)

            if not any(declarations.values()):
                continue

            relative_path = requirements_path.relative_to(TREE_ROOT)
            for package_name, expected_declaration in EXPECTED_MEMORY_DEPENDENCIES.items():
                actual_declarations = declarations[package_name]
                self.assertEqual(
                    len(actual_declarations),
                    1,
                    f"{relative_path}: expected exactly one {package_name} declaration; "
                    f"found {actual_declarations!r}",
                )
                self.assertEqual(
                    actual_declarations[0],
                    expected_declaration,
                    f"{relative_path}: expected {expected_declaration!r}; "
                    f"found {actual_declarations[0]!r}",
                )

    def test_pinned_toolkit_uses_its_type_aware_deletion_api(self):
        source = AGENT_MEMORY_PATH.read_text(encoding="utf-8")

        self.assertIn("await client.delete_cosmos(", source)
        self.assertNotIn("await client.delete_memory(", source)


if __name__ == "__main__":
    unittest.main()
