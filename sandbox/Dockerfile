# Minimal sandbox image: Python 3.11 + allowlisted analysis libraries only.
# The container is always run with network_mode=none, a memory/CPU cap and a
# read-only root filesystem — see api/services/sandbox.py.
FROM python:3.11-slim

RUN pip install --no-cache-dir \
    pandas==2.2.3 \
    numpy==1.26.4 \
    scipy==1.13.1 \
    statsmodels==0.14.4 \
    prophet==1.1.6 \
    plotly==5.24.1 \
    scikit-learn==1.5.2 \
    matplotlib==3.9.2 \
    openpyxl==3.1.5 \
    kaleido==0.2.1

# pyarrow: parquet support for the cleaned-dataset handoff between steps
RUN pip install --no-cache-dir pyarrow==17.0.0

RUN useradd --create-home --uid 1001 sandbox
COPY executor.py /app/executor.py

USER sandbox
WORKDIR /workspace
ENTRYPOINT ["python", "/app/executor.py"]
