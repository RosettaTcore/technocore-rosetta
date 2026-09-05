from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_static_origin_exposes_only_closed_read_only_paths() -> None:
    bootstrap = (ROOT / "deploy/rosetta-static-origin-http.conf").read_text()
    nginx = (ROOT / "deploy/rosetta-static-origin-https.conf").read_text()

    assert "listen 80 default_server" in bootstrap
    assert "location ^~ /.well-known/acme-challenge/" in bootstrap
    assert "location / {\n        return 404;" in bootstrap
    assert "__ROSETTA_PUBLIC_IP__" in nginx
    assert "disable_symlinks on" in nginx
    assert "autoindex off" in nginx
    assert "limit_except GET HEAD { deny all; }" in nginx
    assert 'Access-Control-Allow-Origin "*"' in nginx
    assert "Content-Security-Policy \"default-src 'none'" in nginx
    assert "Strict-Transport-Security" in nginx
    assert "location = /.well-known/agent.json" in nginx
    assert "location = /service-card.json" in nginx
    assert "location = /service-card.attestation.json" in nginx
    assert "location = /skill.md" in nginx
    assert "^/schemas/rosetta-(request|result)-v1\\.json$" in nginx
    assert "^/reports/[0-9a-f]{64}/" in nginx
    assert "proxy_pass" not in nginx
    assert "fastcgi_pass" not in nginx


def test_ip_certificate_is_pinned_renewed_and_monitored() -> None:
    installer = (ROOT / "deploy/install-rosetta-static-origin.sh").read_text()
    renewer = (ROOT / "deploy/renew-rosetta-ip-certificate.sh").read_text()
    checker = (ROOT / "deploy/check-rosetta-static-origin.sh").read_text()
    renewal_unit = (ROOT / "deploy/rosetta-certificate-renew.service").read_text()
    renewal_timer = (ROOT / "deploy/rosetta-certificate-renew.timer").read_text()
    health_unit = (ROOT / "deploy/rosetta-static-origin-healthcheck.service").read_text()
    health_timer = (ROOT / "deploy/rosetta-static-origin-healthcheck.timer").read_text()

    pinned = (
        "certbot/certbot@sha256:" "1dc5b4a99cce916f154c706569baf062600d7dea13e0711e7d7e1461d6230e39"
    )
    assert pinned in installer
    assert pinned in renewer
    assert "--preferred-profile shortlived" in installer
    assert '--ip-address "$public_ip"' in installer
    assert "--webroot-path /var/www/certbot" in installer
    assert "--cap-drop ALL" in installer
    assert "--security-opt no-new-privileges:true" in installer
    assert "renew --no-random-sleep-on-renew" in renewer
    assert "openssl x509 -checkend 129600" in renewer
    assert "openssl x509 -checkend 129600" in checker
    assert 'test -z "$(find /var/lib/rosetta/public -type l' in checker
    assert "https://$public_ip/healthz" in checker
    assert "OnFailure=rosetta-healthcheck-notify@fail.service" in renewal_unit
    assert "OnFailure=rosetta-healthcheck-notify@fail.service" in health_unit
    assert "OnUnitActiveSec=8h" in renewal_timer
    assert "OnUnitActiveSec=6h" in health_timer
    assert "ProtectSystem=strict" in renewal_unit
    assert "ProtectSystem=strict" in health_unit
