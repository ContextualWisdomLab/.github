# Doctoring: CWL ecosystem integration standards

This record supports the organization-level integration profile. Product-domain scientific decisions remain in the owning repository's doctoring/research documentation.

## Design implications

- **CloudEvents 1.0** provides a vendor-neutral event data model. CWL uses CloudEvents `specversion: "1.0"` and keeps organization metadata under the event `data` object so the profile is explicit and contract-testable.
- **OpenAPI 3.2.0** is the published OpenAPI baseline for new shared synchronous interfaces.
- **AsyncAPI 3.1.0** is the current published baseline for repositories that publish asynchronous channel contracts.
- **JSON Schema Draft 2020-12** is the baseline for shared JSON contracts.
- **RFC 9457** defines Problem Details for HTTP APIs and supersedes RFC 7807.
- **RFC 9562** defines UUIDs; UUIDv7 supplies a time-ordered Unix-millisecond layout appropriate for organization-level event/command/correlation identifiers when time-ordering is useful.
- **W3C Trace Context** defines stable cross-service tracing headers. The 2021 Recommendation is used as the production baseline rather than making a draft-level successor a hard dependency. The CWL v1 envelope profile pins traceparent version `00` and rejects the Recommendation's forbidden all-zero trace and parent identifiers.
- **W3C PROV-O** supplies a standard vocabulary for provenance entities, activities, and agents when products expose provenance graphs.

## APA 7th references

AsyncAPI Initiative. (2026). *AsyncAPI specification (Version 3.1.0).* https://www.asyncapi.com/docs/reference/specification/v3.1.0

Cloud Native Computing Foundation. (2022). *CloudEvents specification (Version 1.0.2).* https://github.com/cloudevents/spec/tree/v1.0.2

Davis, K., Peabody, B., & Leach, P. (2024). *Universally unique identifiers (UUIDs)* (RFC 9562). Internet Engineering Task Force. https://doi.org/10.17487/RFC9562

Lebo, T., Sahoo, S., & McGuinness, D. (Eds.). (2013). *PROV-O: The PROV ontology.* World Wide Web Consortium. https://www.w3.org/TR/prov-o/

Nottingham, M., Wilde, E., & Dalal, S. (2023). *Problem details for HTTP APIs* (RFC 9457). Internet Engineering Task Force. https://doi.org/10.17487/RFC9457

OpenAPI Initiative. (2025). *OpenAPI specification (Version 3.2.0).* Linux Foundation. https://spec.openapis.org/oas/v3.2.0.html

World Wide Web Consortium. (2021). *Trace Context.* https://www.w3.org/TR/trace-context/

Wright, A., Andrews, H., Hutton, B., & Dennis, G. (2022). *JSON Schema: A media type for describing JSON documents (Draft 2020-12).* JSON Schema. https://json-schema.org/draft/2020-12/json-schema-core
