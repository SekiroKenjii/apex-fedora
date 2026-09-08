Name: shadcn-gnome-theme
Version: 1.0.0
Release: 2.apex%{?dist}
Summary: Graphite theme for GNOME and GTK
License: MIT
URL: https://github.com/SekiroKenjii/shadcn-gnome
Source0: shadcn-gnome.tar.gz
Source1: gtk3-adwaita-dark.css
BuildArch: noarch
BuildRequires: nodejs
Requires: gtk3

%description
Graphite GTK and GNOME Shell theme, built from a pinned source archive.

%prep
%setup -q -n shadcn-gnome-39d566801b07c7ef6af4377ef58904a019e9693b

%build
node lib/build-theme.mjs graphite

%install
mkdir -p %{buildroot}%{_datadir}/themes/Shadcn-Graphite/gnome-shell
cp -a build/graphite/gtk-3.0 build/graphite/gtk-4.0 %{buildroot}%{_datadir}/themes/Shadcn-Graphite/
cp build/graphite/shell/gnome-shell.css %{buildroot}%{_datadir}/themes/Shadcn-Graphite/gnome-shell/apex-overrides.css
install -Dm0644 %{SOURCE1} %{buildroot}%{_datadir}/themes/Adwaita-dark/gtk-3.0/gtk.css

%files
%license LICENSE
%{_datadir}/themes/Shadcn-Graphite
%dir %{_datadir}/themes/Adwaita-dark
%{_datadir}/themes/Adwaita-dark/gtk-3.0

%changelog
