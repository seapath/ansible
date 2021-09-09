# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

FROM ubuntu:20.04

ENV DEBIAN_FRONTEND noninteractive

ENV LANG en_US.UTF-8
ENV LANGUAGE en_US.UTF-8
ENV LC_ALL en_US.UTF-8

RUN apt-get update && apt-get install -y \
	bash \
	locales \
	ruby \
	git \
	ssh \
	python3-libvirt \
	docker.io \
	docker-compose \
	yamllint \
	ansible \
	python3-pip

RUN sed -i "s/# en_US\.UTF-8 UTF-8/en_US\.UTF-8 UTF-8/" /etc/locale.gen
RUN locale-gen
RUN dpkg-reconfigure locales
# Asciidoctor PDF generator for generating the manual
RUN gem install asciidoctor-pdf --pre -v 1.5.0.rc2
ADD check_yaml.sh /usr/bin/check_yaml
ADD documentation_requirements.txt /tmp/requirements.txt
RUN python3 -m pip install -r /tmp/requirements.txt
