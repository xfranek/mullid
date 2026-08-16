# mullid pod Apple `container` — kontener Linux na Apple silicon.
#
# wireproxy dziala w calosci w przestrzeni uzytkownika: robi UDP na zewnatrz
# i wystawia SOCKS5 do srodka. Nie potrzebuje ani /dev/net/tun, ani NET_ADMIN,
# ani trybu uprzywilejowanego.
FROM python:3.12-slim

ARG WIREPROXY_VERSION=v1.1.3
ARG TARGETARCH=arm64

# ca-certificates zostaje na stale — health() strzela po HTTPS do
# am.i.mullvad.net, zeby sprawdzic szczelnosc.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL \
      "https://github.com/whyvl/wireproxy/releases/download/${WIREPROXY_VERSION}/wireproxy_linux_${TARGETARCH}.tar.gz" \
      | tar -xz -C /usr/local/bin wireproxy \
 && chmod 755 /usr/local/bin/wireproxy \
 && /usr/local/bin/wireproxy --version \
 && apt-get purge -y curl \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY mullid/ /app/mullid/

# MULLID_HOME nie jest ustawiane: domysl to ~/.mullid, czyli /root/.mullid,
# i tam montujemy katalog z hosta (klucz, katalog relayow, state.json).
ENV MULLID_WIREPROXY_BIN=/usr/local/bin/wireproxy \
    MULLID_BIND=0.0.0.0 \
    PYTHONUNBUFFERED=1

EXPOSE 8888 8889

CMD ["python", "-m", "mullid"]
