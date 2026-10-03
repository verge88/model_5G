FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git build-essential meson ninja-build pkg-config cmake flex bison \
    libsctp-dev libc-ares-dev libgnutls28-dev libgcrypt-dev libssl-dev libidn-dev \
    libmongoc-dev libbson-dev libyaml-dev libnghttp2-dev libmicrohttpd-dev \
    libcurl4-gnutls-dev libtins-dev libtalloc-dev python3 python3-venv \
    iproute2 tcpdump prometheus && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install \
    PyYAML==6.0.2 h2==4.2.0 pymongo==4.18.2 numpy==2.2.6 matplotlib==3.10.3
ENV PATH=/opt/venv/bin:$PATH
RUN git clone --depth 1 --branch v2.8.0 https://github.com/open5gs/open5gs.git /build/pristine \
    && test "$(git -C /build/pristine rev-parse HEAD)" = 157f611a530e292e40ec50f9d23f0ef5d4fcd6a6 \
    && cd /build/pristine && meson setup build --prefix=/opt/model5g-baseline \
    && ninja -C build -j6 && ninja -C build install
COPY patches /patches
RUN cd /build/pristine && git apply --check /patches/open5gs-v2.8.0-lab.patch \
    && git apply /patches/open5gs-v2.8.0-lab.patch \
    && meson configure build --prefix=/opt/model5g-patched \
    && ninja -C build -j6 && ninja -C build install
RUN git clone --depth 1 --branch v3.2.7 https://github.com/aligungr/UERANSIM.git /build/model5g-ueransim \
    && test "$(git -C /build/model5g-ueransim rev-parse HEAD)" = 1d1e154f869260b5e98f6905827b1bd9b8663afc \
    && cd /build/model5g-ueransim && git apply /patches/ueransim-v3.2.7-cli.patch && make -j6
WORKDIR /work
CMD ["sleep", "infinity"]
