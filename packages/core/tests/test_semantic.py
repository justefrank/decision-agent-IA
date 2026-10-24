from decision_core import AssistantMessage, load_semantic


def test_semantic_layer_loads_and_hash_is_stable():
    a, b = load_semantic(), load_semantic()
    assert a.version == b.version
    assert set(a.metrics) == {
        "volume_transactions", "valeur_transferee", "revenus_frais",
        "clients_actifs", "agents_actifs", "taux_echec",
    }
    assert "analytics.fact_transaction" in a.allowed_tables
    assert len(a.allowed_tables) == 5


def test_decideur_never_receives_sql():
    msg = AssistantMessage(kind="answer", text="x", sql=["SELECT 1"])
    assert msg.for_role("decideur").sql is None
    assert msg.for_role("analyste").sql == ["SELECT 1"]
