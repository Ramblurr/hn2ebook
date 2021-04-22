FROM docker.io/python:3.9-buster AS base
ARG NODE_VERSION=14
ARG NPM_VERSION=6

RUN groupadd --gid 1000 node \
  && useradd --uid 1000 --gid node --shell /bin/bash --create-home node

ENV LANG=C.UTF-8
ENV DEBIAN_FRONTEND=noninteractive
ENV NPM_CONFIG_PREFIX=/home/node/.npm-global

RUN set -ex ; \
  apt-get update ; \
  apt-get  install -y gnupg2 wget curl ; \
  echo "deb https://deb.nodesource.com/node_$NODE_VERSION.x buster main" > /etc/apt/sources.list.d/nodesource.list ; \
  wget -qO- https://deb.nodesource.com/gpgkey/nodesource.gpg.key | apt-key add - ; \
  echo "deb https://dl.yarnpkg.com/debian/ stable main" > /etc/apt/sources.list.d/yarn.list ; \
  wget -qO- https://dl.yarnpkg.com/debian/pubkey.gpg | apt-key add - ; \
  apt-get update ; \
  apt-get install -yqq nodejs=$( apt-cache show nodejs | grep Version | grep nodesource| cut -c 10- ) yarn ; \
  apt-get install -yqq git jq ; \
  apt-mark hold nodejs ; \
  pip install -U pip && pip install pipenv ; \
  npm i -g npm@^$NPM_VERSION ; \
  rm -rf /var/lib/apt/lists/*

ARG CHROME_VERSION="google-chrome-stable"
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
  && echo "deb http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
  && apt-get update -qqy \
  && apt-get -qqy install ${CHROME_VERSION:-google-chrome-stable}  \
     unzip xmlstarlet python3-cairosvg python3-tinycss python3-cssselect imagemagick icnsutils \
  && rm /etc/apt/sources.list.d/google-chrome.list \
  && apt-get -y autoremove --purge \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

FROM base

RUN set -ex ; \
  npm install -g 'git+https://github.com/ramblurr/readability-extractor#0.0.1' ; \
  npm install -g 'git+https://github.com/ramblurr/srcset-parser#0.0.1'

RUN mkdir /home/node/hn2ebook
WORKDIR /home/node/hn2ebook
COPY hn2ebook hn2ebook
ADD setup.py setup.py
ENV HN2EBOOK_CONFIG=/config

RUN set -ex ; \
  chmod -R 755 . ; \
  pip install --no-cache-dir -e . ;


ENTRYPOINT ["/usr/local/bin/hn2ebook"]
