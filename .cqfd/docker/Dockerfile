# Copyright (C) 2025, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

FROM debian:12

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8

RUN set -x \
    && apt-get update \
    && apt-get install -y \
        curl \
        libarchive-tools \
        locales \
        git \
        python3-full \
        python3-matplotlib \
        rstcheck \
        rsync \
        ruby-asciidoctor-pdf \
        npm \
        vim \
    && sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && locale-gen \
    && python3 -m venv --system-site-packages /env \
    && /env/bin/pip install \
        ansible-core~=2.16.0 \
        ansible-lint \
        yamllint \
        six \
        netaddr \
        jmespath \
    && rm -rf /var/lib/{apt,dpkg,cache,log}/*

ENV PATH="/env/bin:/env/usr/bin:/env/sbin:/env/usr/sbin:$PATH"

COPY check_yaml.sh /usr/bin/check_yaml
