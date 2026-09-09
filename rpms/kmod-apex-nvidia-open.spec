%{!?apex_kernel_release:%{error:apex_kernel_release is required}}
%{!?apex_kernel_devel_evr:%{error:apex_kernel_devel_evr is required}}
%{!?apex_compiler_evr:%{error:apex_compiler_evr is required}}
%{!?apex_nvidia_version:%{error:apex_nvidia_version is required}}
%{!?apex_nvidia_commit:%{error:apex_nvidia_commit is required}}
%global debug_package %{nil}

Name: kmod-apex-nvidia-open
Epoch: 3
Version: %{apex_nvidia_version}
Release: 1%{?dist}
Summary: Prebuilt NVIDIA open modules for the locked Apex kernel
License: MIT OR GPL-2.0-only
URL: https://github.com/NVIDIA/open-gpu-kernel-modules
Source0: open-gpu-kernel-modules.tar.gz
Source1: nvidia-check.py
Source2: nvidia.lock.json
ExclusiveArch: x86_64
BuildRequires: kernel-devel = %{apex_kernel_devel_evr}
BuildRequires: gcc = %{apex_compiler_evr}
BuildRequires: gcc-c++ = %{apex_compiler_evr}
BuildRequires: make
BuildRequires: elfutils-libelf-devel
BuildRequires: kmod
BuildRequires: python3
Requires: kernel-uname-r = %{apex_kernel_release}
Requires: nvidia-kmod-common = 3:%{version}
Provides: nvidia-kmod = 3:%{version}
Provides: kmod-nvidia-open = 3:%{version}

%description
Four NVIDIA modules built for one Fedora kernel. This package does not build
modules at boot, load a driver, select the display GPU or change power policy.
The image assembly step must validate dependencies and regenerate its initramfs.

%prep
%setup -q -n open-gpu-kernel-modules-%{apex_nvidia_commit}

%build
python3 %{SOURCE1} compiler /usr/src/kernels/%{apex_kernel_release}/.config %{SOURCE2}
make -j2 modules CC=gcc CXX=g++ ARCH=x86_64 KERNEL_UNAME=%{apex_kernel_release} \
    SYSSRC=/usr/src/kernels/%{apex_kernel_release} \
    SYSOUT=/usr/src/kernels/%{apex_kernel_release} \
    NV_EXCLUDE_KERNEL_MODULES="nvidia-peermem nvidia-vgpu-vfio"
python3 %{SOURCE1} modules kernel-open %{SOURCE2} > modules.json

%install
install -d %{buildroot}/usr/lib/modules/%{apex_kernel_release}/extra/apex-nvidia
for module in nvidia nvidia-modeset nvidia-drm nvidia-uvm; do
    install -m0644 kernel-open/$module.ko \
        %{buildroot}/usr/lib/modules/%{apex_kernel_release}/extra/apex-nvidia/
done
install -Dm0644 modules.json %{buildroot}%{_datadir}/apex/nvidia/modules.json
install -Dm0644 %{SOURCE2} %{buildroot}%{_datadir}/apex/nvidia/source-lock.json

%check
python3 %{SOURCE1} modules \
    %{buildroot}/usr/lib/modules/%{apex_kernel_release}/extra/apex-nvidia %{SOURCE2}

%files
%license COPYING
/usr/lib/modules/%{apex_kernel_release}/extra/apex-nvidia
%{_datadir}/apex/nvidia
