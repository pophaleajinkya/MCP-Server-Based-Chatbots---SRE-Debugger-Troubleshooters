# =============================================================================
# STAGE 1: Build
# =============================================================================
FROM docker.ci.artifacts.walmart.com/hub-docker-release-remote/node:20-slim AS build

WORKDIR /app

# Create non-root user first
ENV APP_USER=app
ENV APP_GROUP=app
RUN groupadd -g 10000 $APP_GROUP && \
    useradd -u 10000 -d /home/$APP_USER -s /bin/bash -g $APP_GROUP $APP_USER

# Copy package files first for better layer caching
COPY package.json .npmrc* ./
RUN [ -f .npmrc ] || echo "registry=https://npme.walmart.com/" >> ./.npmrc
COPY package-lock.json ./

# Install dependencies — use ci for reproducible, locked installs
RUN npm ci --legacy-peer-deps

# Copy source code
COPY . .

# Build Next.js production bundle in the build stage where all deps are available.
# pipefail ensures a `next build` failure is not masked by `tee`.
ENV NODE_ENV=production
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN npm run build 2>&1 | tee build.log
SHELL ["/bin/sh", "-c"]

# Hard-fail if the build did not produce a valid production bundle
RUN if [ ! -f /app/.next/BUILD_ID ]; then \
      echo "ERROR: .next/BUILD_ID not found — Next.js build failed or is incomplete!"; \
      cat build.log; \
      exit 1; \
    fi

RUN echo "===== END BUILD PHASE ====="

# =============================================================================
# STAGE 2: Test
# =============================================================================
FROM build AS test

ARG looperId
ARG cpd
ARG buildUrl
ARG tbBuildVersion
ARG github_repo_git_url
ARG github_branch_name
ARG looper_job_type

# Reduce noisy warnings and silence test logs in CI
ENV NODE_OPTIONS=--no-deprecation
ENV SILENCE_TEST_LOGS=true

# Propagate build version and metadata to TestBurst
ENV TB_BUILD_VERSION=${tbBuildVersion}
ENV CONCORDID=${cpd}
ENV BUILDURL=${buildUrl}
ENV LOOPER_RUN_ID=${looperId}
ENV LOOPERID=${looperId}
ENV GITHUB_REPO_GIT_URL=${github_repo_git_url}
ENV GITHUB_BRANCH_NAME=${github_branch_name}
ENV LOOPER_JOB_TYPE=${looper_job_type}

# Echo TestBurst metadata for diagnostics
RUN echo "TestBurst metadata: TB_BUILD_VERSION=$TB_BUILD_VERSION CONCORDID=$CONCORDID LOOPER_RUN_ID=$LOOPER_RUN_ID GITHUB=$GITHUB_REPO_GIT_URL BRANCH=$GITHUB_BRANCH_NAME"

# Mark and run unit tests with coverage
ENV TESTBURST_TESTTYPE=unit
ENV TB_TEST_TYPE=unit
RUN npm run test:coverage -- --CONCORDID=${cpd} --BUILDURL=${buildUrl} --LOOPERID=${looperId}

RUN echo "===== END TESTS PHASE ====="

# =============================================================================
# STAGE 3: Sonar Validation
# =============================================================================
FROM docker.ci.artifacts.walmart.com/strati-docker/docker-sonarqube-scanner:latest AS sonar

ARG sonarEnable
ARG job_name
ARG job_url
ARG jenkins_url
ARG looper_run_id
ARG github_repo_git_url
ARG github_branch_name
ARG looper_job_type

ENV JOB_NAME=$job_name
ENV JOB_URL=$job_url
ENV JENKINS_URL=$jenkins_url
ENV LOOPER_RUN_ID=$looper_run_id
ENV GITHUB_REPO_GIT_URL=$github_repo_git_url
ENV GITHUB_BRANCH_NAME=$github_branch_name
ENV LOOPER_JOB_TYPE=$looper_job_type
ENV SONAR_ENABLE=$sonarEnable

RUN mkdir -p /app
COPY --from=build /app /app
# Copy coverage files from test stage
COPY --from=test /app/coverage /app/coverage
WORKDIR /app

RUN echo "JOB_NAME -> ${JOB_NAME}"
RUN echo "JOB_URL -> ${JOB_URL}"
RUN echo "JENKINS_URL -> ${JENKINS_URL}"
RUN echo "LOOPER_RUN_ID -> ${LOOPER_RUN_ID}"
RUN echo "GITHUB_REPO_GIT_URL -> ${GITHUB_REPO_GIT_URL}"
RUN echo "GITHUB_BRANCH_NAME -> ${GITHUB_BRANCH_NAME}"
RUN echo "LOOPER_JOB_TYPE -> ${LOOPER_JOB_TYPE}"
RUN echo "SONAR_ENABLE -> ${SONAR_ENABLE}"

RUN if [ "${sonarEnable}" = "true" ]; then \
      sonar-scanner -Dproject.settings=sonar-project.properties \
        -Dsonar.scanner.metadataFilePath=/tmp/sonar-report.json; \
      SONAR_EXIT=$?; \
      if [ $SONAR_EXIT -eq 0 ] && [ -f /tmp/sonar-report.json ]; then \
        curl -k --location https://sonarlooperproducer.walmart.com/looper-sonar-results \
          --form sonarResultsFile=@/tmp/sonar-report.json \
          --form jobName="${JOB_NAME}" \
          --form jobUrl="${JOB_URL}" \
          --form instanceUrl="${JENKINS_URL}" \
          --form buildUUID="${LOOPER_RUN_ID}" \
          --form gitUrl="${GITHUB_REPO_GIT_URL}" \
          --form gitBranch="${GITHUB_BRANCH_NAME}" \
          --form jobType="${LOOPER_JOB_TYPE}"; \
      else \
        echo "SonarQube analysis failed or report file not found"; \
        if [ $SONAR_EXIT -ne 0 ]; then exit $SONAR_EXIT; fi; \
      fi; \
    else \
      echo "SonarQube Disabled."; \
    fi

RUN echo "===== END SONAR PHASE ====="

# =============================================================================
# STAGE 4: Production (Next.js)
# =============================================================================
FROM docker.ci.artifacts.walmart.com/hub-docker-release-remote/node:20-slim

WORKDIR /app

# Create non-root user
ENV APP_USER=app
ENV APP_GROUP=app
RUN groupadd -g 10000 $APP_GROUP && \
    useradd -u 10000 -d /home/$APP_USER -s /bin/bash -g $APP_GROUP $APP_USER

# Runtime configuration
# All other runtime config (PingFed, ADK, etc.) is loaded at startup
# from /secrets/.env.* via src/instrumentation.ts
ENV NODE_ENV=production
ENV PORT=3000

# Copy source code (node_modules and .next excluded by .dockerignore)
COPY . .

# Copy linux-compatible node_modules from build stage
COPY --from=build /app/node_modules ./node_modules

# Copy the pre-built Next.js production bundle from Stage 1
COPY --from=build /app/.next ./.next

# Final verification — fail the image build if .next is not valid
RUN if [ ! -f /app/.next/BUILD_ID ]; then \
      echo "FATAL: .next/BUILD_ID missing in production image!"; \
      exit 1; \
    fi

# Clean up build artifacts not needed at runtime
RUN rm -f build.log

# Set permissions
RUN chown -R $APP_USER:$APP_GROUP /app && \
    chmod -R 755 /app

# Switch to non-root user
USER 10000

EXPOSE 3000

CMD ["node_modules/.bin/next", "start", "-p", "3000"]
