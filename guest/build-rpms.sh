#!/usr/bin/bash
set -euo pipefail
test -f /etc/apex-builder
mkdir -p sources output/rpms local-rpms
install -m0644 rpms/gtk3-adwaita-dark.css sources/gtk3-adwaita-dark.css
tar --sort=name --mtime=@0 --owner=0 --group=0 -czf sources/apex-config.tar.gz system_files
for package in apex-config shadcn-gnome-theme gnome-shell-extension-macos-genie apex-fonts; do
    mkdir -p "output/rpms/$package/srpm" "output/rpms/$package/rpm"
    mock -r fedora-44-x86_64 --buildsrpm --spec "rpms/$package.spec" --sources sources \
        --resultdir "$PWD/output/rpms/$package/srpm"
    srpms=("output/rpms/$package/srpm/"*.src.rpm)
    test "${#srpms[@]}" = 1
    mock -r fedora-44-x86_64 --rebuild "${srpms[0]}" --resultdir "$PWD/output/rpms/$package/rpm"
    for rpm in "output/rpms/$package/rpm/"*.rpm; do
        [[ $rpm == *.src.rpm ]] && continue
        cp "$rpm" local-rpms/
    done
done
createrepo_c local-rpms
