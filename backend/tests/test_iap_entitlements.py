import os
import sys

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


def test_free_user_only_has_sp500(temp_db):
    """無料ユーザーはSP500のみ"""
    ent = main._compute_entitlements("u_free")
    assert ent["available_index_types"] == ["SP500"]


def test_entitlements_flow_nikkei225(temp_db):
    """nikkei225_a購入後にNIKKEI225が使えるようになる"""
    user_id = "u1"
    created = purchases_store.add_purchase(user_id, "nikkei225_a", "tx-nikkei-1")
    assert created is True

    ent = main._compute_entitlements(user_id)
    assert "NIKKEI225" in ent["available_index_types"]

    indices_resp = main.get_indices_api(x_user_id=user_id)
    assert "NIKKEI225" in indices_resp["indices"]


def test_entitlements_flow_topix(temp_db):
    """topix_a購入後にTOPIXが使えるようになる"""
    user_id = "u2"
    purchases_store.add_purchase(user_id, "topix_a", "tx-topix-1")
    ent = main._compute_entitlements(user_id)
    assert "TOPIX" in ent["available_index_types"]


def test_entitlements_flow_nifty50(temp_db):
    """nifty50_a購入後にNIFTY50が使えるようになる"""
    user_id = "u3"
    purchases_store.add_purchase(user_id, "nifty50_a", "tx-nifty-1")
    ent = main._compute_entitlements(user_id)
    assert "NIFTY50" in ent["available_index_types"]


def test_entitlements_flow_allcountry(temp_db):
    """allcountry_a購入後にALLCOUNTRYが使えるようになる"""
    user_id = "u4"
    purchases_store.add_purchase(user_id, "allcountry_a", "tx-allcountry-1")
    ent = main._compute_entitlements(user_id)
    assert "ALLCOUNTRY" in ent["available_index_types"]


def test_entitlements_flow_sp500_jpy(temp_db):
    """sp500_jpy_a購入後にSP500_JPYが使えるようになる（SP500ではない）"""
    user_id = "u5"
    purchases_store.add_purchase(user_id, "sp500_jpy_a", "tx-sp500jpy-1")
    ent = main._compute_entitlements(user_id)
    assert "SP500_JPY" in ent["available_index_types"]
    assert "SP500" in ent["available_index_types"]  # SP500はfreeで常に含まれる
    # SP500_JPY と SP500 は別エンティティ
    assert ent["available_index_types"].count("SP500_JPY") == 1


def test_entitlements_flow_allcountry_jpy(temp_db):
    """allcountry_jpy_a購入後にALLCOUNTRY_JPYが使えるようになる"""
    user_id = "u6"
    purchases_store.add_purchase(user_id, "allcountry_jpy_a", "tx-allcountryjpy-1")
    ent = main._compute_entitlements(user_id)
    assert "ALLCOUNTRY_JPY" in ent["available_index_types"]


def test_all_paid_indices_can_be_purchased(temp_db):
    """有料指数6種すべてが正しく登録・entitlement反映される"""
    user_id = "u_all"
    product_to_canonical = {
        "nikkei225_a": "NIKKEI225",
        "topix_a": "TOPIX",
        "nifty50_a": "NIFTY50",
        "allcountry_a": "ALLCOUNTRY",
        "sp500_jpy_a": "SP500_JPY",
        "allcountry_jpy_a": "ALLCOUNTRY_JPY",
    }
    for i, (product_id, expected_canonical) in enumerate(product_to_canonical.items()):
        created = purchases_store.add_purchase(user_id, product_id, f"tx-all-{i}")
        assert created is True, f"Failed to create purchase for {product_id}"

    ent = main._compute_entitlements(user_id)
    for canonical in product_to_canonical.values():
        assert canonical in ent["available_index_types"], f"{canonical} not in entitlements"


