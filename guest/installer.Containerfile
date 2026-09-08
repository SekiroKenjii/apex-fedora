ARG TARGET_IMAGE
FROM ${TARGET_IMAGE}
RUN dnf5 -y --exclude='kernel*' install anaconda anaconda-install-img-deps anaconda-dracut \
    dracut-config-generic dracut-network net-tools grub2-efi-x64-cdboot grub2-pc-modules \
    plymouth default-fonts-core-sans default-fonts-other-sans google-noto-sans-cjk-fonts \
    xorriso squashfs-tools isomd5sum && dnf5 clean all
ARG PAYLOAD_REF
COPY guest/installer-configure.sh guest/installer-iso.yaml guest/installer-logind.conf \
    guest/installer-pam.conf guest/installer-shell.conf guest/installer-pre.conf \
    guest/installer-start.conf guest/installer-attach.conf guest/installer-diagnostics.py /apex-installer-source/
RUN \
    bash /apex-installer-source/installer-configure.sh "${PAYLOAD_REF}"
