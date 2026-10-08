FROM python:3.11-slim

WORKDIR /app
ENV HOME=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements-evaluator.txt /app/requirements-evaluator.txt

# The package's optional game and LLM integrations pull several GiB of
# dependencies. FarmCraft uses only its included Kaggriculture environment.
RUN pip install --no-cache-dir -r /app/requirements-evaluator.txt \
    && pip install --no-cache-dir --no-deps kaggle-environments==1.32.2

COPY docker/worker.py /app/worker.py
COPY docker/sandbox_worker.py /app/sandbox_worker.py

USER 65534:65534
ENTRYPOINT ["python"]
