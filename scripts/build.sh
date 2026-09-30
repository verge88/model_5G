#!/bin/bash
set -euo pipefail
cd /build/model5g-baseline
meson setup build --prefix=/opt/model5g-baseline
ninja -C build -j 6
ninja -C build install
cp -a /work/upstream/UERANSIM /build/model5g-ueransim
cd /build/model5g-ueransim
make -j6
