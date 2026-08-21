# PostgreSQL 17 with pg_textsearch (BM25) and pgvector + pgvectorscale (StreamingDiskANN)
FROM postgres:17

# Install pg_textsearch v0.5.1 from pre-built package (zip containing .deb)
# Release page: https://github.com/timescale/pg_textsearch/releases/tag/v0.5.1
# Auto-detect architecture and download correct package
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates unzip && \
    ARCH=$(dpkg --print-architecture) && \
    curl -L -o /tmp/pg_textsearch.zip \
      "https://github.com/timescale/pg_textsearch/releases/download/v0.5.1/pg-textsearch-v0.5.1-pg17-${ARCH}.zip" && \
    unzip /tmp/pg_textsearch.zip -d /tmp && \
    dpkg -i /tmp/pg-textsearch-postgresql-17_0.5.1-1_${ARCH}.deb && \
    rm /tmp/pg_textsearch.zip /tmp/pg-textsearch-postgresql-17_0.5.1-1_${ARCH}.deb && \
    apt-get purge -y --auto-remove curl unzip && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install pgvector from the PGDG apt repo the base image already has configured.
# Must come before pgvectorscale, which links against it.
RUN apt-get update && \
    apt-get install -y --no-install-recommends postgresql-17-pgvector && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install pgvectorscale 0.9.0 from pre-built package (zip containing .deb + dbgsym)
# Release page: https://github.com/timescale/pgvectorscale/releases/tag/0.9.0
# Auto-detect architecture and download correct package
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates unzip && \
    ARCH=$(dpkg --print-architecture) && \
    curl -L -o /tmp/pgvectorscale.zip \
      "https://github.com/timescale/pgvectorscale/releases/download/0.9.0/pgvectorscale-0.9.0-pg17-${ARCH}.zip" && \
    unzip /tmp/pgvectorscale.zip -d /tmp && \
    dpkg -i /tmp/pgvectorscale-postgresql-17_0.9.0-Linux_${ARCH}.deb && \
    rm /tmp/pgvectorscale.zip /tmp/pgvectorscale-postgresql-17*.deb && \
    apt-get purge -y --auto-remove curl unzip && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
