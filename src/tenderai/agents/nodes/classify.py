"""Classify items for IT/Engineering relevance."""

import re
import time
import uuid
from datetime import UTC, datetime

from ...db import get_db_context
from ...logging import get_logger, log_classification
from ...models import CompanyNoticeStatus
from ...utils.dates import parse_flexible_date
from ...utils.llm_utils import get_llm_instance
from ...utils.node_logger import clear_node_output, log_node_output
from .._cfg import cfg, company_cfg

logger = get_logger(__name__)


def _upsert_company_notice_status(db, company_id: int, item: dict) -> None:
    """Record this item's classification result for this company.

    Every classified item gets a row (relevant or not) — a row's absence is
    what select_new_notices treats as "not yet classified", so an item with
    no row would be reclassified on every future delivery run.
    """
    existing = (
        db.query(CompanyNoticeStatus)
        .filter(
            CompanyNoticeStatus.company_id == company_id,
            CompanyNoticeStatus.notice_id == item["id"],
        )
        .first()
    )
    if existing:
        existing.is_relevant = bool(item.get("is_relevant", False))
        existing.relevance_score = item.get("relevance_score")
        existing.classification_method = item.get("classification_method")
    else:
        db.add(
            CompanyNoticeStatus(
                id=str(uuid.uuid4()),
                company_id=company_id,
                notice_id=item["id"],
                is_relevant=bool(item.get("is_relevant", False)),
                relevance_score=item.get("relevance_score"),
                classification_method=item.get("classification_method"),
            )
        )


_ATTRIBUTION_SIGNALS = [
    # Attribution / marché attribué
    "résultats provisoires",
    "résultats définitifs",
    "résultat provisoire",
    "résultat définitif",
    "avis d'attribution",
    "attribution du marché",
    "recours préalable",
    "adjudicataire",
    "attributaire",
    "marché attribué",
    "contrat attribué",
    "rectificatif des résultats",
    # PV de dépouillement / ouverture des plis — soumissions déjà reçues et comptées
    "nombre de plis reçus",
    "plis reçus",
    "nombre d'offres reçues",
    "offres reçues",
    "candidats retenus",
    "soumissionnaires retenus",
    "nombre de candidats retenus",
    "procès-verbal de dépouillement",
    "pv de dépouillement",
    "séance de dépouillement",
    "avis d'appel à la concurrence annulé",
    "infructueux",
]

# Signals that identify supplier/provider registration calls (not actionable IT tenders)
_SUPPLIER_REGISTRATION_SIGNALS = [
    "constitution d'une base de données de fournisseurs",
    "constitution d'une base de données des fournisseurs",
    "constitution d'une base de données de prestataires",
    "constitution d'une base de données des prestataires",
    "constitution d'une base de données complémentaire",
    "constitution d'une base de donnees",
    "base de données de fournisseurs",
    "base de données des fournisseurs",
    "base de données de prestataires",
    "base de données des prestataires",
    "liste de fournisseurs agréés",
    "fichier de fournisseurs",
    "répertoire de fournisseurs",
    "répertoire de prestataires",
    "préqualification de fournisseurs",
    "préqualification de prestataires",
]


def _normalize_apostrophes(text: str) -> str:
    """Replace typographic/curly apostrophes with the standard ASCII apostrophe."""
    return text.replace("’", "'").replace("‘", "'").replace("ʼ", "'")  # noqa: RUF001 — this line's purpose IS normalizing these exact unicode variants


def _is_attribution_notice(item: dict) -> bool:
    """Return True if this item concerns attribution results, not an open procurement."""
    text = _normalize_apostrophes(
        " ".join(
            [
                item.get("title") or "",
                item.get("tender_object") or "",
                item.get("description") or "",
            ]
        ).lower()
    )
    return any(signal in text for signal in _ATTRIBUTION_SIGNALS)


