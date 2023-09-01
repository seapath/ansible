# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

FROM debian:12

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8

RUN set -x \
    && apt-get update \
    && apt-get install -y \
        git \
        python3-full \
        rstcheck \
        rsync \
        ruby-asciidoctor-pdf \
        vim \
    && python3 -m venv --system-site-packages /env \
    && /env/bin/pip install ansible==2.9.27 ansible-lint==5.4.0 yamllint six netaddr \
    && rm -rf /var/lib/{apt,dpkg,cache,log}/*

ENV PATH="$PATH:/env/bin:/env/usr/bin:/env/sbin:/env/usr/sbin"

COPY check_yaml.sh /usr/bin/check_yaml
