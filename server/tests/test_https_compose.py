"""compose.https.yaml is compose.yaml with Caddy in front, and nothing else.

SERVER.md recommends it, so it has to be the same server as compose.yaml,
the same project and volumes, so that moving to it keeps the password and
the sign-ins, with only what HTTPS needs changed. The panel is published on
no port, Caddy alone is, and the names they are given agree. Read as text,
since the Python that runs this suite may have no YAML parser.
"""
import re
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parent
PLAIN = (SERVER / "compose.yaml").read_text(encoding="utf-8")
HTTPS = (SERVER / "compose.https.yaml").read_text(encoding="utf-8")
CADDYFILE = (SERVER / "Caddyfile").read_text(encoding="utf-8")


def service(text: str, name: str) -> list:
    """The lines of one service, comments left out."""
    out, inside = [], False
    for line in text.splitlines():
        if re.match(r"^  [\w-]+:\s*$", line):
            inside = line.strip() == name + ":"
            continue
        if inside and line and not line.startswith("    "):
            inside = False
        if inside and line.strip() and not line.strip().startswith("#"):
            out.append(line)
    return out


def test_it_is_the_same_project_with_the_same_volumes():
    assert re.search(r"^name: paperpull$", HTTPS, re.M)
    for volume in ("profiles", "settings", "browser"):
        assert re.search(r"^  %s:$" % volume, HTTPS, re.M), volume


def test_the_panel_is_the_same_server_with_only_what_https_needs():
    plain = service(PLAIN, "paperpull")
    https = service(HTTPS, "paperpull")
    published = ["    ports:", '      - "8765:8765"']
    added = ["      PAPERPULL_HOSTS: *names", "      PAPERPULL_PROXY: proxy"]
    assert [line for line in plain if line not in published] == \
        [line for line in https if line not in added]
    assert all(line in plain for line in published) and all(line in https for line in added)
    assert "ports:" not in "\n".join(https), "the panel is published on no port"


def test_caddy_alone_is_published_on_the_panels_port():
    proxy = service(HTTPS, "proxy")
    assert proxy.count("    ports:") == 1 and '      - "8765:8765"' in proxy
    assert re.search(r"^\thttps_port 8765$", CADDYFILE, re.M)
    # The panel's own port, where server/start.sh serves it.
    assert "--port 8765" in (SERVER / "start.sh").read_text(encoding="utf-8")
    assert re.search(r"^\treverse_proxy paperpull:8765$", CADDYFILE, re.M)


def test_caddy_is_named_by_an_exact_version():
    images = re.findall(r"^    image: (\S+)$", HTTPS, re.M)
    assert len(images) == 2 and re.fullmatch(r"caddy:\d+\.\d+\.\d+", images[1]), images


def test_the_panel_knows_the_proxy_by_its_service_name():
    assert "PAPERPULL_PROXY: proxy" in HTTPS and re.search(r"^  proxy:$", HTTPS, re.M)
    assert 'os.environ.get("PAPERPULL_PROXY")' in (REPO / "gui" / "server_mode.py").read_text(
        encoding="utf-8")


def test_the_names_caddy_makes_certificates_for_are_the_ones_the_panel_answers_to():
    assert re.search(r'^x-address: &address "[^"]*"$', HTTPS, re.M)
    assert re.search(r'^x-names: &names "[^"]*"$', HTTPS, re.M)
    proxy = service(HTTPS, "proxy")
    assert "      PAPERPULL_ADDRESS: *address" in proxy and "      PAPERPULL_NAMES: *names" in proxy
    assert "{$PAPERPULL_NAMES}, {$PAPERPULL_ADDRESS} {" in CADDYFILE
    # A browser names no site when it opens an address.
    assert re.search(r"^\tdefault_sni \{\$PAPERPULL_ADDRESS\}$", CADDYFILE, re.M)


def test_caddys_authority_stays_in_a_volume_of_its_own():
    """Its key makes certificates the person's devices trust, for any site,
    so it is never written into a folder that might be shared."""
    proxy = service(HTTPS, "proxy")
    assert "      - proxy-data:/data" in proxy and re.search(r"^  proxy-data:$", HTTPS, re.M)
    assert not any(re.match(r"^      - \.?/", line) for line in proxy
                   if "Caddyfile" not in line), proxy


def test_caddy_is_kept_to_what_it_needs():
    proxy = "\n".join(service(HTTPS, "proxy"))
    assert "cap_drop:\n      - ALL\n    cap_add:\n      - NET_BIND_SERVICE" in proxy
    assert "no-new-privileges:true" in proxy and "read_only: true" in proxy
    assert "./Caddyfile:/etc/caddy/Caddyfile:ro" in proxy
    for setting in ("admin off", "skip_install_trust", "auto_https disable_redirects",
                    "protocols h1 h2", "tls internal", "header -Server"):
        assert setting in CADDYFILE, setting


def test_the_https_file_keeps_the_house_punctuation():
    for text in (HTTPS, CADDYFILE):
        assert "—" not in text
        assert not [line for line in text.splitlines() if line.lstrip().startswith("#") and ";" in line]
