# MinIO no longer publishes container images (the Docker Hub repository is gone and quay.io
# refuses pulls), so this builds the pinned release from its source: same server, same S3 API.
# The commit check makes sure the tag still points where it did when this file was written.
FROM golang:1.24.7-alpine AS build
ARG MINIO_RELEASE=RELEASE.2025-09-07T16-13-09Z
ARG MINIO_COMMIT=07c3a429bfed433e49018cb0f78a52145d4bedeb
RUN apk add --no-cache git
RUN git clone --depth 1 --branch "$MINIO_RELEASE" https://github.com/minio/minio /src
WORKDIR /src
RUN test "$(git rev-parse HEAD)" = "$MINIO_COMMIT"
RUN CGO_ENABLED=0 GOTOOLCHAIN=local go build -trimpath -ldflags "-s -w" -o /minio .

FROM alpine:3.22
RUN adduser -D -u 10002 minio && mkdir /data && chown minio /data
COPY --from=build /minio /usr/local/bin/minio
USER minio
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
