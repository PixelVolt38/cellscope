import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set, Tuple

try:
    # requests is optional; importing lazily keeps the dependency soft.
    import requests
except Exception:  # pragma: no cover - optional dep
    requests = None  # type: ignore

SCHEMA = "http://schema.org/"
PROV = "http://www.w3.org/ns/prov#"
DCAT = "http://www.w3.org/ns/dcat#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
OFLOW = "https://example.org/ontology/ontoflow#"
ONTODT = "https://example.org/ontology/ontodt#"

PREFIXES = {
    "schema": SCHEMA,
    "prov": PROV,
    "dcat": DCAT,
    "rdf": RDF,
    "oflow": OFLOW,
    "ontodt": ONTODT,
}


def _ensure_trailing_slash(value: str) -> str:
    return value if value.endswith("/") else value + "/"


def _is_uri(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _resolve_identifier(base: str, identifier: str) -> str:
    if not identifier:
        return identifier
    if _is_uri(identifier):
        return identifier
    if identifier.startswith("#"):
        return base + identifier[1:]
    return base + identifier


def _resolve_term(term: str) -> str:
    if _is_uri(term):
        return term
    if ":" in term:
        prefix, local = term.split(":", 1)
        ns = PREFIXES.get(prefix)
        if ns:
            return ns + local
        return prefix + ":" + local
    return SCHEMA + term


def _iter_values(value: Any) -> Iterable[Any]:
    if isinstance(value, list):
        for item in value:
            yield from _iter_values(item)
    else:
        yield value


def _iter_entity_refs(value: Any) -> Iterable[Tuple[str, bool]]:
    """
    Yield (value, is_literal) pairs for an entity reference field.
    """
    for item in _iter_values(value):
        if isinstance(item, dict):
            if "@id" in item:
                yield item["@id"], False
            elif "name" in item:
                yield str(item["name"]), True
        elif isinstance(item, str):
            if item.startswith("#") or _is_uri(item):
                yield item, False
            else:
                yield item, True


def _escape_literal(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\"", '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def _collect_triples(
    data: Dict[str, Any],
    base_uri: str,
) -> Set[Tuple[str, str, str, bool, Optional[str]]]:
    triples: Set[Tuple[str, str, str, bool, Optional[str]]] = set()
    graph = data.get("@graph", [])
    for entity in graph:
        subject_id = entity.get("@id")
        if not subject_id:
            continue
        subject = _resolve_identifier(base_uri, subject_id)

        types = entity.get("@type")
        if types:
            type_values = types if isinstance(types, list) else [types]
            for t in type_values:
                triples.add((subject, RDF + "type", _resolve_term(str(t)), False, None))

        name = entity.get("name")
        if isinstance(name, str):
            triples.add((subject, SCHEMA + "name", name, True, None))

        version = entity.get("version")
        if version is not None:
            triples.add((subject, SCHEMA + "version", str(version), True, None))

        content_hash = entity.get("contentHash")
        if isinstance(content_hash, dict):
            hash_value = content_hash.get("value")
            if hash_value:
                triples.add(
                    (subject, SCHEMA + "checksum", str(hash_value), True, None)
                )
            algo = content_hash.get("algorithm")
            if algo:
                triples.add(
                    (
                        subject,
                        SCHEMA + "checksumAlgorithm",
                        str(algo),
                        True,
                        None,
                    )
                )

        sensitivity = entity.get("sensitivity")
        if sensitivity is not None:
            triples.add(
                (
                    subject,
                    SCHEMA + "additionalProperty",
                    str(sensitivity),
                    True,
                    None,
                )
            )

        category = entity.get("category")
        if category is not None:
            for cat_value, is_literal in _iter_entity_refs(category):
                if is_literal:
                    triples.add(
                        (subject, SCHEMA + "category", str(cat_value), True, None)
                    )
                else:
                    triples.add(
                        (
                            subject,
                            SCHEMA + "category",
                            _resolve_identifier(base_uri, str(cat_value)),
                            False,
                            None,
                        )
                    )

        creator = entity.get("creator")
        for creator_value, is_literal in _iter_entity_refs(creator):
            if is_literal:
                triples.add(
                    (subject, SCHEMA + "creator", str(creator_value), True, None)
                )
            else:
                triples.add(
                    (
                        subject,
                        SCHEMA + "creator",
                        _resolve_identifier(base_uri, str(creator_value)),
                        False,
                        None,
                    )
                )

        encoding_format = entity.get("encodingFormat") or entity.get(SCHEMA + "encodingFormat")
        if encoding_format:
            for value in _iter_values(encoding_format):
                if value is None:
                    continue
                triples.add(
                    (subject, SCHEMA + "encodingFormat", str(value), True, None)
                )

        keywords = entity.get("keywords") or entity.get(SCHEMA + "keywords")
        if keywords:
            for kw in _iter_values(keywords):
                if kw is None:
                    continue
                triples.add(
                    (subject, SCHEMA + "keywords", str(kw), True, None)
                )

        activity_roles = entity.get("roles")
        if activity_roles:
            for role_entry in _iter_values(activity_roles):
                if not role_entry:
                    continue
                triples.add(
                    (subject, SCHEMA + "roles", str(role_entry), True, None)
                )
                if isinstance(role_entry, str) and ":" in role_entry:
                    var_name, role_label = role_entry.split(":", 1)
                    var_name = var_name.strip()
                    role_label = role_label.strip()
                    if var_name:
                        var_identifier = _resolve_identifier(base_uri, f"#var-{var_name}")
                        triples.add(
                            (var_identifier, SCHEMA + "roleName", role_label, True, None)
                        )

        for predicate in ("prov:used", "prov:wasGeneratedBy", "prov:wasDerivedFrom", "prov:wasRevisionOf"):
            pred_iri = _resolve_term(predicate)
            values = entity.get(predicate)
            if not values:
                values = entity.get(pred_iri)
            if not values:
                continue
            for ref_value, is_literal in _iter_entity_refs(values):
                if is_literal:
                    triples.add((subject, pred_iri, str(ref_value), True, None))
                else:
                    triples.add(
                        (
                            subject,
                            pred_iri,
                            _resolve_identifier(base_uri, str(ref_value)),
                            False,
                            None,
                        )
                    )

    return triples


def _render_sparql(
    triples: Set[Tuple[str, str, str, bool, Optional[str]]]
) -> str:
    prefix_lines = [
        f"PREFIX {prefix}: <{iri}>"
        for prefix, iri in PREFIXES.items()
    ]
    prefix_block = "\n".join(sorted(set(prefix_lines)))

    body_lines = []
    for subj, pred, obj, is_literal, datatype in sorted(triples):
        if is_literal:
            literal = _escape_literal(obj)
            if datatype:
                body_lines.append(
                    f"<{subj}> <{pred}> \"{literal}\"^^<{datatype}> ."
                )
            else:
                body_lines.append(f"<{subj}> <{pred}> \"{literal}\" .")
        else:
            body_lines.append(f"<{subj}> <{pred}> <{obj}> .")
    body = "\n  ".join(body_lines)
    return f"{prefix_block}\n\nINSERT DATA {{\n  {body}\n}}"


def index_crate(
    crate_dir: Optional[str] = None,
    crate_metadata: Optional[Dict[str, Any]] = None,
    *,
    endpoint: Optional[str] = None,
    output_path: Optional[str] = None,
    base_uri: Optional[str] = None,
    session: Optional[Any] = None,
    auth: Optional[Any] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Generate a SPARQL UPDATE payload projecting the RO-Crate metadata.

    Parameters
    ----------
    crate_dir:
        Directory containing an RO-Crate (expects ro-crate-metadata.json).
    crate_metadata:
        Optional in-memory JSON-LD (already loaded). If provided, crate_dir is
        only used for defaults (e.g., base URI, output path).
    endpoint:
        When provided, issue an HTTP POST with the generated payload.
    output_path:
        Where to write the SPARQL UPDATE. Defaults to <crate>/index/last_update.sparql.
    base_uri:
        Base URI used to resolve relative identifiers. Defaults to file:// URI
        derived from crate_dir.
    session:
        Optional requests-like session for HTTP interactions (mainly test hooks).
    auth:
        Optional requests-compatible auth object (e.g., tuple username/password).
    headers:
        Extra headers to merge with the default SPARQL Content-Type header.
    timeout:
        Optional request timeout (seconds) when POSTing to an endpoint.
    """

    if crate_metadata is None:
        if not crate_dir:
            raise ValueError("crate_dir is required when crate_metadata is not provided")
        crate_path = Path(crate_dir)
        metadata_path = crate_path / "ro-crate-metadata.json"
        crate_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    else:
        crate_path = Path(crate_dir) if crate_dir else None

    if crate_path and base_uri is None:
        base_uri = _ensure_trailing_slash(crate_path.resolve().as_uri())
    base_uri = base_uri or "https://cellscope.local/crate/"

    triples = _collect_triples(crate_metadata, base_uri)
    sparql_payload = _render_sparql(triples)

    if output_path:
        output_file = Path(output_path)
    elif crate_path:
        output_file = crate_path / "index" / "last_update.sparql"
    else:
        output_file = Path("last_update.sparql")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(sparql_payload, encoding="utf-8")

    post_status: Optional[int] = None
    if endpoint:
        if requests is None:
            raise RuntimeError("requests is required to POST to an endpoint")
        http = session or requests
        post_headers = {"Content-Type": "application/sparql-update"}
        if headers:
            post_headers.update(headers)
        response = http.post(
            endpoint,
            data=sparql_payload.encode("utf-8"),
            headers=post_headers,
            auth=auth,
            timeout=timeout,
        )
        post_status = response.status_code
        response.raise_for_status()

    return {
        "triples": len(triples),
        "output": str(output_file),
        "endpoint": endpoint,
        "status": post_status,
    }


__all__ = ["index_crate"]
