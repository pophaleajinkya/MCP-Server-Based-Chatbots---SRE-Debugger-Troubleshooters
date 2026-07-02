FROM hub.docker.prod.walmart.com/library/python:3.11-slim as build

# ---- Environment Variables ----
ENV http_proxy=http://sysproxy.wal-mart.com:8080 \
    https_proxy=http://sysproxy.wal-mart.com:8080 \
    PYTHONUNBUFFERED=1 \
    UV_INDEX_URL=https://pypi.ci.artifacts.walmart.com/artifactory/api/pypi/pythonhosted-pypi-release-remote/simple \
    UV_EXTRA_INDEX_URL=https://pypi.ci.artifacts.walmart.com/artifactory/api/pypi/intl-ecomm-svcs-pypi/simple:https://pypi.ci.artifacts.walmart.com/artifactory/api/pypi/devtools-pypi/simple

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv --index-url https://pypi.ci.artifacts.walmart.com/artifactory/api/pypi/external-pypi/simple

COPY pyproject.toml /app/
COPY README.md /app/

RUN uv pip install --system -e .

COPY . /app/

# ---- Test Phase ----
ARG run_tests=true
ENV run_tests=$run_tests
ARG cpd
ARG BUILDURL
ARG LOOPERID
RUN if [ "${run_tests}" = "true" ]; then \
    export CONCORDID=${cpd} LOOPERID=${LOOPERID} BUILDURL=${BUILDURL} && \
    pytest --junitxml=pytest-report.xml --cov=src/ ; \
    coverage xml; \
else \
    echo "test cases execution has been disabled."; \
fi

RUN echo '===== END TEST PHASE ====='

# ---- SonarQube Phase ----
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

ENV GITHUB_REPO_GIT_URL=$github_repo_git_url
ENV GITHUB_BRANCH_NAME=$github_branch_name
ENV SONAR_ENABLE=$sonarEnable
ENV LOOPER_RUN_ID=$looper_run_id
ENV JOB_NAME=$job_name
ENV JOB_URL=$job_url
ENV JENKINS_URL=$jenkins_url
ENV LOOPER_JOB_TYPE=$looper_job_type

RUN mkdir -p /tmp/sonar
RUN if [ "${sonarEnable}" = "true" ]; then \
      echo "Running SonarQube analysis..."; \
      sonar-scanner -Dproject.settings=sonar-project.properties -Dsonar.scanner.metadataFilePath=/tmp/sonar/report-task.txt || true; \
      SONAR_EXIT=$?; \
      if [ $SONAR_EXIT -eq 0 ] && [ -f "/tmp/sonar/report-task.txt" ]; then \
        echo "SonarQube analysis succeeded, uploading results..."; \
        curl -k --location 'https://sonarlooperproducer.walmart.com/looper-sonar-results' \
          --form sonarResultsFile=@/tmp/sonar/report-task.txt \
          --form gitUrl="${GITHUB_REPO_GIT_URL}" \
          --form gitBranch="${GITHUB_BRANCH_NAME}" \
          --form buildUUID="${LOOPER_RUN_ID}" \
          --form jobName="${JOB_NAME}" \
          --form jobUrl="${JOB_URL}" \
          --form instanceUrl="${JENKINS_URL}" \
          --form jobType="${LOOPER_JOB_TYPE}" || echo "Warning: Failed to upload SonarQube results"; \
      else \
        echo "Warning: SonarQube analysis failed or report file not found (exit code: $SONAR_EXIT)"; \
        echo "Build will continue despite SonarQube failure"; \
      fi; \
    else \
      echo "SonarQube Disabled."; \
    fi
RUN rm -rf coverage xml
RUN rm -rf pytest-report.xml
RUN echo '===== END SONAR PHASE ====='

############################################################################################################
########################## APPLICATION SECTION #############################################################
############################################################################################################

FROM hub.docker.prod.walmart.com/library/python:3.11-slim

ENV http_proxy=http://sysproxy.wal-mart.com:8080 \
    https_proxy=http://sysproxy.wal-mart.com:8080 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /app
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /app /app
COPY --from=build /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=build /usr/local/bin /usr/local/bin

ENV APP_USER=app
ENV APP_GROUP=app
RUN groupadd -g 10000 $APP_GROUP && \
    useradd -u 10000 -d /app -s /bin/sh -g $APP_GROUP $APP_USER && \
    chown -R $APP_USER:$APP_USER /app

RUN chmod -R 755 /app/

USER 10000

RUN chmod +x /app/entrypoint.sh
EXPOSE 8020

ENTRYPOINT ["/app/entrypoint.sh"]
