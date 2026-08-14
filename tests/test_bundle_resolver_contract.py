import json
from pathlib import Path

from spec_compiler.constants import is_bundle_md


CONTRACT = json.loads(
    (Path(__file__).parent / "fixtures" / "contracts" / "spec-bundle-resolver-v1.json").read_text()
)


def test_bundle_resolver_matches_the_language_neutral_contract():
    for case in CONTRACT["cases"]:
        assert is_bundle_md(
            case["path"],
            manifest_spec=case["manifest_spec"],
            frontmatter=case["frontmatter"],
        ) is case["expected"], case["name"]
