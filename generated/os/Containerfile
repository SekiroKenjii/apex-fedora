ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG KERNEL_PROFILE=fedora
RUN --mount=type=bind,source=local-rpms,target=/tmp/apex-rpms,ro \
    --mount=type=bind,source=guest,target=/tmp/apex-guest,ro \
    --mount=type=bind,source=config,target=/tmp/apex-build-config,ro \
    bash /tmp/apex-guest/image-configure.sh "${KERNEL_PROFILE}" && bootc container lint --fatal-warnings
