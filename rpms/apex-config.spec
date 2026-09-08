Name: apex-config
Version: 0.1.0
Release: 1%{?dist}
Summary: Desktop defaults and diagnostic helpers for Apex
License: MIT
Source0: apex-config.tar.gz
BuildArch: noarch
BuildRequires: systemd-rpm-macros
Requires: python3
Requires: dconf

%description
Desktop defaults and local diagnostic helpers for Apex test images.

%prep
%setup -q -c

%build

%install
mkdir -p %{buildroot}
cp -a system_files/. %{buildroot}/
chmod 0755 %{buildroot}%{_libexecdir}/apex/desktop-defaults.py
chmod 0755 %{buildroot}%{_prefix}/lib/greenboot/check/required.d/20-apex-system.sh

%files
/etc/dconf/db/local.d/00-apex
%{_libexecdir}/apex
%{_userunitdir}/apex-desktop-defaults.service
%{_unitdir}/greenboot-healthcheck.service.d/20-apex.conf
%{_unitdir}/mcelog.service.d/20-apex-cpu-check.conf
%{_prefix}/lib/greenboot/check/required.d/20-apex-system.sh
%{_datadir}/apex

%changelog