def _parse_deadline(item: dict) -> datetime | None:
    """Extract deadline date from item fields or raw description text."""
    # Try structured field first
    raw = item.get("deadline_at") or item.get("deadline") or ""
    if not raw:
        # Fall back to scanning the description for explicit close dates
        text = (item.get("description") or "") + " " + (item.get("raw_text") or "")
        # First pass: require an explicit deadline keyword
        for pattern in [
            r"(?:date\s+de\s+cl[oô]ture|closing\s+date|deadline|date\s+limite)[^\d]{0,10}(\d{4}[-/]\d{2}[-/]\d{2})",
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                raw = m.group(1)
                break

        if not raw:
            # Second pass: bare ISO date — skip dates preceded by modification/publication keywords
            # (e.g. "Date de modification: 2026-06-05") to avoid false expiry filtering
            _EXCLUDE_PREFIXES = (  # noqa: N806 — module-level-style constant, scoped locally by design
                "modif",
                "publi",
                "créé",
                "créat",
                "posted",
                "annoncé",
                "soumis",
            )
            for date_match in re.finditer(r"(\d{4}[-/]\d{2}[-/]\d{2})", text):
                preceding = text[
                    max(0, date_match.start() - 40) : date_match.start()
                ].lower()
                if not any(excl in preceding for excl in _EXCLUDE_PREFIXES):
                    raw = date_match.group(1)
                    break

    return parse_flexible_date(raw)


def _is_expired(item: dict) -> bool:
    """Return True if the tender deadline is clearly in the past."""
    deadline = _parse_deadline(item)
    if deadline is None:
        return False
    return deadline < datetime.now(tz=UTC)


def _is_supplier_registration(item: dict) -> bool:
    """Return True if this item is a supplier/provider registration call, not an IT tender.

    These are administrative calls for companies to register as approved vendors —
    they are not procurement contracts YULCOM can bid on as an IT provider.
    """
    text = " ".join(
        [
            item.get("title") or "",
            item.get("tender_object") or "",
            item.get("description") or "",
        ]
    ).lower()
    return any(signal in text for signal in _SUPPLIER_REGISTRATION_SIGNALS)


def _is_geographic_mismatch(item: dict, country_name: str) -> bool:
    """Return True if the item explicitly targets a different country than the target.

    Only uses hard signals to avoid false positives: (1) the location field names
    another country, (2) the UNDP entity code encodes a different country.
    Returns False when uncertain so legitimate items are never dropped.
    """
    if not country_name:
        return False

    country_lower = country_name.lower()

    # 1. Explicit location field — skip if absent or placeholder
    location = (item.get("location") or "").strip()
    if (
        location
        and location.lower() not in ("n/a", "non disponible", "none", "-", "")
        and country_lower not in location.lower()
    ):
        logger.debug(
            "Geographic mismatch: location does not match target country",
            location=location,
            target=country_name,
            item_id=item.get("id"),
        )
        return True

    # 2. UNDP country code in entity ("UNDP-ZWE/ZIMBABWE") or reference ("UNDP-LBR-00899")
    for field_name in ("entity", "reference", "ref_no"):
        field_val = (item.get(field_name) or "").strip()
        # Pattern: UNDP-{ISO3}/{COUNTRY} or UNDP-{ISO3}-{number}
        undp_match = re.match(r"UNDP-([A-Z]{3})(?:/(.+)|-\d)", field_val, re.IGNORECASE)
        if undp_match:
            iso3 = undp_match.group(1).upper()
            country_in_field = (undp_match.group(2) or "").lower()
            if country_lower not in country_in_field and not _iso3_matches_country(
                iso3, country_lower
            ):
                logger.debug(
                    "Geographic mismatch: UNDP country code does not match target",
                    field=field_name,
                    value=field_val,
                    target=country_name,
                    item_id=item.get("id"),
                )
                return True

    # 3. Entity field is itself a country name (e.g. entity="Géorgie")
    entity_lower = (item.get("entity") or "").strip().lower()
    for _iso3, fragments in _ISO3_TO_FRAGMENTS.items():
        if entity_lower in fragments and not any(
            frag in country_lower for frag in fragments
        ):  # exact match: entity IS a country name, but not this target's fragments
            logger.debug(
                "Geographic mismatch: entity is a foreign country name",
                entity=entity_lower,
                target=country_name,
                item_id=item.get("id"),
            )
            return True

    return False


def _is_real_open_tender(item: dict) -> bool:
    """Heuristic fallback: item has a verifiable future deadline.

    Used only in keyword-mode where no LLM is available.
    Prefer _llm_verify_is_real_tender() when an LLM instance is at hand.
    """
    deadline = _parse_deadline(item)
    if deadline is None:
        return False
    return deadline >= datetime.now(tz=UTC)


def _llm_verify_is_real_tender(item: dict, llm) -> bool:
    """Ask the LLM whether this is a genuine open procurement tender.

    Called only for items with no geographic context (location=N/A), to filter out
    consultant postings, attribution notices, and other non-bidable content that
    slipped through earlier filters.
    Fails open (returns True) on LLM errors to avoid dropping legitimate tenders.
    """
    title = (item.get("tender_object") or item.get("title") or "")[:200]
    entity = (item.get("entity") or "")[:100]
    reference = (item.get("reference") or item.get("ref_no") or "")[:80]
    description = (item.get("description") or "")[:400]
    deadline_raw = str(
        item.get("deadline_at") or item.get("deadline") or "non précisée"
    )

    prompt = (
        "Tu analyses un marché public. Réponds UNIQUEMENT par OUI ou NON.\n\n"
        "Est-ce un appel d'offres ouvert auquel une entreprise peut soumissionner "
        "(pas un avis d'attribution déjà attribué, pas un recrutement de consultant, "
        "pas une inscription fournisseur, pas une actualité ou étude) ?\n\n"
        f"Titre : {title}\n"
        f"Entité : {entity}\n"
        f"Référence : {reference}\n"
        f"Date limite : {deadline_raw}\n"
        f"Description : {description}\n\n"
        "Réponse (OUI/NON uniquement) :"
    )
    try:
        response = llm.invoke(prompt)
        text = (
            response.content.strip().upper()
            if hasattr(response, "content")
            else str(response).strip().upper()
        )
        is_real = "OUI" in text or "YES" in text
        logger.debug(
            "LLM real-tender verification",
            item_id=item.get("id"),
            title=title[:60],
            is_real=is_real,
            llm_response=text[:80],
        )
        return is_real
    except Exception as e:
        logger.warning(
            "LLM real-tender check failed, defaulting to keep",
            item_id=item.get("id"),
            error=str(e),
        )
        return True  # fail-open: keep dubious item rather than silently drop a real one


# Mapping of UNDP/UN ISO-3 country codes to country name fragments for target matching
_ISO3_TO_FRAGMENTS: dict[str, list[str]] = {
    "BFA": ["burkina"],
    "CAN": ["canada"],
    "CIV": ["côte d'ivoire", "cote d'ivoire", "ivory coast"],
    "SEN": ["sénégal", "senegal"],
    "MLI": ["mali"],
    "NER": ["niger"],
    "GIN": ["guinée", "guinea"],
    "TGO": ["togo"],
    "BEN": ["bénin", "benin"],
    "CMR": ["cameroun", "cameroon"],
    "TCD": ["tchad", "chad"],
    "GHA": ["ghana"],
    "NGA": ["nigeria"],
    "KEN": ["kenya"],
    "ETH": ["éthiopie", "ethiopia"],
    "RWA": ["rwanda"],
    "UGA": ["uganda"],
    "TZA": ["tanzanie", "tanzania"],
    "MOZ": ["mozambique"],
    "ZWE": ["zimbabwe"],
    "ZMB": ["zambie", "zambia"],
    "MWI": ["malawi"],
    "MDG": ["madagascar"],
    "LBR": ["liberia"],
    "SLE": ["sierra leone"],
    "LSO": ["lesotho"],
    "ZAF": ["south africa", "afrique du sud"],
    "BDI": ["burundi"],
    "IND": ["india", "inde"],
    "KAZ": ["kazakhstan"],
    "KGZ": ["kyrgyzstan", "kirghizistan"],
    "MDA": ["moldova"],
    "HND": ["honduras"],
    "GEO": ["georgie", "géorgie", "georgia"],
}


def _iso3_matches_country(iso3: str, country_lower: str) -> bool:
    """Return True if the ISO-3 code corresponds to the target country."""
    fragments = _ISO3_TO_FRAGMENTS.get(iso3.upper(), [])
    return any(frag in country_lower for frag in fragments)


def classify_node(state) -> dict:
    """Classify items for IT/Engineering relevance."""

    # Clear output file at start
    clear_node_output("classify")

    if state.error_occurred:
        return state

    logger.info("Starting classify step", run_id=state.run_id)

    try:
        # Choose classification method based on configuration
        _use_llm = cfg(state, "pipeline", "use_llm_classification")
        if _use_llm:
            # Use LLM-based classification (requires LLM setup)
            logger.info("Using LLM-based classification", run_id=state.run_id)
            return classify_with_llm(state)
        else:
            # Use keyword-based classification (default)
            logger.info("Using keyword-based classification", run_id=state.run_id)
            return classify_with_keywords(state)

    except Exception as e:
        logger.error(
            "Classification failed", error=str(e), run_id=state.run_id, exc_info=True
        )
        state.add_error("classify", str(e))
        return state


def classify_with_keywords(state) -> dict:
    """Classify items using keyword-based matching."""
    start_time = time.time()
    relevant_items = []

    try:
        # Get keywords from configuration
        # Combine all keywords from different categories
        it_keywords = []

        relevant_keywords = company_cfg(state, "classification", "relevant_keywords")
        if relevant_keywords:
            for _category, keywords in relevant_keywords.items():
                it_keywords.extend(keywords)
        else:
            # Fallback to default keywords if not in config
            it_keywords = [
                "informatique",
                "logiciel",
                "réseau",
                "serveur",
                "ordinateur",
                "internet",
                "site web",
                "application",
                "base de données",
                "cybersécurité",
                "cloud",
                "données",
                "numérique",
                "digital",
                "ERP",
                "CRM",
                "SIG",
                "GIS",
                "télécommunication",
                "fibre optique",
            ]

        logger.debug(
            f"Using {len(it_keywords)} keywords for classification",
            keywords_count=len(it_keywords),
            run_id=state.run_id,
        )

        target_country = getattr(state, "country_name", "") or ""

        for item in state.items_parsed:
            # Hard disqualification filters — applied to ALL items regardless of whether
            # they were pre-classified by the extraction LLM (classification_embedded).
            # Pre-classification is a relevance signal, not an override of these rules.

            if _is_geographic_mismatch(item, target_country):
                item["relevance_score"] = 0.0
                item["is_relevant"] = False
                item["classification_method"] = "geographic_filter"
                continue

            if _is_attribution_notice(item):
                item["relevance_score"] = 0.0
                item["is_relevant"] = False
                item["classification_method"] = "attribution_filter"
                logger.debug(
                    "Excluded attribution notice",
                    item_id=item.get("id"),
                    run_id=state.run_id,
                )
                continue

            if _is_supplier_registration(item):
                item["relevance_score"] = 0.0
                item["is_relevant"] = False
                item["classification_method"] = "supplier_registration_filter"
                logger.debug(
                    "Excluded supplier registration call",
                    item_id=item.get("id"),
                    run_id=state.run_id,
                )
                continue

            if _is_expired(item):
                item["relevance_score"] = 0.0
                item["is_relevant"] = False
                item["classification_method"] = "expired_filter"
                logger.debug(
                    "Excluded expired tender",
                    item_id=item.get("id"),
                    deadline=str(_parse_deadline(item)),
                    run_id=state.run_id,
                )
                continue

            # Perform keyword-based classification for items without scores
            # Get all text fields for matching
            title_lower = item.get("title", "").lower()
            description_lower = item.get("description", "").lower()
            tender_object_lower = item.get("tender_object", "").lower()
            category_lower = item.get("category", "").lower()

            # Combine all text for search
            all_text = f"{title_lower} {description_lower} {tender_object_lower} {category_lower}"

            # Calculate relevance score (0.0 to 1.0)
            # Score based on: any keyword match = 1.0, no match = 0.0
            # This is a simpler approach: if ANY keyword matches, it's relevant
            keyword_matches = sum(
                1 for keyword in it_keywords if keyword.lower() in all_text
            )

            # For keyword matching: if ANY keyword matches, consider it relevant
            # Otherwise score is proportional to number of matches
            if keyword_matches > 0:
                relevance_score = min(
                    1.0, 0.5 + (keyword_matches / len(it_keywords) * 0.5)
                )
            else:
                relevance_score = 0.0

            # Use a lower threshold for keyword-based classification
            # (LLM-scored items already passed through extraction with 0.7 threshold)
            keyword_threshold = min(
                0.3,
                company_cfg(state, "classification", "min_relevance_score"),
            )
            is_relevant = relevance_score >= keyword_threshold

            # Update item with classification
            item["relevance_score"] = relevance_score
            item["is_relevant"] = is_relevant
            item["classification_method"] = "keyword_matching"

            if is_relevant:
                relevant_items.append(item)

            log_classification(
                item["id"],
                relevance_score,
                is_relevant,
                keyword_matches=keyword_matches,
                method="keyword",
            )

        state.relevant_items = relevant_items
        state.unique_items = relevant_items

        with get_db_context() as _db:
            for item in state.items_parsed:
                _upsert_company_notice_status(_db, state.company_id, item)
            _db.commit()

        state.update_stats(
            relevant_items=len(relevant_items),
            unique_items=len(relevant_items),
            classify_time_seconds=time.time() - start_time,
        )

        # Log output to JSON
        log_node_output("classify", relevant_items, run_id=state.run_id)

        logger.info(
            "Keyword-based classification completed",
            total_items=len(state.items_parsed),
            relevant_items=len(relevant_items),
            threshold=company_cfg(state, "classification", "min_relevance_score"),
            run_id=state.run_id,
        )

        return state

    except RuntimeError:
        raise
    except Exception as e:
        logger.error(
            "Keyword classification failed",
            error=str(e),
            run_id=state.run_id,
            exc_info=True,
        )
        state.add_error("classify", str(e))
        return state


def classify_with_llm(state) -> dict:
    """Classify items using LLM-based analysis with keyword fallback."""
    start_time = time.time()
    relevant_items = []

    try:
        # Get LLM instance
        llm = get_llm_instance(temperature=0.1, max_tokens=200)
        if not llm:
            logger.error("LLM not available, falling back to keyword classification")
            return classify_with_keywords(state)

        # Get LLM model name for logging
        llm_model = getattr(llm, "model_name", getattr(llm, "model", "unknown"))
        llm_provider = cfg(state, "llm", "provider")

        logger.info(
            "Starting LLM-based classification",
            llm_provider=llm_provider,
            llm_model=llm_model,
            items_to_classify=len(state.items_parsed),
            run_id=state.run_id,
        )

        # Get keywords for keyword-based fallback
        it_keywords = []
        relevant_keywords = company_cfg(state, "classification", "relevant_keywords")
        for _category, keywords in relevant_keywords.items():
            it_keywords.extend(keywords)

        # Classification prompt — two-gate: (1) is it a procurement notice? (2) is it IT/engineering?
        classification_prompt = """Vous êtes un expert en marchés publics IT. Analysez le contenu suivant.

Entité : {entity}
Référence : {reference}
Objet : {objet}
Description : {description}

ÉTAPE 1 — EST-CE UN APPEL D'OFFRES OU UN AVIS DE MARCHÉ ?
Répondez NON immédiatement si le contenu est :
- Une page d'aide, guide utilisateur, documentation ou tutoriel (ex. "comment utiliser X", "introduction à Y")
- Une offre d'emploi ou annonce de recrutement
- Un article de blog, actualité, rapport statistique ou étude de marché
- Une page d'accueil, annuaire ou agrégateur listant des ressources
- Une page institutionnelle de présentation d'un organisme
- Un contrat déjà attribué ou un résultat d'appel d'offres
- Une inscription à une base de données de fournisseurs

Pour être un appel d'offres valide, le contenu doit explicitement solliciter des soumissions, offres ou propositions de la part de fournisseurs, avec un objet de marché, une entité adjudicatrice et généralement une date limite de soumission.

ÉTAPE 2 — EST-CE DANS LES DOMAINES CIBLÉS ? (seulement si ÉTAPE 1 = OUI)
Répondez OUI UNIQUEMENT si l'objet porte EXPLICITEMENT sur l'un des domaines suivants :
1. Services IT : développement logiciel, systèmes d'information, ERP, CRM, SIG, GIS, cybersécurité, cloud, hébergement, infogérance, réseau informatique, fibre optique, wifi, vidéoconférence, intelligence artificielle, data center
2. Matériel informatique : ordinateurs, serveurs, imprimantes, scanners, photocopieurs, routeurs, switches, modems, écrans, onduleurs, tablettes, téléphones, accessoires informatiques, consommables informatiques
3. Conseil/ingénierie IT : études informatiques, audits de sécurité informatique, assistance technique IT, schémas directeurs informatiques, formation informatique, déploiement/intégration de systèmes, licences logicielles

Répondez NON à l'étape 2 si l'appel d'offres concerne — même partiellement — l'un des domaines suivants :
- Travaux de génie civil, construction, BTP, routes, bâtiments, hydraulique, assainissement
- Agriculture, élevage, alimentation, nettoyage, gardiennage, sécurité physique
- Véhicules, carburant, mobilier de bureau (tables, chaises, armoires)
- Fournitures générales de bureau (papier, stylos, cartouches non-informatiques)
- Matériel médical, équipements de laboratoire, instruments de mesure scientifique
- Équipements de surveillance environnementale, matériel de terrain, capteurs météo
- Matériel pharmaceutique, agricole, vétérinaire
- Services de transport, logistique ou manutention
- Entretien de véhicules, bâtiments ou équipements non-informatiques (si l'objet ne mentionne pas explicitement "informatique" ou "numérique")

RÈGLE ABSOLUE : si l'objet est trop vague ou tronqué et ne mentionne PAS explicitement un terme IT (informatique, logiciel, numérique, digital, réseau, serveur, cloud, etc.), répondez NON.

Répondez UNIQUEMENT par "OUI" ou "NON" suivi d'une explication en une phrase précisant pourquoi ce contenu est ou n'est pas un appel d'offres IT pertinent."""

        target_country = getattr(state, "country_name", "") or ""

        # Classify each item
        for item in state.items_parsed:
            # Hard disqualification filters — applied to ALL items regardless of whether
            # they were pre-classified by the extraction LLM (classification_embedded).
            # Pre-classification is a relevance signal, not an override of these rules.

            if _is_geographic_mismatch(item, target_country):
                item["relevance_score"] = 0.0
                item["is_relevant"] = False
                item["classification_method"] = "geographic_filter"
                continue

            if _is_attribution_notice(item):
                item["relevance_score"] = 0.0
                item["is_relevant"] = False
                item["classification_method"] = "attribution_filter"
                logger.debug(
                    "Excluded attribution notice",
                    item_id=item.get("id"),
                    run_id=state.run_id,
                )
                continue

            if _is_supplier_registration(item):
                item["relevance_score"] = 0.0
                item["is_relevant"] = False
                item["classification_method"] = "supplier_registration_filter"
                logger.debug(
                    "Excluded supplier registration call",
                    item_id=item.get("id"),
                    run_id=state.run_id,
                )
                continue

            if _is_expired(item):
                item["relevance_score"] = 0.0
                item["is_relevant"] = False
                item["classification_method"] = "expired_filter"
                logger.debug(
                    "Excluded expired tender",
                    item_id=item.get("id"),
                    deadline=str(_parse_deadline(item)),
                    run_id=state.run_id,
                )
                continue

            llm_error = None
            try:
                # Prepare item data
                entity = item.get("entity", item.get("title", "")) or "Inconnu"
                reference = item.get("reference", item.get("ref_no", "")) or "N/A"
                objet = (item.get("tender_object") or item.get("title") or "")[:300]
                description = (item.get("description") or "")[:800]
                keywords_val = item.get("keywords") or []
                keywords = (
                    ", ".join(keywords_val)
                    if isinstance(keywords_val, list)
                    else str(keywords_val)
                )

                # Build the prompt message
                message = classification_prompt.format(
                    entity=entity,
                    reference=reference,
                    objet=objet,
                    description=description,
                    keywords=keywords,
                )

                # Get LLM response
                try:
                    response = llm.invoke(message)
                    response_text = (
                        response.content.strip().upper()
                        if hasattr(response, "content")
                        else str(response).upper()
                    )
                except Exception as e:
                    llm_error = e
                    logger.warning(
                        f"LLM invocation failed for item {item.get('id')}, using keyword fallback: {e}"
                    )
                    response_text = "FALLBACK"

                # Parse response - check for OUI/NON indicators
                is_relevant = "OUI" in response_text or "YES" in response_text

                # Use keyword-based scoring as confidence check
                # Only use content fields (tender_object, description, keywords), not entity/reference
                all_text = f"{objet} {description} {keywords}".lower()
                keyword_matches = sum(
                    1 for keyword in it_keywords if keyword.lower() in all_text
                )

                # Calculate relevance score
                if "FALLBACK" in response_text or llm_error:
                    # Use keyword-based score for fallback cases
                    if keyword_matches > 0:
                        relevance_score = min(
                            1.0,
                            0.5 + (keyword_matches / max(len(it_keywords), 1) * 0.5),
                        )
                    else:
                        relevance_score = 0.0
                    logger.debug(
                        f"Using keyword fallback for item {item.get('id')}: score={relevance_score}"
                    )
                else:
                    # Use LLM response-based score
                    if is_relevant:
                        # Higher score if LLM says OUI, but still consider keyword matches
                        if keyword_matches > 0:
                            relevance_score = min(
                                1.0,
                                0.8
                                + (keyword_matches / max(len(it_keywords), 1) * 0.2),
                            )
                        else:
                            # LLM OUI but no IT keyword found — penalise score.
                            # Threshold for this path is 0.7, so 0.6 will be rejected.
                            relevance_score = 0.6
                    else:
                        # LLM says NON → reject; keywords cannot override LLM judgment
                        relevance_score = 0.1

                # Clamp score to 0-1 range
                item["relevance_score"] = min(1.0, max(0.0, relevance_score))
                item["classification_method"] = "llm_with_keyword_fallback"
                item["keyword_matches"] = keyword_matches

                logger.debug(
                    "LLM classification complete",
                    item_id=item.get("id"),
                    llm_result=is_relevant,
                    score=item["relevance_score"],
                    keyword_matches=keyword_matches,
                )

                # When LLM says OUI, be permissive. When LLM says NON, always be strict.
                if is_relevant and keyword_matches > 0:
                    threshold = 0.3  # LLM OUI + keywords → permissif
                elif is_relevant:
                    threshold = (
                        0.7  # LLM OUI seul, sans keyword IT → exiger confirmation
                    )
                else:
                    threshold = 0.7  # LLM NON → strict regardless of keyword count

                # Include item if score meets threshold
                if item["relevance_score"] >= threshold:
                    item["is_relevant"] = True
                    relevant_items.append(item)
                    log_classification(
                        item["id"],
                        item["relevance_score"],
                        True,
                        keyword_matches=keyword_matches,
                        method="llm",
                    )
                else:
                    item["is_relevant"] = False
                    log_classification(
                        item["id"],
                        item["relevance_score"],
                        False,
                        keyword_matches=keyword_matches,
                        method="llm",
                    )

            except Exception as e:
                logger.error(f"Failed to classify item {item.get('id')} with LLM: {e}")
                # Fallback: use keyword matching for this item
                # Only use content fields, not entity/reference
                all_text = f"{item.get('tender_object', '')} {item.get('description', '')}".lower()
                keyword_matches = sum(
                    1 for keyword in it_keywords if keyword.lower() in all_text
                )
                if keyword_matches > 0:
                    item["relevance_score"] = min(
                        1.0, 0.5 + (keyword_matches / max(len(it_keywords), 1) * 0.5)
                    )
                    item["classification_method"] = "keyword_fallback_on_error"
                    if item["relevance_score"] >= 0.3:
                        item["is_relevant"] = True
                        relevant_items.append(item)
                    else:
                        item["is_relevant"] = False
                else:
                    item["relevance_score"] = 0.0
                    item["is_relevant"] = False

        # Set state
        state.relevant_items = relevant_items
        state.unique_items = relevant_items

        with get_db_context() as _db:
            for item in state.items_parsed:
                _upsert_company_notice_status(_db, state.company_id, item)
            _db.commit()

        state.update_stats(
            relevant_items=len(relevant_items),
            unique_items=len(relevant_items),
            classify_time_seconds=time.time() - start_time,
        )

        # Log output to JSON
        log_node_output("classify", relevant_items, run_id=state.run_id)

        duration = time.time() - start_time
        logger.info(
            "LLM-based classification completed",
            total_items=len(state.items_parsed),
            relevant_items=len(relevant_items),
            provider=cfg(state, "llm", "provider"),
            duration_seconds=duration,
            run_id=state.run_id,
        )

        return state

    except RuntimeError:
        raise
    except Exception as e:
        logger.error(
            "LLM classification failed",
            error=str(e),
            run_id=state.run_id,
            exc_info=True,
        )
        logger.info("Falling back to keyword-based classification")
        return classify_with_keywords(state)
