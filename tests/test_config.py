import unittest
from pathlib import Path

from grm.config import Config, parse_config
from grm.util import InvalidConfigError


class ParseConfigTest(unittest.TestCase):
    def test_parses_nested_config(self):
        result = parse_config(
            {
                "debug": True,
                "sync": [
                    {
                        "path": "src",
                        "clone": [
                            {
                                "owner": "example",
                                "globs": ["service-*"],
                                "prune": True,
                            }
                        ],
                        "fetch": {"tags": False},
                        "merge": {"ff_only": True},
                    }
                ],
            }
        )

        self.assertIsInstance(result, Config)
        self.assertTrue(result.debug)
        self.assertEqual(result.sync[0].path, Path("src"))
        self.assertEqual(result.sync[0].clone[0].owner, "example")
        self.assertEqual(result.sync[0].clone[0].globs, ["service-*"])
        self.assertTrue(result.sync[0].clone[0].prune)
        self.assertFalse(result.sync[0].fetch.tags)
        self.assertTrue(result.sync[0].merge.ff_only)

    def test_applies_defaults(self):
        result = parse_config({"sync": [{"path": "src"}]})

        self.assertFalse(result.debug)
        self.assertEqual(result.sync[0].clone, [])
        self.assertFalse(result.sync[0].fetch.prune)
        self.assertIsNone(result.sync[0].merge.ff)

    def test_reports_nested_type_error(self):
        with self.assertRaisesRegex(
            InvalidConfigError,
            "expected bool, got str",
        ) as context:
            parse_config(
                {
                    "sync": [
                        {
                            "path": "src",
                            "fetch": {"prune": "yes"},
                        }
                    ]
                }
            )

        self.assertEqual(context.exception.field, "sync[0].fetch.prune")

    def test_rejects_unknown_property(self):
        with self.assertRaisesRegex(InvalidConfigError, "unknown property") as context:
            parse_config({"verbose": True})

        self.assertEqual(context.exception.field, "verbose")

    def test_requires_sync_path(self):
        with self.assertRaisesRegex(
            InvalidConfigError,
            "missing required property",
        ) as context:
            parse_config({"sync": [{}]})

        self.assertEqual(context.exception.field, "sync[0].path")


if __name__ == "__main__":
    unittest.main()
