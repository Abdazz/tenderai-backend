import os

os.environ.setdefault("TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx")
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")


def test_delivery_graph_node_sequence():
    from tenderai_bf.agents.delivery_graph import DeliveryGraph

    graph = DeliveryGraph()
    node_names = set(graph.graph.nodes.keys())
    assert node_names == {
        "select_new_notices", "classify", "summarize", "compose_report",
        "email_report", "mark_delivered", "error_handler",
    }
