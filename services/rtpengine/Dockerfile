# RTPEngine Dockerfile
# Based on Debian Bullseye for compatibility with required libraries

FROM debian:bullseye-slim AS builder

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    git \
    libpcre3-dev \
    libglib2.0-dev \
    libavahi-client-dev \
    libhiredis-dev \
    libjpeg-dev \
    libjson-glib-dev \
    liblua5.3-dev \
    libspandsp-dev \
    libssl-dev \
    libxmlrpc-core-c3-dev \
    libcurl4-openssl-dev \
    libbcg729-dev \
    libsystemd-dev \
    zlib1g-dev \
    iptables \
    markdown \
    libopus-dev \
    libsrtp2-dev \
    dpkg-dev

# Clone rtpengine source
WORKDIR /src
RUN git -c http.sslVerify=false clone https://github.com/sipwise/rtpengine.git -b mr10.5.1.1 rtpengine-src

# Build rtpengine
WORKDIR /src/rtpengine-src
RUN ./debian/flavours/no_ngcp
RUN dpkg-buildpackage -b -uc -us

# Create final image
FROM debian:bullseye-slim

# Install runtime dependencies from the builder
COPY --from=builder /src/*.deb /src/
RUN apt-get update && \
    apt-get install -y --no-install-recommends /src/*.deb && \
    rm -rf /var/lib/apt/lists/* /src/*.deb

# Expose ports
EXPOSE 2223/tcp
EXPOSE 10000-20000/udp

# Entrypoint
ENTRYPOINT ["rtpengine"]
CMD ["--help"]
