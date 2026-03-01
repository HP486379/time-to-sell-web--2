import os
import sys
from datetime import date

import pytest
from fastapi import HTTPException

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main
import purchases_store


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "purchases.sqlite"
    monkeypatch.setattr(purchases_store, "DB_PATH", str(db_path))
    purchases_store.init_db()
    return db_path


def test_entitlements_flow_and_indices(temp_db):
    user_id = "u1"

    ent = main._compute_entitlements(user_id)
    assert ent["available_index_types"] == ["SP500"]

    created = purchases_store.add_purchase(user_id, "indices.nikkei225", "tx-1")
    assert created is True

    ent_after = main._compute_entitlements(user_id)
    assert "NIKKEI225" in ent_after["available_index_types"]

    indices_resp = main.get_indices_api(x_user_id=user_id)
    assert "NIKKEI225" in indices_resp["indices"]


def test_verify_is_idempotent_on_duplicate_transaction(temp_db):
    user_id = "u1"

    first = main.verify_ios_iap(
        main.IOSVerifyRequest(product_id="indices.nikkei225", transaction_id="dup-tx"),
        x_user_id=user_id,
    )
    second = main.verify_ios_iap(
        main.IOSVerifyRequest(product_id="indices.nikkei225", transaction_id="dup-tx"),
        x_user_id=user_id,
    )

    assert first["ok"] is True and first["created"] is True
    assert second["ok"] is True and second["created"] is False


def test_evaluate_access_control_with_entitlements(temp_db, monkeypatch):
    user_id = "u1"

    # entitlement前はNIKKEIが拒否される
    with pytest.raises(HTTPException) as denied:
        main._ensure_index_allowed(main.IndexType.NIKKEI, user_id)
    assert denied.value.status_code == 403

    purchases_store.add_purchase(user_id, "indices.nikkei225", "tx-allow")

    # entitlement後はNIKKEIが許可される
    ent = main._ensure_index_allowed(main.IndexType.NIKKEI, user_id)
    assert "NIKKEI225" in ent["available_index_types"]

    # evaluateは許可されれば既存 _evaluate に委譲される
    monkeypatch.setattr(main, "_evaluate", lambda position: {"ok": True, "index": position.index_type.value})
    payload = main.PositionRequest(total_quantity=1, avg_cost=1, index_type="NIKKEI225", score_ma=200)
    result = main.evaluate(payload, x_user_id=user_id)
    assert result["ok"] is True
    assert result["index"] == "NIKKEI"

    with pytest.raises(HTTPException) as missing_user:
        main.evaluate(payload, x_user_id=None)
    assert missing_user.value.status_code == 400
