FROM python@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
COPY agent.py evaluator.py insights.py search.py site_discovery.py frozen_registry.py registry_discovery.py contacts.py ./
ENTRYPOINT ["python", "evaluator.py"]
