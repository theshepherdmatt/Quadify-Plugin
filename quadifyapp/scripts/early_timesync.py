#!/usr/bin/env python3
"""Quadify early one-shot time sync.

On a no-RTC Pi the clock boots stuck at a stale fake-hwclock value, and ntpd
takes several minutes to formally declare sync (leap=00). That left the OLED
"Connecting to network" placeholder on screen for ~5 minutes before the clock
could be trusted.

This one-shot queries SNTP directly (stdlib only -- no extra packages), steps
the system clock to the real time within seconds of the network coming up, and
drops a marker (/run/quadify-timesynced) that startup.is_clock_synced() trusts.
ntpd remains the long-term disciplinarian; this just gets a correct time on
screen fast. If no server answers within the deadline we exit cleanly without
failing the unit -- the placeholder simply holds as before and ntpd is the
backstop.
"""

import logging
import os
import socket
import struct
import subprocess
import sys
import time

MARKER = "/run/quadify-timesynced"
# Try literal anycast IPs FIRST: on a WiFi cold boot the default route appears
# seconds before DNS actually resolves, so hostname-based NTP can't answer for
# ~30s. These well-known anycast addresses need no DNS, letting us step the
# clock the instant the network has egress. Hostnames stay as fallback in case
# a network blocks these specific IPs.
SERVERS = [
    "162.159.200.1",      # Cloudflare time anycast (time.cloudflare.com)
    "216.239.35.0",       # Google time anycast (time.google.com)
    "0.debian.pool.ntp.org",
    "1.debian.pool.ntp.org",
    "pool.ntp.org",
    "time.cloudflare.com",
]
# NTP epoch (1900) to Unix epoch (1970) offset, in seconds.
NTP_UNIX_DELTA = 2208988800
# Total attempt budget; ntpd is the backstop if we never succeed.
DEADLINE_S = 60
PER_QUERY_TIMEOUT_S = 3

log = logging.getLogger("early_timesync")


def query_sntp(server, timeout=PER_QUERY_TIMEOUT_S):
    """Return the server's UTC time as a float Unix timestamp, or None."""
    pkt = bytearray(48)
    pkt[0] = 0x1B  # LI=0, VN=3, Mode=3 (client)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        t0 = time.time()
        sock.sendto(pkt, (server, 123))
        data, _ = sock.recvfrom(48)
        t3 = time.time()
    finally:
        sock.close()
    if len(data) < 48:
        return None
    # Transmit timestamp = bytes 40..47 (seconds + fraction, big-endian).
    secs, frac = struct.unpack("!II", data[40:48])
    if secs == 0:
        return None
    server_time = (secs - NTP_UNIX_DELTA) + frac / 2 ** 32
    # Correct for half the round-trip so we land close to true time.
    return server_time + (t3 - t0) / 2.0


def set_clock(unix_ts):
    """Step the system clock to unix_ts (UTC). Requires root."""
    iso = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(unix_ts))
    subprocess.run(
        ["/bin/date", "-u", "-s", iso],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )


def iso_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    # Already trusted this boot (e.g. the unit was restarted)? Nothing to do.
    if os.path.exists(MARKER):
        log.info("Marker %s already present; clock already trusted this boot.", MARKER)
        return 0

    deadline = time.time() + DEADLINE_S
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        for server in SERVERS:
            try:
                ts = query_sntp(server)
            except Exception as exc:
                log.debug("SNTP query to %s failed: %s", server, exc)
                ts = None
            if ts is None:
                continue

            before = time.time()
            try:
                set_clock(ts)
            except Exception as exc:
                log.error("Got time from %s but failed to set clock: %s", server, exc)
                return 1
            try:
                with open(MARKER, "w") as fh:
                    fh.write(iso_now() + "\n")
            except Exception as exc:
                log.error("Clock set from %s but failed to write marker %s: %s",
                          server, MARKER, exc)
                return 1

            log.info("Clock stepped %.1fs from %s; marker %s written on attempt %d.",
                     ts - before, server, MARKER, attempt)
            return 0

        log.info("No SNTP server answered on attempt %d; retrying…", attempt)
        time.sleep(2)

    log.warning("Gave up after %ds without an SNTP reply; ntpd remains the backstop.",
                DEADLINE_S)
    return 0  # Do not fail the unit; the placeholder holds as it did before.


if __name__ == "__main__":
    sys.exit(main())
