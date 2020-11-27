FROM ubuntu:20.04

ENV DEBIAN_FRONTEND noninteractive

ENV LANG en_US.UTF-8
ENV LANGUAGE en_US.UTF-8
ENV LC_ALL en_US.UTF-8

RUN apt-get update && apt-get install -y \
	bash \
	locales \
	ansible \
	ruby \
	git \
	ssh \
	python3-libvirt \
	yamllint

RUN sed -i "s/# en_US\.UTF-8 UTF-8/en_US\.UTF-8 UTF-8/" /etc/locale.gen
RUN locale-gen
RUN dpkg-reconfigure locales
# Asciidoctor PDF generator for generating the manual
RUN gem install asciidoctor-pdf --pre -v 1.5.0.rc2
ADD check_yaml.sh /usr/bin/check_yaml
