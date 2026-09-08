ARG TOOLBOX_IMAGE
FROM ${TOOLBOX_IMAGE}
RUN dnf5 -y install dosfstools e2fsprogs util-linux-core policycoreutils selinux-policy-targeted qemu-img bootc bootupd grub2-tools grub2-tools-extra grub2-pc-modules grub2-efi-x64-cdboot shim-x64 xorriso squashfs-tools isomd5sum \
    && for tool in mkfs.vfat mkfs.ext4 sfdisk setfiles qemu-img bootc bootupctl xorriso mksquashfs implantisomd5; do command -v "$tool" || exit 1; done \
    && test -s /etc/selinux/targeted/contexts/files/file_contexts \
    && mkdir -p /boot/efi && cp -a /usr/lib/efi/*/*/EFI /boot/efi/ \
    && test -s /boot/efi/EFI/fedora/gcdx64.efi \
    && test -s /usr/lib/grub/i386-pc/boot_hybrid.img \
    && dnf5 clean all
