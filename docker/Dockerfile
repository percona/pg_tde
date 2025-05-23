FROM postgres:16

RUN apt-get update; \
    apt-get install -y --no-install-recommends \
    curl \
    libssl-dev \
    gcc \
    postgresql-server-dev-16 \
    make \
    libcurl4-openssl-dev

WORKDIR /opt/pg_tde

COPY . .

RUN make USE_PGXS=1 MAJORVERSION=16 && \
    make USE_PGXS=1 install
RUN cp /usr/share/postgresql/postgresql.conf.sample /etc/postgresql/postgresql.conf; \
    echo "shared_preload_libraries = 'pg_tde'" >> /etc/postgresql/postgresql.conf; \
    #    echo "log_min_messages = debug3" >> /etc/postgresql/postgresql.conf; \
    #    echo "log_min_error_statement = debug3" >> /etc/postgresql/postgresql.conf; \
    chown postgres /etc/postgresql/tde_conf.json; \
    mkdir -p /docker-entrypoint-initdb.d
COPY ./docker/pg-tde-create-ext.sh /docker-entrypoint-initdb.d/pg-tde-create-ext.sh
COPY ./docker/pg-tde-streaming-repl.sh /docker-entrypoint-initdb.d/pg-tde-streaming-repl.sh

VOLUME /etc/postgresql/

CMD ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf"]
