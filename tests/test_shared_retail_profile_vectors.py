import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from atreides.retail_identity import CustomerProfile

VECTOR_PATH = Path(__file__).parent / "fixtures" / "shared_retail_profile_vectors.json"
EXPECTED_CHECKSUM = "5758d315bbeaea178af899cd074a323e92223467321ca180575f3f4f241108b5"


def test_shared_profile_vectors_and_checksum() -> None:
    raw = VECTOR_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_CHECKSUM
    document = json.loads(raw)
    for index, vector in enumerate(document["vectors"], 1):
        fields = {key: value for key, value in vector.items() if key not in {"name", "expected"}}
        fields["investment_objectives"] = tuple(fields["investment_objectives"])
        fields["investment_experience"] = tuple(fields["investment_experience"])
        profile = CustomerProfile(
            record_id=f"SYN-PROFILE-VECTOR{index}",
            updated_at=datetime(2026, 11, 9, tzinfo=UTC),
            **fields,
        )
        expected = "ACCEPT" if profile.complete else "REFUSE_PROFILE_INCOMPLETE"
        assert expected == vector["expected"]
