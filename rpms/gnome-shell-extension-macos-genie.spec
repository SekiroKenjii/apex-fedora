Name: gnome-shell-extension-macos-genie
Version: 1.1
Release: 1.apex%{?dist}
Summary: Window minimize and restore animation for GNOME Shell
License: GPL-2.0-or-later
URL: https://github.com/SekiroKenjii/macos-genie
Source0: macos-genie.tar.gz
BuildArch: noarch
BuildRequires: glib2
Requires: gnome-shell >= 50
Requires: gnome-shell < 51

%description
Window animation extension packaged for GNOME Shell 50.

%prep
%setup -q -n macos-genie-375f785b74b7903e48923e88b250e10cd813fd13

%build
glib-compile-schemas --strict schemas

%install
mkdir -p %{buildroot}%{_datadir}/gnome-shell/extensions/macos-genie@thuongvo.dev
cp *.js metadata.json %{buildroot}%{_datadir}/gnome-shell/extensions/macos-genie@thuongvo.dev/
cp -a schemas %{buildroot}%{_datadir}/gnome-shell/extensions/macos-genie@thuongvo.dev/

%files
%license LICENSE
%{_datadir}/gnome-shell/extensions/macos-genie@thuongvo.dev

%changelog
