# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND noninteractive

ENV LANG en_US.UTF-8
ENV LANGUAGE en_US.UTF-8
ENV LC_ALL en_US.UTF-8

RUN set -x \
    && apt-get update \
    && apt-get install -y \
        ansible-lint \
        bash \
        docker.io \
        docker-compose \
        git \
        locales \
        python3-docutils \
        python3-libvirt \
        python3-netaddr \
        python3-pip \
        python3-pygments \
        python3-sphinx \
	python3-matplotlib \
        python3-sphinx-notfound-page \
        rstcheck \
        rsync \
        ruby-asciidoctor-pdf \
        ssh \
        vim \
        yamllint \
    && sed -i "s/# en_US\.UTF-8 UTF-8/en_US\.UTF-8 UTF-8/" /etc/locale.gen \
    && locale-gen \
    && dpkg-reconfigure locales \
    && pip install "ansible>=2.9,<2.10,!=2.9.10" \
    && rm -rf /var/lib/{apt,dpkg,cache,log}/*

COPY check_yaml.sh /usr/bin/check_yaml
