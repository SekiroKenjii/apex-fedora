Name: apex-fonts
Version: 1.0
Release: 1%{?dist}
Summary: Geist and Maple Mono NF fonts for Apex
License: OFL-1.1
Source0: MapleMono-NF.zip
Source1: geist-font-v1.7.2.zip
BuildArch: noarch
BuildRequires: unzip
Requires: fontconfig

%description
Geist 1.7.2 for the interface and Maple Mono NF 7.9 for monospace text.

%prep
%setup -q -c -T
mkdir maple geist
unzip -q %{SOURCE0} -d maple
unzip -q %{SOURCE1} -d geist

%build

%install
mkdir -p %{buildroot}%{_datadir}/fonts/apex-maple %{buildroot}%{_datadir}/fonts/apex-geist
install -m 0644 maple/*.ttf %{buildroot}%{_datadir}/fonts/apex-maple/
install -m 0644 geist/geist-font/Geist/ttf/*.ttf %{buildroot}%{_datadir}/fonts/apex-geist/

%files
%license maple/LICENSE.txt geist/geist-font/OFL.txt
%{_datadir}/fonts/apex-maple
%{_datadir}/fonts/apex-geist

%changelog
