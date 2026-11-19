FROM rust:1.100.0-alpine@sha256:8d0e82abfdf9a38071e07cabc5afba4ddbe077631a80e4e742a760c38beadc33 AS build
RUN apk add --no-cache build-base ca-certificates
WORKDIR /src
COPY Cargo.toml Cargo.lock rust-toolchain.toml clippy.toml ./
COPY app/server-rs ./app/server-rs
RUN cargo build --locked --release --target x86_64-unknown-linux-musl \
    && install -m 755 target/x86_64-unknown-linux-musl/release/fit /fit \
    && install -d -m 750 -o 10001 -g 10001 /data

FROM scratch
COPY --from=build /fit /fit
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build --chown=10001:10001 /data /data
COPY app/public /app/public
COPY app/server/piani /app/server/piani
WORKDIR /app
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=4 CMD ["/fit", "--healthcheck"]
ENTRYPOINT ["/fit"]
CMD ["--root", "/app/public", "--data", "/data", "--port", "8080"]
