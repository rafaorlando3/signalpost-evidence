FROM python:3.12.15-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
COPY free_search.py public_recruiting.py publication.py attribution.py social_ownership.py hiring_discovery.py organization_types.json output_contract.py cli.py validate.py readable_report.py report.py agent.py evaluator.py insights.py search.py site_discovery.py frozen_registry.py registry_discovery.py contacts.py business_identity.py audit.py ./
ENTRYPOINT ["python", "-B", "cli.py"]
