# Static dashboard server + auth edge.
FROM caddy:2.11.4-alpine
RUN setcap -r /usr/bin/caddy
COPY web/Caddyfile /etc/caddy/Caddyfile
COPY web/site /srv/site
USER 1000:1000
