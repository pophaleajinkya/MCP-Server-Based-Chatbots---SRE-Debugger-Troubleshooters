# Walmart CA roots — provides /etc/ssl/certs/ca-certificates.crt with internal CAs
FROM docker.ci.artifacts.prod.walmart.com/wce-docker/ca-roots:latest AS roots

# ==============================================================================
# Stage 1: deps — install Python dependencies only (cached independently)
# ==============================================================================
FROM hub.docker.prod.walmart.com/library/python:3.13-slim AS deps

# ---- Walmart CA certificates ----
COPY --from=roots /usr/local/share/ca-certificates /usr/local/share/ca-certificates
COPY --from=roots /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
RUN update-ca-certificates

# ---- Environment Variables ----
ENV http_proxy=http://sysproxy.wal-mart.com:8080 \
    https_proxy=http://sysproxy.wal-mart.com:8080 \
    PYTHONUNBUFFERED=1 \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    UV_INDEX_URL=https://pypi.ci.artifacts.walmart.com/artifactory/api/pypi/pythonhosted-pypi-release-remote/simple \
    UV_EXTRA_INDEX_URL=https://pypi.ci.artifacts.walmart.com/artifactory/api/pypi/intl-ecomm-svcs-pypi/simple:https://pypi.ci.artifacts.walmart.com/artifactory/api/pypi/devtools-pypi/simple \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# ---- Install OS build deps (single cached layer) ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# ---- Install uv ----
RUN pip install --no-cache-dir uv \
    --index-url https://pypi.ci.artifacts.walmart.com/artifactory/api/pypi/external-pypi/simple

# ---- Copy lock + project metadata ONLY (maximises cache hit on dep layer) ----
COPY pyproject.toml uv.lock README.md /app/

# ---- Install all dependencies into /app/.venv using the lockfile ----
# This layer is only invalidated when pyproject.toml or uv.lock change
RUN uv sync --frozen --no-install-project

# ==============================================================================
# Stage 2: test — run unit + e2e test suite (CI burst phase)
# ==============================================================================
FROM deps AS test

# ---- Copy full source ----
COPY . /app/

# ---- Install the project itself (editable) on top of cached deps ----
RUN uv sync --frozen

ARG run_tests=true
ENV run_tests=$run_tests

ARG cpd
ARG BUILDURL
ARG LOOPERID

RUN if [ "${run_tests}" = "true" ]; then \
    export CONCORDID=${cpd} LOOPERID=${LOOPERID} BUILDURL=${BUILDURL} && \
    uv run pytest --junitxml=pytest-report.xml --cov=src/ ; \
    uv run coverage xml; \
    uv run pytest tests/e2e --maxfail=1 --disable-warnings -v --tb=short; \
else \
    echo "Test execution disabled."; \
fi

RUN ls -lrt
RUN echo '===== END TEST BURST REPORT ====='

# ==============================================================================
# Stage 3: sonar — SonarQube analysis
# ==============================================================================
FROM docker.ci.artifacts.walmart.com/strati-docker/docker-sonarqube-scanner:latest AS sonar

RUN mkdir -p /app
COPY --from=test /app /app
WORKDIR /app

ARG sonarEnable
ARG github_repo_git_url
ARG github_branch_name
ARG looper_run_id
ARG job_name
ARG job_url
ARG jenkins_url
ARG looper_job_type

ENV GITHUB_REPO_GIT_URL=$github_repo_git_url \
    GITHUB_BRANCH_NAME=$github_branch_name \
    SONAR_ENABLE=$sonarEnable \
    LOOPER_RUN_ID=$looper_run_id \
    JOB_NAME=$job_name \
    JOB_URL=$job_url \
    JENKINS_URL=$jenkins_url \
    LOOPER_JOB_TYPE=$looper_job_type

RUN mkdir -p /tmp/sonar
RUN if [ "${sonarEnable}" = "true" ]; then \
      sonar-scanner -Dproject.settings=sonar-project.properties -Dsonar.scanner.metadataFilePath=/tmp/sonar/report-task.txt; \
      SONAR_EXIT=$?; \
      if [ $SONAR_EXIT -eq 0 ] && [ -f "/tmp/sonar/report-task.txt" ]; then \
        curl -k --location 'https://sonarlooperproducer.walmart.com/looper-sonar-results' \
          --form sonarResultsFile=@/tmp/sonar/report-task.txt \
          --form gitUrl="${GITHUB_REPO_GIT_URL}" \
          --form gitBranch="${GITHUB_BRANCH_NAME}" \
          --form buildUUID="${LOOPER_RUN_ID}" \
          --form jobName="${JOB_NAME}" \
          --form jobUrl="${JOB_URL}" \
          --form instanceUrl="${JENKINS_URL}" \
          --form jobType="${LOOPER_JOB_TYPE}"; \
      else \
        echo "SonarQube analysis failed or report file not found"; \
        if [ $SONAR_EXIT -ne 0 ]; then exit $SONAR_EXIT; fi; \
      fi; \
    else \
      echo "SonarQube Disabled."; \
    fi

RUN rm -rf coverage.xml pytest-report.xml
RUN ls -lrt
RUN echo '===== END SONAR PHASE ====='

# ==============================================================================
# Stage 4: runtime — lean production image
# ==============================================================================
FROM hub.docker.prod.walmart.com/library/python:3.13-slim AS runtime

# ---- Walmart CA certificates ----
COPY --from=roots /usr/local/share/ca-certificates /usr/local/share/ca-certificates
COPY --from=roots /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
RUN update-ca-certificates

# ---- Runtime environment ----
ENV http_proxy=http://sysproxy.wal-mart.com:8080 \
    https_proxy=http://sysproxy.wal-mart.com:8080 \
    PYTHONUNBUFFERED=1 \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# ---- Runtime OS deps only — no build-essential, no vim ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ---- Copy pre-built venv + app source from deps stage ----
# Does NOT re-install anything — pure file copy, very fast
COPY --from=deps /app/.venv /app/.venv
COPY src/ /app/src/
COPY resources/ /app/resources/
COPY skills/ /app/skills/
COPY entrypoint.sh /app/entrypoint.sh

# ---- Non-root user ----
ENV APP_USER=app \
    APP_GROUP=app
RUN groupadd -g 10000 $APP_GROUP && \
    useradd -u 10000 -d /app -s /bin/sh -g $APP_GROUP $APP_USER && \
    chown -R $APP_USER:$APP_USER /app && \
    chmod -R 755 /app/ && \
    chmod +x /app/entrypoint.sh

USER 10000

EXPOSE 8010
ENTRYPOINT ["/app/entrypoint.sh"]