def test_verify_ios_iap_idempotent(temp_db):
    """同じtransaction_idで2回verifyしても2回目はcreated=Falseになる（冪等性）"""
    user_id = "u1"
    first = main.verify_ios_iap(
        main.IOSVerifyRequest(product_id="nikkei225_a", transaction_id="dup-tx"),
        x_user_id=user_id,
    )
    second = main.verify_ios_iap(
        main.IOSVerifyRequest(product_id="nikkei225_a", transaction_id="dup-tx"),
        x_user_id=user_id,
    )
    assert first["ok"] is True and first["created"] is True
    assert second["ok"] is True and second["created"] is False


def test_purchase_endpoint_idempotent(temp_db):
    """/purchase エンドポイントの冪等性テスト"""
    first = main.purchase(
        main.PurchaseRequest(user_id="u2", product_id="topix_a", transaction_id="tx-topix-1")
    )
    second = main.purchase(
        main.PurchaseRequest(user_id="u2", product_id="topix_a", transaction_id="tx-topix-1")
    )
    assert first["success"] is True and first["created"] is True
    assert second["success"] is True and second["created"] is False

    ent = main._compute_entitlements("u2")
    assert "TOPIX" in ent["available_index_types"]


def test_unsupported_product_id_returns_400(temp_db):
    """未知のproduct_idは400を返す"""
    with pytest.raises(HTTPException) as exc_info:
        main.purchase(
            main.PurchaseRequest(user_id="u3", product_id="indices.topix", transaction_id="tx-old")
        )
    assert exc_info.value.status_code == 400


def test_access_control_denied_before_purchase(temp_db):
    """購入前は有料指数が403になる"""
    with pytest.raises(HTTPException) as exc_info:
        main._ensure_index_allowed(main.IndexType.NIKKEI225, "u_new")
    assert exc_info.value.status_code == 403


def test_access_control_allowed_after_purchase(temp_db):
    """購入後は有料指数が許可される"""
    user_id = "u_buy"
    purchases_store.add_purchase(user_id, "nikkei225_a", "tx-access-1")

    ent = main._ensure_index_allowed(main.IndexType.NIKKEI225, user_id)
    assert "NIKKEI225" in ent["available_index_types"]


def test_access_control_sp500_jpy(temp_db):
    """SP500_JPY購入後にSP500_JPYが許可される"""
    user_id = "u_sp500jpy"
    purchases_store.add_purchase(user_id, "sp500_jpy_a", "tx-sp500jpy-access")

    ent = main._ensure_index_allowed(main.IndexType.SP500_JPY, user_id)
    assert "SP500_JPY" in ent["available_index_types"]


def test_missing_user_id_returns_400(temp_db):
    """X-User-Idなしは400"""
    with pytest.raises(HTTPException) as exc_info:
        main._ensure_index_allowed(main.IndexType.NIKKEI225, None)
    assert exc_info.value.status_code == 400


def test_index_type_normalization(temp_db):
    """旧canonical名は入口でNIKKEI225/ALLCOUNTRY/ALLCOUNTRY_JPY/SP500_JPYに正規化される"""
    # "NIKKEI225" は PositionRequest で受け付けられる
    payload = main.PositionRequest(total_quantity=1, avg_cost=1, index_type="NIKKEI225", score_ma=200)
    assert payload.index_type == main.IndexType.NIKKEI225

    # "nikkei" も正規化される
    payload2 = main.PositionRequest(total_quantity=1, avg_cost=1, index_type="nikkei", score_ma=200)
    assert payload2.index_type == main.IndexType.NIKKEI225

    # "orukan" → ALLCOUNTRY
    payload3 = main.PositionRequest(total_quantity=1, avg_cost=1, index_type="orukan", score_ma=200)
    assert payload3.index_type == main.IndexType.ALLCOUNTRY

    # "sp500_jpy" → SP500_JPY
    payload4 = main.PositionRequest(total_quantity=1, avg_cost=1, index_type="sp500_jpy", score_ma=200)
    assert payload4.index_type == main.IndexType.SP500_JPY
