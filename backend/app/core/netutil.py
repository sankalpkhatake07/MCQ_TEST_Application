import ipaddress
from typing import Iterable, Optional


def ip_allowed(ip: Optional[str], rules: Iterable[str]) -> bool:
    """Empty rules => everyone allowed. Rules may be single IPs or CIDR blocks."""
    rules = [r.strip() for r in (rules or []) if r and r.strip()]
    if not rules:
        return True
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return False
    for r in rules:
        try:
            if addr in ipaddress.ip_network(r, strict=False):
                return True
        except ValueError:
            continue
    return False


def invalid_rules(rules: Iterable[str]):
    bad = []
    for r in rules:
        try:
            ipaddress.ip_network(r.strip(), strict=False)
        except ValueError:
            bad.append(r)
    return bad


def client_ip(peer: Optional[str], forwarded_for: Optional[str], trust_proxy: bool) -> str:
    if trust_proxy and forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return peer or ""
