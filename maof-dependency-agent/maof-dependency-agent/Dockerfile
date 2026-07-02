FROM hub.docker.prod.walmart.com/library/python:3.11-slim as build

# ---- Environment Variables ----
ENV http_proxy=http://sysproxy.wal-mart.com:8080 \
    https_proxy=http://sysproxy.wal-mart.com:8080 \
    PYTHONUNBUFFERED=1 \
    UV_INDEX_URL=https://pypi.ci.artifacts.walmart.com/artifactory/api/pypi/pythonhosted-pypi-release-remote/simple \
    UV_EXTRA_INDEX_URL=https://pypi.ci.artifacts.walmart.com/artifactory/api/pypi/intl-ecomm-svcs-pypi/simple:https://pypi.ci.artifacts.walmart.com/artifactory/api/pypi/devtools-pypi/simple

# ---- Set working directory ----
WORKDIR /app

# ---- Install OS dependencies ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    vim \
    && rm -rf /var/lib/apt/lists/*

# ---- Install Poetry ----
RUN pip install uv --index-url https://pypi.ci.artifacts.walmart.com/artifactory/api/pypi/external-pypi/simple

# ---- Copy only dependency files first for better Docker layer caching ----
COPY pyproject.toml /app/
COPY README.md /app/

# ---- Install Python dependencies ----
RUN uv pip install --system -e .

# ---- Copy entire application ----
COPY . /app/

# ---- Test Burst Phase ----
ARG run_tests=true
ENV run_tests=$run_tests

ARG cpd
ARG BUILDURL
ARG LOOPERID

RUN if [ "${run_tests}" = "true" ]; then \
  export CONCORDID=${cpd} LOOPERID=${LOOPERID} BUILDURL=${BUILDURL} && \
   pytest --junitxml=pytest-report.xml --cov=src/ ; \
   coverage xml; \
   pytest tests/e2e --maxfail=1 --disable-warnings -v --tb=short; \
else \
   echo "test cases execution has been disabled."; \
fi

RUN ls -lrt
RUN echo '===== END TEST BURST REPORT ====='

# ==============================================================================
# Stage 3: sonar — SonarQube analysis
# ==============================================================================
FROM docker.ci.artifacts.walmart.com/strati-docker/docker-sonarqube-scanner:latest AS sonar

RUN mkdir -p /app
COPY --from=build /app /app
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
        echo "WARNING: SonarQube analysis failed or report file not found (exit=$SONAR_EXIT)"; \
      fi; \
    else \
      echo "SonarQube Disabled."; \
    fi; \
    touch /tmp/sonar-done

RUN rm -rf coverage.xml pytest-report.xml
RUN ls -lrt
RUN echo '===== END SONAR PHASE ====='

############################################################################################################
########################## APPLICATION SECTION #############################################################
############################################################################################################

FROM hub.docker.prod.walmart.com/library/python:3.11-slim

# ---- Environment Variables ----
ENV http_proxy=http://sysproxy.wal-mart.com:8080 \
    https_proxy=http://sysproxy.wal-mart.com:8080 \
    PYTHONUNBUFFERED=1

# ---- Set working directory ----
RUN mkdir -p /app
WORKDIR /app

# ---- Install minimal runtime OS dependencies (if needed) ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    vim \
    && rm -rf /var/lib/apt/lists/*

# ---- Force sonar stage to execute (required for DX Test Hub Static Gate) ----
COPY --from=sonar /tmp/sonar-done /tmp/sonar-done

# ---- Copy application and dependencies from build stage ----
COPY --from=build /app /app
COPY --from=build /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=build /usr/local/bin /usr/local/bin

# ---- Create non-root user and set permissions ----
ENV APP_USER=app
ENV APP_GROUP=app
RUN groupadd -g 10000 $APP_GROUP && \
    useradd -u 10000 -d /app -s /bin/sh -g $APP_GROUP $APP_USER && \
    chown -R $APP_USER:$APP_USER /app

# ---- Give minimal required permissions ----
RUN chmod -R 755  /app/

# ---- Switch to non-root user ----
USER 10000

# ---- Make entrypoint executable ----
RUN chmod +x /app/entrypoint.sh
EXPOSE 8010

#CMD ["python", "main.py"]
ENTRYPOINT [ "/app/entrypoint.sh" ]
