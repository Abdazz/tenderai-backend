"""constat #22 regression: PNUD/UNDP notices on Joffres.net label their
reference as "Reference Number : XXX" (no "N°"), which the original regex
list didn't cover, leaving ref_no empty for every such notice."""

import os
import sys

os.environ.setdefault("TENDERAI_ENVIRONMENT", "test")
os.environ.setdefault("TENDERAI_DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")
sys.path.insert(0, "src")

from tenderai.agents.nodes.fetch_joffres import extract_joffres_detail  # noqa: E402

UNDP_HTML = """
<html><body>
<div class="small-section-tittle">
  <h3>Acquisition et installation d'équipements informatiques</h3>
  Structure : PNUD Burkina Faso
</div>
<div class="post-details1">
  <p>Reference Number : UNDP-BFA-00734 — appel à propositions pour l'acquisition
  et l'installation d'équipements informatiques au profit du bureau pays.</p>
</div>
</body></html>
"""


def test_reference_number_label_without_n_symbol():
    result = extract_joffres_detail(UNDP_HTML, "https://www.joffres.net/notice/1")
    assert result["ref_no"] == "Reference Number : UNDP-BFA-00734"
